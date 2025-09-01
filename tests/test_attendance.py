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

    test_admin_id = "123456789012345678"
    test_user_id = "987654321098765432"
    test_username = "TestUser"
    test_session = 1
    test_code = "TEST2025"

    print("1. 출석 코드 생성 테스트")
    print(f"   - 세션: {test_session}회차")
    print(f"   - 코드: {test_code}")
    result = await attendance_service.create_attendance_code(
        test_session, test_code, test_admin_id
    )
    print(f"   결과: {result['message']}\n")

    print("2. 출석 체크 테스트")
    print(f"   - 유저: {test_username} ({test_user_id})")
    print(f"   - 세션: {test_session}회차")
    print(f"   - 코드: {test_code}")
    result = await attendance_service.check_in(
        test_user_id, test_username, test_session, test_code
    )
    print(f"   결과: {result['message']}\n")

    print("3. 중복 출석 방지 테스트")
    result = await attendance_service.check_in(
        test_user_id, test_username, test_session, test_code
    )
    print(f"   결과: {result['message']}\n")

    print("4. 잘못된 코드 테스트")
    result = await attendance_service.check_in(
        test_user_id, test_username, test_session, "WRONG"
    )
    print(f"   결과: {result['message']}\n")

    print("5. 출석 현황 조회 테스트")
    result = await attendance_service.get_my_attendance(test_user_id)
    print(f"   결과:\n{result['message']}\n")

    print("6. 포인트 조회 테스트")
    points = await db.get_user_points(test_user_id)
    print(f"   현재 포인트: {points:,}점\n")

    print("7. 데이터베이스 직접 확인")
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
