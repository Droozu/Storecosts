from aiogram import Router, F
from aiogram.types import Message

router = Router()

# Ловим фото
@router.message(F.photo)
async def handle_photo(message: Message):
    # Берём самое большое фото
    photo = message.photo[-1]

    file_id = photo.file_id
    file_unique_id = photo.file_unique_id

    await message.answer(
        f"📸 Фото получено!\n"
        f"file_id: {file_id}\n"
        f"unique_id: {file_unique_id}"
    )

# Ловим файл, если пользователь отправил как документ
@router.message(F.document)
async def handle_document(message: Message):
    document = message.document

    await message.answer(
        f"📎 Файл получен!\n"
        f"Имя: {document.file_name}\n"
        f"Тип: {document.mime_type}"
    )