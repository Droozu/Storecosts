from typing import Set
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhitelistSettings(BaseSettings):
    """
    TG_WHITELIST_USERS=12345678,98765432
    """
    TG_WHITELIST_USERS: str = ""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


class WhitelistAuth:
    def __init__(self) -> None:
        settings = WhitelistSettings()
        self.allowed_users: Set[int] = self._parse_users(settings.TG_WHITELIST_USERS)

    @staticmethod
    def _parse_users(raw: str) -> Set[int]:
        if not raw:
            return set()
        return {int(user_id.strip()) for user_id in raw.split(",") if user_id.strip()}

    def is_allowed(self, telegram_user_id: int) -> bool:
        # если whitelist пуст — никого не пускаем
        if not self.allowed_users:
            return False
        return telegram_user_id in self.allowed_users