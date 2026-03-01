from aiogram.types import Message
from aiogram import Bot, Router, F

router = Router()
@router.message(F.text)
async def any_text(message: Message):
    await message.answer("Сообщение получено (текст).")