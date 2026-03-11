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
        *,
        from_nickname: str | None = None,
        to_nickname: str | None = None,
        message: str | None = None,
        from_generation: int | None = None,
        to_generation: int | None = None,
    ) -> dict[str, Any]:
        # Ensure DB is connected in case another test/module closed it
        self.db.ensure_connected()
        if from_discord_id == to_discord_id:
            return {
                "success": False,
                "message": "❌ 자기 자신에게는 감사를 보낼 수 없습니다.",
            }

        from_user = await self.db.get_or_create_user(
            from_discord_id,
            from_username,
            from_generation,
            nickname=from_nickname,
        )
        to_user = await self.db.get_or_create_user(
            to_discord_id,
            to_username,
            to_generation,
            nickname=to_nickname,
        )

        # Enforce new quota: up to 2 sends/day
        sent_today = await self.db.count_gratitude_sent_today(from_discord_id)
        if sent_today >= 2:
            return {
                "success": False,
                "message": (
                    "❌ 오늘은 감사 전송 한도를 모두 사용했어요.\n"
                    "감사는 하루에 최대 2회, 1회당 +5p/+5p 적립됩니다.\n"
                    "내일 다시 따뜻한 마음을 전해 보아요!"
                ),
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
            # Recompute count after successful send
            sent_today_after = await self.db.count_gratitude_sent_today(from_discord_id)
            remaining_today = max(0, 2 - sent_today_after)

            def _display(u) -> str:
                try:
                    nn = getattr(u, "nickname", None)
                    un = getattr(u, "username", None)
                    if nn and un and nn != un:
                        return f"{nn}({un})"
                    return un or nn or "Unknown"
                except Exception:
                    return "Unknown"

            response = {
                "success": True,
                "message": (
                    f"💝 **{_display(from_user)}**님이 **{_display(to_user)}**님에게 감사를 전했습니다!"
                ),
                "from_user": {
                    "id": from_discord_id,
                    "username": from_user.username,
                    "points_added": 5,
                    "total_points": from_points,
                },
                "to_user": {
                    "id": to_discord_id,
                    "username": to_user.username,
                    "points_added": 5,
                    "total_points": to_points,
                },
            }

            # 강조: 감사 메시지 본문은 인용으로 표시
            if norm_message:
                response["message"] = response["message"] + "\n" + f'"{norm_message}"'

            # 안내: 1회당 +5p/+5p, 하루 2회 제한 및 남은 횟수 표시
            response["message"] = (
                response["message"]
                + "\n\n감사는 하루 최대 2회 보낼 수 있어요 (1회당 +5p/+5p).\n"
                + f"오늘 남은 가능 횟수: {remaining_today}회"
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
            to_user = await self.db.get_or_create_user(record["to_user_id"], "Unknown")
            sent_list.append(
                {
                    "to_user_id": record["to_user_id"],
                    "to_username": to_user.nickname
                    if (to_user.nickname and to_user.nickname != to_user.username)
                    else to_user.username,
                    "date": record["date"],
                    "points": record["points"],
                }
            )

        for record in received_cursor:
            from_user = await self.db.get_or_create_user(
                record["from_user_id"], "Unknown"
            )
            received_list.append(
                {
                    "from_user_id": record["from_user_id"],
                    "from_username": from_user.nickname
                    if (from_user.nickname and from_user.nickname != from_user.username)
                    else from_user.username,
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

        sent_today_count = await self.db.count_gratitude_sent_today(discord_id)
        has_sent_today = sent_today_count >= 1

        message_lines = [
            "💝 **감사 내역**",
            f"• 보낸 감사: {total_sent}회 (+{total_sent * 5:,}점)",
            f"• 받은 감사: {total_received}회 (+{total_received * 5:,}점)",
            f"• 오늘 감사 전송: {sent_today_count}/2",
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
            user = await self.db.get_or_create_user(item["_id"], "Unknown")
            top_recipients.append(
                {
                    "user_id": item["_id"],
                    "username": user.nickname
                    if (user.nickname and user.nickname != user.username)
                    else user.username,
                    "count": item["count"],
                }
            )

        return {
            "total_sent": total_sent,
            "total_received": total_received,
            "has_sent_today": has_sent_today,
            "points_from_sent": total_sent * 5,
            "points_from_received": total_received * 5,
            "top_recipients": top_recipients,
        }


gratitude_service = GratitudeService()
