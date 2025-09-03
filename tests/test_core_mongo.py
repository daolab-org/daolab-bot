import asyncio
import socket
import pytest
from app.database import db
from app.models import Transaction
from app.settings import settings


async def run_core_scenarios():
    print("=== MongoDB 기능 테스트 ===\n")

    # 1. DB 연결 및 컬렉션 확인
    print("1. MongoDB 연결 테스트")
    db.connect()
    assert db.client is not None, "MongoDB client 연결 실패"
    assert db.users_collection is not None, "users 컬렉션 없음"
    assert db.transactions_collection is not None, "transactions 컬렉션 없음"
    print("   ✓ DB 연결 및 컬렉션 생성 완료\n")

    # 2. 유저 생성 및 중복 방지 테스트
    print("2. 유저 생성 및 중복 방지")
    test_user_id = "999888777666555444"  # 18자리 Discord ID

    # 첫 번째 생성
    user1 = await db.get_or_create_user(test_user_id, "TestUser", 6)
    assert user1.discord_id == test_user_id
    assert user1.total_points == 0
    print(f"   ✓ 유저 생성: {user1.username} (포인트: {user1.total_points})")

    # 같은 ID로 재시도 (중복 방지)
    user2 = await db.get_or_create_user(test_user_id, "DifferentName", 6)
    assert user2.discord_id == user1.discord_id
    assert user2.id == user1.id  # 같은 문서
    print(f"   ✓ 중복 생성 방지 확인 (같은 _id: {user2.id})\n")

    # 3. 트랜잭션과 포인트 업데이트 원자성
    print("3. 트랜잭션 기록 및 포인트 원자성 업데이트")

    # 출석 트랜잭션 추가
    tx = Transaction(user_id=test_user_id, points=100, reason="출석", session=1)
    await db.add_transaction(tx)

    # 포인트 확인
    updated_points = await db.get_user_points(test_user_id)
    assert updated_points == 100, f"포인트 업데이트 실패: {updated_points}"
    print(f"   ✓ 출석 트랜잭션 +100 → 총 {updated_points}점")

    # users 컬렉션 직접 확인
    user_doc = db.users_collection.find_one({"discord_id": test_user_id})
    assert user_doc["total_points"] == 100
    print(f"   ✓ users 컬렉션 포인트 동기화 확인: {user_doc['total_points']}점\n")

    # 4. 출석 중복 방지 (unique index)
    print("4. 출석 중복 방지 테스트")

    # 첫 출석 (6기 1주차 1일)
    attendance1 = await db.record_attendance_by_period(
        generation=6, week=1, day=1, user_id=test_user_id
    )
    assert attendance1 is not None
    print(
        f"   ✓ 첫 출석 성공 ({attendance1.generation}기 {attendance1.week}주차 {attendance1.day}일)"
    )

    # 중복 출석 시도 (같은 메타)
    attendance2 = await db.record_attendance_by_period(
        generation=6, week=1, day=1, user_id=test_user_id
    )
    # 변경된 정책: 동일 주차/일차 중복 시 기존 기록을 반환 (idempotent)
    assert attendance2 is not None, "기존 출석 레코드 반환 실패"
    print("   ✓ 중복 출석 시 기존 레코드 반환(포인트 중복 없음) 확인\n")

    # 5. 모든 트랜잭션 불변성 확인
    print("5. 트랜잭션 불변성 및 조회")

    # 모든 트랜잭션 조회
    all_txs = list(db.transactions_collection.find({"user_id": test_user_id}))
    assert len(all_txs) == 2, f"트랜잭션 수 불일치: {len(all_txs)}"

    total_from_txs = sum(tx["points"] for tx in all_txs)
    current_points = await db.get_user_points(test_user_id)
    assert total_from_txs == current_points, "트랜잭션 합계와 총 포인트 불일치"

    print(f"   ✓ 트랜잭션 수: {len(all_txs)}개")
    for tx in all_txs:
        print(f"     • {tx['reason']}: {tx['points']:+d}점")
    print(f"   ✓ 트랜잭션 합계({total_from_txs}) == 유저 포인트({current_points})")

    # 6. 정리: 테스트 데이터 삭제
    print("\n6. 테스트 데이터 정리")
    db.users_collection.delete_one({"discord_id": test_user_id})
    db.transactions_collection.delete_many({"user_id": test_user_id})
    db.attendance_collection.delete_many({"user_id": test_user_id})
    # no attendance_codes in new design
    print("   ✓ 테스트 데이터 삭제 완료")

    db.close()
    print("\n=== 모든 테스트 통과 ✅ ===")


if __name__ == "__main__":
    try:
        asyncio.run(run_core_scenarios())
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback

        traceback.print_exc()


def test_core_mongo_pytest():
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

    asyncio.run(run_core_scenarios())
