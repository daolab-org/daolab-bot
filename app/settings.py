from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    discord_token: str
    mongo_host: str
    mongo_user: str
    mongo_port: int = 27017
    mongo_pass: str
    daolab_guild_id: int = 1405880720496394240


settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
