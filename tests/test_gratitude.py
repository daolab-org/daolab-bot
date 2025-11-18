"""Tests for gratitude feature using mocked database.

All tests use MockDatabase to avoid side effects from real DB connections.
"""

import sys
import os
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.gratitude_service import gratitude_service
from app.models import User, Gratitude

import pytest


class MockDatabase:
    """Mock database for testing without side effects"""

    def __init__(self):
        self.users: dict[str, User] = {}
        self.gratitudes: list[Gratitude] = []
        self.transactions: list[dict[str, Any]] = []
        self.user_points: dict[str, int] = {}

    @property
    def gratitude_collection(self):
        return MockGratitudeCollection(self.gratitudes)

    def ensure_connected(self) -> None:
        pass

    async def get_or_create_user(
        self,
        discord_id: str,
        username: str,
        generation: int | None = None,
        nickname: str | None = None,
    ) -> User:
        if discord_id not in self.users:
            self.users[discord_id] = User(
                discord_id=discord_id,
                username=username,
                generation=generation or 6,
                nickname=nickname or username,
                total_points=0,
            )
        return self.users[discord_id]

    async def count_gratitude_sent_today(self, from_user_id: str) -> int:
        return sum(
            1
            for g in self.gratitudes
            if g.from_user_id == from_user_id and g.date == "2025-01-15"
        )

    async def send_gratitude(
        self, from_user_id: str, to_user_id: str, message: str | None = None
    ) -> Gratitude | None:
        sent_count = await self.count_gratitude_sent_today(from_user_id)
        if sent_count >= 2:
            return None

        gratitude = Gratitude(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            date="2025-01-15",
            slot=sent_count + 1,
            message=message,
        )
        self.gratitudes.append(gratitude)

        # Update points
        self.user_points[from_user_id] = self.user_points.get(from_user_id, 0) + 5
        self.user_points[to_user_id] = self.user_points.get(to_user_id, 0) + 5

        return gratitude

    async def get_user_points(self, discord_id: str) -> int:
        return self.user_points.get(discord_id, 0)

    async def get_gratitude_summary(self, user_id: str) -> dict[str, Any]:
        total_sent = sum(1 for g in self.gratitudes if g.from_user_id == user_id)
        total_received = sum(1 for g in self.gratitudes if g.to_user_id == user_id)
        sent_today_count = await self.count_gratitude_sent_today(user_id)

        return {
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": sent_today_count >= 1,
            "sent_today_count": sent_today_count,
            "remaining_today": max(0, 2 - sent_today_count),
            "points_from_sent": total_sent * 5,
            "points_from_received": total_received * 5,
        }

    async def check_gratitude_sent_today(self, from_user_id: str) -> bool:
        count = await self.count_gratitude_sent_today(from_user_id)
        return count >= 1


class MockGratitudeCollection:
    """Mock gratitude collection for history queries"""

    def __init__(self, gratitudes: list[Gratitude]):
        self.gratitudes = gratitudes

    def find(self, query: dict[str, Any]):
        filtered = []
        for g in self.gratitudes:
            match = True
            if "from_user_id" in query and g.from_user_id != query["from_user_id"]:
                match = False
            if "to_user_id" in query and g.to_user_id != query["to_user_id"]:
                match = False
            if match:
                filtered.append(g)
        return MockCursor(filtered)

    def count_documents(self, query: dict[str, Any]) -> int:
        count = 0
        for g in self.gratitudes:
            match = True
            if "from_user_id" in query and g.from_user_id != query["from_user_id"]:
                match = False
            if "to_user_id" in query and g.to_user_id != query["to_user_id"]:
                match = False
            if match:
                count += 1
        return count

    def aggregate(self, pipeline: list[dict[str, Any]]):
        # Simple mock for aggregation used in stats
        result = []
        for g in self.gratitudes:
            if pipeline and "$match" in pipeline[0]:
                match_criteria = pipeline[0]["$match"]
                if "from_user_id" in match_criteria:
                    if g.from_user_id == match_criteria["from_user_id"]:
                        result.append({"_id": g.to_user_id, "count": 1})
        return result


class MockCursor:
    """Mock cursor for database queries"""

    def __init__(self, data: list[Any]):
        self.data = data

    def sort(self, *args, **kwargs):
        return self

    def limit(self, count: int):
        self.data = self.data[:count]
        return self

    def __iter__(self):
        for item in self.data:
            yield {
                "from_user_id": item.from_user_id,
                "to_user_id": item.to_user_id,
                "date": item.date,
                "points": 5,
            }


@pytest.fixture
def mock_db():
    """Fixture to provide fresh mock database for each test"""
    return MockDatabase()


@pytest.fixture
def setup_service(mock_db, monkeypatch):
    """Fixture to setup service with mocked database"""
    monkeypatch.setattr(gratitude_service, "db", mock_db)
    return gratitude_service


@pytest.mark.asyncio
async def test_should_send_gratitude_successfully_when_valid_users(setup_service):
    """Test: Should send gratitude successfully when valid users provided"""
    # Arrange
    from_id = "123456789012345678"
    to_id = "123456789012345679"
    from_username = "TestUser1"
    to_username = "TestUser2"

    # Act
    result = await setup_service.send_gratitude(
        from_id, from_username, to_id, to_username
    )

    # Assert
    assert result["success"] is True
    assert "감사를 전했습니다" in result["message"]
    assert result["from_user"]["points_added"] == 5
    assert result["to_user"]["points_added"] == 5

    from_points = await setup_service.db.get_user_points(from_id)
    to_points = await setup_service.db.get_user_points(to_id)
    assert from_points == 5
    assert to_points == 5


