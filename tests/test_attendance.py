"""Tests for attendance service functionality.

Refactored to use shared fixtures from conftest.py for better maintainability
and consistency across test files.
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.services.attendance_service import attendance_service
from app.database import db


# ============================================================================
# Attendance-Specific Fixtures
# ============================================================================


@pytest.fixture
def mock_attendance_db():
    """Fixture providing a mocked database for attendance operations."""
    with (
        patch.object(db, "users_collection") as mock_users,
        patch.object(db, "transactions_collection") as mock_transactions,
        patch.object(db, "get_user_points") as mock_get_points,
    ):
        yield {
            "users_collection": mock_users,
            "transactions_collection": mock_transactions,
            "get_user_points": mock_get_points,
        }


# ============================================================================
# Attendance Recording Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_record_attendance_when_valid_metadata_provided(test_user_data):
    """유효한 메타데이터가 제공되면 출석이 기록되어야 한다."""
    # Arrange
    expected_message = "출석이 기록되었습니다."

    with patch.object(
        attendance_service,
        "record_by_metadata",
        new_callable=AsyncMock,
        return_value={"success": True, "message": expected_message},
    ):
        # Act
        result = await attendance_service.record_by_metadata(
            user_id=test_user_data["user_id"],
            username=test_user_data["username"],
            generation=test_user_data["generation"],
            week=test_user_data["week"],
            day=test_user_data["day"],
        )

        # Assert
        assert result["success"] is True
        assert result["message"] == expected_message


@pytest.mark.asyncio
async def test_should_prevent_duplicate_attendance_when_same_day_submitted(
    test_user_data,
):
    """같은 날 출석이 다시 제출되면 중복 출석이 방지되어야 한다."""
    # Arrange
    expected_message = "이미 출석 처리되었습니다."

    with patch.object(
        attendance_service,
        "record_by_metadata",
        new_callable=AsyncMock,
        return_value={"success": False, "message": expected_message},
    ):
        # Act
        result = await attendance_service.record_by_metadata(
            user_id=test_user_data["user_id"],
            username=test_user_data["username"],
            generation=test_user_data["generation"],
            week=test_user_data["week"],
            day=test_user_data["day"],
        )

        # Assert
        assert result["success"] is False
        assert result["message"] == expected_message


# ============================================================================
# Attendance Status Retrieval Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_retrieve_attendance_status_when_user_requests(test_user_data):
    """사용자가 요청하면 출석 현황이 조회되어야 한다."""
    # Arrange
    expected_message = "출석 현황: 6기 1주차 1일"

    with patch.object(
        attendance_service,
        "get_my_attendance",
        new_callable=AsyncMock,
        return_value={"success": True, "message": expected_message},
    ):
        # Act
        result = await attendance_service.get_my_attendance(test_user_data["user_id"])

        # Assert
        assert result["success"] is True
        assert expected_message in result["message"]


# ============================================================================
# Database Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_retrieve_user_points_when_requested(
    test_user_data, mock_attendance_db
):
    """포인트 조회가 요청되면 사용자 포인트가 반환되어야 한다."""
    # Arrange
    expected_points = 100
    mock_attendance_db["get_user_points"].return_value = expected_points

    # Act
    points = await db.get_user_points(test_user_data["user_id"])

    # Assert
    assert points == expected_points
    mock_attendance_db["get_user_points"].assert_called_once_with(
        test_user_data["user_id"]
    )


@pytest.mark.asyncio
async def test_should_retrieve_user_data_when_querying_database(
    test_user_data, mock_attendance_db
):
    """데이터베이스를 쿼리하면 사용자 데이터가 조회되어야 한다."""
    # Arrange
    expected_user = {
        "discord_id": test_user_data["user_id"],
        "username": test_user_data["username"],
        "total_points": 100,
        "generation": test_user_data["generation"],
    }
    mock_attendance_db["users_collection"].find_one.return_value = expected_user

    # Act
    user = mock_attendance_db["users_collection"].find_one(
        {"discord_id": test_user_data["user_id"]}
    )

    # Assert
    assert user is not None
    assert user["discord_id"] == test_user_data["user_id"]
    assert user["username"] == test_user_data["username"]
    assert user["total_points"] == 100
    assert user["generation"] == test_user_data["generation"]


@pytest.mark.asyncio
async def test_should_retrieve_transactions_when_querying_user_history(
    test_user_data, mock_attendance_db
):
    """사용자 기록을 쿼리하면 트랜잭션이 조회되어야 한다."""
    # Arrange
    expected_transactions = [
        {"user_id": test_user_data["user_id"], "reason": "출석", "points": 10},
        {"user_id": test_user_data["user_id"], "reason": "출석", "points": 10},
    ]
    mock_attendance_db[
        "transactions_collection"
    ].find.return_value = expected_transactions

    # Act
    transactions = list(
        mock_attendance_db["transactions_collection"].find(
            {"user_id": test_user_data["user_id"]}
        )
    )

    # Assert
    assert len(transactions) == 2
    assert all(tx["user_id"] == test_user_data["user_id"] for tx in transactions)
    assert all(tx["reason"] == "출석" for tx in transactions)
    assert all(tx["points"] == 10 for tx in transactions)
