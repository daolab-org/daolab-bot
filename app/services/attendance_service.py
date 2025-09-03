from typing import Any
from app.database import db


class AttendanceService:
    def __init__(self):
        self.db = db

    async def record_by_metadata(
        self,
        *,
        user_id: str,
        username: str,
        generation: int,
        week: int,
        day: int,
        nickname: str | None = None,
        channel_id: int | None = None,
        announcement_message_id: int | None = None,
        reply_message_id: int | None = None,
    ) -> dict[str, Any]:
        self.db.ensure_connected()
        await self.db.get_or_create_user(
            user_id, username, generation, nickname=nickname
        )

        # 일 단위 구분은 사용하지 않으므로 day는 고정값(1)으로 처리한다.
        attendance = await self.db.record_attendance_by_period(
            generation=generation,
            week=week,
            day=1,
            user_id=user_id,
            channel_id=channel_id,
            announcement_message_id=announcement_message_id,
            reply_message_id=reply_message_id,
        )

        if attendance:
            new_points = await self.db.get_user_points(user_id)
            return {
                "success": True,
                "message": (
                    f"✅ {generation}기 {week}주차 출석 완료! (+100 포인트)\n"
                    f"현재 포인트: {new_points:,}점"
                ),
                "points_added": 100,
                "total_points": new_points,
            }
        else:
            return {
                "success": False,
                "message": "❌ 이미 출석 처리되었거나 오류가 발생했습니다.",
            }

    async def get_my_attendance(self, discord_id: str) -> dict[str, Any]:
        self.db.ensure_connected()
        records = await self.db.get_user_attendance_records(discord_id)

        if not records:
            return {
                "success": True,
                "message": "📊 출석 기록이 없습니다.",
                "total_attendance": 0,
                "records": [],
            }

        attendance_list = []
        for record in records:
            attendance_list.append(
                {
                    "generation": record.get("generation"),
                    "week": record.get("week"),
                    "day": record.get("day"),
                    "date": record.get("date"),
                }
            )

        total_points = len(records) * 100

        message_lines = [
            "📊 **출석 현황**",
            f"총 출석: {len(records)}회",
            f"획득 포인트: {total_points:,} point",
            "",
            "**최근 출석:**",
        ]

        for record in attendance_list[-5:]:
            message_lines.append(
                f"• {record['generation']}기 {record['week']}주차 ({record['date']})"
            )

        if len(attendance_list) > 5:
            message_lines.append(f"... 외 {len(attendance_list) - 5}건")

        return {
            "success": True,
            "message": "\n".join(message_lines),
            "total_attendance": len(records),
            "records": attendance_list,
        }


attendance_service = AttendanceService()
