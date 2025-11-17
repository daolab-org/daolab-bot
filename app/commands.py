from __future__ import annotations
import time

import discord
from discord import app_commands
from discord.ext import commands

from app.database import db
from app.models import Transaction
from app.settings import settings
from app.services.attendance_service import attendance_service
from app.services.gratitude_service import gratitude_service


def register_commands(bot: commands.Bot) -> None:
    """Register all slash and prefix commands on the given bot.

    Idempotent: safe to call multiple times. Keeps main.py lean while avoiding
    over-fragmentation (single module for commands).
    """

    if getattr(bot, "_dao_commands_registered", False):
        return

    # ----- /dao 그룹 및 하위 명령어 -----
    dao = app_commands.Group(name="dao", description="DAO 명령어")

    @dao.command(name="출석내역", description="내 출석 내역 조회")
    async def dao_my_attendance(interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        result = await attendance_service.get_my_attendance(user_id)
        await interaction.followup.send(result["message"])

    @dao.command(name="포인트", description="현재 포인트 및 출석/감사 요약")
    async def dao_points(interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        points = await db.get_user_points(user_id)
        attendance_summary = await db.get_attendance_summary(user_id)
        gratitude_summary = await db.get_gratitude_summary(user_id)

        message_lines = [
            f"💰 **현재 포인트: {points:,} point**",
            "",
            "**1) 출석 내역:**",
            f"• 총 출석: {attendance_summary['total_attendance']}회 (+{attendance_summary['points_from_attendance']:,} point)",
            f"• 오늘 출석: {'완료 ✓' if attendance_summary['has_attended_today'] else '가능 ○'}",
            "",
            "**2) 감사 내역:**",
            f"• 오늘 감사: {gratitude_summary.get('sent_today_count', 0)}/2",
            f"• 보낸 감사: {gratitude_summary['total_sent']}회 (+{gratitude_summary['points_from_sent']:,} point)",
            f"• 받은 감사: {gratitude_summary['total_received']}회 (+{gratitude_summary['points_from_received']:,} point)",
        ]

        await interaction.followup.send("\n".join(message_lines))

    @dao.command(name="감사", description="감사 보내기 (1회 +5p/+5p, 하루 2회)")
    @app_commands.describe(
        target="감사를 보낼 대상", message="상대에게 전할 메시지 (선택)"
    )
    async def dao_gratitude(
        interaction: discord.Interaction,
        target: discord.User,
        message: str | None = None,
    ) -> None:
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        username = interaction.user.name
        member = (
            interaction.guild.get_member(interaction.user.id)
            if interaction.guild is not None
            else None
        )
        nickname = member.display_name if member is not None else username

        target_id = str(target.id)
        target_username = target.name
        target_member = (
            interaction.guild.get_member(target.id)
            if interaction.guild is not None
            else None
        )
        target_nickname = (
            target_member.display_name if target_member is not None else target_username
        )

        result = await gratitude_service.send_gratitude(
            user_id,
            username,
            target_id,
            target_username,
            message=message,
            from_nickname=nickname,
            to_nickname=target_nickname,
        )
        await interaction.followup.send(result["message"])

    @dao.command(name="감사내역", description="감사 내역 조회")
    async def dao_gratitude_history(interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        result = await gratitude_service.get_gratitude_history(user_id)
        await interaction.followup.send(result["message"])

    # Localize subcommand names for Korean UX
    dao_my_attendance.name_localizations = {"ko": "출석내역"}
    dao_points.name_localizations = {"ko": "포인트"}
    dao_gratitude.name_localizations = {"ko": "감사"}
    dao_gratitude_history.name_localizations = {"ko": "감사내역"}

    # Avoid duplicate registration on reload
    try:
        if not any(cmd.name == dao.name for cmd in bot.tree.get_commands()):
            bot.tree.add_command(dao)
    except Exception:
        bot.tree.add_command(dao)

    # --------- Ping / Help ---------
    def _help_message() -> str:
        lines = [
            "📚 **도움말 (명령어 안내)**",
            "",
            "**일반**",
            "• /ping — 봇 및 DB 상태 확인",
            "• /help — 이 도움말 표시",
            "• /도움말 — 이 도움말 표시",
            "",
            "**DAO 명령어**",
            "• 출석: 공지(예: `6주차`)에 댓글 달면, 관리자가 이모지 반응으로 승인할 때 적립됩니다. (주차당 1회 인정)",
            "• /dao 출석내역 — 내 출석 내역",
            "• /dao 감사 @대상 [메시지] — 감사 보내기 (하루 2회, 1회당 +5p/+5p)",
            "• /dao 감사내역 — 감사 내역",
            "• /dao 포인트 — 포인트 및 출석/감사 요약",
            "",
            "**관리자**",
            "• /dao_admin 출석현황 [기수] [주차] — 주차별 출석 집계",
            "• /dao_admin 지급 @유저 [수량] [사유] — 특정 유저에게 포인트 지급",
            "• /dao_admin 회수 @유저 [수량] [사유] — 특정 유저로부터 포인트 회수",
        ]
        return "\n".join(lines)

    @bot.tree.command(name="ping", description="봇 상태 확인")
    async def ping_command(interaction: discord.Interaction) -> None:
        # Discord 게이트웨이 지연
        gw_latency_ms = int(getattr(interaction.client, "latency", 0.0) * 1000)

        # DB 상태 확인
        db_status = "알 수 없음"
        db_latency_ms: int | None = None
        try:
            db.ensure_connected()
            t0 = time.perf_counter()
            db.client.admin.command("ping")  # type: ignore[union-attr]
            db_latency_ms = int((time.perf_counter() - t0) * 1000)
            db_status = "연결됨 ✓"
        except Exception:
            db_status = "연결 실패 ✗"

        lines = [
            "🏓 Pong!",
            f"• 게이트웨이 지연: {gw_latency_ms}ms",
            f"• DB 상태: {db_status}"
            + (f" ({db_latency_ms}ms)" if db_latency_ms is not None else ""),
        ]
        await interaction.response.send_message("\n".join(lines))

    @bot.tree.command(name="help", description="명령어 도움말")
    async def help_command(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(_help_message())

    @bot.tree.command(name="도움말", description="명령어 도움말")
    async def 도움말_command(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(_help_message())

    # --------- 관리자 명령어 ---------
    @bot.tree.command(name="dao_admin", description="DAO 관리자 명령어")
    @app_commands.describe(
        action="수행할 작업",
        generation="기수",
        week="주차",
        target="대상 유저",
        amount="포인트 수량 (양수)",
        reason="사유",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="출석현황", value="weekly_summary"),
            app_commands.Choice(name="6기불러오기", value="fetch_gen6_members"),
            app_commands.Choice(name="6기포인트집계", value="gen6_points_summary"),
            app_commands.Choice(name="지급", value="grant_points"),
            app_commands.Choice(name="회수", value="deduct_points"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def dao_admin_command(
        interaction: discord.Interaction,
        action: str,
        generation: int | None = None,
        week: int | None = None,
        target: discord.User | None = None,
        amount: int | None = None,
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()

        if action == "weekly_summary":
            if generation is None or week is None:
                await interaction.followup.send(
                    "❌ 기수와 주차를 모두 입력해주세요.\n예: `/dao_admin 출석현황 6 1`"
                )
                return

            overview = await db.get_attendance_overview(generation, week)

            # Header
            lines: list[str] = []
            lines.append(f"📅 {generation}기 — {week}주차 기준 출석 현황")

            # Weekly totals
            weekly_str = ", ".join(
                [
                    f"{item['week']}주차: {item['count']}명"
                    for item in overview["weekly_counts"]
                ]
            )
            lines.append(f"• 주차별 총 참여자 수: {weekly_str}")
            lines.append(
                f"• 누적 참여 횟수: {overview['total_attendance']}건 (고유 인원 {overview['unique_participants']}명)"
            )
            lines.append(f"• 전체 참여율: {overview['overall_rate']}%")

            # Per-user matrix, nickname-based, no mentions
            participants = overview["participants"]
            nicknames = overview["nicknames"]
            if participants:
                lines.append("")
                lines.append("**개인별 출석 현황:**")
                # Sort by nickname for readability
                participants_sorted = sorted(
                    participants,
                    key=lambda p: (nicknames.get(p["user_id"], p["user_id"]).lower()),
                )
                max_rows = 50  # limit for Discord message length
                for p in participants_sorted[:max_rows]:
                    name = nicknames.get(
                        p["user_id"], p["user_id"]
                    )  # nickname/username
                    attended = set(p.get("weeks", []))
                    marks = []
                    for w in range(1, week + 1):
                        marks.append(f"{w}주차 {'✅' if w in attended else '❌'}")
                    lines.append(f"• {name} — {', '.join(marks)}")
                if len(participants_sorted) > max_rows:
                    lines.append(f"... 외 {len(participants_sorted) - max_rows}명")

            await interaction.followup.send("\n".join(lines))

        elif action == "fetch_gen6_members":
            # Fetch members with 6기 역할
            role_id = settings.generation_6_role_id
            guild = interaction.guild

            if guild is None:
                await interaction.followup.send("❌ 길드 정보를 가져올 수 없습니다.")
                return

            # Ensure guild members are loaded
            if not guild.chunked:
                await guild.chunk()

            role = guild.get_role(role_id)

            if role is None:
                await interaction.followup.send(
                    f"❌ 역할 ID {role_id}를 찾을 수 없습니다."
                )
                return

            members = role.members

            if not members:
                await interaction.followup.send(
                    f"ℹ️ {role.name} 역할을 가진 멤버가 없습니다."
                )
                return

            # Format member list
            lines = [f"👥 **{role.name} 역할 멤버 목록** (총 {len(members)}명)", ""]

            for idx, member in enumerate(members, start=1):
                lines.append(
                    f"{idx}. {member.display_name} (@{member.name}) - ID: {member.id}"
                )

            # Discord message length limit handling (2000 chars max)
            message = "\n".join(lines)
            if len(message) > 2000:
                # Split into multiple messages
                chunks = []
                current_chunk = [lines[0], lines[1]]  # Header
                current_length = len(lines[0]) + len(lines[1]) + 2

                for line in lines[2:]:  # Skip header lines
                    line_length = len(line) + 1  # +1 for newline
                    if current_length + line_length > 1900:  # Leave some margin
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [line]
                        current_length = line_length
                    else:
                        current_chunk.append(line)
                        current_length += line_length

                if current_chunk:
                    chunks.append("\n".join(current_chunk))

                # Send first chunk
                await interaction.followup.send(chunks[0])
                # Send remaining chunks
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(message)

        elif action == "gen6_points_summary":
            # Get all 6기 users' points
            generation = 6
            users = await db.get_generation_points(generation)

            if not users:
                await interaction.followup.send(f"ℹ️ {generation}기 유저가 없습니다.")
                return

            # Sort by nickname (Korean alphabetical order)
            users_sorted = sorted(users, key=lambda u: u["nickname"].lower())

            # Format as markdown table in code block
            lines = [
                f"💰 **{generation}기 포인트 집계** (총 {len(users_sorted)}명)",
                "",
                "```",
                "| 순번 | 닉네임 | 유저명 | 포인트 |",
                "|------|--------|--------|-------:|",
            ]

            for idx, user in enumerate(users_sorted, start=1):
                nickname = user["nickname"]
                username = user["username"]
                points = user["total_points"]
                lines.append(f"| {idx} | {nickname} | @{username} | {points:,} |")

            lines.append("```")

            # Discord message length limit handling (2000 chars max)
            message = "\n".join(lines)
            if len(message) > 2000:
                # Split into multiple messages
                chunks = []
                header = "\n".join(
                    lines[:5]
                )  # Header + table header (including opening ```)
                current_chunk = [header]
                current_length = len(header)

                for line in lines[5:-1]:  # Skip header and closing ```
                    line_length = len(line) + 1  # +1 for newline
                    if current_length + line_length + 4 > 1900:  # +4 for closing ```
                        current_chunk.append("```")
                        chunks.append("\n".join(current_chunk))
                        current_chunk = [
                            lines[0],
                            "",
                            lines[2],
                            lines[3],
                            lines[4],
                        ]  # Restart with header
                        current_length = len("\n".join(current_chunk))
                    current_chunk.append(line)
                    current_length += line_length

                if len(current_chunk) > 5:  # Has content beyond header
                    current_chunk.append("```")
                    chunks.append("\n".join(current_chunk))

                # Send first chunk
                await interaction.followup.send(chunks[0])
                # Send remaining chunks
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(message)

        elif action in ["grant_points", "deduct_points"]:
            # Check if user has admin role
            member = (
                interaction.guild.get_member(interaction.user.id)
                if interaction.guild
                else None
            )
            if member is None:
                await interaction.followup.send(
                    "❌ 길드 멤버 정보를 가져올 수 없습니다."
                )
                return

            has_admin_role = any(
                role.id == settings.admin_role_id for role in member.roles
            )
            if not has_admin_role:
                await interaction.followup.send("❌ 관리자 권한이 필요합니다.")
                return

            # Validate parameters
            if target is None or amount is None or reason is None:
                await interaction.followup.send(
                    f"❌ 포인트 {('지급' if action == 'grant_points' else '회수')}에 필요한 값이 누락되었습니다.\n"
                    f"필수 파라미터: target(대상 유저), amount(포인트 수량), reason(사유)"
                )
                return

            if amount <= 0:
                await interaction.followup.send("❌ 포인트 수량은 양수여야 합니다.")
                return

            # if target.bot:
            #     await interaction.followup.send(
            #         "❌ 봇에게는 포인트를 지급하거나 회수할 수 없습니다."
            #     )
            #     return

            # Get target user info
            target_id = str(target.id)
            target_username = target.name
            target_member = (
                interaction.guild.get_member(target.id) if interaction.guild else None
            )
            target_nickname = (
                target_member.display_name if target_member else target_username
            )

            # Ensure user exists in database
            await db.get_or_create_user(
                discord_id=target_id,
                username=target_username,
                nickname=target_nickname,
                generation=settings.attendance_generation,
            )

            # Get current points
            current_points = await db.get_user_points(target_id)

            # Create transaction
            is_grant = action == "grant_points"
            points_delta = amount if is_grant else -amount

            # Check if deduction would result in negative points
            if not is_grant and current_points + points_delta < 0:
                await interaction.followup.send(
                    f"❌ 포인트 회수 실패\n"
                    f"• 현재 포인트: {current_points:,} point\n"
                    f"• 회수 시도: {amount:,} point\n"
                    f"• 포인트는 0 미만이 될 수 없습니다."
                )
                return

            base_reason = "관리자지급" if is_grant else "관리자회수"
            transaction_reason: str = f'{base_reason} "{reason}"'

            transaction = Transaction(
                user_id=target_id,
                points=points_delta,
                reason=base_reason,
                admin_id=str(interaction.user.id),
                admin_note=transaction_reason,
            )

            await db.add_transaction(transaction)

            # Get updated points
            updated_points = await db.get_user_points(target_id)

            # Format message
            action_text = "지급" if is_grant else "회수"
            emoji = "💰" if is_grant else "📤"
            await interaction.followup.send(
                f"{emoji} **포인트 {action_text} 완료**\n"
                f"• 대상: {target_nickname} (@{target_username})\n"
                f"• 수량: {amount:,} point {'지급' if is_grant else '회수'}\n"
                f"• 사유: {reason}\n"
                f"• 현재 포인트: {updated_points:,} point"
            )

    # --------- 수동 동기화 (prefix: !sync) ---------
    @bot.command(name="sync")
    async def sync_command(ctx: commands.Context, gid: int | None = None) -> None:
        """명령어 트리 수동 동기화.

        사용법:
        - `!sync`           → 글로벌 동기화 (전파 지연 가능)
        - `!sync <guildId>` → 해당 길드에 즉시 반영
        - `!sync 0`         → settings.daolab_guild_id 사용
        """
        if gid is None:
            cmds = await bot.tree.sync()
            await ctx.send(f"Global sync: {len(cmds)} (전파 지연 가능)")
            return

        target_gid = settings.daolab_guild_id if gid == 0 else gid
        guild = discord.Object(id=target_gid)
        bot.tree.copy_global_to(guild=guild)
        cmds = await bot.tree.sync(guild=guild)
        await ctx.send(f"Guild sync: {len(cmds)} (gid={target_gid}) — 즉시 반영")

    # mark as registered to prevent duplication on hot-reload
    setattr(bot, "_dao_commands_registered", True)
