import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from telethon import TelegramClient
from telethon.sessions import StringSession
from database import db
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Registration(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

class ChannelComment(StatesGroup):
    waiting_for_channel_details = State()
    waiting_for_channel_link = State()
    waiting_for_comment_text = State()

class JoinAll(StatesGroup):
    waiting_for_link = State()

# Temporary storage for clients during registration
registration_clients = {}

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Akkauntlar", callback_data="manage_accounts"))
    builder.row(types.InlineKeyboardButton(text="📢 Kanallar", callback_data="manage_channels"))
    builder.row(types.InlineKeyboardButton(text="➕ Akkaunt Qo'shish", callback_data="add_account"))
    builder.row(types.InlineKeyboardButton(text="🔗 Ommaviy Qo'shilish", callback_data="join_all"))
    return builder.as_markup()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👋 Salom Admin! Quyidagi menyudan foydalaning:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("👋 Salom Admin! Quyidagi menyudan foydalaning:", reply_markup=get_main_menu())

# --- Account Management ---
@dp.callback_query(F.data == "manage_accounts")
async def manage_accounts(callback: types.CallbackQuery):
    accounts = await db.pool.fetch("SELECT id, name, phone, is_active FROM accounts")
    builder = InlineKeyboardBuilder()
    
    text = "👥 **Akkauntlar ro'yxati:**\n\n"
    if not accounts:
        text += "ℹ️ Hech qanday akkaunt topilmadi."
    else:
        for acc in accounts:
            status = "✅" if acc['is_active'] else "❌"
            btn_text = f"{status} {acc['name']}"
            builder.row(types.InlineKeyboardButton(text=btn_text, callback_data=f"toggle_acc_{acc['id']}"))
    
    builder.row(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("toggle_acc_"))
async def toggle_account(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[-1])
    current_status = await db.pool.fetchval("SELECT is_active FROM accounts WHERE id = $1", acc_id)
    await db.toggle_account(acc_id, not current_status)
    await manage_accounts(callback)

# --- Account Registration ---
@dp.callback_query(F.data == "add_account")
async def add_account_btn(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📱 Telefon raqamni yuboring (masalan: +998901234567):")
    await state.set_state(Registration.waiting_for_phone)
    await callback.answer()

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    try:
        code_hash = await client.send_code_request(phone)
        registration_clients[message.from_user.id] = {
            "client": client, "phone": phone, "phone_code_hash": code_hash.phone_code_hash
        }
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
        await message.answer("❌ Seans topilmadi.")
        await state.clear()
        return

    client, phone, phone_code_hash = user_data["client"], user_data["phone"], user_data["phone_code_hash"]
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        me = await client.get_me()
        await db.add_account(session_str, me.first_name, phone)
        await message.answer(f"✅ Akkaunt muvaffaqiyatli qo'shildi: {me.first_name}", reply_markup=get_main_menu())
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
    except Exception as e:
        if "password" in str(e).lower():
            await message.answer("🔐 2FA parolini yuboring:")
            await state.set_state(Registration.waiting_for_password)
        else:
            await message.answer(f"❌ Xatolik: {e}")
            await client.disconnect()
            await state.clear()

@dp.message(Registration.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    user_data = registration_clients.get(message.from_user.id)
    client, phone = user_data["client"], user_data["phone"]
    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        me = await client.get_me()
        await db.add_account(session_str, me.first_name, phone)
        await message.answer(f"✅ Akkaunt (2FA bilan) qo'shildi: {me.first_name}", reply_markup=get_main_menu())
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}"); await client.disconnect(); await state.clear()

# --- Channel & Comment Management ---
@dp.callback_query(F.data == "manage_channels")
async def manage_channels(callback: types.CallbackQuery):
    channels = await db.get_active_channels()
    builder = InlineKeyboardBuilder()
    text = "📢 **Kanallar ro'yxati:**\n\n"
    if not channels:
        text += "ℹ️ Hech qanday kanal topilmadi."
    else:
        for ch in channels:
            text += f"• {ch['name']} (`{ch['channel_id']}`)\n"
    
    builder.row(types.InlineKeyboardButton(text="➕ Kanal Qo'shish", callback_data="add_channel_step"))
    builder.row(types.InlineKeyboardButton(text="💬 Komment Qo'shish", callback_data="add_comment_step"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_channel_step")
async def add_channel_step(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🆔 Kanal ID sini yuboring (Masalan: -100123456):")
    await state.set_state(ChannelComment.waiting_for_channel_details)
    await callback.answer()

@dp.message(ChannelComment.waiting_for_channel_details)
async def process_channel_details(message: types.Message, state: FSMContext):
    try:
        ch_id = int(message.text.strip())
        await state.update_data(ch_id=ch_id)
        await message.answer(f"🆔 ID qabul qilindi: `{ch_id}`\n\n🔗 Endi ushbu kanalning havolasini (link) yuboring. Bu orqali kanal nomi aniqlanadi va barcha akkauntlar qo'shiladi:", parse_mode="Markdown")
        await state.set_state(ChannelComment.waiting_for_channel_link)
    except Exception as e:
        await message.answer("❌ Xato format. Faqat so'zlarsiz ID raqamini yuboring.")

@dp.message(ChannelComment.waiting_for_channel_link)
async def process_channel_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    data = await state.get_data()
    ch_id = data['ch_id']
    
    accounts = await db.get_active_accounts()
    if not accounts:
        await message.answer("❌ Hech qanday faol akkaunt topilmadi. Avval /add_account orqali akkaunt qo'shing.")
        await state.clear()
        return

    status_msg = await message.answer("⏳ Kanal nomi aniqlanmoqda va akkauntlar qo'shilmoqda...")
    
    ch_name = "Noma'lum Kanal"
    success, fail = 0, 0
    
    # Use the first account to get the channel name
    first_acc = accounts[0]
    client = TelegramClient(StringSession(first_acc['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        # Try to get entity by ID or Link
        try:
            entity = await client.get_entity(link)
            ch_name = entity.title
        except:
            try:
                entity = await client.get_entity(ch_id)
                ch_name = entity.title
            except:
                pass
        
        # Save to database now that we have the name
        await db.add_channel(ch_id, ch_name)
        
    except Exception as e:
        print(f"Name fetch error: {e}")
    finally:
        await client.disconnect()

    # Bulk Join
    for acc in accounts:
        client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        try:
            await client.connect()
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest
            if "joinchat" in link or "+" in link:
                await client(ImportChatInviteRequest(link.split('/')[-1].replace('+', '')))
            else:
                await client(JoinChannelRequest(link))
            success += 1
        except: fail += 1
        finally: await client.disconnect()
        
    await status_msg.edit_text(f"✅ Kanal qo'shildi: **{ch_name}**\n\n🏁 Qo'shilish yakunlandi:\n✅ Muvaffaqiyatli: {success}\n❌ Xato: {fail}", reply_markup=get_main_menu(), parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "add_comment_step")
async def add_comment_btn(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🆔 Kanal ID sini yuboring:")
    await state.set_state(ChannelComment.waiting_for_comment_text) # Reusing state sequence
    await callback.answer()

@dp.message(ChannelComment.waiting_for_comment_text)
async def process_comment_id(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("💬 Komment matnini yuboring:")
    # Using a sub-state would be cleaner but let's keep it simple
    @dp.message(F.text, ChannelComment.waiting_for_comment_text) # This is a bit hacky, but works for quick refactor
    async def process_final_comment(msg: types.Message, st: FSMContext):
        data = await st.get_data()
        await db.add_comment(int(data['ch_id']), msg.text)
        await msg.answer("✅ Komment qo'shildi!", reply_markup=get_main_menu())
        await st.clear()

# --- Bulk Join ---
@dp.callback_query(F.data == "join_all")
async def join_all_btn(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔗 Kanal havolasini (link) yuboring:")
    await state.set_state(JoinAll.waiting_for_link)
    await callback.answer()

@dp.message(JoinAll.waiting_for_link)
async def process_join_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    accounts = await db.get_active_accounts()
    status_msg = await message.answer(f"⏳ {len(accounts)} ta akkaunt qo'shilmoqda...")
    success, fail = 0, 0
    for acc in accounts:
        client = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        try:
            await client.connect()
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest
            if "joinchat" in link or "+" in link:
                await client(ImportChatInviteRequest(link.split('/')[-1].replace('+', '')))
            else:
                await client(JoinChannelRequest(link))
            success += 1
        except: fail += 1
        finally: await client.disconnect()
    await status_msg.edit_text(f"🏁 Yakunlandi:\n✅ Muvaffaqiyatli: {success}\n❌ Xato: {fail}", reply_markup=get_main_menu())
    await state.clear()

async def admin_bot_main():
    await db.connect()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(admin_bot_main())
