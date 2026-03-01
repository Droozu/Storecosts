
from os import getenv

from aiogram import Bot, Router, html
from aiogram.filters import CommandStart
from aiogram.methods import get_file
from aiogram.types import Message

router = Router()

@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Hello, {html.bold(message.from_user.full_name)}!")


@router.message()
async def fallback(_: Message) -> None:
    return