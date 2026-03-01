from aiogram import Router
from aiogram.types import ChatMemberUpdated

router = Router()

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    # изменения статуса самого бота (добавили/удалили/забанили)
    print("MY_CHAT_MEMBER:", event.new_chat_member.status, "chat:", event.chat.id)

@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated):
    # изменения статуса обычных участников в чате
    print("CHAT_MEMBER:", event.new_chat_member.status, "chat:", event.chat.id)