import asyncio
import socket
import pytest
from app.database import db
from app.services.attendance_service import attendance_service
from app.settings import settings


async def run_attendance():
    print("=== 출석 기능 테스트 시작 ===\n")

    db.connect()
    print("✓ Database 연결 완료\n")

    test_user_id = "987654321098765432"
    test_username = "TestUser"
    generation = 6
    week = 1
    day = 1

    print("1. 출석 체크 테스트 (관리자 반응 승인 흐름 시뮬레이션)")
    print(f"   - 유저: {test_username} ({test_user_id})")
    print(f"   - 메타: {generation}기 {week}주차 {day}일")
    result = await attendance_service.record_by_metadata(
        user_id=test_user_id,
        username=test_username,
        generation=generation,
        week=week,
        day=day,
    )
    print(f"   결과: {result['message']}\n")

    print("2. 중복 출석 방지 테스트 (같은 일차)")
    result = await attendance_service.record_by_metadata(
        user_id=test_user_id,
        username=test_username,
        generation=generation,
        week=week,
        day=day,
    )
    print(f"   결과: {result['message']}\n")

    print("3. 출석 현황 조회 테스트")
    result = await attendance_service.get_my_attendance(test_user_id)
    print(f"   결과:\n{result['message']}\n")

    print("4. 포인트 조회 테스트")
    points = await db.get_user_points(test_user_id)
    print(f"   현재 포인트: {points:,}점\n")

    print("5. 데이터베이스 직접 확인")
    user = db.users_collection.find_one({"discord_id": test_user_id})
    if user:
        print(f"   - 유저: {user['username']}")
        print(f"   - 총 포인트: {user['total_points']:,}점")
        print(f"   - 기수: {user['generation']}기")

    transactions = list(db.transactions_collection.find({"user_id": test_user_id}))
    print(f"   - 트랜잭션 수: {len(transactions)}건")
    for tx in transactions:
        print(f"     • {tx['reason']}: {tx['points']:+d}점")

    db.close()
    print("\n=== 테스트 완료 ===")


if __name__ == "__main__":
    asyncio.run(run_attendance())


def test_attendance_pytest():
    """Pytest wrapper to run the async test. Skips if DB is unavailable."""
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect((settings.mongo_host, settings.mongo_port))
    except Exception as e:
        pytest.skip(f"Skipping integration test (Mongo unavailable): {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass

    asyncio.run(run_attendance())
