"""Integration test for gratitude feature"""

import asyncio
import sys
import os
import socket

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import db
from app.services.gratitude_service import gratitude_service
from app.settings import settings


import pytest


async def cleanup_test_data():
    """Clean up test data"""
    test_user_ids = ["123456789012345678", "123456789012345679", "123456789012345680"]

    for user_id in test_user_ids:
        db.users_collection.delete_one({"discord_id": user_id})
        db.transactions_collection.delete_many({"user_id": user_id})
        db.gratitude_collection.delete_many({"from_user_id": user_id})
        db.gratitude_collection.delete_many({"to_user_id": user_id})

    print("✓ Test data cleaned up")


# Ensure clean state for this module's tests regardless of prior runs
@pytest.fixture(scope="module", autouse=True)
async def _gratitude_module_setup_teardown():
    # Skip this module if MongoDB is not reachable
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect((settings.mongo_host, settings.mongo_port))
    except Exception as e:
        pytest.skip(f"Skipping gratitude integration tests (Mongo unavailable): {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass

    db.connect()

    # Ensure legacy unique index (from_user_id, date) is removed to allow 2/day
    try:
        for idx in db.gratitude_collection.list_indexes():
            key = list(idx.get("key", {}).items())
            if idx.get("unique") and key == [("from_user_id", 1), ("date", 1)]:
                db.gratitude_collection.drop_index(idx["name"])
                break
    except Exception:
        pass

    await cleanup_test_data()
    yield
    await cleanup_test_data()
    db.close()


async def test_gratitude_send_success():
    """Test successful gratitude sending"""
    print("\n[Test 1] Testing successful gratitude sending...")

    from_id = "123456789012345678"
    to_id = "123456789012345679"

    result = await gratitude_service.send_gratitude(
        from_id, "TestUser1", to_id, "TestUser2"
    )

    assert result["success"]
    assert "감사를 전했습니다" in result["message"]
    assert result["from_user"]["points_added"] == 5
    assert result["to_user"]["points_added"] == 5

    from_points = await db.get_user_points(from_id)
    to_points = await db.get_user_points(to_id)
    assert from_points == 5
    assert to_points == 5

    print("✓ Gratitude sent successfully")
    print(f"  From user points: {from_points}")
    print(f"  To user points: {to_points}")


async def test_gratitude_daily_limit():
    """Test daily limit (2 per day)"""
    print("\n[Test 2] Testing daily limit...")

    from_id = "123456789012345678"
    to_id = "123456789012345680"

    # Second send should succeed (2/2)
    result = await gratitude_service.send_gratitude(
        from_id, "TestUser1", to_id, "TestUser3"
    )

    assert result["success"]
    assert "감사를 전했습니다" in result["message"]

    # Third send should be blocked (exceeds 2/day)
    result_block = await gratitude_service.send_gratitude(
        from_id, "TestUser1", "123456789012345679", "TestUser2"
    )
    assert not result_block["success"]
    assert "한도를 모두 사용" in result_block["message"]
    assert result_block["already_sent"]

    print("✓ Daily limit enforced correctly")


async def test_gratitude_self_send_prevention():
    """Test preventing self-gratitude"""
    print("\n[Test 3] Testing self-send prevention...")

    user_id = "123456789012345678"

    result = await gratitude_service.send_gratitude(
        user_id, "TestUser1", user_id, "TestUser1"
    )

    assert not result["success"]
    assert "자기 자신에게는" in result["message"]

    print("✓ Self-gratitude prevented correctly")


async def test_gratitude_history():
    """Test gratitude history retrieval"""
    print("\n[Test 4] Testing gratitude history...")

    result = await gratitude_service.get_gratitude_history("123456789012345678")

    assert result["success"]
    # Sent 2 gratitudes (tests 1 and 2)
    assert result["total_sent"] == 2
    assert result["has_sent_today"]
    assert "감사 내역" in result["message"]

    print("✓ Gratitude history retrieved correctly")
    print(f"  Total sent: {result['total_sent']}")
    print(f"  Has sent today: {result['has_sent_today']}")


async def test_gratitude_stats():
    """Test gratitude statistics"""
    print("\n[Test 5] Testing gratitude statistics...")

    stats = await gratitude_service.get_gratitude_stats("123456789012345678")

    assert stats["total_sent"] == 2
    assert stats["has_sent_today"]
    assert stats["points_from_sent"] == 10

    print("✓ Gratitude statistics calculated correctly")
    print(f"  Total sent: {stats['total_sent']}")
    print(f"  Points from sent: {stats['points_from_sent']}")


async def test_gratitude_summary_in_db():
    """Test database gratitude summary method"""
    print("\n[Test 6] Testing database gratitude summary...")

    summary = await db.get_gratitude_summary("123456789012345678")

    assert summary["total_sent"] == 2
    assert summary["total_received"] == 0
    assert summary["has_sent_today"]
    assert summary["points_from_sent"] == 10
    assert summary["points_from_received"] == 0

    print("✓ Database gratitude summary working correctly")
    print(f"  Summary: {summary}")


async def test_gratitude_received():
    """Test gratitude received tracking"""
    print("\n[Test 7] Testing gratitude received tracking...")

    summary = await db.get_gratitude_summary("123456789012345679")

    assert summary["total_sent"] == 0
    assert summary["total_received"] == 1  # Received from test_user_1 in test 1
    assert not summary["has_sent_today"]
    assert summary["points_from_sent"] == 0
    assert summary["points_from_received"] == 5

    print("✓ Gratitude received tracked correctly")
    print(f"  Total received: {summary['total_received']}")
    print(f"  Points from received: {summary['points_from_received']}")


async def main():
    """Run all gratitude tests"""
    print("=" * 50)
    print("GRATITUDE FEATURE INTEGRATION TEST")
    print("=" * 50)

    try:
        db.connect()
        print("✓ Database connected")

        await cleanup_test_data()

        await test_gratitude_send_success()
        await test_gratitude_daily_limit()
        await test_gratitude_self_send_prevention()
        await test_gratitude_history()
        await test_gratitude_stats()
        await test_gratitude_summary_in_db()
        await test_gratitude_received()

        print("\n" + "=" * 50)
        print("ALL TESTS PASSED ✓")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        raise
    finally:
        await cleanup_test_data()
        db.close()
        print("\n✓ Database connection closed")


if __name__ == "__main__":
    asyncio.run(main())
