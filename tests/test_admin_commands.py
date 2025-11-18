"""Tests for admin commands, specifically the fetch_gen6_members functionality.

Refactored to use shared fixtures from conftest.py for better maintainability
and consistency across test files.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from discord import Member
from app.settings import settings


# ============================================================================
# Generation 6 Member Fetch Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_fetch_gen6_members_successfully_when_role_has_members(
    mock_interaction, mock_guild, mock_role, mock_members, dao_admin_command
):
    """Test successful fetching of generation 6 members."""
    # Arrange
    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_guild.get_role.assert_called_once_with(settings.generation_6_role_id)
    mock_interaction.followup.send.assert_called_once()

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "6기" in sent_message
    assert "총 5명" in sent_message
    assert "유저0" in sent_message
    assert "유저4" in sent_message


@pytest.mark.asyncio
async def test_should_return_error_when_guild_is_none(
    mock_interaction, dao_admin_command
):
    """Test when guild is None."""
    # Arrange
    mock_interaction.guild = None

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_interaction.followup.send.assert_called_once_with(
        "❌ 길드 정보를 가져올 수 없습니다."
    )


@pytest.mark.asyncio
async def test_should_return_error_when_role_not_found(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test when role is not found."""
    # Arrange
    mock_guild.get_role.return_value = None
    mock_interaction.guild = mock_guild

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_guild.get_role.assert_called_once_with(settings.generation_6_role_id)

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 역할 ID" in sent_message
    assert "찾을 수 없습니다" in sent_message


@pytest.mark.asyncio
async def test_should_return_info_message_when_role_has_no_members(
    mock_interaction, mock_guild, mock_role, dao_admin_command
):
    """Test when role has no members."""
    # Arrange
    mock_role.members = []
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    mock_interaction.response.defer.assert_called_once()

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "ℹ️" in sent_message
    assert "역할을 가진 멤버가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_should_call_guild_chunk_when_guild_is_not_chunked(
    mock_interaction, mock_guild, mock_role, mock_members, dao_admin_command
):
    """Test guild chunking when guild is not chunked."""
    # Arrange
    mock_guild.chunked = False
    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role
    mock_interaction.guild = mock_guild

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    mock_guild.chunk.assert_called_once()
    mock_interaction.followup.send.assert_called_once()


@pytest.mark.asyncio
async def test_should_split_messages_when_content_exceeds_2000_characters(
    mock_interaction, mock_guild, mock_role, dao_admin_command
):
    """Test message splitting when content exceeds 2000 characters."""
    # Arrange
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

    # Act
    await dao_admin_command.callback(
        mock_interaction, action="fetch_gen6_members", generation=None
    )

    # Assert
    assert mock_interaction.followup.send.call_count > 1, (
        "Should send multiple messages for large member list"
    )

    for call in mock_interaction.followup.send.call_args_list:
        message = call[0][0]
        assert len(message) <= 2000, (
            f"Message length {len(message)} exceeds 2000 characters"
        )


# ============================================================================
# Weekly Summary Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_require_generation_when_requesting_weekly_summary(
    mock_interaction, dao_admin_command
):
    """weekly_summary should require generation input."""
    # Act
    await dao_admin_command.callback(
        mock_interaction, action="weekly_summary", generation=None
    )

    # Assert
    mock_interaction.followup.send.assert_called_with(
        "❌ 기수를 입력해주세요.\n예: `/dao_admin 출석현황 6`"
    )


@pytest.mark.asyncio
async def test_should_show_weekly_summary_with_auto_weeks_and_counts_when_valid_generation(
    mock_interaction, dao_admin_command
):
    """weekly_summary automatically spans full weeks and shows per-user totals."""
    # Arrange
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

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview = AsyncMock(return_value=mock_overview)

        await dao_admin_command.callback(
            mock_interaction, action="weekly_summary", generation=6
        )

    # Assert
    mock_db.get_attendance_overview.assert_awaited_once_with(6)
    mock_interaction.followup.send.assert_called_once()
    message = mock_interaction.followup.send.call_args[0][0]
    assert "1~3주차" in message
    assert "1주차: 2명" in message
    assert "1. Alice — 3회" in message
    assert "2. Bob — 1회" in message
    assert "3. Cara — 1회" in message
    assert "✅" in message and "⬜" in message
    assert "```" in message


