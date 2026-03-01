from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Set

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from app.infra.auth.whitelist import WhitelistAuth
from app.infra.auth.otp import OTPService
from app.infra.db.auth_repository import AuthRepository


class AuthMiddleware(BaseMiddleware):
    def __init__(
        self,
        whitelist: WhitelistAuth,
        repo: AuthRepository,
        otp: Optional[OTPService] = None,
        *,
        session_ttl_minutes: int = 60,
        allow_start_without_auth: bool = True,
        admin_ids: list[int] | None = None,
    ) -> None:
        self.whitelist = whitelist
        self.repo = repo
        self.admin_ids = admin_ids or []
        self.otp = otp
        self.session_ttl_minutes = session_ttl_minutes
        self.allow_start_without_auth = allow_start_without_auth

        self._awaiting_code: Set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        data["otp"] = self.otp
        data["admin_ids"] = self.admin_ids
        if user_id is None:
            return await handler(event, data)

        # 0) валидная сессия — сразу пускаем
        if self.repo.is_session_valid(user_id):
            return await handler(event, data)

        # 1) whitelist (AUTH_USERS active) — создаём сессию и пускаем
        if self.whitelist.is_allowed(user_id):
            self.repo.upsert_session(user_id, self.session_ttl_minutes)
            self._awaiting_code.discard(user_id)
            return await handler(event, data)

        # 2) /start без авторизации разрешаем
        if self.allow_start_without_auth and self._is_start_command(event):
            return await handler(event, data)

        # 3) если нет сервиса кодов — блокируем
        if self.otp is None:
            await self._reply(event, "⛔ У вас нет доступа. Обратитесь к администратору.")
            return None

        # 4) ждём access code
        if user_id not in self._awaiting_code:
            self._awaiting_code.add(user_id)
            await self._reply(
                event,
                "🔐 Требуется доступ.\n"
                "Отправьте **код доступа** обычным текстом одним сообщением.",
                parse_mode="Markdown",
            )
            return None

        # 5) принимаем только текст/подпись
        if isinstance(event, Message):
            code_text = (event.text or event.caption or "").strip()
            if not code_text:
                await event.answer("Сейчас нужен код (текстом). Фото/файлы не подходят.")
                return None

            ok = self.otp.verify_code(user_id, code_text)
            if ok:
                # создаём сессию
                self.repo.upsert_session(user_id, self.session_ttl_minutes)
                self._awaiting_code.discard(user_id)
                await event.answer("✅ Доступ подтверждён. Теперь можно отправлять чеки.")
                return None

            await event.answer("❌ Неверный/просроченный/отозванный код. Попробуйте ещё раз.")
            return None

        await self._reply(event, "🔐 Сначала отправьте код доступа (текстом).")
        return None

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> Optional[int]:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    @staticmethod
    def _is_start_command(event: TelegramObject) -> bool:
        return isinstance(event, Message) and bool(event.text) and event.text.strip().startswith("/start")

    @staticmethod
    async def _reply(event: TelegramObject, text: str, **kwargs: Any) -> None:
        if isinstance(event, Message):
            await event.answer(text, **kwargs)
        elif isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(text, **kwargs)