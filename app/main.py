import os
import asyncio
import logging
import sys
from dataclasses import dataclass

from app.setting import Settings
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers.start import router as start_router
from app.bot.handlers.receipt import router as receipt_router

from app.infra.db.client import RedDatabaseClient
from app.logging_settings import setup_logging
from app.infra.auth.whitelist import WhitelistAuth
from app.infra.auth.otp import OTPService
from app.bot.middlewares import AuthMiddleware
from app.infra.db.auth_repository import AuthRepository
from app.bot.handlers.admin import router as admin_router

@dataclass
class AppContainer:
    bot: Bot
    dispatcher: Dispatcher
    auth_middleware: AuthMiddleware

def create_app(settings: Settings) -> AppContainer:
    setup_logging()

    bot = Bot(
        token=settings.tg_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    db = RedDatabaseClient(
            host=settings.rdb_host,
            port=settings.rdb_port,
            database=settings.rdb_database,
            user=settings.rdb_user,
            password=settings.rdb_password,
            charset=settings.rdb_charset,
        )

    auth_repo = AuthRepository(db, invite_salt=settings.invite_salt)
    whitelist = WhitelistAuth(auth_repo)
    otp = OTPService(auth_repo)

    auth_middleware = AuthMiddleware(
        whitelist=whitelist,
        repo=auth_repo,
        otp=otp,
        session_ttl_minutes=settings.session_ttl_minutes,
        allow_start_without_auth=True,
        admin_ids=settings.admin_ids,
    )

    dp = Dispatcher()
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)
    dp.include_router(receipt_router)
    dp.include_router(admin_router)
    dp.include_router(start_router)

    return AppContainer(
        bot=bot,
        dispatcher=dp,
        auth_middleware=auth_middleware,
    )
    
async def main() -> None:
    settings = Settings()
    app = create_app(settings)

    await app.dispatcher.start_polling(app.bot)


if __name__ == "__main__":
    asyncio.run(main())