@pytest.mark.asyncio
async def test_should_create_thread_when_weekly_summary_messages_are_split(
    mock_interaction, dao_admin_command
):
    """Test that weekly_summary creates a thread when messages are split."""
    # Arrange
    participants = []
    nicknames = {}
    for i in range(50):
        user_id = str(1000 + i)
        participants.append({"user_id": user_id, "weeks": [1, 2, 3]})
        nicknames[user_id] = f"User{i:03d}"

    mock_overview = {
        "generation": 6,
        "up_to_week": 10,
        "weekly_counts": [{"week": w, "count": 45} for w in range(1, 11)],
        "total_attendance": 450,
        "unique_participants": 50,
        "overall_rate": 90.0,
        "participants": participants,
        "nicknames": nicknames,
    }

    mock_thread = MagicMock()
    mock_thread.send = AsyncMock()

    mock_first_message = MagicMock()
    mock_first_message.create_thread = AsyncMock(return_value=mock_thread)

    mock_interaction.followup.send = AsyncMock(return_value=mock_first_message)

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview = AsyncMock(return_value=mock_overview)

        await dao_admin_command.callback(
            mock_interaction, action="weekly_summary", generation=6
        )

    # Assert
    mock_interaction.followup.send.assert_called_once()

    if mock_first_message.create_thread.called:
        mock_first_message.create_thread.assert_called_once()
        thread_name = mock_first_message.create_thread.call_args[1]["name"]
        assert thread_name == "6기 출석 현황"
        assert mock_thread.send.call_count > 0


@pytest.mark.asyncio
async def test_should_handle_duplicate_nicknames_with_sub_numbering_when_weekly_summary(
    mock_interaction, dao_admin_command
):
    """Test weekly_summary handles duplicate nicknames with sub-numbering."""
    # Arrange
    mock_overview = {
        "generation": 6,
        "up_to_week": 2,
        "weekly_counts": [
            {"week": 1, "count": 3},
            {"week": 2, "count": 2},
        ],
        "total_attendance": 5,
        "unique_participants": 4,
        "overall_rate": 62.5,
        "participants": [
            {"user_id": "1", "weeks": [1, 2]},
            {"user_id": "2", "weeks": [1]},
            {"user_id": "3", "weeks": [1, 2]},
            {"user_id": "4", "weeks": [2]},
        ],
        "nicknames": {
            "1": "Alice",
            "2": "Alice",
            "3": "Bob",
            "4": "Bob",
        },
    }

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_attendance_overview = AsyncMock(return_value=mock_overview)

        await dao_admin_command.callback(
            mock_interaction, action="weekly_summary", generation=6
        )

    # Assert
    message = mock_interaction.followup.send.call_args[0][0]
    assert "1-1. Alice" in message or "1. Alice" in message
    assert "1-2. Alice" in message or "2. Alice" in message
    assert "Bob" in message


# ============================================================================
# Point Grant/Deduct Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_grant_points_successfully_when_valid_admin_and_target(
    point_operation_setup, dao_admin_command
):
    """Test successful point grant."""
    # Arrange
    setup = point_operation_setup

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 200])
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            setup["interaction"],
            action="grant_points",
            generation=None,
            target=setup["target_user"],
            amount=100,
            reason="이벤트 참여 보상",
        )

    # Assert
    setup["interaction"].response.defer.assert_called_once()
    mock_db.get_or_create_user.assert_called_once()
    mock_db.add_transaction.assert_called_once()

    transaction_call = mock_db.add_transaction.call_args[0][0]
    assert transaction_call.user_id == str(setup["target_user"].id)
    assert transaction_call.points == 100
    assert transaction_call.reason == "관리자지급"
    assert transaction_call.admin_id == str(setup["admin"].id)
    assert "이벤트 참여 보상" in transaction_call.admin_note

    sent_message = setup["interaction"].followup.send.call_args[0][0]
    assert "💰" in sent_message
    assert "포인트 지급 완료" in sent_message
    assert "200" in sent_message


@pytest.mark.asyncio
async def test_should_deduct_points_successfully_when_sufficient_balance(
    point_operation_setup, dao_admin_command
):
    """Test successful point deduction."""
    # Arrange
    setup = point_operation_setup

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(side_effect=[100, 50])
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            setup["interaction"],
            action="deduct_points",
            generation=None,
            target=setup["target_user"],
            amount=50,
            reason="규정 위반",
        )

    # Assert
    transaction_call = mock_db.add_transaction.call_args[0][0]
    assert transaction_call.points == -50
    assert transaction_call.reason == "관리자회수"
    assert "규정 위반" in transaction_call.admin_note

    sent_message = setup["interaction"].followup.send.call_args[0][0]
    assert "📤" in sent_message
    assert "포인트 회수 완료" in sent_message


