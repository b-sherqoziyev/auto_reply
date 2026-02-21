import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from telethon import TelegramClient
from telethon.sessions import StringSession
from database import db
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("CHAT_ID")) # Using existing CHAT_ID as ADMIN_ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Registration(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

# Temporary storage for clients during registration
registration_clients = {}

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👋 Salom Admin! Akkaunt qo'shish uchun /add_account buyrug'ini bering.")

@dp.message(Command("add_account"))
async def add_account_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("📱 Telefon raqamni yuboring (masalan: +998901234567):")
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    try:
        code_hash = await client.send_code_request(phone)
        registration_clients[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": code_hash.phone_code_hash
        }
        await state.update_data(phone=phone)
        await message.answer("🔢 Telegramdan kelgan kodni yuboring:")
        await state.set_state(Registration.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        await client.disconnect()
        await state.clear()

@dp.message(Registration.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    user_data = registration_clients.get(message.from_user.id)
    
    if not user_data:
        await message.answer("❌ Seans topilmadi. Qatdan boshlang.")
        await state.clear()
        return

    client = user_data["client"]
    phone = user_data["phone"]
    phone_code_hash = user_data["phone_code_hash"]

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        # Success!
        session_str = client.session.save()
        me = await client.get_me()
        name = me.first_name or me.username
        
        await db.connect()
        await db.add_account(session_str, name, phone)
        
        await message.answer(f"✅ Akkaunt muvaffaqiyatli qo'shildi: {name}")
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
        
    except Exception as e:
        if "password" in str(e).lower():
            await message.answer("🔐 2-bosqichli parolni (2FA) yuboring:")
            await state.set_state(Registration.waiting_for_password)
        else:
            await message.answer(f"❌ Xatolik: {e}")
            await client.disconnect()
            await state.clear()

@dp.message(Registration.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    user_data = registration_clients.get(message.from_user.id)
    
    client = user_data["client"]
    phone = user_data["phone"]

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        me = await client.get_me()
        name = me.first_name or me.username
        
        await db.connect()
        await db.add_account(session_str, name, phone)
        
        await message.answer(f"✅ Akkaunt (2FA bilan) muvaffaqiyatli qo'shildi: {name}")
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        await client.disconnect()
        await state.clear()

@dp.message(Command("accounts"))
async def list_accounts_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    accounts = await db.pool.fetch("SELECT id, name, phone, is_active FROM accounts")
    if not accounts:
        await message.answer("ℹ️ Hech qanday akkaunt topilmadi.")
        return
    
    text = "👥 **Akkauntlar ro'yxati:**\n\n"
    for acc in accounts:
        status = "✅" if acc['is_active'] else "❌"
        text += f"{acc['id']}. {status} {acc['name']} ({acc['phone']})\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("add_channel"))
async def add_channel_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            await message.answer("⚠️ Format: `/add_channel [ID] [Nomi]`", parse_mode="Markdown")
            return
        channel_id = int(args[1])
        name = " ".join(args[2:])
        await db.add_channel(channel_id, name)
        await message.answer(f"✅ Kanal qo'shildi: {name} ({channel_id})")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("add_comment"))
async def add_comment_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        args = message.text.split(None, 2)
        if len(args) < 3:
            await message.answer("⚠️ Format: `/add_comment [ChannelID] [Matn]`", parse_mode="Markdown")
            return
        channel_id = int(args[1])
        text = args[2]
        await db.add_comment(channel_id, text)
        await message.answer(f"✅ Komment qo'shildi: {text[:20]}...")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("join_all"))
async def join_all_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Format: `/join_all [link]`")
        return
    
    link = args[1]
    accounts = await db.get_active_accounts()
    
    status_msg = await message.answer(f"⏳ {len(accounts)} ta akkaunt qo'shilmoqda...")
    
    success_count = 0
    fail_count = 0
    
    for acc in accounts:
        client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        try:
            await client.connect()
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest
            
            if "joinchat" in link or "+" in link:
                hash_code = link.split('/')[-1].replace('+', '')
                await client(ImportChatInviteRequest(hash_code))
            else:
                await client(JoinChannelRequest(link))
            success_count += 1
        except Exception as e:
            print(f"Error joining {acc['name']}: {e}")
            fail_count += 1
        finally:
            await client.disconnect()
            
    await status_msg.edit_text(f"🏁 Yakunlandi:\n✅ Muvaffaqiyatli: {success_count}\n❌ Xato: {fail_count}")

async def admin_bot_main():
    await db.connect()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(admin_bot_main())
