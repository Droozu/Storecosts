from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.infra.auth.otp import OTPService

router = Router()


def _parse_args(text: str) -> tuple[int, int | None]:
    """
    /create_code <max_uses> [ttl_minutes]
    примеры:
      /create_code 1
      /create_code 5 1440
    """
    parts = text.strip().split()
    if len(parts) < 2:
        return 1, None
    max_uses = int(parts[1])
    ttl = int(parts[2]) if len(parts) >= 3 else None
    return max_uses, ttl


@router.message(Command("create_code"))
async def create_code(message: Message, otp: OTPService, admin_ids: list[int]):
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in admin_ids:
        await message.answer("⛔ Недостаточно прав.")
        return

    try:
        max_uses, ttl = _parse_args(message.text or "")
        if max_uses <= 0:
            raise ValueError("max_uses must be > 0")
    except Exception:
        await message.answer("Формат: /create_code <max_uses> [ttl_minutes]\nПример: /create_code 3 1440")
        return

    invite = otp.create_invite_code(
        created_by=user_id,
        max_uses=max_uses,
        ttl_minutes=ttl,
    )

    ttl_text = f"{invite.ttl_minutes} мин" if invite.ttl_minutes is not None else "∞"
    await message.answer(
        "✅ Код создан:\n"
        f"<b>{invite.code}</b>\n"
        f"max_uses: {invite.max_uses}\n"
        f"ttl: {ttl_text}"
    )