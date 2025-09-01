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

        await self.tree.sync()
        print(f"Synced {len(self.tree.get_commands())} command(s)")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")


bot = DaoBot()


@bot.tree.command(name="dao", description="DAO 명령어")
@app_commands.describe(
    action="수행할 작업",
    session="출석 회차 (출석 시 필수)",
    code="출석 코드 (출석 시 필수)",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="출석", value="attendance"),
        app_commands.Choice(name="내출석", value="my_attendance"),
        app_commands.Choice(name="포인트", value="points"),
    ]
)
async def dao_command(
    interaction: discord.Interaction, action: str, session: int = None, code: str = None
):
    await interaction.response.defer()

    user_id = str(interaction.user.id)
    username = interaction.user.name

    if action == "attendance":
        if session is None or code is None:
            await interaction.followup.send(
                "❌ 출석하려면 회차와 코드를 모두 입력해주세요.\n예: `/dao 출석 1 ABC123`"
            )
            return

        result = await attendance_service.check_in(user_id, username, session, code)
        await interaction.followup.send(result["message"])

    elif action == "my_attendance":
        result = await attendance_service.get_my_attendance(user_id)
        await interaction.followup.send(result["message"])

    elif action == "points":
        points = await db.get_user_points(user_id)
        await interaction.followup.send(f"💰 현재 포인트: **{points:,}점**")


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


def main():
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
