from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Set

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from app.infra.auth.whitelist import WhitelistAuth
from app.infra.auth.otp import OTPService


class AuthMiddleware(BaseMiddleware):
    def __init__(
        self,
        whitelist: WhitelistAuth,
        otp: Optional[OTPService] = None,
        *,
        allow_start_without_auth: bool = True,
    ) -> None:
        self.whitelist = whitelist
        self.otp = otp
        self.allow_start_without_auth = allow_start_without_auth

        self._authed_users: Set[int] = set()
        self._awaiting_otp: Set[int] = set()

    def mark_authed(self, user_id: int) -> None:
        self._authed_users.add(user_id)
        self._awaiting_otp.discard(user_id)

    def is_authed(self, user_id: int) -> bool:
        return user_id in self._authed_users

    def is_awaiting_otp(self, user_id: int) -> bool:
        return user_id in self._awaiting_otp

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        if isinstance(event, Message):
            print("AUTH:", "user=", user_id, "ctype=", event.content_type, "text=", repr(event.text), "caption=", repr(event.caption),
            "awaiting=", (user_id in self._awaiting_otp), "authed=", (user_id in self._authed_users), "mw_id=", id(self))  
        # безопасный дебаг (по желанию)
        if isinstance(event, Message):
            print(
                "MW MSG:",
                event.content_type,
                "text=", repr(event.text),
                "caption=", repr(event.caption),
                "from=", user_id,
            )
        elif isinstance(event, CallbackQuery):
            print("MW CBQ:", "data=", repr(event.data), "from=", user_id)
        else:
            print("MW EVENT:", type(event), "from=", user_id)

        if user_id is None:
            return await handler(event, data)

        # 1) whitelist всегда имеет приоритет
        if self.whitelist.is_allowed(user_id):
            self.mark_authed(user_id)
            return await handler(event, data)

        # 2) уже подтверждён
        if self.is_authed(user_id):
            return await handler(event, data)

        # 3) /start без авторизации разрешаем
        if self.allow_start_without_auth and self._is_start_command(event):
            return await handler(event, data)

        # 4) OTP не настроен — блокируем
        if self.otp is None:
            await self._reply(event, "⛔ У вас нет доступа. Обратитесь к администратору.")
            return None

        # 5) если ещё не ждём OTP — выдаём
        if not self.is_awaiting_otp(user_id):
            code = self.otp.generate_code(user_id)
            self._awaiting_otp.add(user_id)

            await self._reply(
                event,
                "🔐 Требуется подтверждение.\n"
                "Отправьте одноразовый код **сообщением** (не фото и не файл).\n\n"
                f"OTP (MVP): `{code}`",
                parse_mode="Markdown",
            )
            return None

        # 6) ждём OTP: принимаем только текст (или caption)
        if isinstance(event, Message):
            code_text = (event.text or event.caption or "").strip()

            if not code_text:
                await event.answer("🔐 Сейчас нужен код (обычным текстом). Фото/файлы пока не принимаю.")
                return None

            ok = self.otp.verify_code(user_id, code_text)
            if ok:
                self.mark_authed(user_id)
                await event.answer("✅ Доступ подтверждён. Теперь можно отправлять чеки.")
                return None

            await event.answer("❌ Неверный или просроченный код. Попробуйте ещё раз.")
            return None

        # если это callback_query или другое событие
        await self._reply(event, "🔐 Сначала отправьте одноразовый код (текстом).")
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
        if isinstance(event, Message) and event.text:
            return event.text.strip().startswith("/start")
        return False

    @staticmethod
    async def _reply(event: TelegramObject, text: str, **kwargs: Any) -> None:
        if isinstance(event, Message):
            await event.answer(text, **kwargs)
        elif isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(text, **kwargs)