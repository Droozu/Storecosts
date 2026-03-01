import secrets
import time
from typing import Dict


class OTPService:
    def __init__(self, ttl_seconds: int = 300) -> None:
        """
        ttl_seconds — время жизни кода (по умолчанию 5 минут)
        """
        self.ttl_seconds = ttl_seconds
        self._storage: Dict[str, tuple[str, float]] = {}
        # формат: {telegram_user_id: (otp_code, expires_at)}

    def generate_code(self, telegram_user_id: int) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = time.time() + self.ttl_seconds
        self._storage[str(telegram_user_id)] = (code, expires_at)
        return code

    def verify_code(self, telegram_user_id: int, code: str) -> bool:
        key = str(telegram_user_id)

        if key not in self._storage:
            return False

        saved_code, expires_at = self._storage[key]

        # Проверка срока действия
        if time.time() > expires_at:
            del self._storage[key]
            return False

        # Проверка совпадения
        if saved_code == code:
            del self._storage[key]  # одноразовый — удаляем
            return True

        return False