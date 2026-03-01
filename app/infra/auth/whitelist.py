from app.infra.db.auth_repository import AuthRepository


class WhitelistAuth:
    def __init__(self, repo: AuthRepository) -> None:
        self.repo = repo

    def is_allowed(self, telegram_user_id: int) -> bool:
        return self.repo.is_user_active(telegram_user_id)