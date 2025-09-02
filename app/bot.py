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


def create_bot() -> DaoBot:
    return DaoBot()
