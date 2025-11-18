"""Shared pytest fixtures for all test modules.

This module contains reusable fixtures for mocking Discord objects, database operations,
and common test data. Fixtures are organized by scope and responsibility.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from discord import Interaction, Role, Member, Guild, User
from app.bot import DaoBot
from app.commands import register_commands
from app.settings import settings


# ============================================================================
# Discord Object Fixtures (function scope - lightweight, created per test)
# ============================================================================


@pytest.fixture
def mock_interaction():
    """Create a mock Discord Interaction object with response and followup."""
    interaction = MagicMock(spec=Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def mock_guild():
    """Create a mock Discord Guild object with chunking capabilities."""
    guild = MagicMock(spec=Guild)
    guild.chunked = True
    guild.chunk = AsyncMock()
    guild.get_role = MagicMock()
    guild.get_member = MagicMock()
    return guild


@pytest.fixture
def mock_role():
    """Create a mock Discord Role object for generation 6."""
    role = MagicMock(spec=Role)
    role.name = "6기"
    role.id = settings.generation_6_role_id
    role.members = []
    return role


@pytest.fixture
def mock_sherpa_role():
    """Create a mock Discord Role object for generation 6 Sherpa."""
    role = MagicMock(spec=Role)
    role.name = "6기 셰르파"
    role.id = settings.generation_6_sherpa_role_id
    role.members = []
    return role


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


# ============================================================================
# Bot and Command Fixtures (module scope - reusable across module)
# ============================================================================


@pytest.fixture(scope="module")
def bot():
    """Create a DaoBot instance with registered commands.

    Module-scoped for performance - bot setup is expensive and stateless.
    """
    bot_instance = DaoBot()
    register_commands(bot_instance)
    return bot_instance


@pytest.fixture(scope="module")
def dao_admin_command(bot):
    """Get the dao_admin command from the bot's command tree.

    Depends on bot fixture, module-scoped for performance.
    """
    for command in bot.tree.get_commands():
        if command.name == "dao_admin":
            return command
    pytest.fail("dao_admin command not found")


# ============================================================================
# Test Data Fixtures (function scope - mutable data)
# ============================================================================


@pytest.fixture
def test_user_data():
    """Provide test user data for attendance and user operations."""
    return {
        "user_id": "987654321098765432",
        "username": "TestUser",
        "generation": 6,
        "week": 1,
        "day": 1,
    }


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


# ============================================================================
# Database Mock Fixtures (function scope - stateful, needs fresh instance)
# ============================================================================


@pytest.fixture
def mock_db():
    """Provide a mocked database with common operations.

    Function-scoped to ensure test isolation - each test gets fresh state.
    """
    with (
        patch("app.commands.db") as mock_db_instance,
    ):
        # Setup common mock methods
        mock_db_instance.get_or_create_user = AsyncMock()
        mock_db_instance.get_user_points = AsyncMock(return_value=0)
        mock_db_instance.add_transaction = AsyncMock()
        mock_db_instance.get_generation_points = AsyncMock(return_value=[])
        mock_db_instance.get_attendance_overview = AsyncMock(return_value={})
        mock_db_instance.users_collection = MagicMock()
        mock_db_instance.transactions_collection = MagicMock()

        yield mock_db_instance


# ============================================================================
# Composite Setup Fixtures (function scope - combines multiple fixtures)
# ============================================================================


@pytest.fixture
def admin_interaction_setup(mock_interaction, mock_guild, mock_admin_member):
    """Setup interaction with admin user and guild.

    Composite fixture that combines common admin command test setup.
    Returns configured interaction, guild, and admin member.
    """
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(return_value=mock_admin_member)

    return {
        "interaction": mock_interaction,
        "guild": mock_guild,
        "admin": mock_admin_member,
    }


@pytest.fixture
def point_operation_setup(
    mock_interaction,
    mock_guild,
    mock_admin_member,
    mock_target_user,
    mock_target_member,
):
    """Setup for point grant/deduct operations.

    Composite fixture that configures interaction, guild, admin, and target user
    for point operation tests.
    """
    mock_interaction.guild = mock_guild
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = mock_admin_member.id
    mock_guild.get_member = MagicMock(
        side_effect=lambda uid: {
            mock_admin_member.id: mock_admin_member,
            mock_target_user.id: mock_target_member,
        }.get(uid)
    )

    return {
        "interaction": mock_interaction,
        "guild": mock_guild,
        "admin": mock_admin_member,
        "target_user": mock_target_user,
        "target_member": mock_target_member,
    }


# ============================================================================
# Parametrized Fixtures (for data-driven tests)
# ============================================================================


@pytest.fixture(
    params=[
        {"generation": 6, "week": 1, "day": 1},
        {"generation": 6, "week": 2, "day": 3},
        {"generation": 6, "week": 3, "day": 5},
    ]
)
def attendance_metadata(request):
    """Parametrized fixture for various attendance metadata scenarios."""
    return request.param


# ============================================================================
# Cleanup Fixtures (using yield for teardown)
# ============================================================================


@pytest.fixture
def cleanup_db():
    """Fixture demonstrating setup/teardown pattern with yield.

    Use this pattern when you need explicit cleanup after tests.
    """
    # Setup
    db_state = {"connected": True}

    yield db_state

    # Teardown
    db_state["connected"] = False
