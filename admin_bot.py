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

class ChannelAddition(StatesGroup):
    waiting_for_id = State()
    waiting_for_link = State()

class CommentAddition(StatesGroup):
    waiting_for_ch_id = State()
    waiting_for_text = State()

class JoinAll(StatesGroup):
    waiting_for_link = State()

# --- Keyboards ---
def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Akkauntlar", callback_data="manage_accounts"))
    builder.row(types.InlineKeyboardButton(text="📢 Kanallar", callback_data="manage_channels"))
    builder.row(types.InlineKeyboardButton(text="➕ Akkaunt Qo'shish", callback_data="add_account"))
    builder.row(types.InlineKeyboardButton(text="🔗 Ommaviy Qo'shilish", callback_data="join_all_start"))
    return builder.as_markup()

def get_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action"))
    return builder.as_markup()

# --- General Handlers ---
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👋 Salom Admin! Quyidagi menyudan foydalaning:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Amal bekor qilindi.", reply_markup=get_main_menu())

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👋 Salom Admin! Quyidagi menyudan foydalaning:", reply_markup=get_main_menu())

# --- Account Management ---
@dp.callback_query(F.data == "manage_accounts")
async def manage_accounts(callback: types.CallbackQuery):
    accounts = await db.pool.fetch("SELECT id, name, phone, is_active FROM accounts ORDER BY id ASC")
    builder = InlineKeyboardBuilder()
    
    text = "👥 **Akkauntlar ro'yxati:**\n\n"
    if not accounts:
        text += "ℹ️ Hech qanday akkaunt topilmadi."
    else:
        for acc in accounts:
            status = "✅" if acc['is_active'] else "❌"
            btn_text = f"{status} {acc['name'] or acc['phone']}"
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
registration_clients = {}

@dp.callback_query(F.data == "add_account")
async def add_account_btn(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📱 Telefon raqamni yuboring (masalan: +998901234567):", reply_markup=get_cancel_kb())
    await state.set_state(Registration.waiting_for_phone)

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
        await message.answer("🔢 Telegramdan kelgan kodni yuboring:", reply_markup=get_cancel_kb())
        await state.set_state(Registration.waiting_for_code)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=get_main_menu())
        await client.disconnect()
        await state.clear()

@dp.message(Registration.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    user_data = registration_clients.get(message.from_user.id)
    if not user_data:
        await message.answer("❌ Seans topilmadi.", reply_markup=get_main_menu())
        await state.clear()
        return

    client, phone, phone_code_hash = user_data["client"], user_data["phone"], user_data["phone_code_hash"]
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        me = await client.get_me()
        await db.add_account(session_str, (me.first_name or "") + " " + (me.last_name or ""), phone)
        await message.answer(f"✅ Akkaunt muvaffaqiyatli qo'shildi: {me.first_name}", reply_markup=get_main_menu())
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
    except Exception as e:
        if "password" in str(e).lower():
            await message.answer("🔐 2FA parolini yuboring:", reply_markup=get_cancel_kb())
            await state.set_state(Registration.waiting_for_password)
        else:
            await message.answer(f"❌ Xatolik: {e}", reply_markup=get_main_menu())
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
        await db.add_account(session_str, (me.first_name or "") + " " + (me.last_name or ""), phone)
        await message.answer(f"✅ Akkaunt (2FA bilan) qo'shildi: {me.first_name}", reply_markup=get_main_menu())
        await client.disconnect()
        del registration_clients[message.from_user.id]
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=get_main_menu())
        await client.disconnect()
        await state.clear()

# --- Channel Management ---
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
    
    builder.row(types.InlineKeyboardButton(text="➕ Kanal Qo'shish", callback_data="add_channel_start"))
    builder.row(types.InlineKeyboardButton(text="💬 Komment Qo'shish", callback_data="add_comment_start"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_channel_start")
async def add_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🆔 Kanal ID sini yuboring (Masalan: -100123456):", reply_markup=get_cancel_kb())
    await state.set_state(ChannelAddition.waiting_for_id)

@dp.message(ChannelAddition.waiting_for_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    try:
        ch_id = int(message.text.strip())
        await state.update_data(ch_id=ch_id)
        await message.answer("🔗 Endi ushbu kanal havolasini (link) yuboring:", reply_markup=get_cancel_kb())
        await state.set_state(ChannelAddition.waiting_for_link)
    except:
        await message.answer("❌ Xato ID. Faqat raqamlarni yuboring.")

@dp.message(ChannelAddition.waiting_for_link)
async def process_channel_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    data = await state.get_data()
    ch_id = data['ch_id']
    
    accounts = await db.get_active_accounts()
    if not accounts:
        await message.answer("❌ Faol akkauntlar yo'q.", reply_markup=get_main_menu())
        await state.clear()
        return

    status_msg = await message.answer("⏳ Kanal nomi aniqlanmoqda va akkauntlar qo'shilmoqda...")
    ch_name = "Noma'lum Kanal"
    
    # Fetch name using the first account
    client = TelegramClient(StringSession(accounts[0]['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        try:
            entity = await client.get_entity(link)
            ch_name = entity.title
        except:
            try:
                entity = await client.get_entity(ch_id)
                ch_name = entity.title
            except: pass
        await db.add_channel(ch_id, ch_name)
    finally: await client.disconnect()

    success, fail = 0, 0
    for acc in accounts:
        cli = TelegramClient(StringSession(acc['session_string']), API_ID, API_HASH)
        try:
            await cli.connect()
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest
            if "joinchat" in link or "+" in link:
                await cli(ImportChatInviteRequest(link.split('/')[-1].replace('+', '')))
            else:
                await cli(JoinChannelRequest(link))
            success += 1
        except: fail += 1
        finally: await cli.disconnect()
        
    await status_msg.edit_text(f"✅ Kanal: **{ch_name}** qo'shildi!\n✅ {success} akkaunt kirdi.\n❌ {fail} xato.", reply_markup=get_main_menu(), parse_mode="Markdown")
    await state.clear()

# --- Comment Management ---
@dp.callback_query(F.data == "add_comment_start")
async def add_comment_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🆔 Kanal ID sini yuboring:", reply_markup=get_cancel_kb())
    await state.set_state(CommentAddition.waiting_for_ch_id)

@dp.message(CommentAddition.waiting_for_ch_id)
async def process_comment_ch_id(message: types.Message, state: FSMContext):
    try:
        ch_id = int(message.text.strip())
        await state.update_data(ch_id=ch_id)
        await message.answer("💬 Komment matnini yuboring:", reply_markup=get_cancel_kb())
        await state.set_state(CommentAddition.waiting_for_text)
    except:
        await message.answer("❌ Xato ID.")

@dp.message(CommentAddition.waiting_for_text)
async def process_comment_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await db.add_comment(data['ch_id'], message.text)
    await message.answer("✅ Komment qo'shildi!", reply_markup=get_main_menu())
    await state.clear()

# --- Bulk Join ---
@dp.callback_query(F.data == "join_all_start")
async def join_all_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔗 Kanal havolasini (link) yuboring:", reply_markup=get_cancel_kb())
    await state.set_state(JoinAll.waiting_for_link)

@dp.message(JoinAll.waiting_for_link)
async def process_join_all_link(message: types.Message, state: FSMContext):
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