@pytest.mark.asyncio
async def test_should_fail_to_deduct_points_when_insufficient_balance(
    point_operation_setup, dao_admin_command
):
    """Test point deduction with insufficient balance."""
    # Arrange
    setup = point_operation_setup

    # Act
    with patch("app.commands.db") as mock_db:
        mock_db.get_or_create_user = AsyncMock()
        mock_db.get_user_points = AsyncMock(return_value=30)
        mock_db.add_transaction = AsyncMock()

        await dao_admin_command.callback(
            setup["interaction"],
            action="deduct_points",
            generation=None,
            target=setup["target_user"],
            amount=50,
            reason="테스트",
        )

    # Assert
    mock_db.add_transaction.assert_not_called()

    sent_message = setup["interaction"].followup.send.call_args[0][0]
    assert "❌ 포인트 회수 실패" in sent_message
    assert "30" in sent_message
    assert "0 미만이 될 수 없습니다" in sent_message


@pytest.mark.asyncio
async def test_should_reject_when_user_has_no_admin_role(
    mock_interaction, mock_guild, mock_target_user, dao_admin_command
):
    """Test point grant without admin role."""
    # Arrange
    non_admin_member = MagicMock(spec=Member)
    non_admin_member.id = 111111111
    non_admin_member.roles = []

    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = non_admin_member.id
    mock_guild.get_member = MagicMock(return_value=non_admin_member)

    # Act
    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=100,
        reason="테스트",
    )

    # Assert
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 관리자 권한이 필요합니다" in sent_message


@pytest.mark.asyncio
async def test_should_reject_when_required_parameters_are_missing(
    admin_interaction_setup, dao_admin_command
):
    """Test point grant with missing parameters."""
    # Arrange
    setup = admin_interaction_setup

    # Act
    await dao_admin_command.callback(
        setup["interaction"],
        action="grant_points",
        generation=None,
        target=None,
        amount=100,
        reason="테스트",
    )

    # Assert
    sent_message = setup["interaction"].followup.send.call_args[0][0]
    assert "❌" in sent_message
    assert "누락" in sent_message


@pytest.mark.asyncio
async def test_should_reject_when_amount_is_zero_or_negative(
    admin_interaction_setup, mock_target_user, dao_admin_command
):
    """Test point grant with invalid amount (zero or negative)."""
    # Arrange
    setup = admin_interaction_setup

    # Act
    await dao_admin_command.callback(
        setup["interaction"],
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=0,
        reason="테스트",
    )

    # Assert
    sent_message = setup["interaction"].followup.send.call_args[0][0]
    assert "❌ 포인트 수량은 양수여야 합니다" in sent_message


@pytest.mark.asyncio
async def test_should_return_error_when_guild_info_unavailable(
    mock_interaction, mock_target_user, dao_admin_command
):
    """Test point grant when guild is None."""
    # Arrange
    mock_interaction.guild = None

    # Act
    await dao_admin_command.callback(
        mock_interaction,
        action="grant_points",
        generation=None,
        target=mock_target_user,
        amount=100,
        reason="테스트",
    )

    # Assert
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 길드 멤버 정보를 가져올 수 없습니다" in sent_message


# ============================================================================
# Generation 6 Points Summary Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_show_gen6_points_summary_successfully_when_users_exist(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test successful generation 6 points summary."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True

    mock_role = MagicMock()
    mock_role.name = "6기"
    mock_role.id = settings.generation_6_role_id

    mock_members = []
    for i in range(1, 4):
        member = MagicMock(spec=Member)
        member.id = int(f"11111111{i}")
        mock_members.append(member)

    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role

    mock_users = [
        {
            "discord_id": "111111111",
            "username": "user1",
            "nickname": "유저1",
            "total_points": 1500,
        },
        {
            "discord_id": "111111112",
            "username": "user2",
            "nickname": "유저2",
            "total_points": 1200,
        },
        {
            "discord_id": "111111113",
            "username": "user3",
            "nickname": "유저3",
            "total_points": 900,
        },
    ]

    # Act
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

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_db.get_generation_points.assert_called_once_with(6)
    mock_interaction.followup.send.assert_called_once()

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "6기 포인트 집계" in sent_message
    assert "총 3명" in sent_message
    assert "유저1" in sent_message
    assert "1,500" in sent_message
    assert "유저2" in sent_message
    assert "1,200" in sent_message
    assert "유저3" in sent_message
    assert "900" in sent_message
    assert "순번" in sent_message
    assert "닉네임" in sent_message
    assert "유저명" in sent_message
    assert "포인트" in sent_message
    assert "@user1" in sent_message
    assert "@user2" in sent_message
    assert "@user3" in sent_message
    assert "|" in sent_message


