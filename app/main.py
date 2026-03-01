import os
import asyncio
import logging
import sys

from app.setting import Settings
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


from app.bot.handlers.start import router as start_router



    
async def main() -> None:
    settings = Settings()
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    bot = Bot(token=settings.tg_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start_router)
    # And the run events dispatching
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())