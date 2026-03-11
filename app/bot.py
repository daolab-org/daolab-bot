from __future__ import annotations

import discord
from discord.ext import commands

from app.database import db
from app.settings import settings
from app.models import Transaction
from app.filters import is_test_like_name
from app.roles import has_role, is_admin


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

        # Register transaction publisher observer
        async def _observer(tx: Transaction) -> None:
            try:
                await self._publish_transaction(tx)
            except Exception as e:
                print(f"Transaction publish error: {e}")

        db.add_transaction_observer(_observer)

    async def on_ready(self) -> None:
        assert self.user is not None
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def _publish_transaction(self, tx: Transaction) -> None:
        """Publish a transaction to the configured channel, skipping test data."""
        # Resolve primary user
        user_doc = db.users_collection.find_one({"discord_id": tx.user_id})
        username = (
            user_doc.get("nickname") or user_doc.get("username") if user_doc else None
        )

        # For gratitude, resolve the counterparty too
        from_doc = (
            db.users_collection.find_one({"discord_id": tx.from_user_id})
            if tx.from_user_id
            else None
        )
        to_doc = (
            db.users_collection.find_one({"discord_id": tx.to_user_id})
            if tx.to_user_id
            else None
        )

        # Skip if any related user is a test account
        if is_test_like_name(username):
            return
        if from_doc is not None and is_test_like_name(
            from_doc.get("nickname") or from_doc.get("username")
        ):
            return
        if to_doc is not None and is_test_like_name(
            to_doc.get("nickname") or to_doc.get("username")
        ):
            return

        # Resolve channel
        channel = self.get_channel(settings.transaction_channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(settings.transaction_channel_id)
            except Exception:
                channel = None
        if channel is None:
            return

        # Compose message by reason
        reason = tx.reason
        pts = tx.points
        sign = "+" if pts >= 0 else ""

        # Fetch current points of affected user
        try:
            total = await db.get_user_points(tx.user_id)
        except Exception:
            total = None

        # Mentions
        mention_user = f"<@{tx.user_id}>"
        from_mention = f"<@{tx.from_user_id}>" if tx.from_user_id else None
        to_mention = f"<@{tx.to_user_id}>" if tx.to_user_id else None

        if reason == "출석":
            msg = f"📝 [출석] {sign}{pts}p → {mention_user}"
            if total is not None:
                msg += f" (총 {total:,}p)"
        elif reason == "감사줌":
            # From user sent gratitude (tx.user_id == from_user_id)
            arrow = (
                f"{from_mention} → {to_mention}"
                if from_mention and to_mention
                else mention_user
            )
            msg = f"💝 [감사 전송] {sign}{pts}p — {arrow}"
            if total is not None:
                msg += f" (보낸 사람 {total:,}p)"
        elif reason == "감사받음":
            arrow = (
                f"{from_mention} → {to_mention}"
                if from_mention and to_mention
                else mention_user
            )
            msg = f"💝 [감사 수신] {sign}{pts}p — {arrow}"
            if total is not None:
                msg += f" (받은 사람 {total:,}p)"
        elif reason == "관리자지급":
            admin_mention = f"<@{tx.admin_id}>" if tx.admin_id else "관리자"
            msg = f"⚙️ [관리자 지급] {sign}{pts}p → {mention_user}"
            if total is not None:
                msg += f" (총 {total:,}p)"
            if tx.admin_note:
                msg += f"\n사유: {tx.admin_note}"
            msg += f"\n담당자: {admin_mention}"
        elif reason == "관리자회수":
            admin_mention = f"<@{tx.admin_id}>" if tx.admin_id else "관리자"
            msg = f"⚙️ [관리자 회수] {sign}{pts}p → {mention_user}"
            if total is not None:
                msg += f" (총 {total:,}p)"
            if tx.admin_note:
                msg += f"\n사유: {tx.admin_note}"
            msg += f"\n담당자: {admin_mention}"
        else:
            msg = f"📒 [{reason}] {sign}{pts}p → {mention_user}"
            if total is not None:
                msg += f" (총 {total:,}p)"

        try:
            # type: ignore[attr-defined]
            await channel.send(msg)
        except Exception as e:
            print(f"Failed to send transaction message: {e}")

    async def _can_start_attendance_thread(
        self, guild: discord.Guild | None, owner_id: int | None
    ) -> bool:
        if guild is None or owner_id is None:
            return False

        member = guild.get_member(owner_id)
        if member is None:
            try:
                member = await guild.fetch_member(owner_id)
            except Exception:
                return False

        return is_admin(member) or has_role(member, settings.generation_7_role_id)

    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Handle reaction-based attendance approval.

        Flow:
        - Only for threads whose name contains "X주차"
        - Only when the thread starter is admin or 7기
        - Only when the reactor is admin or has one of the configured manager roles
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
                r.id in settings.attendance_manager_role_ids for r in member.roles
            )
            if not (is_admin or has_role):
                return

            # Only handle reactions inside threads; week is parsed from thread name
            channel = await self.fetch_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread):
                return

            if not await self._can_start_attendance_thread(
                guild, getattr(channel, "owner_id", None)
            ):
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
        """Post a notice for eligible attendance threads.

        If a thread name matches "N주차" and the creator is an admin or 7기,
        the bot joins the thread and leaves a short monitoring notice.
        """
        try:
            guild = thread.guild
            if guild is None:
                return

            if not await self._can_start_attendance_thread(
                guild, getattr(thread, "owner_id", None)
            ):
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
