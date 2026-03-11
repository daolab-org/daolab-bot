from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Callable

import discord
from discord import app_commands
from discord.ext import commands

from app.database import db
from app.models import Transaction
from app.roles import (
    is_admin,
    is_friends,
    is_generation_7,
    is_official_crew,
    member_generation,
)
from app.settings import settings
from app.services.attendance_service import attendance_service
from app.services.gratitude_service import gratitude_service


def _chunk_lines(lines: list[str], limit: int = 1900) -> list[str]:
    """Split joined lines into Discord-friendly chunks."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in lines:
        addition = len(line) + 1  # newline when joined
        if current and current_length + addition > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_length = len(line)
        else:
            current.append(line)
            current_length += addition

    if current:
        chunks.append("\n".join(current))

    return chunks


@dataclass(frozen=True)
class RoleViewSpec:
    label: str
    role_id: int
    matcher: Callable[[discord.Member], bool]


ROLE_VIEWS: dict[str, RoleViewSpec] = {
    "generation_7": RoleViewSpec("7기", settings.generation_7_role_id, is_generation_7),
    "official_crew": RoleViewSpec(
        "정식크루", settings.official_crew_role_id, is_official_crew
    ),
    "friends": RoleViewSpec("프렌즈", settings.friends_role_id, is_friends),
}

ROLE_ACTIONS: dict[str, tuple[str, str]] = {
    "fetch_gen7_members": ("generation_7", "members"),
    "gen7_points_summary": ("generation_7", "points"),
    "fetch_official_crew_members": ("official_crew", "members"),
    "official_crew_points_summary": ("official_crew", "points"),
    "official_crew_attendance_summary": ("official_crew", "attendance"),
    "fetch_friends_members": ("friends", "members"),
    "friends_points_summary": ("friends", "points"),
    "friends_attendance_summary": ("friends", "attendance"),
}


async def _get_view_members(
    interaction: discord.Interaction,
    spec: RoleViewSpec,
) -> list[discord.Member] | None:
    guild = interaction.guild

    if guild is None:
        await interaction.followup.send("❌ 길드 정보를 가져올 수 없습니다.")
        return None

    if not guild.chunked:
        await guild.chunk()

    role = guild.get_role(spec.role_id)
    if role is None:
        await interaction.followup.send(
            f"❌ 역할 ID {spec.role_id}를 찾을 수 없습니다."
        )
        return None

    members = [member for member in role.members if spec.matcher(member)]
    return members


async def _send_role_member_list(
    interaction: discord.Interaction,
    spec: RoleViewSpec,
) -> None:
    members = await _get_view_members(interaction, spec)
    if members is None:
        return

    if not members:
        await interaction.followup.send(f"ℹ️ {spec.label} 기준에 맞는 멤버가 없습니다.")
        return

    lines = [f"👥 **{spec.label} 멤버 목록** (총 {len(members)}명)", ""]
    for idx, member in enumerate(members, start=1):
        lines.append(f"{idx}. {member.display_name} (@{member.name}) - ID: {member.id}")

    message = "\n".join(lines)
    if len(message) <= 2000:
        await interaction.followup.send(message)
        return

    chunks = []
    current_chunk = [lines[0], lines[1]]
    current_length = len(lines[0]) + len(lines[1]) + 2

    for line in lines[2:]:
        line_length = len(line) + 1
        if current_length + line_length > 1900:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_length = line_length
        else:
            current_chunk.append(line)
            current_length += line_length

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    for chunk in chunks:
        await interaction.followup.send(chunk)


async def _aggregate_points_by_role_view(
    interaction: discord.Interaction,
    spec: RoleViewSpec,
) -> None:
    members = await _get_view_members(interaction, spec)
    if members is None:
        return

    if not members:
        await interaction.followup.send(f"ℹ️ {spec.label} 기준에 맞는 멤버가 없습니다.")
        return

    member_ids = {str(member.id) for member in members}
    all_users = list(db.users_collection.find({}))

    from app.filters import is_test_user_doc

    filtered_users = []
    for user_doc in all_users:
        if is_test_user_doc(user_doc):
            continue
        if user_doc.get("discord_id") not in member_ids:
            continue
        filtered_users.append(
            {
                "discord_id": user_doc.get("discord_id"),
                "username": user_doc.get("username"),
                "nickname": user_doc.get("nickname")
                or user_doc.get("username")
                or user_doc.get("discord_id"),
                "total_points": user_doc.get("total_points", 0),
            }
        )

    if not filtered_users:
        await interaction.followup.send(f"ℹ️ {spec.label} 기준에 맞는 유저가 없습니다.")
        return

    await _send_points_table(interaction, filtered_users, spec.label)


async def _send_points_table(
    interaction: discord.Interaction,
    users: list[dict],
    role_name: str,
) -> None:
    """Send points table for given users.

    Args:
        interaction: Discord interaction object
        users: List of user dictionaries with discord_id, username, nickname, total_points
        role_name: Display name of the role
    """
    # Sort by nickname (Korean alphabetical order)
    users_sorted = sorted(users, key=lambda u: u["nickname"].lower())

    # Format as markdown table in code block
    lines = [
        f"💰 **{role_name} 포인트 집계** (총 {len(users_sorted)}명)",
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
        header = "\n".join(lines[:5])  # Header + table header (including opening ```)
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


async def _get_attendance_overview_for_view(
    interaction: discord.Interaction, spec: RoleViewSpec
) -> dict | None:
    members = await _get_view_members(interaction, spec)
    if members is None:
        return None

    member_ids = [str(member.id) for member in members]
    overview = await db.get_attendance_overview_for_user_ids(member_ids)
    return overview


async def _send_role_attendance_summary(
    interaction: discord.Interaction, spec: RoleViewSpec
) -> None:
    overview = await _get_attendance_overview_for_view(interaction, spec)
    if overview is None:
        return

    if overview.get("up_to_week", 0) == 0:
        await interaction.followup.send(f"ℹ️ {spec.label} 출석 데이터가 없습니다.")
        return

    weekly_counts = overview["weekly_counts"]
    weekly_str = (
        ", ".join(f"{item['week']}주차: {item['count']}명" for item in weekly_counts)
        if weekly_counts
        else "데이터 없음"
    )

    lines = [
        f"📅 **{spec.label} 출석 현황 요약**",
        f"• 기준 주차: 1~{overview['up_to_week']}주차",
        f"• 주차별 총 참여자 수: {weekly_str}",
        f"• 누적 참여 횟수: {overview['total_attendance']}건",
        f"• 고유 인원: {overview['unique_participants']}명",
        f"• 전체 참여율: {overview['overall_rate']}%",
    ]
    await interaction.followup.send("\n".join(lines))


async def _handle_role_action(
    interaction: discord.Interaction,
    action: str,
) -> bool:
    role_action = ROLE_ACTIONS.get(action)
    if role_action is None:
        return False

    spec_key, handler_kind = role_action
    spec = ROLE_VIEWS[spec_key]

    if handler_kind == "members":
        await _send_role_member_list(interaction, spec)
    elif handler_kind == "points":
        await _aggregate_points_by_role_view(interaction, spec)
    else:
        await _send_role_attendance_summary(interaction, spec)

    return True


async def _send_detailed_attendance_overview(
    interaction: discord.Interaction,
    overview: dict,
    title: str,
    thread_name: str,
) -> None:
    max_week = overview.get("up_to_week", 0)
    weekly_counts = overview["weekly_counts"]
    weekly_str = (
        ", ".join(f"{item['week']}주차: {item['count']}명" for item in weekly_counts)
        if weekly_counts
        else "데이터 없음"
    )

    lines = [
        f"📅 {title} — 1~{max_week}주차 출석 현황",
        f"• 주차별 총 참여자 수: {weekly_str}",
        f"• 누적 참여 횟수: {overview['total_attendance']}건 (고유 인원 {overview['unique_participants']}명)",
        f"• 전체 참여율: {overview['overall_rate']}%",
    ]

    participants = overview["participants"]
    nicknames = overview["nicknames"]
    chunks = []
    header_text = "\n".join(lines)

    if participants:
        attendance_header = "\n\n**개인별 출석 현황 (✅ 출석 / ⬜ 미출석):**"
        week_header = f"주차: {' '.join(f'{w:02d}' for w in range(1, max_week + 1))}"
        current_chunk = [header_text, attendance_header, "```", week_header]
        current_length = (
            sum(len(line) for line in current_chunk) + len(current_chunk) - 1
        )

        participants_sorted = sorted(
            participants,
            key=lambda p: nicknames.get(p["user_id"], p["user_id"]).lower(),
        )

        nickname_count: dict[str, int] = {}
        for participant in participants_sorted:
            name = nicknames.get(participant["user_id"], participant["user_id"])
            nickname_count[name] = nickname_count.get(name, 0) + 1

        nickname_index: dict[str, int] = {}
        current_number = 1

        for participant in participants_sorted:
            name = nicknames.get(participant["user_id"], participant["user_id"])
            attended = set(participant.get("weeks", []))
            attendance_count = len(attended)
            marks = " ".join(
                "✅" if week in attended else "⬜" for week in range(1, max_week + 1)
            )

            if nickname_count[name] > 1:
                nickname_index[name] = nickname_index.get(name, 0) + 1
                number_str = f"{current_number}-{nickname_index[name]}"
                if nickname_index[name] == nickname_count[name]:
                    current_number += 1
            else:
                number_str = str(current_number)
                current_number += 1

            line = f"{number_str}. {name} — {attendance_count}회 | {marks}"
            line_length = len(line) + 1

            if current_length + line_length + 10 > 1800:
                current_chunk.append("```")
                chunks.append("\n".join(current_chunk))
                current_chunk = [
                    f"📅 {title} 출석 현황 (계속)",
                    attendance_header,
                    "```",
                    week_header,
                    line,
                ]
                current_length = (
                    sum(len(chunk_line) for chunk_line in current_chunk)
                    + len(current_chunk)
                    - 1
                )
            else:
                current_chunk.append(line)
                current_length += line_length

        if len(current_chunk) > 4:
            current_chunk.append("```")
            chunks.append("\n".join(current_chunk))
    else:
        chunks.append("\n".join(lines))

    first_message = await interaction.followup.send(chunks[0])
    if len(chunks) > 1:
        thread = await first_message.create_thread(
            name=thread_name,
            auto_archive_duration=1440,
        )
        for chunk in chunks[1:]:
            await thread.send(chunk)


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
            from_generation=member_generation(member) if member is not None else None,
            to_generation=member_generation(target_member)
            if target_member is not None
            else None,
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
            "• 출석: 어떤 채널이든 `N주차` 스레드에 댓글을 남기면, 관리자가 리액션으로 승인할 때 적립됩니다. (주차당 1회 인정)",
            "• 출석 스레드 시작: 7기 역할 또는 관리자가 채널에 `N주차 출석 시작`이라고 보내면 봇이 `N주차` 스레드를 자동으로 만듭니다.",
            "• 예시: `3주차 출석 시작` → 봇이 `3주차` 스레드를 만들고 안내 메시지를 남깁니다.",
            "• 직접 `N주차` 이름으로 스레드를 만들어도 기존처럼 출석 스레드로 인식됩니다.",
            "• /dao 출석내역 — 내 출석 내역",
            "• /dao 감사 @대상 [메시지] — 감사 보내기 (하루 2회, 1회당 +5p/+5p)",
            "• /dao 감사내역 — 감사 내역",
            "• /dao 포인트 — 포인트 및 출석/감사 요약",
            "",
            "**관리자**",
            "• /dao_admin 출석현황 [기수] — 기수별 상세 출석 현황",
            "• /dao_admin 7기불러오기 — 7기 기준 멤버 목록 조회",
            "• /dao_admin 7기포인트집계 — 7기 포인트 집계",
            "• /dao_admin 정식크루불러오기 — 정식크루 멤버 목록 조회",
            "• /dao_admin 정식크루포인트집계 — 정식크루 포인트 집계",
            "• /dao_admin 정식크루출석현황 — 정식크루 출석 요약",
            "• /dao_admin 프렌즈불러오기 — 프렌즈 멤버 목록 조회",
            "• /dao_admin 프렌즈포인트집계 — 프렌즈 포인트 집계",
            "• /dao_admin 프렌즈출석현황 — 프렌즈 출석 요약",
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
        target="대상 유저",
        amount="포인트 수량 (양수)",
        reason="사유",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="출석현황", value="weekly_summary"),
            app_commands.Choice(name="7기불러오기", value="fetch_gen7_members"),
            app_commands.Choice(name="7기포인트집계", value="gen7_points_summary"),
            app_commands.Choice(
                name="정식크루불러오기", value="fetch_official_crew_members"
            ),
            app_commands.Choice(
                name="정식크루포인트집계", value="official_crew_points_summary"
            ),
            app_commands.Choice(
                name="정식크루출석현황", value="official_crew_attendance_summary"
            ),
            app_commands.Choice(name="프렌즈불러오기", value="fetch_friends_members"),
            app_commands.Choice(
                name="프렌즈포인트집계", value="friends_points_summary"
            ),
            app_commands.Choice(
                name="프렌즈출석현황", value="friends_attendance_summary"
            ),
            app_commands.Choice(name="지급", value="grant_points"),
            app_commands.Choice(name="회수", value="deduct_points"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def dao_admin_command(
        interaction: discord.Interaction,
        action: str,
        generation: int | None = None,
        target: discord.User | None = None,
        amount: int | None = None,
        reason: str | None = None,
    ) -> None:
        await interaction.response.defer()

        if action == "weekly_summary":
            if generation is None:
                await interaction.followup.send(
                    "❌ 기수를 입력해주세요.\n예: `/dao_admin 출석현황 7`"
                )
                return

            if generation == settings.attendance_generation:
                members = await _get_view_members(
                    interaction, ROLE_VIEWS["generation_7"]
                )
                if members is None:
                    return
                overview = await db.get_attendance_overview_for_user_ids(
                    [str(member.id) for member in members]
                )
            else:
                overview = await db.get_attendance_overview(generation)

            if overview.get("up_to_week", 0) == 0:
                await interaction.followup.send(
                    f"ℹ️ {generation}기 출석 데이터가 없습니다."
                )
                return

            await _send_detailed_attendance_overview(
                interaction,
                overview,
                title=f"{generation}기",
                thread_name=f"{generation}기 출석 현황",
            )
            return

        if await _handle_role_action(interaction, action):
            return

        if action in ["grant_points", "deduct_points"]:
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

            if not is_admin(member):
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
                generation=member_generation(target_member)
                if target_member is not None
                else None,
                nickname=target_nickname,
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
            return

        await interaction.followup.send("❌ 지원하지 않는 관리자 작업입니다.")

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
