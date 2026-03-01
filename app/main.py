import os
import asyncio
import logging
import sys

from app.setting import Settings
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers.start import router as start_router
from app.bot.handlers.receipt import router as receipt_router

from app.logging_set import setup_logging
from app.infra.auth.whitelist import WhitelistAuth
from app.infra.auth.otp import OTPService
from app.bot.middlewares import AuthMiddleware

async def main() -> None:
    setup_logging()
    settings = Settings()
    bot = Bot(token=settings.tg_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    whitelist = WhitelistAuth()
    otp = OTPService(ttl_seconds=300)
    auth_mw = AuthMiddleware(whitelist=whitelist, otp=otp, allow_start_without_auth=False)

    dp = Dispatcher()
    dp.message.middleware(auth_mw)
    dp.callback_query.middleware(auth_mw)
    dp.include_router(receipt_router)
    dp.include_router(start_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())