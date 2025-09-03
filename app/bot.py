from __future__ import annotations

import discord
from discord.ext import commands

from app.database import db
from app.settings import settings


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    return intents


class DaoBot(commands.Bot):
    """Discord bot for DAOLAB.

    Keeps runtime setup minimal; commands are registered via `register_commands`.
    """

    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=_build_intents())

    async def setup_hook(self) -> None:
        # Connect DB and ensure indexes
        db.connect()
        print("Database connected")

        # Register commands (idempotent)
        from app.commands import register_commands  # lazy import to avoid cycles

        register_commands(self)

        # Fast sync to the DAOLAB guild for immediate availability
        try:
            guild = discord.Object(id=settings.daolab_guild_id)
            self.tree.copy_global_to(guild=guild)
            cmds = await self.tree.sync(guild=guild)
            print(
                f"Guild sync complete: {len(cmds)} command(s) → gid={settings.daolab_guild_id}"
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"Guild sync failed: {e}")

    async def on_ready(self) -> None:
        assert self.user is not None
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Handle reaction-based attendance approval.

        Flow:
        - Only in the configured attendance channel
        - Only when the reactor is admin or has the configured manager role
        - The reacted message must be in a channel/thread whose name contains "X주차"
        - Day granularity is ignored; a user gets credit once per week when approved
        """
        try:
            # Ignore bot reactions
            if payload.user_id == (self.user.id if self.user else None):
                return

            guild = self.get_guild(payload.guild_id) if payload.guild_id else None
            if guild is None:
                return

            member = guild.get_member(payload.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(payload.user_id)
                except Exception:
                    return

            is_admin = getattr(member.guild_permissions, "administrator", False)
            has_role = any(
                r.id == settings.attendance_manager_role_id for r in member.roles
            )
            if not (is_admin or has_role):
                return

            # Only handle reactions inside threads; week is parsed from thread name
            channel = await self.fetch_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread):
                return

            # Ensure the bot can access the thread (especially for private threads)
            try:
                await channel.join()
            except Exception:
                # Joining may fail if already joined or not required; continue
                pass

            # Fetch the reacted message (the attendee's reply inside the thread)
            try:
                msg = await channel.fetch_message(payload.message_id)
            except Exception:
                # Retry once after attempting to join (helps with race conditions)
                try:
                    await channel.join()
                except Exception:
                    pass
                try:
                    msg = await channel.fetch_message(payload.message_id)
                except Exception:
                    return

            # Parse pattern like "6주차" (day is ignored for attendance purposes)
            import re

            # Extract week number from the thread name
            m = re.search(r"(\d+)\s*주차", channel.name)
            if not m:
                return
            week = int(m.group(1))
            day = 1  # 일 단위는 미사용. 고정값으로 처리하여 주차 단위 출석만 인정
            generation = settings.attendance_generation

            print(f"Attendance reaction detected: gen={generation}, week={week}")
            # Credit attendance to the author of the reply message
            attendee_user = msg.author
            attendee_nickname = None
            attendee_member = guild.get_member(attendee_user.id)
            if attendee_member is not None:
                attendee_nickname = attendee_member.display_name

            from app.services.attendance_service import attendance_service

            res = await attendance_service.record_by_metadata(
                user_id=str(attendee_user.id),
                username=attendee_user.name,
                generation=generation,
                week=week,
                day=day,
                nickname=attendee_nickname,
                channel_id=payload.channel_id,
                announcement_message_id=msg.id,
                reply_message_id=msg.id,
            )

            # Add a small confirmation reaction to the reply (check mark) if success
            if res.get("success"):
                try:
                    await msg.add_reaction("✅")
                except Exception as e:
                    print(f"Failed to add reaction to message: {msg.id}, error: {e}")
                    pass
        except Exception as e:
            # Keep errors from crashing the bot; log minimal info
            print(f"on_raw_reaction_add error: {e}")

    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Post a notice when an admin/manager creates an attendance thread.

        If a thread name matches the pattern like "N주차" and the creator is an
        admin or has the configured manager role, the bot joins the thread and
        leaves a short message indicating it's monitoring the thread.
        """
        try:
            guild = thread.guild
            if guild is None:
                return

            # Validate creator permissions (admin or manager role)
            owner_id = getattr(thread, "owner_id", None)
            if owner_id is None:
                return

            member = guild.get_member(owner_id)
            if member is None:
                try:
                    member = await guild.fetch_member(owner_id)
                except Exception:
                    return

            is_admin = getattr(member.guild_permissions, "administrator", False)
            has_role = any(
                r.id == settings.attendance_manager_role_id for r in member.roles
            )
            if not (is_admin or has_role):
                return

            # Check thread name pattern like "6주차"
            import re

            m = re.search(r"(\d+)\s*주차", thread.name)
            if not m:
                return

            week = int(m.group(1))

            # Try to join the thread (for private threads) and send a notice
            try:
                await thread.join()
            except Exception:
                pass

            try:
                await thread.send(
                    f"안녕하세요! 출석 스레드를 인식했어요. 이 스레드에서 관리자가 리액션으로 승인하면 자동으로 출석이 기록됩니다. (주차: {week}주차)"
                )
            except Exception as e:
                print(f"on_thread_create send error: {e}")
                return
        except Exception as e:
            print(f"on_thread_create error: {e}")


def create_bot() -> DaoBot:
    return DaoBot()
