from pydantic_settings import BaseSettings, SettingsConfigDict

bot_development_channel_id: int = 1409906888203571210


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # MongoDB connection settings
    mongo_host: str
    mongo_user: str
    mongo_port: int = 27017
    mongo_pass: str

    # Discord bot token
    discord_token: str

    # Daolab guild ID
    daolab_guild_id: int = 1405880720496394240

    # Transaction updates channel
    transaction_channel_id: int = 1412842871635316867

    # Attendance settings
    attendance_channel_id: int = 1412500749702791239
    attendance_manager_role_ids: tuple[int, ...] = (
        1405883481812373564,  # 관리자 역할
        1423336658744639549,  # 출석체크 역할
    )
    attendance_generation: int = 7
    default_generation: int = 999  # 기본 기수 (미확인 사용자)

    # 관리자 role ID
    admin_role_id: int = 1405883481812373564  # 관리자 역할

    # 운영 role IDs
    generation_7_role_id: int = 1475683723453141224  # 7기 역할
    official_crew_role_id: int = 1412166218659532961  # 정식크루 역할
    friends_role_id: int = 1475500500072927384  # 프렌즈 역할


settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
