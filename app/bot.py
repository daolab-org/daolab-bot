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
        - The reacted message must be a reply to an announcement message whose content matches "X주차 Y일"
        - The author of the reacted reply is credited attendance for the configured generation/week/day
        """
        try:
            channel = await self.fetch_channel(payload.channel_id)
            if isinstance(channel, discord.Thread):
                # parent_ch_name = channel.parent
                parent_ch_id = channel.parent_id

            if parent_ch_id != settings.attendance_channel_id:
                return

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

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return

            # Fetch the reacted message (the attendee's reply)
            try:
                msg = await channel.fetch_message(payload.message_id)
            except Exception:
                return

            # Parse pattern like "6주차 1일" (generation is configured per channel)
            import re

            m = re.search(r".*(\d+)\s*주차.*(\d+)\s*일.*", channel.name)
            if not m:
                return
            week = int(m.group(1))
            day = int(m.group(2))
            generation = settings.attendance_generation

            print(
                f"Attendance reaction detected: gen={generation}, week={week}, day={day}"
            )
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


def create_bot() -> DaoBot:
    return DaoBot()
