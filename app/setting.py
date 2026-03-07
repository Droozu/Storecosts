from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")
    tg_bot_token: str = Field(alias="TG_BOT_TOKEN")
    ds_token: str = Field(alias="DEEPSEEK_TOKEN")


    # RedDatabase 5 (Firebird)
    rdb_host: str = Field(default="localhost", alias="RDB_HOST")
    rdb_port: int = Field(default=3050, alias="RDB_PORT")
    rdb_database: str = Field(alias="RDB_DATABASE")
    rdb_user: str = Field(alias="RDB_USER")
    rdb_password: str = Field(alias="RDB_PASSWORD")
    rdb_charset: str = Field(default="UTF8", alias="RDB_CHARSET")

    # Auth
    invite_salt: str = Field(alias="INVITE_SALT")
    session_ttl_minutes: int = Field(default=60, alias="SESSION_TTL_MINUTES")

        # В .env кладём CSV строкой
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    @property
    def admin_ids(self) -> List[int]:
        raw = (self.admin_ids_raw or "").strip()
        if not raw:
            return []
        out: List[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            out.append(int(part))
        return out