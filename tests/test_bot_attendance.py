"""Tests for attendance thread permissions and approvals."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from app.bot import DaoBot
from app.settings import settings


def _make_member(
    member_id: int,
    *,
    role_ids: list[int] | None = None,
    administrator: bool = False,
    display_name: str = "사용자",
):
    member = MagicMock()
    member.id = member_id
    member.roles = [SimpleNamespace(id=role_id) for role_id in (role_ids or [])]
    member.guild_permissions = SimpleNamespace(administrator=administrator)
    member.display_name = display_name
    return member


def _make_thread(name: str, owner_id: int):
    thread = MagicMock()
    thread.__class__ = discord.Thread
    thread.name = name
    thread.owner_id = owner_id
    thread.join = AsyncMock()
    thread.send = AsyncMock()
    return thread


@pytest.mark.asyncio
async def test_on_thread_create_allows_generation7_starter_any_parent():
    bot = DaoBot()
    guild = MagicMock()
    starter = _make_member(
        1001, role_ids=[settings.generation_7_role_id], display_name="7기유저"
    )
    guild.get_member.return_value = starter

    thread = _make_thread("3주차", starter.id)
    thread.guild = guild
    thread.parent = SimpleNamespace(id=999999999)

    await bot.on_thread_create(thread)

    thread.join.assert_awaited_once()
    thread.send.assert_awaited_once()
    sent_message = thread.send.call_args[0][0]
    assert "3주차" in sent_message


@pytest.mark.asyncio
async def test_on_thread_create_ignores_unauthorized_starter():
    bot = DaoBot()
    guild = MagicMock()
    guild.get_member.return_value = _make_member(1002, role_ids=[])

    thread = _make_thread("4주차", 1002)
    thread.guild = guild

    await bot.on_thread_create(thread)

    thread.join.assert_not_awaited()
    thread.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_raw_reaction_add_ignores_thread_from_unauthorized_starter():
    bot = DaoBot()
    guild = MagicMock()
    reactor = _make_member(
        2001,
        role_ids=[settings.attendance_manager_role_ids[1]],
        display_name="출석매니저",
    )
    unauthorized_owner = _make_member(2002, role_ids=[])
    attendee = _make_member(2003, role_ids=[], display_name="참석자")
    guild.get_member.side_effect = lambda uid: {
        reactor.id: reactor,
        unauthorized_owner.id: unauthorized_owner,
        attendee.id: attendee,
    }.get(uid)

    thread = _make_thread("2주차", unauthorized_owner.id)
    message = MagicMock()
    message.id = 555
    message.author = SimpleNamespace(id=attendee.id, name="attendee")
    message.add_reaction = AsyncMock()
    thread.fetch_message = AsyncMock(return_value=message)

    bot.get_guild = MagicMock(return_value=guild)
    bot.fetch_channel = AsyncMock(return_value=thread)

    payload = SimpleNamespace(
        user_id=reactor.id,
        guild_id=1,
        channel_id=10,
        message_id=555,
    )

    with patch(
        "app.services.attendance_service.attendance_service.record_by_metadata",
        new=AsyncMock(),
    ) as record_mock:
        await bot.on_raw_reaction_add(payload)

    record_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_raw_reaction_add_records_attendance_for_any_participant():
    bot = DaoBot()
    guild = MagicMock()
    reactor = _make_member(
        3001,
        role_ids=[settings.attendance_manager_role_ids[1]],
        display_name="출석매니저",
    )
    starter = _make_member(
        3002, role_ids=[settings.generation_7_role_id], display_name="7기유저"
    )
    attendee = _make_member(3003, role_ids=[], display_name="참석자")
    guild.get_member.side_effect = lambda uid: {
        reactor.id: reactor,
        starter.id: starter,
        attendee.id: attendee,
    }.get(uid)

    thread = _make_thread("5주차", starter.id)
    message = MagicMock()
    message.id = 777
    message.author = SimpleNamespace(id=attendee.id, name="attendee")
    message.add_reaction = AsyncMock()
    thread.fetch_message = AsyncMock(return_value=message)

    bot.get_guild = MagicMock(return_value=guild)
    bot.fetch_channel = AsyncMock(return_value=thread)

    payload = SimpleNamespace(
        user_id=reactor.id,
        guild_id=1,
        channel_id=10,
        message_id=777,
    )

    with patch(
        "app.services.attendance_service.attendance_service.record_by_metadata",
        new=AsyncMock(return_value={"success": True}),
    ) as record_mock:
        await bot.on_raw_reaction_add(payload)

    record_mock.assert_awaited_once_with(
        user_id=str(attendee.id),
        username="attendee",
        generation=settings.attendance_generation,
        week=5,
        day=1,
        nickname="참석자",
        channel_id=payload.channel_id,
        announcement_message_id=message.id,
        reply_message_id=message.id,
    )
    message.add_reaction.assert_awaited_once_with("✅")
