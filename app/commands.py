from __future__ import annotations
import time

import discord
from discord import app_commands
from discord.ext import commands

from app.database import db
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
            f"• 오늘 감사: {'전송 완료 ✓' if gratitude_summary['has_sent_today'] else '전송 가능 ○'}",
            f"• 보낸 감사: {gratitude_summary['total_sent']}회 (+{gratitude_summary['points_from_sent']:,} point)",
            f"• 받은 감사: {gratitude_summary['total_received']}회 (+{gratitude_summary['points_from_received']:,} point)",
        ]

        await interaction.followup.send("\n".join(message_lines))

    @dao.command(name="감사", description="감사 보내기 (+10p)")
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
            "• 출석: 공지(예: `6주차 1일`)에 댓글 달면, 관리자가 이모지 반응으로 승인할 때 적립됩니다.",
            "• /dao 출석내역 — 내 출석 내역",
            "• /dao 감사 @대상 [메시지] — 감사 보내기 (1일 1회, +10p/+10p)",
            "• /dao 감사내역 — 감사 내역",
            "• /dao 포인트 — 포인트 및 출석/감사 요약",
            "",
            "**관리자**",
            "• /dao_admin 출석현황 [기수] [주차] — 주차별 출석 집계",
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
    @app_commands.describe(action="수행할 작업", generation="기수", week="주차")
    @app_commands.choices(
        action=[app_commands.Choice(name="출석현황", value="weekly_summary")]
    )
    @app_commands.default_permissions(administrator=True)
    async def dao_admin_command(
        interaction: discord.Interaction,
        action: str,
        generation: int | None = None,
        week: int | None = None,
    ) -> None:
        await interaction.response.defer()

        if action == "weekly_summary":
            if generation is None or week is None:
                await interaction.followup.send(
                    "❌ 기수와 주차를 모두 입력해주세요.\n예: `/dao_admin 출석현황 6 1`"
                )
                return

            summary = await db.get_weekly_attendance(generation, week)
            lines: list[str] = []
            lines.append(
                f"📅 **{generation}기 {week}주차 출석 현황** (고유 인원 {summary['total_attendees']}명)"
            )
            if summary["by_day"]:
                day_str = ", ".join(
                    [
                        f"{item['day']}일: {item['count']}건"
                        for item in summary["by_day"]
                    ]
                )
                lines.append(f"• 일별 합계: {day_str}")
            if summary["users"]:
                lines.append("")
                lines.append("**참여자 요약 (일차):**")
                # Limit to 30 lines for readability
                for user in summary["users"][:30]:
                    days = ", ".join(str(d) for d in user["days"]) or "-"
                    lines.append(f"• <@{user['user_id']}> — {days}")
                if len(summary["users"]) > 30:
                    lines.append(f"... 외 {len(summary['users']) - 30}명")
            await interaction.followup.send("\n".join(lines))

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