@pytest.mark.asyncio
async def test_should_show_info_message_when_no_gen6_users_exist(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test points summary when no users exist."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True

    mock_role = MagicMock()
    mock_role.name = "6기"
    mock_role.id = settings.generation_6_role_id
    mock_role.members = []
    mock_guild.get_role.return_value = mock_role

    # Act
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

    # Assert
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "ℹ️" in sent_message
    assert "역할을 가진 멤버가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_should_split_messages_when_gen6_points_summary_exceeds_limit(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test message splitting for large user lists."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True

    mock_role = MagicMock()
    mock_role.name = "6기"
    mock_role.id = settings.generation_6_role_id
    mock_members = []
    for i in range(100):
        member = MagicMock(spec=Member)
        member.id = 1000000000 + i
        mock_members.append(member)
    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role

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

    # Act
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

    # Assert
    assert mock_interaction.followup.send.call_count >= 1, (
        "Should send at least one message"
    )

    for call in mock_interaction.followup.send.call_args_list:
        message = call[0][0]
        assert len(message) <= 2000, (
            f"Message length {len(message)} exceeds 2000 characters"
        )


# ============================================================================
# Generation 6 Sherpa Points Summary Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_show_gen6_sherpa_points_summary_successfully_when_sherpas_exist(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test successful generation 6 Sherpa points summary (role only, not filtered by generation)."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True

    mock_role = MagicMock()
    mock_role.name = "6기 셰르파"
    mock_role.id = settings.generation_6_sherpa_role_id

    mock_members = []
    for i in range(1, 4):
        member = MagicMock(spec=Member)
        member.id = int(f"55555555{i}")
        mock_members.append(member)

    mock_role.members = mock_members
    mock_guild.get_role.return_value = mock_role

    mock_user_docs = [
        {
            "discord_id": "555555551",
            "username": "sherpa1",
            "nickname": "셰르파1",
            "total_points": 2000,
        },
        {
            "discord_id": "555555552",
            "username": "sherpa2",
            "nickname": "셰르파2",
            "total_points": 1800,
        },
        {
            "discord_id": "555555553",
            "username": "sherpa3",
            "nickname": "셰르파3",
            "total_points": 1600,
        },
        {
            "discord_id": "999999999",
            "username": "regular_user",
            "nickname": "일반유저",
            "total_points": 1400,
        },
    ]

    # Act
    with patch("app.commands.db") as mock_db:
        mock_cursor = MagicMock()
        mock_cursor.to_list = MagicMock(return_value=mock_user_docs)
        mock_db.users_collection.find.return_value = mock_cursor

        await dao_admin_command.callback(
            mock_interaction,
            action="gen6_sherpa_points_summary",
            generation=None,
            target=None,
            amount=None,
            reason=None,
        )

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_db.users_collection.find.assert_called_once_with({})
    mock_interaction.followup.send.assert_called_once()

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "6기 셰르파 포인트 집계" in sent_message
    assert "총 3명" in sent_message
    assert "셰르파1" in sent_message
    assert "2,000" in sent_message
    assert "셰르파2" in sent_message
    assert "1,800" in sent_message
    assert "셰르파3" in sent_message
    assert "1,600" in sent_message
    assert "일반유저" not in sent_message
    assert "1,400" not in sent_message
    assert "순번" in sent_message
    assert "닉네임" in sent_message
    assert "유저명" in sent_message
    assert "포인트" in sent_message
    assert "@sherpa1" in sent_message
    assert "@sherpa2" in sent_message
    assert "@sherpa3" in sent_message
    assert "|" in sent_message


@pytest.mark.asyncio
async def test_should_show_info_message_when_no_sherpas_exist(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test Sherpa points summary when no Sherpas exist."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True

    mock_role = MagicMock()
    mock_role.name = "6기 셰르파"
    mock_role.id = settings.generation_6_sherpa_role_id
    mock_role.members = []
    mock_guild.get_role.return_value = mock_role

    # Act
    await dao_admin_command.callback(
        mock_interaction,
        action="gen6_sherpa_points_summary",
        generation=None,
        target=None,
        amount=None,
        reason=None,
    )

    # Assert
    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "ℹ️" in sent_message
    assert "역할을 가진 멤버가 없습니다" in sent_message


@pytest.mark.asyncio
async def test_should_return_error_when_sherpa_role_not_found(
    mock_interaction, mock_guild, dao_admin_command
):
    """Test when Sherpa role is not found."""
    # Arrange
    mock_interaction.guild = mock_guild
    mock_guild.chunked = True
    mock_guild.get_role.return_value = None

    # Act
    await dao_admin_command.callback(
        mock_interaction,
        action="gen6_sherpa_points_summary",
        generation=None,
        target=None,
        amount=None,
        reason=None,
    )

    # Assert
    mock_interaction.response.defer.assert_called_once()
    mock_guild.get_role.assert_called_once_with(settings.generation_6_sherpa_role_id)

    sent_message = mock_interaction.followup.send.call_args[0][0]
    assert "❌ 역할 ID" in sent_message
    assert "찾을 수 없습니다" in sent_message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
