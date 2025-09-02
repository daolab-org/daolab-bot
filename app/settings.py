from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    discord_token: str
    mongo_host: str
    mongo_user: str
    mongo_port: int = 27017
    mongo_pass: str
    daolab_guild_id: int = 1405880720496394240
    # Attendance settings
    attendance_channel_id: int = 1412500749702791239  # 1409906888203571210
    attendance_manager_role_id: int = 1405882704825679984
    attendance_generation: int = 6


settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