@pytest.mark.asyncio
async def test_should_enforce_daily_limit_when_exceeding_two_sends(setup_service):
    """Test: Should enforce daily limit when exceeding two sends"""
    # Arrange
    from_id = "123456789012345678"
    to_id_1 = "123456789012345679"
    to_id_2 = "123456789012345680"
    to_id_3 = "123456789012345681"

    # Act - First send (should succeed)
    await setup_service.send_gratitude(from_id, "TestUser1", to_id_1, "TestUser2")

    # Act - Second send (should succeed)
    result_second = await setup_service.send_gratitude(
        from_id, "TestUser1", to_id_2, "TestUser3"
    )

    # Act - Third send (should be blocked)
    result_third = await setup_service.send_gratitude(
        from_id, "TestUser1", to_id_3, "TestUser4"
    )

    # Assert
    assert result_second["success"] is True
    assert "감사를 전했습니다" in result_second["message"]

    assert result_third["success"] is False
    assert "한도를 모두 사용" in result_third["message"]
    assert result_third["already_sent"] is True


@pytest.mark.asyncio
async def test_should_prevent_self_gratitude_when_same_user(setup_service):
    """Test: Should prevent self-gratitude when same user ID"""
    # Arrange
    user_id = "123456789012345678"
    username = "TestUser1"

    # Act
    result = await setup_service.send_gratitude(user_id, username, user_id, username)

    # Assert
    assert result["success"] is False
    assert "자기 자신에게는" in result["message"]


@pytest.mark.asyncio
async def test_should_retrieve_gratitude_history_when_user_has_records(setup_service):
    """Test: Should retrieve gratitude history when user has records"""
    # Arrange
    from_id = "123456789012345678"
    to_id_1 = "123456789012345679"
    to_id_2 = "123456789012345680"

    await setup_service.send_gratitude(from_id, "TestUser1", to_id_1, "TestUser2")
    await setup_service.send_gratitude(from_id, "TestUser1", to_id_2, "TestUser3")

    # Act
    result = await setup_service.get_gratitude_history(from_id)

    # Assert
    assert result["success"] is True
    assert result["total_sent"] == 2
    assert result["has_sent_today"] is True
    assert "감사 내역" in result["message"]


@pytest.mark.asyncio
async def test_should_calculate_gratitude_stats_when_user_has_activity(setup_service):
    """Test: Should calculate gratitude statistics when user has activity"""
    # Arrange
    from_id = "123456789012345678"
    to_id_1 = "123456789012345679"
    to_id_2 = "123456789012345680"

    await setup_service.send_gratitude(from_id, "TestUser1", to_id_1, "TestUser2")
    await setup_service.send_gratitude(from_id, "TestUser1", to_id_2, "TestUser3")

    # Act
    stats = await setup_service.get_gratitude_stats(from_id)

    # Assert
    assert stats["total_sent"] == 2
    assert stats["has_sent_today"] is True
    assert stats["points_from_sent"] == 10


@pytest.mark.asyncio
async def test_should_return_summary_when_querying_database(setup_service):
    """Test: Should return summary when querying database"""
    # Arrange
    from_id = "123456789012345678"
    to_id_1 = "123456789012345679"
    to_id_2 = "123456789012345680"

    await setup_service.send_gratitude(from_id, "TestUser1", to_id_1, "TestUser2")
    await setup_service.send_gratitude(from_id, "TestUser1", to_id_2, "TestUser3")

    # Act
    summary = await setup_service.db.get_gratitude_summary(from_id)

    # Assert
    assert summary["total_sent"] == 2
    assert summary["total_received"] == 0
    assert summary["has_sent_today"] is True
    assert summary["points_from_sent"] == 10
    assert summary["points_from_received"] == 0


@pytest.mark.asyncio
async def test_should_track_received_gratitude_when_user_receives(setup_service):
    """Test: Should track received gratitude when user receives"""
    # Arrange
    from_id = "123456789012345678"
    to_id = "123456789012345679"

    await setup_service.send_gratitude(from_id, "TestUser1", to_id, "TestUser2")

    # Act
    summary = await setup_service.db.get_gratitude_summary(to_id)

    # Assert
    assert summary["total_sent"] == 0
    assert summary["total_received"] == 1
    assert summary["has_sent_today"] is False
    assert summary["points_from_sent"] == 0
    assert summary["points_from_received"] == 5


@pytest.mark.asyncio
async def test_should_trim_message_when_exceeding_200_chars(setup_service):
    """Test: Should trim message when exceeding 200 characters"""
    # Arrange
    from_id = "123456789012345678"
    to_id = "123456789012345679"
    long_message = "x" * 250

    # Act
    result = await setup_service.send_gratitude(
        from_id, "TestUser1", to_id, "TestUser2", message=long_message
    )

    # Assert
    assert result["success"] is True
    assert '"' + ("x" * 200) + '"' in result["message"]
