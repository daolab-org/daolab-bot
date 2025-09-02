from typing import Any
from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from app.settings import settings
from app.models import User, Transaction, Attendance, AttendanceCode, Gratitude
from app.timezone import now_kst, today_kst_str, KST


class Database:
    def __init__(self):
        # Lazily connected client/collections so tests and CLI can decide when to connect
        self.client = None
        self.db = None
        self.users_collection = None
        self.transactions_collection = None
        self.attendance_collection = None
        self.attendance_codes_collection = None
        self.gratitude_collection = None

    def connect(self):
        url = f"mongodb://{settings.mongo_user}:{settings.mongo_pass}@{settings.mongo_host}:{settings.mongo_port}"
        self.client = MongoClient(url, tz_aware=True, tzinfo=KST)
        self.db = self.client["daolab"]

        self.users_collection = self.db["users"]
        self.transactions_collection = self.db["transactions"]
        self.attendance_collection = self.db["attendance"]
        self.attendance_codes_collection = self.db["attendance_codes"]
        self.gratitude_collection = self.db["gratitude"]

        self._create_indexes()

    def ensure_connected(self) -> None:
        """Ensure the Mongo client/collections are initialized.

        Tests sometimes call `db.close()` between modules; calling this at the
        start of public methods avoids `InvalidOperation: MongoClient after close`.
        """
        if self.client is None or self.db is None:
            self.connect()

    def _create_indexes(self):
        self.users_collection.create_index("discord_id", unique=True, sparse=True)
        self.users_collection.create_index("generation")

        self.transactions_collection.create_index("user_id")
        self.transactions_collection.create_index([("timestamp", DESCENDING)])
        self.transactions_collection.create_index("reason")

        self.attendance_collection.create_index(
            [("session", ASCENDING), ("user_id", ASCENDING)], unique=True
        )
        self.attendance_collection.create_index("user_id")
        self.attendance_collection.create_index("date")

        self.attendance_codes_collection.create_index(
            [("session", ASCENDING), ("code", ASCENDING)], unique=True
        )
        self.attendance_codes_collection.create_index("is_active")

        self.gratitude_collection.create_index(
            [("from_user_id", ASCENDING), ("date", ASCENDING)], unique=True
        )
        self.gratitude_collection.create_index("to_user_id")

    def close(self):
        if self.client:
            self.client.close()
        # Null out references so subsequent operations can reconnect cleanly
        self.client = None
        self.db = None
        self.users_collection = None
        self.transactions_collection = None
        self.attendance_collection = None
        self.attendance_codes_collection = None
        self.gratitude_collection = None

    async def get_or_create_user(
        self,
        discord_id: str,
        username: str,
        generation: int = 6,
        nickname: str | None = None,
    ) -> User:
        self.ensure_connected()
        user_data = self.users_collection.find_one({"discord_id": discord_id})

        if user_data:
            # Update username/nickname if they changed
            updates: dict[str, Any] = {}
            if username and user_data.get("username") != username:
                updates["username"] = username
            if nickname and user_data.get("nickname") != nickname:
                updates["nickname"] = nickname
            if updates:
                updates["updated_at"] = now_kst()
                self.users_collection.update_one(
                    {"discord_id": discord_id}, {"$set": updates}
                )
                user_data.update(updates)
            return User(**user_data)

        new_user = User(
            discord_id=discord_id,
            username=username,
            generation=generation,
            nickname=nickname or username,
            total_points=0,
        )

        try:
            result = self.users_collection.insert_one(
                new_user.model_dump(by_alias=True)
            )
            new_user.id = result.inserted_id
            return new_user
        except DuplicateKeyError:
            user_data = self.users_collection.find_one({"discord_id": discord_id})
            return User(**user_data)

    async def update_user_points(self, discord_id: str, points_delta: int) -> bool:
        self.ensure_connected()
        result = self.users_collection.update_one(
            {"discord_id": discord_id},
            {
                "$inc": {"total_points": points_delta},
                "$set": {"updated_at": now_kst()},
            },
        )
        return result.modified_count > 0

    async def add_transaction(self, transaction: Transaction) -> Transaction:
        self.ensure_connected()
        result = self.transactions_collection.insert_one(
            transaction.model_dump(by_alias=True)
        )
        transaction.id = result.inserted_id

        await self.update_user_points(transaction.user_id, transaction.points)

        return transaction

    async def check_attendance_exists(self, session: int, user_id: str) -> bool:
        self.ensure_connected()
        existing = self.attendance_collection.find_one(
            {"session": session, "user_id": user_id}
        )
        return existing is not None

    async def record_attendance(
        self, session: int, user_id: str, code: str
    ) -> Attendance | None:
        self.ensure_connected()
        if await self.check_attendance_exists(session, user_id):
            return None

        date_str = today_kst_str()
        attendance = Attendance(
            session=session, user_id=user_id, code=code, date=date_str
        )

        try:
            result = self.attendance_collection.insert_one(
                attendance.model_dump(by_alias=True)
            )
            attendance.id = result.inserted_id

            transaction = Transaction(
                user_id=user_id, points=100, reason="출석", session=session
            )
            await self.add_transaction(transaction)

            return attendance
        except DuplicateKeyError:
            return None

    async def get_valid_attendance_code(
        self, session: int, code: str
    ) -> AttendanceCode | None:
        self.ensure_connected()
        code_upper = code.upper()
        code_data = self.attendance_codes_collection.find_one(
            {"session": session, "code": code_upper, "is_active": True}
        )

        if not code_data:
            return None

        attendance_code = AttendanceCode(**code_data)

        if attendance_code.expires_at:
            exp = attendance_code.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            if exp < now_kst():
                return None

        return attendance_code

    async def create_attendance_code(
        self,
        session: int,
        code: str,
        created_by: str,
        expires_at: datetime | None = None,
    ) -> AttendanceCode:
        self.ensure_connected()
        attendance_code = AttendanceCode(
            session=session, code=code, created_by=created_by, expires_at=expires_at
        )

        try:
            result = self.attendance_codes_collection.insert_one(
                attendance_code.model_dump(by_alias=True)
            )
            attendance_code.id = result.inserted_id
            return attendance_code
        except DuplicateKeyError:
            raise ValueError(f"Code {code} already exists for session {session}")

    async def get_user_attendance_records(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_connected()
        cursor = self.attendance_collection.find({"user_id": user_id}).sort(
            "session", ASCENDING
        )
        return list(cursor)

    async def get_user_points(self, discord_id: str) -> int:
        self.ensure_connected()
        user_data = self.users_collection.find_one({"discord_id": discord_id})
        if user_data:
            return user_data.get("total_points", 0)
        return 0

    async def get_user_transactions(
        self, user_id: str, limit: int = 10
    ) -> list[Transaction]:
        self.ensure_connected()
        cursor = (
            self.transactions_collection.find({"user_id": user_id})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        return [Transaction(**doc) for doc in cursor]

    async def check_gratitude_sent_today(self, from_user_id: str) -> bool:
        self.ensure_connected()
        today = today_kst_str()
        existing = self.gratitude_collection.find_one(
            {"from_user_id": from_user_id, "date": today}
        )
        return existing is not None

    async def send_gratitude(
        self, from_user_id: str, to_user_id: str, message: str | None = None
    ) -> Gratitude | None:
        self.ensure_connected()
        if from_user_id == to_user_id:
            raise ValueError("Cannot send gratitude to yourself")

        if await self.check_gratitude_sent_today(from_user_id):
            return None

        today = today_kst_str()
        gratitude = Gratitude(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            date=today,
            message=message.strip()
            if isinstance(message, str) and message.strip()
            else None,
        )

        try:
            result = self.gratitude_collection.insert_one(
                gratitude.model_dump(by_alias=True)
            )
            gratitude.id = result.inserted_id

            from_transaction = Transaction(
                user_id=from_user_id,
                points=10,
                reason="감사줌",
                from_user_id=from_user_id,
                to_user_id=to_user_id,
            )
            await self.add_transaction(from_transaction)

            to_transaction = Transaction(
                user_id=to_user_id,
                points=10,
                reason="감사받음",
                from_user_id=from_user_id,
                to_user_id=to_user_id,
            )
            await self.add_transaction(to_transaction)

            return gratitude
        except DuplicateKeyError:
            return None

    async def get_gratitude_summary(self, user_id: str) -> dict[str, Any]:
        self.ensure_connected()
        total_sent = self.gratitude_collection.count_documents(
            {"from_user_id": user_id}
        )
        total_received = self.gratitude_collection.count_documents(
            {"to_user_id": user_id}
        )
        has_sent_today = await self.check_gratitude_sent_today(user_id)

        return {
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": has_sent_today,
            "points_from_sent": total_sent * 10,
            "points_from_received": total_received * 10,
        }

    async def get_attendance_summary(self, user_id: str) -> dict[str, Any]:
        """Return quick stats for attendance activity.

        - total_attendance: number of attendance records
        - points_from_attendance: total points earned from attendance (100 each)
        - has_attended_today: whether user already checked in today
        """
        self.ensure_connected()
        total_attendance = self.attendance_collection.count_documents(
            {"user_id": user_id}
        )
        has_attended_today = (
            self.attendance_collection.find_one(
                {"user_id": user_id, "date": today_kst_str()}
            )
            is not None
        )

        return {
            "total_attendance": total_attendance,
            "points_from_attendance": total_attendance * 100,
            "has_attended_today": has_attended_today,
        }


db = Database()
