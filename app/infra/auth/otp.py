import secrets
from app.infra.db.auth_repository import AuthRepository, ConsumeCodeResult
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class InviteCode:
    code: str          # то, что показываем человеку
    code_hash: str     # то, что ушло в БД
    max_uses: int
    ttl_minutes: Optional[int]


class OTPService:
    def __init__(self, repo: AuthRepository) -> None:
        self.repo = repo

    def create_invite_code(
        self,
        *,
        created_by: Optional[int] = None,
        max_uses: int = 1,
        ttl_minutes: Optional[int] = None,
    ) -> InviteCode:
        code = secrets.token_urlsafe(8)
        code_hash = self.repo.hash_code(code)

        self.repo.create_invite_code(
            code_hash=code_hash,
            status="active",
            max_uses=max_uses,
            created_by=created_by,
            ttl_minutes=ttl_minutes,
        )
        return InviteCode(code=code, code_hash=code_hash, max_uses=max_uses, ttl_minutes=ttl_minutes)

    def verify_code(self, telegram_user_id: int, code: str) -> bool:
        res: ConsumeCodeResult = self.repo.consume_invite_code(telegram_user_id, code)
        if not res.ok:
            return False

        # код съели — добавляем/активируем пользователя в AUTH_USERS
        self.repo.upsert_user_active(telegram_user_id)
        return True