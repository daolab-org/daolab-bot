from typing import List, Dict, Any
from app.database import db


class AttendanceService:
    def __init__(self):
        self.db = db

    async def check_in(
        self,
        discord_id: str,
        username: str,
        session: int,
        code: str,
        generation: int = 6,
    ) -> Dict[str, Any]:
        user = await self.db.get_or_create_user(discord_id, username, generation)  # noqa

        valid_code = await self.db.get_valid_attendance_code(session, code)
        if not valid_code:
            return {
                "success": False,
                "message": f"❌ 유효하지 않은 출석 코드입니다: {code}",
            }

        if await self.db.check_attendance_exists(session, discord_id):
            return {
                "success": False,
                "message": f"❌ {session}회차에 이미 출석했습니다.",
            }

        attendance = await self.db.record_attendance(session, discord_id, code)

        if attendance:
            new_points = await self.db.get_user_points(discord_id)
            return {
                "success": True,
                "message": f"✅ {session}회차 출석 완료! (+100 포인트)\n현재 포인트: {new_points:,}점",
                "points_added": 100,
                "total_points": new_points,
            }
        else:
            return {"success": False, "message": "❌ 출석 처리 중 오류가 발생했습니다."}

    async def get_my_attendance(self, discord_id: str) -> Dict[str, Any]:
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
                    "session": record["session"],
                    "date": record["date"],
                    "code": record["code"],
                }
            )

        total_points = len(records) * 100

        message_lines = [
            "📊 **출석 현황**",
            f"총 출석: {len(records)}회",
            f"획득 포인트: {total_points:,}점",
            "",
            "**출석 내역:**",
        ]

        for record in attendance_list[-5:]:
            message_lines.append(f"• {record['session']}회차 ({record['date']})")

        if len(attendance_list) > 5:
            message_lines.append(f"... 외 {len(attendance_list) - 5}건")

        return {
            "success": True,
            "message": "\n".join(message_lines),
            "total_attendance": len(records),
            "records": attendance_list,
        }

    async def create_attendance_code(
        self, session: int, code: str, admin_id: str
    ) -> Dict[str, Any]:
        try:
            attendance_code = await self.db.create_attendance_code(
                session, code, admin_id
            )
            return {
                "success": True,
                "message": f"✅ {session}회차 출석 코드 생성 완료: **{attendance_code.code}**",
                "code": attendance_code.code,
                "session": session,
            }
        except ValueError as e:
            return {"success": False, "message": f"❌ {str(e)}"}

    async def get_session_attendance(self, session: int) -> List[Dict[str, Any]]:
        cursor = self.db.attendance_collection.find({"session": session})
        attendance_list = []

        for record in cursor:
            user = await self.db.get_or_create_user(record["user_id"], "Unknown", 6)
            attendance_list.append(
                {
                    "user_id": record["user_id"],
                    "username": user.username,
                    "date": record["date"],
                    "code": record["code"],
                }
            )

        return attendance_list


attendance_service = AttendanceService()
