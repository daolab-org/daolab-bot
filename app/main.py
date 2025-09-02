import os
import sys

# Prefer certifi's CA bundle on platforms where system CAs may be missing (e.g., macOS python.org builds)
try:
    import certifi  # type: ignore

    # Only set if not already configured by the environment
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception as _cert_err:  # pragma: no cover - best-effort hardening
    # Continue without override; aiohttp will use system defaults
    pass

import discord
from discord import app_commands
from discord.ext import commands

from app.settings import settings
from app.database import db
from app.services.attendance_service import attendance_service
from app.services.gratitude_service import gratitude_service

# Ensure project root is on sys.path when executed as a script (python app/main.py)
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DaoBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        db.connect()
        print("Database connected")

        # Register grouped commands
        try:
            # Avoid duplicate registration on reload
            if not any(cmd.name == dao.name for cmd in self.tree.get_commands()):
                self.tree.add_command(dao)
        except Exception:
            # Fallback: ensure group is present before sync
            self.tree.add_command(dao)

        await self.tree.sync()
        print(f"Synced {len(self.tree.get_commands())} command(s)")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")


bot = DaoBot()


# ----- /dao 그룹 및 하위 명령어 정의 -----
dao = app_commands.Group(name="dao", description="DAO 명령어")


@dao.command(name="출석", description="출석 체크 (+100점)")
@app_commands.describe(session="출석 회차", code="출석 코드")
async def dao_attendance(interaction: discord.Interaction, session: int, code: str):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    username = interaction.user.name

    result = await attendance_service.check_in(user_id, username, session, code)
    await interaction.followup.send(result["message"])


@dao.command(name="출석내역", description="내 출석 내역 조회")
async def dao_my_attendance(interaction: discord.Interaction):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    result = await attendance_service.get_my_attendance(user_id)
    await interaction.followup.send(result["message"])


@dao.command(name="포인트", description="현재 포인트 및 출석/감사 요약")
async def dao_points(interaction: discord.Interaction):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    points = await db.get_user_points(user_id)
    attendance_summary = await db.get_attendance_summary(user_id)
    gratitude_summary = await db.get_gratitude_summary(user_id)

    message_lines = [
        f"💰 **현재 포인트: {points:,}점**",
        "",
        "**1) 출석 내역:**",
        f"• 총 출석: {attendance_summary['total_attendance']}회 (+{attendance_summary['points_from_attendance']:,}점)",
        f"• 오늘 출석: {'완료 ✓' if attendance_summary['has_attended_today'] else '가능 ○'}",
        "",
        "**2) 감사 내역:**",
        f"• 오늘 감사: {'전송 완료 ✓' if gratitude_summary['has_sent_today'] else '전송 가능 ○'}",
        f"• 보낸 감사: {gratitude_summary['total_sent']}회 (+{gratitude_summary['points_from_sent']:,}점)",
        f"• 받은 감사: {gratitude_summary['total_received']}회 (+{gratitude_summary['points_from_received']:,}점)",
    ]

    await interaction.followup.send("\n".join(message_lines))


@dao.command(name="감사", description="감사 보내기 (+10/+10)")
@app_commands.describe(target="감사를 보낼 대상")
async def dao_gratitude(interaction: discord.Interaction, target: discord.User):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    username = interaction.user.name

    target_id = str(target.id)
    target_username = target.name

    result = await gratitude_service.send_gratitude(
        user_id, username, target_id, target_username
    )
    await interaction.followup.send(result["message"])


@dao.command(name="감사내역", description="감사 내역 조회")
async def dao_gratitude_history(interaction: discord.Interaction):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    result = await gratitude_service.get_gratitude_history(user_id)
    await interaction.followup.send(result["message"])


# Localize subcommand names for Korean UX
dao_attendance.name_localizations = {"ko": "출석"}
dao_my_attendance.name_localizations = {"ko": "출석내역"}
dao_points.name_localizations = {"ko": "포인트"}
dao_gratitude.name_localizations = {"ko": "감사"}
dao_gratitude_history.name_localizations = {"ko": "감사내역"}


@bot.tree.command(name="dao_admin", description="DAO 관리자 명령어")
@app_commands.describe(action="수행할 작업", session="회차", code="출석 코드")
@app_commands.choices(
    action=[app_commands.Choice(name="출석코드생성", value="create_code")]
)
@app_commands.default_permissions(administrator=True)
async def dao_admin_command(
    interaction: discord.Interaction, action: str, session: int = None, code: str = None
):
    await interaction.response.defer()

    if action == "create_code":
        if session is None or code is None:
            await interaction.followup.send(
                "❌ 회차와 코드를 모두 입력해주세요.\n예: `/dao_admin 출석코드생성 1 ABC123`"
            )
            return

        admin_id = str(interaction.user.id)
        result = await attendance_service.create_attendance_code(
            session, code, admin_id
        )
        await interaction.followup.send(result["message"])


# --------- Ping / Help ---------
def _help_message() -> str:
    lines = [
        "📚 **도움말 (명령어 안내)**",
        "",
        "**일반**",
        "• /ping — 봇 및 DB 상태 확인",
        "• /help — 이 도움말 표시",
        "",
        "**DAO 명령어**",
        "• /dao 출석 [회차] [코드] — 출석 체크 (+100점)",
        "• /dao 내출석 — 내 출석 내역",
        "• /dao 포인트 — 포인트 및 출석/감사 요약",
        "• /dao 감사 @대상 — 감사 보내기 (1일 1회, +10/+10)",
        "• /dao 감사내역 — 감사 내역",
        "",
        "**관리자**",
        "• /dao_admin 출석코드생성 [회차] [코드] — 출석 코드 생성",
    ]
    return "\n".join(lines)


@bot.tree.command(name="ping", description="봇 상태 확인")
async def ping_command(interaction: discord.Interaction):
    # Discord 게이트웨이 지연
    gw_latency_ms = int(getattr(interaction.client, "latency", 0.0) * 1000)

    # DB 상태 확인
    db_status = "알 수 없음"
    db_latency_ms: int | None = None
    try:
        db.ensure_connected()
        import time

        t0 = time.perf_counter()
        # ping은 가벼운 헬스체크
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
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(_help_message())


def main():
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
