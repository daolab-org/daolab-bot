from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict, GetCoreSchemaHandler
from pydantic_core import core_schema
from bson import ObjectId
from app.timezone import now_kst


class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(v):
            if isinstance(v, ObjectId):
                return v
            if isinstance(v, str) and ObjectId.is_valid(v):
                return ObjectId(v)
            raise ValueError("Invalid ObjectId")

        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.no_info_plain_validator_function(validate),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: str(v), when_used="json"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")


class User(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    discord_id: str = Field(..., description="Discord user ID")
    username: str = Field(..., description="Discord username")
    nickname: str | None = Field(None, description="서버 별명")
    generation: int = Field(..., ge=1, description="기수")
    total_points: int = Field(default=0, ge=0, description="총 포인트")
    created_at: datetime = Field(default_factory=now_kst)
    updated_at: datetime = Field(default_factory=now_kst)

    @field_validator("discord_id")
    @classmethod
    def validate_discord_id(cls, v):
        if not v.isdigit() or len(v) < 17:
            raise ValueError("Invalid Discord ID format")
        return v


TransactionReason = Literal["출석", "감사줌", "감사받음", "관리자지급", "관리자회수"]


class Transaction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="대상 유저 Discord ID")
    points: int = Field(..., description="포인트 변동량 (+/-)")
    reason: TransactionReason = Field(..., description="변동 사유")
    session: int | None = Field(None, description="출석 회차")
    from_user_id: str | None = Field(None, description="보낸 유저 (감사)")
    to_user_id: str | None = Field(None, description="받은 유저 (감사)")
    admin_id: str | None = Field(None, description="관리자 ID")
    admin_note: str | None = Field(None, description="관리자 메모")
    timestamp: datetime = Field(default_factory=now_kst)

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if v == 0:
            raise ValueError("Points cannot be zero")
        return v


class Attendance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    session: int = Field(..., ge=1, description="출석 회차")
    user_id: str = Field(..., description="출석한 유저 Discord ID")
    code: str = Field(..., description="출석 코드")
    date: str = Field(..., description="출석 날짜 (YYYY-MM-DD)")
    checked_at: datetime = Field(default_factory=now_kst)


class AttendanceCode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    session: int = Field(..., ge=1, description="회차")
    code: str = Field(..., min_length=4, max_length=20, description="출석 코드")
    created_by: str = Field(..., description="생성한 관리자 Discord ID")
    is_active: bool = Field(default=True, description="활성화 여부")
    created_at: datetime = Field(default_factory=now_kst)
    expires_at: datetime | None = Field(None, description="만료 시간")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if not v.isalnum():
            raise ValueError("Code must be alphanumeric")
        return v.upper()


class Gratitude(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    from_user_id: str = Field(..., description="감사를 보낸 유저")
    to_user_id: str = Field(..., description="감사를 받은 유저")
    date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    points: int = Field(default=10, description="감사 포인트")
    message: str | None = Field(
        None, max_length=200, description="감사 전달 메시지 (선택)"
    )
    created_at: datetime = Field(default_factory=now_kst)

    @field_validator("to_user_id")
    @classmethod
    def validate_not_self(cls, v, values):
        if "from_user_id" in values.data and v == values.data["from_user_id"]:
            raise ValueError("Cannot send gratitude to yourself")
        return v
