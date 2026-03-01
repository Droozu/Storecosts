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

from app.infra.auth.whitelist import WhitelistAuth
from app.infra.auth.otp import OTPService
from app.bot.middlewares import AuthMiddleware

async def main() -> None:
    settings = Settings()
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    bot = Bot(token=settings.tg_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    whitelist = WhitelistAuth()
    otp = OTPService(ttl_seconds=300)
    auth_mw = AuthMiddleware(whitelist=whitelist, otp=otp)

    dp.message.middleware(auth_mw)
    dp.callback_query.middleware(auth_mw)
    dp.include_router(start_router)
    dp.include_router(receipt_router)
    # And the run events dispatching
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())