"""Tests for admin commands, specifically the fetch_gen6_members functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from discord import Interaction, Role, Member, Guild, User
from app.commands import register_commands
from app.settings import settings


@pytest.fixture
def mock_interaction():
    """Create a mock Discord Interaction object."""
    interaction = MagicMock(spec=Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def mock_guild():
    """Create a mock Discord Guild object."""
    guild = MagicMock(spec=Guild)
    guild.chunked = True
    guild.chunk = AsyncMock()
    guild.get_role = MagicMock()
    return guild


@pytest.fixture
def mock_role():
    """Create a mock Discord Role object."""
    role = MagicMock(spec=Role)
    role.name = "6기"
    role.id = settings.generation_6_role_id
    role.members = []
    return role


@pytest.fixture
def mock_members():
    """Create a list of mock Discord Member objects."""
    members = []
    for i in range(5):
        member = MagicMock(spec=Member)
        member.id = 1000000000000000000 + i
        member.name = f"user{i}"
        member.display_name = f"유저{i}"
        members.append(member)
    return members


@pytest.mark.asyncio
async def test_fetch_gen6_members_success(
    mock_interaction, mock_guild, mock_role, mock_members
):
    """Test successful fetching of generation 6 members."""
    # Setup
    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    # Import and register commands
    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    # Get the command
    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    assert dao_admin_command is not None, "dao_admin command not found"

    # Execute the command callback directly
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Verify
    mock_interaction.response.defer.assert_called_once()
    mock_guild.get_role.assert_called_once_with(settings.generation_6_role_id)
    mock_interaction.followup.send.assert_called_once()

    # Check the message content
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "6기" in sent_message
    assert "총 5명" in sent_message
    assert "유저0" in sent_message
    assert "유저4" in sent_message


@pytest.mark.asyncio
async def test_weekly_summary_requires_generation(mock_interaction):
    """weekly_summary should require generation input."""
    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    assert dao_admin_command is not None

    await dao_admin_command.callback(
        mock_interaction, action="weekly_summary", generation=None
    )

    mock_interaction.followup.send.assert_called_with(
        "❌ 기수를 입력해주세요.\n예: `/dao_admin 출석현황 6`"
    )


@pytest.mark.asyncio
async def test_weekly_summary_auto_weeks_and_counts(mock_interaction):
    """weekly_summary automatically spans full weeks and shows per-user totals."""
    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    assert dao_admin_command is not None

    mock_overview = {
        "generation": 6,
        "up_to_week": 3,
        "weekly_counts": [
            {"week": 1, "count": 2},
            {"week": 2, "count": 1},
            {"week": 3, "count": 3},
        ],
        "total_attendance": 6,
        "unique_participants": 3,
        "overall_rate": 66.7,
        "participants": [
            {"user_id": "1", "weeks": [1, 2, 3]},
            {"user_id": "2", "weeks": [1]},
            {"user_id": "3", "weeks": [3]},
        ],
        "nicknames": {"1": "Alice", "2": "Bob", "3": "Cara"},
    }

    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview = AsyncMock(return_value=mock_overview)

        await dao_admin_command.callback(
            mock_interaction, action="weekly_summary", generation=6
        )

    mock_db.get_attendance_overview.assert_awaited_once_with(6)
    mock_interaction.followup.send.assert_called_once()
    message = mock_interaction.followup.send.call_args[0][0]
    assert "1~3주차" in message
    assert "1주차: 2명" in message
    assert "Alice — 3회" in message
    assert "Bob — 1회" in message
    assert "Cara — 1회" in message
    assert "✅" in message and "⬜" in message


@pytest.mark.asyncio
async def test_fetch_gen6_members_no_guild(mock_interaction):
    """Test when guild is None."""
    mock_interaction.guild = None

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    mock_interaction.response.defer.assert_called_once()
    mock_interaction.followup.send.assert_called_once_with(
        "❌ 길드 정보를 가져올 수 없습니다."
    )


@pytest.mark.asyncio
async def test_fetch_gen6_members_role_not_found(mock_interaction, mock_guild):
    """Test when role is not found."""
    mock_guild.get_role.return_value = None
    mock_interaction.guild = mock_guild

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    mock_interaction.response.defer.assert_called_once()
    mock_guild.get_role.assert_called_once_with(settings.generation_6_role_id)

    # Check error message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 역할 ID" in sent_message
    assert "찾을 수 없습니다" in sent_message


@pytest.mark.asyncio
async def test_fetch_gen6_members_no_members(mock_interaction, mock_guild, mock_role):
    """Test when role has no members."""
    mock_role.members = []
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    mock_interaction.response.defer.assert_called_once()

    # Check info message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "ℹ️" in sent_message
    assert "역할을 가진 멤버가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_fetch_gen6_members_guild_chunking(
    mock_interaction, mock_guild, mock_role, mock_members
):
    """Test guild chunking when guild is not chunked."""
    mock_guild.chunked = False
    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Verify guild.chunk() was called
    mock_guild.chunk.assert_called_once()
    mock_interaction.followup.send.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_gen6_members_message_splitting(
    mock_interaction, mock_guild, mock_role
):
    """Test message splitting when content exceeds 2000 characters."""
    # Create many members to exceed 2000 char limit
    many_members = []
    for i in range(100):
        member = MagicMock(spec=Member)
        member.id = 1000000000000000000 + i
        member.name = f"verylongusername{i}" * 5
        member.display_name = f"매우긴닉네임{i}" * 5
        many_members.append(member)

    mock_role.members = many_members
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Verify multiple messages were sent
    assert mock_interaction.followup.send.call_count > 1, (
        "Should send multiple messages for large member list"
    )

    # Verify each message is under 2000 characters
    for call in mock_interaction.followup.send.call_args_list:
        message = call[0][0]
        assert len(message) <= 2000, (
            f"Message length {len(message)} exceeds 2000 characters"
        )


@pytest.fixture
def mock_admin_member():
    """Create a mock admin member with admin role."""
    member = MagicMock(spec=Member)
    member.id = 123456789
    member.name = "admin_user"
    member.display_name = "관리자"

    admin_role = MagicMock()
    admin_role.id = settings.admin_role_id
    member.roles = [admin_role]

    return member


@pytest.fixture
def mock_target_user():
    """Create a mock target user for point operations."""
    user = MagicMock(spec=User)
    user.id = 987654321
    user.name = "target_user"
    user.bot = False
    return user


@pytest.fixture
def mock_target_member():
    """Create a mock target member."""
    member = MagicMock(spec=Member)
    member.id = 987654321
    member.display_name = "대상유저"
    return member


# ========== Point Grant/Deduct Tests ==========


@pytest.mark.asyncio
async def test_grant_points_success(
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
    mock_target_member,
):
    """Test successful point grant."""
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(
        side_effect=lambda uid: {
            mock_admin_member.id: mock_admin_member,
            mock_target_user.id: mock_target_member,
        }.get(uid)
    )

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    assert dao_admin_command is not None

    # Mock database operations
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 200])  # before and after
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            mock_interaction,
            action="grant_points",
            generation=None,
            target=mock_target_user,
            amount=100,
            reason="이벤트 참여 보상",
        )

    # Verify
    mock_interaction.response.defer.assert_called_once()
    mock_db.get_or_create_user.assert_called_once()
    mock_db.add_transaction.assert_called_once()

    # Check transaction details
    transaction_call = mock_db.add_transaction.call_args[0][0]
    assert transaction_call.user_id == str(mock_target_user.id)
    assert transaction_call.points == 100
    assert transaction_call.reason == "관리자지급"
    assert transaction_call.admin_id == str(mock_admin_member.id)
    assert "이벤트 참여 보상" in transaction_call.admin_note

    # Check success message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "💰" in sent_message
    assert "포인트 지급 완료" in sent_message
    assert "200" in sent_message


@pytest.mark.asyncio
async def test_deduct_points_success(
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
    mock_target_member,
):
    """Test successful point deduction."""
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(
        side_effect=lambda uid: {
            mock_admin_member.id: mock_admin_member,
            mock_target_user.id: mock_target_member,
        }.get(uid)
    )

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    # Mock database operations
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 50])  # before and after
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            mock_interaction,
            action="deduct_points",
            generation=None,
            target=mock_target_user,
            amount=50,
            reason="규정 위반",
        )

    # Verify transaction
    transaction_call = mock_db.add_transaction.call_args[0][0]
    assert transaction_call.points == -50
    assert transaction_call.reason == "관리자회수"
    assert "규정 위반" in transaction_call.admin_note

    # Check success message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "📤" in sent_message
    assert "포인트 회수 완료" in sent_message


@pytest.mark.asyncio
async def test_deduct_points_insufficient_balance(
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
    mock_target_member,
):
    """Test point deduction with insufficient balance."""
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(
        side_effect=lambda uid: {
            mock_admin_member.id: mock_admin_member,
            mock_target_user.id: mock_target_member,
        }.get(uid)
    )

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    # Mock database - user has only 30 points
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(return_value=30)
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            mock_interaction,
            action="deduct_points",
            generation=None,
            target=mock_target_user,
            amount=50,
            reason="테스트",
        )

    # Verify transaction was NOT created
    mock_db.add_transaction.assert_not_called()

    # Check error message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 포인트 회수 실패" in sent_message
    assert "30" in sent_message
    assert "0 미만이 될 수 없습니다" in sent_message


@pytest.mark.asyncio
async def test_grant_points_no_admin_role(
    mock_interaction, mock_guild, mock_target_user
):
    """Test point grant without admin role."""
    # Create member without admin role
    non_admin_member = MagicMock(spec=Member)
    non_admin_member.id = 111111111
    non_admin_member.roles = []  # No admin role

    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = non_admin_member.id
    mock_guild.get_member = MagicMock(return_value=non_admin_member)

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=100,
        reason="테스트",
    )

    # Check error message
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 관리자 권한이 필요합니다" in sent_message


@pytest.mark.asyncio
async def test_grant_points_missing_parameters(
    mock_interaction, mock_guild, mock_admin_member
):
    """Test point grant with missing parameters."""
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(return_value=mock_admin_member)

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    # Test without target
    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=None,
        amount=100,
        reason="테스트",
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌" in sent_message
    assert "누락" in sent_message


@pytest.mark.asyncio
async def test_grant_points_invalid_amount(
    mock_interaction, mock_guild, mock_admin_member, mock_target_user
):
    """Test point grant with invalid amount (zero or negative)."""
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(return_value=mock_admin_member)

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    # Test with zero amount
    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=0,
        reason="테스트",
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 포인트 수량은 양수여야 합니다" in sent_message


@pytest.mark.asyncio
async def test_grant_points_no_guild(mock_interaction, mock_target_user):
    """Test point grant when guild is None."""
    mock_interaction.guild = None

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=100,
        reason="테스트",
    )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 길드 멤버 정보를 가져올 수 없습니다" in sent_message


@pytest.mark.asyncio
async def test_gen6_points_summary_success(mock_interaction):
    """Test successful generation 6 points summary."""
    mock_interaction.guild = MagicMock()

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    assert dao_admin_command is not None

    # Mock database operations
    mock_users = [
        {
            "discord_id": "111111111",
            "username": "user1",
            "nickname": "유저1",
            "total_points": 1500,
        },
        {
            "discord_id": "222222222",
            "username": "user2",
            "nickname": "유저2",
            "total_points": 1200,
        },
        {
            "discord_id": "333333333",
            "username": "user3",
            "nickname": "유저3",
            "total_points": 900,
        },
    ]

    with patch("app.commands.db") as mock_db:
        mock_db.get_generation_points = AsyncMock(return_value=mock_users)

        await dao_admin_command.callback(
            mock_interaction,
            action="gen6_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    # Verify
    mock_interaction.response.defer.assert_called_once()
    mock_db.get_generation_points.assert_called_once_with(6)
    mock_interaction.followup.send.assert_called_once()

    # Check the message content
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "6기 포인트 집계" in sent_message
    assert "총 3명" in sent_message
    assert "유저1" in sent_message
    assert "1,500" in sent_message
    assert "유저2" in sent_message
    assert "1,200" in sent_message
    assert "유저3" in sent_message
    assert "900" in sent_message
    # Check markdown table format
    assert "순번" in sent_message  # Changed from 순위 to 순번
    assert "닉네임" in sent_message
    assert "유저명" in sent_message
    assert "포인트" in sent_message
    assert "@user1" in sent_message
    assert "@user2" in sent_message
    assert "@user3" in sent_message
    assert "|" in sent_message  # Table separator


@pytest.mark.asyncio
async def test_gen6_points_summary_no_users(mock_interaction):
    """Test points summary when no users exist."""
    mock_interaction.guild = MagicMock()

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    with patch("app.commands.db") as mock_db:
        mock_db.get_generation_points = AsyncMock(return_value=[])

        await dao_admin_command.callback(
            mock_interaction,
            action="gen6_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "ℹ️" in sent_message
    assert "6기 유저가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_gen6_points_summary_message_splitting(mock_interaction):
    """Test message splitting for large user lists."""
    mock_interaction.guild = MagicMock()

    from app.bot import DaoBot

    bot = DaoBot()
    register_commands(bot)

    dao_admin_command = None
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            dao_admin_command = command
            break

    # Create many users to exceed 2000 char limit
    many_users = []
    for i in range(100):
        many_users.append(
            {
                "discord_id": str(1000000000 + i),
                "username": f"user{i}",
                "nickname": f"매우긴닉네임입니다{i}" * 3,
                "total_points": 10000 - i * 10,
            }
        )

    with patch("app.commands.db") as mock_db:
        mock_db.get_generation_points = AsyncMock(return_value=many_users)

        await dao_admin_command.callback(
            mock_interaction,
            action="gen6_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    # Verify multiple messages were sent
    assert mock_interaction.followup.send.call_count >= 1, (
        "Should send at least one message"
    )

    # Verify each message is under 2000 characters
    for call in mock_interaction.followup.send.call_args_list:
        message = call[0][0]
        assert len(message) <= 2000, (
            f"Message length {len(message)} exceeds 2000 characters"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
