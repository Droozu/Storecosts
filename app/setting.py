from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")
    tg_bot_token: str = Field(alias="TG_BOT_TOKEN")