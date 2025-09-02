from typing import Any
from app.database import db


class GratitudeService:
    def __init__(self):
        self.db = db

    async def send_gratitude(
        self,
        from_discord_id: str,
        from_username: str,
        to_discord_id: str,
        to_username: str,
        message: str | None = None,
        generation: int = 6,
    ) -> dict[str, Any]:
        # Ensure DB is connected in case another test/module closed it
        self.db.ensure_connected()
        if from_discord_id == to_discord_id:
            return {
                "success": False,
                "message": "❌ 자기 자신에게는 감사를 보낼 수 없습니다.",
            }

        from_user = await self.db.get_or_create_user(
            from_discord_id, from_username, generation
        )
        to_user = await self.db.get_or_create_user(
            to_discord_id, to_username, generation
        )

        if await self.db.check_gratitude_sent_today(from_discord_id):
            return {
                "success": False,
                "message": "❌ 오늘은 이미 감사를 보냈습니다. 내일 다시 시도해주세요.",
                "already_sent": True,
            }

        # Normalize and limit message length (max 200 chars)
        norm_message: str | None
        if isinstance(message, str):
            trimmed = message.strip()
            if trimmed:
                norm_message = trimmed[:200]
            else:
                norm_message = None
        else:
            norm_message = None

        gratitude = await self.db.send_gratitude(
            from_discord_id, to_discord_id, norm_message
        )

        if gratitude:
            from_points = await self.db.get_user_points(from_discord_id)
            to_points = await self.db.get_user_points(to_discord_id)

            response = {
                "success": True,
                "message": (
                    f"💝 **{from_user.username}**님이 **{to_user.username}**님에게 감사를 전했습니다!\n"
                    f"• {from_user.username}: +10 포인트 (현재: {from_points:,}점)\n"
                    f"• {to_user.username}: +10 포인트 (현재: {to_points:,}점)"
                ),
                "from_user": {
                    "id": from_discord_id,
                    "username": from_user.username,
                    "points_added": 10,
                    "total_points": from_points,
                },
                "to_user": {
                    "id": to_discord_id,
                    "username": to_user.username,
                    "points_added": 10,
                    "total_points": to_points,
                },
            }

            # Append message line if provided
            if norm_message:
                response["message"] = (
                    response["message"] + "\n\n" + f"📝 메시지: {norm_message}"
                )

            return response
        else:
            return {
                "success": False,
                "message": "❌ 감사 전송 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            }

    async def get_gratitude_history(
        self, discord_id: str, limit: int = 10
    ) -> dict[str, Any]:
        self.db.ensure_connected()
        sent_cursor = (
            self.db.gratitude_collection.find({"from_user_id": discord_id})
            .sort("created_at", -1)
            .limit(limit)
        )

        received_cursor = (
            self.db.gratitude_collection.find({"to_user_id": discord_id})
            .sort("created_at", -1)
            .limit(limit)
        )

        sent_list = []
        received_list = []

        for record in sent_cursor:
            to_user = await self.db.get_or_create_user(
                record["to_user_id"], "Unknown", 6
            )
            sent_list.append(
                {
                    "to_user_id": record["to_user_id"],
                    "to_username": to_user.username,
                    "date": record["date"],
                    "points": record["points"],
                }
            )

        for record in received_cursor:
            from_user = await self.db.get_or_create_user(
                record["from_user_id"], "Unknown", 6
            )
            received_list.append(
                {
                    "from_user_id": record["from_user_id"],
                    "from_username": from_user.username,
                    "date": record["date"],
                    "points": record["points"],
                }
            )

        total_sent = self.db.gratitude_collection.count_documents(
            {"from_user_id": discord_id}
        )
        total_received = self.db.gratitude_collection.count_documents(
            {"to_user_id": discord_id}
        )

        has_sent_today = await self.db.check_gratitude_sent_today(discord_id)

        message_lines = [
            "💝 **감사 내역**",
            f"• 보낸 감사: {total_sent}회 (+{total_sent * 10:,}점)",
            f"• 받은 감사: {total_received}회 (+{total_received * 10:,}점)",
            f"• 오늘 감사 전송: {'완료 ✓' if has_sent_today else '가능 ○'}",
            "",
        ]

        if sent_list:
            message_lines.append("**최근 보낸 감사:**")
            for record in sent_list[:5]:
                message_lines.append(f"• {record['date']} → {record['to_username']}")

        if received_list:
            if sent_list:
                message_lines.append("")
            message_lines.append("**최근 받은 감사:**")
            for record in received_list[:5]:
                message_lines.append(f"• {record['date']} ← {record['from_username']}")

        return {
            "success": True,
            "message": "\n".join(message_lines),
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": has_sent_today,
            "sent_history": sent_list,
            "received_history": received_list,
        }

    async def get_gratitude_stats(self, discord_id: str) -> dict[str, Any]:
        self.db.ensure_connected()
        total_sent = self.db.gratitude_collection.count_documents(
            {"from_user_id": discord_id}
        )
        total_received = self.db.gratitude_collection.count_documents(
            {"to_user_id": discord_id}
        )
        has_sent_today = await self.db.check_gratitude_sent_today(discord_id)

        sent_to_users = self.db.gratitude_collection.aggregate(
            [
                {"$match": {"from_user_id": discord_id}},
                {"$group": {"_id": "$to_user_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 3},
            ]
        )

        top_recipients = []
        for item in sent_to_users:
            user = await self.db.get_or_create_user(item["_id"], "Unknown", 6)
            top_recipients.append(
                {
                    "user_id": item["_id"],
                    "username": user.username,
                    "count": item["count"],
                }
            )

        return {
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": has_sent_today,
            "points_from_sent": total_sent * 10,
            "points_from_received": total_received * 10,
            "top_recipients": top_recipients,
        }


gratitude_service = GratitudeService()
