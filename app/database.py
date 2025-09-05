from typing import Any, Awaitable, Callable
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from app.settings import settings
from app.models import User, Transaction, Attendance, Gratitude
from app.timezone import now_kst, today_kst_str, KST


class Database:
    def __init__(self):
        # Lazily connected client/collections so tests and CLI can decide when to connect
        self.client = None
        self.db = None
        self.users_collection = None
        self.transactions_collection = None
        self.attendance_collection = None
        self.gratitude_collection = None
        # Async observers notified whenever a Transaction is added
        self._transaction_observers: list[Callable[[Transaction], Awaitable[None]]] = []

    def connect(self):
        url = f"mongodb://{settings.mongo_user}:{settings.mongo_pass}@{settings.mongo_host}:{settings.mongo_port}"
        self.client = MongoClient(url, tz_aware=True, tzinfo=KST)
        self.db = self.client["daolab"]

        self.users_collection = self.db["users"]
        self.transactions_collection = self.db["transactions"]
        self.attendance_collection = self.db["attendance"]
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

        # Attendance: unique per (generation, week, day, user)
        self.attendance_collection.create_index(
            [
                ("generation", ASCENDING),
                ("week", ASCENDING),
                ("day", ASCENDING),
                ("user_id", ASCENDING),
            ],
            unique=True,
        )
        self.attendance_collection.create_index("user_id")
        self.attendance_collection.create_index("generation")
        self.attendance_collection.create_index(
            [("generation", ASCENDING), ("week", ASCENDING)]
        )
        self.attendance_collection.create_index("date")

        self.gratitude_collection.create_index(
            # Allow up to 2 sends per day by including a slot field in uniqueness
            [("from_user_id", ASCENDING), ("date", ASCENDING), ("slot", ASCENDING)],
            unique=True,
        )
        self.gratitude_collection.create_index("to_user_id")

    def add_transaction_observer(
        self, observer: Callable[[Transaction], Awaitable[None]]
    ) -> None:
        """Register an async observer to be notified on new transactions."""
        self._transaction_observers.append(observer)

    async def _notify_transaction_observers(self, transaction: Transaction) -> None:
        for obs in list(self._transaction_observers):
            try:
                await obs(transaction)
            except Exception as e:  # pragma: no cover
                print(f"Transaction observer error: {e}")

    def close(self):
        if self.client:
            self.client.close()
        # Null out references so subsequent operations can reconnect cleanly
        self.client = None
        self.db = None
        self.users_collection = None
        self.transactions_collection = None
        self.attendance_collection = None
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
        # Publish to observers (e.g., Discord channel)
        await self._notify_transaction_observers(transaction)
        return transaction

    async def check_attendance_exists(self, session: int, user_id: str) -> bool:
        self.ensure_connected()
        # Legacy shim kept for compatibility if called elsewhere; now unused
        existing = self.attendance_collection.find_one(
            {"user_id": user_id, "date": today_kst_str()}
        )
        return existing is not None

    async def record_attendance(
        self, session: int, user_id: str, code: str
    ) -> Attendance | None:
        self.ensure_connected()
        # Legacy shim: map session-based call to generation/week/day not supported anymore
        # This path is deprecated; always return None
        return None

    # New attendance APIs (generation/week/day)
    async def record_attendance_by_period(
        self,
        *,
        generation: int,
        week: int,
        day: int,
        user_id: str,
        channel_id: int | None = None,
        announcement_message_id: int | None = None,
        reply_message_id: int | None = None,
    ) -> Attendance | None:
        self.ensure_connected()
        date_str = today_kst_str()
        attendance = Attendance(
            generation=generation,
            week=week,
            day=day,
            user_id=user_id,
            channel_id=channel_id,
            announcement_message_id=announcement_message_id,
            reply_message_id=reply_message_id,
            date=date_str,
        )
        try:
            result = self.attendance_collection.insert_one(
                attendance.model_dump(by_alias=True)
            )
            attendance.id = result.inserted_id

            transaction = Transaction(
                user_id=user_id,
                points=100,
                reason="출석",
            )
            await self.add_transaction(transaction)
            return attendance
        except DuplicateKeyError:
            # Already recorded for (generation, week, day, user). Return the existing
            # record to make admin approvals idempotent across multiple checks.
            existing = self.attendance_collection.find_one(
                {
                    "generation": generation,
                    "week": week,
                    "day": day,
                    "user_id": user_id,
                }
            )
            if existing:
                return Attendance(**existing)
            return None

    async def get_user_attendance_records(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_connected()
        cursor = self.attendance_collection.find({"user_id": user_id}).sort(
            [("generation", ASCENDING), ("week", ASCENDING), ("day", ASCENDING)]
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
        # True if at least one gratitude was sent today
        count = self.gratitude_collection.count_documents(
            {"from_user_id": from_user_id, "date": today}
        )
        return count >= 1

    async def count_gratitude_sent_today(self, from_user_id: str) -> int:
        self.ensure_connected()
        today = today_kst_str()
        return self.gratitude_collection.count_documents(
            {"from_user_id": from_user_id, "date": today}
        )

    async def send_gratitude(
        self, from_user_id: str, to_user_id: str, message: str | None = None
    ) -> Gratitude | None:
        self.ensure_connected()
        if from_user_id == to_user_id:
            raise ValueError("Cannot send gratitude to yourself")

        # New daily limit: up to 2 sends per day
        sent_count = await self.count_gratitude_sent_today(from_user_id)
        if sent_count >= 2:
            return None

        today = today_kst_str()
        gratitude = Gratitude(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            date=today,
            slot=sent_count + 1,
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
                points=5,
                reason="감사줌",
                from_user_id=from_user_id,
                to_user_id=to_user_id,
            )
            await self.add_transaction(from_transaction)

            to_transaction = Transaction(
                user_id=to_user_id,
                points=5,
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
        sent_today_count = await self.count_gratitude_sent_today(user_id)
        has_sent_today = sent_today_count >= 1

        return {
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": has_sent_today,
            "sent_today_count": sent_today_count,
            "remaining_today": max(0, 2 - sent_today_count),
            "points_from_sent": total_sent * 5,
            "points_from_received": total_received * 5,
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

    async def get_weekly_attendance(self, generation: int, week: int) -> dict[str, Any]:
        """Aggregate weekly attendance for admin view.

        Returns:
        - total_attendees: number of unique users attended in the week
        - by_day: list of {day, count}
        - users: list of {user_id, days: [int]}
        """
        self.ensure_connected()
        pipeline = [
            {"$match": {"generation": generation, "week": week}},
            {
                "$group": {
                    "_id": "$user_id",
                    "days": {"$addToSet": "$day"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        user_days = list(self.attendance_collection.aggregate(pipeline))
        users = []
        for item in user_days:
            users.append({"user_id": item["_id"], "days": sorted(item["days"])})

        by_day_pipeline = [
            {"$match": {"generation": generation, "week": week}},
            {"$group": {"_id": "$day", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        by_day = [
            {"day": item["_id"], "count": item["count"]}
            for item in self.attendance_collection.aggregate(by_day_pipeline)
        ]

        return {
            "generation": generation,
            "week": week,
            "total_attendees": len(users),
            "by_day": by_day,
            "users": users,
        }

    async def get_attendance_overview(
        self, generation: int, up_to_week: int
    ) -> dict[str, Any]:
        """Aggregate attendance from week 1..N (inclusive) for admin overview.

        Returns a structure suitable for presenting:
        - weekly_counts: list[{week, count}] — unique participants per week
        - total_attendance: sum of weekly unique counts
        - participants: list[{user_id, weeks: [int]}] — weeks attended by user
        - nicknames: mapping user_id -> nickname/username
        - unique_participants: count of unique users across all weeks
        """
        self.ensure_connected()

        # Unique participants per (week, user)
        match = {"generation": generation, "week": {"$lte": up_to_week}}

        # 1) Per-user weeks attended
        per_user_pipeline = [
            {"$match": match},
            {"$group": {"_id": "$user_id", "weeks": {"$addToSet": "$week"}}},
            {"$sort": {"_id": 1}},
        ]
        per_user_docs = list(self.attendance_collection.aggregate(per_user_pipeline))
        participants_all = [
            {"user_id": doc["_id"], "weeks": sorted(doc.get("weeks", []))}
            for doc in per_user_docs
        ]

        # 2) Nickname map and filter tests
        user_ids_all = [p["user_id"] for p in participants_all]
        nickname_map_all: dict[str, str] = {}
        from app.filters import is_test_user_doc

        test_user_ids: set[str] = set()
        if user_ids_all:
            cursor = self.users_collection.find({"discord_id": {"$in": user_ids_all}})
            for u in cursor:
                nickname = u.get("nickname") or u.get("username") or u.get("discord_id")
                uid = u.get("discord_id")
                nickname_map_all[uid] = nickname
                if is_test_user_doc(u):
                    test_user_ids.add(uid)

        participants = [
            p for p in participants_all if p["user_id"] not in test_user_ids
        ]

        # 3) Weekly unique counts recomputed from filtered participants
        weekly_counts = []
        for w in range(1, up_to_week + 1):
            count = sum(1 for p in participants if w in set(p.get("weeks", [])))
            weekly_counts.append({"week": w, "count": count})

        total_attendance = sum(item["count"] for item in weekly_counts)
        unique_participants = len(participants)

        # 4) Overall participation rate among those who ever attended (union set)
        if unique_participants > 0 and up_to_week > 0:
            attended_slots = sum(len(p["weeks"]) for p in participants)
            possible_slots = unique_participants * up_to_week
            overall_rate = round(attended_slots / possible_slots * 100, 1)
        else:
            overall_rate = 0.0

        return {
            "generation": generation,
            "up_to_week": up_to_week,
            "weekly_counts": weekly_counts,
            "total_attendance": total_attendance,
            "unique_participants": unique_participants,
            "overall_rate": overall_rate,
            "participants": participants,
            "nicknames": {
                p["user_id"]: nickname_map_all.get(p["user_id"], p["user_id"])
                for p in participants
            },
        }


db = Database()
