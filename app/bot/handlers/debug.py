
from os import getenv

from aiogram import Bot, Router, html
from aiogram.filters import CommandStart
from aiogram.methods import get_file
from aiogram.types import Message

router = Router()

@router.message()
async def debug_any(m: Message):
    await m.answer(f"DEBUG OK: ctype={m.content_type} text={m.text!r} caption={m.caption!r}")