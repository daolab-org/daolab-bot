"""Tests for updated dao_admin role-based commands."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import Guild, Interaction, Member, Role, User

from app.commands import register_commands
from app.settings import settings


def _find_command(bot, name: str):
    for command in bot.tree.get_commands():
        if command.name == name:
            return command
    return None


@pytest.fixture
def mock_interaction():
    interaction = MagicMock(spec=Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.guild = None
    return interaction


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=Guild)
    guild.chunked = True
    guild.chunk = AsyncMock()
    guild.get_role = MagicMock()
    guild.get_member = MagicMock()
    return guild


@pytest.fixture
def dao_admin_command():
    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)
    command = _find_command(bot, "dao_admin")
    assert command is not None
    return command


def _make_member(
    member_id: int,
    *,
    name: str,
    display_name: str,
    role_ids: list[int] | None = None,
    administrator: bool = False,
):
    member = MagicMock(spec=Member)
    member.id = member_id
    member.name = name
    member.display_name = display_name
    member.roles = [SimpleNamespace(id=role_id) for role_id in (role_ids or [])]
    member.guild_permissions = SimpleNamespace(administrator=administrator)
    return member


def _make_role(name: str, role_id: int, members: list[Member]):
    role = MagicMock(spec=Role)
    role.name = name
    role.id = role_id
    role.members = members
    return role


@pytest.fixture
def mock_admin_member():
    return _make_member(
        123456789,
        name="admin_user",
        display_name="관리자",
        role_ids=[settings.admin_role_id],
        administrator=True,
    )


@pytest.fixture
def mock_target_user():
    user = MagicMock(spec=User)
    user.id = 987654321
    user.name = "target_user"
    user.bot = False
    return user


@pytest.mark.asyncio
async def test_fetch_gen7_members_success(
    dao_admin_command, mock_interaction, mock_guild
):
    generation_member = _make_member(
        1001,
        name="user1",
        display_name="유저1",
        role_ids=[settings.generation_7_role_id],
    )
    transitioned_member = _make_member(
        1002,
        name="user2",
        display_name="전환유저",
        role_ids=[settings.generation_7_role_id, settings.official_crew_role_id],
    )
    role = _make_role(
        "7기", settings.generation_7_role_id, [generation_member, transitioned_member]
    )
    mock_guild.get_role.return_value = role
    mock_interaction.guild = mock_guild

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen7_members", generation=None
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "7기 멤버 목록" in sent_message
    assert "총 1명" in sent_message
    assert "유저1" in sent_message
    assert "전환유저" not in sent_message


@pytest.mark.asyncio
async def test_weekly_summary_requires_generation(dao_admin_command, mock_interaction):
    await dao_admin_command.callback(
        mock_interaction, action="weekly_summary", generation=None
    )

    mock_interaction.followup.send.assert_called_with(
        "❌ 기수를 입력해주세요.\n예: `/dao_admin 출석현황 7`"
    )


@pytest.mark.asyncio
async def test_weekly_summary_generation7_uses_role_based_overview(
    dao_admin_command, mock_interaction, mock_guild
):
    member = _make_member(
        1001,
        name="user1",
        display_name="유저1",
        role_ids=[settings.generation_7_role_id],
    )
    mock_guild.get_role.return_value = _make_role(
        "7기", settings.generation_7_role_id, [member]
    )
    mock_interaction.guild = mock_guild

    mock_overview = {
        "up_to_week": 2,
        "weekly_counts": [{"week": 1, "count": 1}, {"week": 2, "count": 1}],
        "total_attendance": 2,
        "unique_participants": 1,
        "overall_rate": 100.0,
        "participants": [{"user_id": "1001", "weeks": [1, 2]}],
        "nicknames": {"1001": "유저1"},
    }
    mock_first_message = MagicMock()
    mock_first_message.create_thread = AsyncMock()
    mock_interaction.followup.send = AsyncMock(return_value=mock_first_message)

    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview_for_user_ids = AsyncMock(
            return_value=mock_overview
        )
        await dao_admin_command.callback(
            mock_interaction, action="weekly_summary", generation=7
        )

    mock_db.get_attendance_overview_for_user_ids.assert_awaited_once_with(["1001"])
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "7기 — 1~2주차 출석 현황" in sent_message
    assert "1. 유저1 — 2회" in sent_message


@pytest.mark.asyncio
async def test_official_crew_attendance_summary_success(
    dao_admin_command, mock_interaction, mock_guild
):
    member = _make_member(
        2001,
        name="crew1",
        display_name="크루1",
        role_ids=[settings.official_crew_role_id],
    )
    mock_guild.get_role.return_value = _make_role(
        "정식크루", settings.official_crew_role_id, [member]
    )
    mock_interaction.guild = mock_guild

    mock_overview = {
        "up_to_week": 3,
        "weekly_counts": [
            {"week": 1, "count": 1},
            {"week": 2, "count": 0},
            {"week": 3, "count": 1},
        ],
        "total_attendance": 2,
        "unique_participants": 1,
        "overall_rate": 66.7,
        "participants": [{"user_id": "2001", "weeks": [1, 3]}],
        "nicknames": {"2001": "크루1"},
    }

    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview_for_user_ids = AsyncMock(
            return_value=mock_overview
        )
        await dao_admin_command.callback(
            mock_interaction,
            action="official_crew_attendance_summary",
            generation=None,
        )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "정식크루 출석 현황 요약" in sent_message
    assert "1~3주차" in sent_message
    assert "고유 인원: 1명" in sent_message


@pytest.mark.asyncio
async def test_official_crew_attendance_summary_no_history(
    dao_admin_command, mock_interaction, mock_guild
):
    member = _make_member(
        2001,
        name="crew1",
        display_name="크루1",
        role_ids=[settings.official_crew_role_id],
    )
    mock_guild.get_role.return_value = _make_role(
        "정식크루", settings.official_crew_role_id, [member]
    )
    mock_interaction.guild = mock_guild

    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview_for_user_ids = AsyncMock(
            return_value={
                "up_to_week": 0,
                "weekly_counts": [],
                "total_attendance": 0,
                "unique_participants": 1,
                "overall_rate": 0.0,
                "participants": [{"user_id": "2001", "weeks": []}],
                "nicknames": {"2001": "크루1"},
            }
        )
        await dao_admin_command.callback(
            mock_interaction,
            action="official_crew_attendance_summary",
            generation=None,
        )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "정식크루 출석 데이터가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_gen7_points_summary_success(
    dao_admin_command, mock_interaction, mock_guild
):
    member = _make_member(
        111111111,
        name="user1",
        display_name="유저1",
        role_ids=[settings.generation_7_role_id],
    )
    mock_guild.get_role.return_value = _make_role(
        "7기", settings.generation_7_role_id, [member]
    )
    mock_interaction.guild = mock_guild

    mock_user_docs = [
        {
            "discord_id": "111111111",
            "username": "user1",
            "nickname": "유저1",
            "total_points": 1500,
        },
        {
            "discord_id": "999999999",
            "username": "user2",
            "nickname": "유저2",
            "total_points": 300,
        },
    ]

    with patch("app.commands.db") as mock_db:
        mock_db.users_collection.find.return_value = mock_user_docs

        await dao_admin_command.callback(
            mock_interaction,
            action="gen7_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "7기 포인트 집계" in sent_message
    assert "총 1명" in sent_message
    assert "유저1" in sent_message
    assert "유저2" not in sent_message


@pytest.mark.asyncio
async def test_friends_points_summary_excludes_generation7_members(
    dao_admin_command, mock_interaction, mock_guild
):
    friends_only = _make_member(
        3001,
        name="friend1",
        display_name="프렌즈1",
        role_ids=[settings.friends_role_id],
    )
    overlap_member = _make_member(
        3002,
        name="friend2",
        display_name="겹침유저",
        role_ids=[settings.friends_role_id, settings.generation_7_role_id],
    )
    mock_guild.get_role.return_value = _make_role(
        "프렌즈", settings.friends_role_id, [friends_only, overlap_member]
    )
    mock_interaction.guild = mock_guild

    mock_user_docs = [
        {
            "discord_id": "3001",
            "username": "friend1",
            "nickname": "프렌즈1",
            "total_points": 200,
        },
        {
            "discord_id": "3002",
            "username": "friend2",
            "nickname": "겹침유저",
            "total_points": 500,
        },
    ]

    with patch("app.commands.db") as mock_db:
        mock_db.users_collection.find.return_value = mock_user_docs

        await dao_admin_command.callback(
            mock_interaction,
            action="friends_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "프렌즈 포인트 집계" in sent_message
    assert "프렌즈1" in sent_message
    assert "겹침유저" not in sent_message


@pytest.mark.asyncio
async def test_grant_points_success(
    dao_admin_command,
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
):
    target_member = _make_member(
        mock_target_user.id,
        name=mock_target_user.name,
        display_name="대상유저",
        role_ids=[settings.generation_7_role_id],
    )
    mock_interaction.guild = mock_guild
    mock_interaction.user = SimpleNamespace(id=mock_admin_member.id)
    mock_guild.get_member.side_effect = lambda uid: {
        mock_admin_member.id: mock_admin_member,
        mock_target_user.id: target_member,
    }.get(uid)

    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 200])
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            mock_interaction,
            action="grant_points",
            generation=None,
            target=mock_target_user,
            amount=100,
            reason="이벤트 참여 보상",
        )

    transaction_call = mock_db.add_transaction.call_args[0][0]
    assert transaction_call.user_id == str(mock_target_user.id)
    assert transaction_call.points == 100
    mock_db.get_or_create_user.assert_awaited_once_with(
        discord_id=str(mock_target_user.id),
        username=mock_target_user.name,
        generation=7,
        nickname="대상유저",
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "포인트 지급 완료" in sent_message


@pytest.mark.asyncio
async def test_grant_points_official_crew_member_keeps_generation_unset(
    dao_admin_command,
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
):
    transitioned_target = _make_member(
        mock_target_user.id,
        name=mock_target_user.name,
        display_name="전환대상",
        role_ids=[settings.generation_7_role_id, settings.official_crew_role_id],
    )
    mock_interaction.guild = mock_guild
    mock_interaction.user = SimpleNamespace(id=mock_admin_member.id)
    mock_guild.get_member.side_effect = lambda uid: {
        mock_admin_member.id: mock_admin_member,
        mock_target_user.id: transitioned_target,
    }.get(uid)

    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 200])
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            mock_interaction,
            action="grant_points",
            generation=None,
            target=mock_target_user,
            amount=100,
            reason="운영 보정",
        )

    mock_db.get_or_create_user.assert_awaited_once_with(
        discord_id=str(mock_target_user.id),
        username=mock_target_user.name,
        generation=None,
        nickname="전환대상",
    )


@pytest.mark.asyncio
async def test_grant_points_no_admin_role(
    dao_admin_command, mock_interaction, mock_guild, mock_target_user
):
    non_admin_member = _make_member(
        111111111,
        name="non_admin",
        display_name="일반유저",
        role_ids=[],
        administrator=False,
    )
    mock_interaction.guild = mock_guild
    mock_interaction.user = SimpleNamespace(id=non_admin_member.id)
    mock_guild.get_member.return_value = non_admin_member

    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=100,
        reason="테스트",
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 관리자 권한이 필요합니다" in sent_message
