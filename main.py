import os
import asyncio
import aiohttp
import random
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserDeactivatedError, AuthKeyDuplicatedError,
    ChannelPrivateError, ChatWriteForbiddenError, PeerIdInvalidError
)
from database import db

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") # Admin for logging

# Global Cache
class Cache:
    channels_config = {} # {channel_id: [comments]}
    entities = {} # {channel_id: title}

cache = Cache()

async def update_cache():
    """Updates the in-memory cache from the database"""
    cache.channels_config = await db.get_all_config()
    print(f"🔄 Cache yangilandi: {len(cache.channels_config)} kanal yuklandi.")

async def send_to_admin(session, text: str):
    """Sends logs to the admin bot without blocking"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                print(f"⚠️ Admin logda xato: {resp.status}")
    except Exception as e:
        print(f"⚠️ Admin log yuborilmadi: {e}")

async def send_comment(session, client, name, channel_id, post_id, comment):
    try:
        # Zero-latency: directly send using cached info
        await client.send_message(entity=channel_id, message=comment, comment_to=post_id)
        
        channel_name = cache.entities.get(channel_id)
        if not channel_name:
            try:
                entity = await client.get_entity(channel_id)
                channel_name = entity.title
                cache.entities[channel_id] = channel_name
            except Exception:
                channel_name = f"ID: {channel_id}"

        text = f"✅ **{name}** → {channel_name}\n💬 {comment}"
        print(text)
        asyncio.create_task(send_to_admin(session, text))
        
    except FloodWaitError as e:
        await send_to_admin(session, f"⏳ **{name}**: FloodWait ({e.seconds}s). To'xtatildi.")
        await asyncio.sleep(e.seconds + 2)
    except ChatWriteForbiddenError:
        await send_to_admin(session, f"🚫 **{name}**: [{channel_id}] da yozish taqiqlangan (Banned?).")
    except ChannelPrivateError:
        await send_to_admin(session, f"🔒 **{name}**: [{channel_id}] kanal yopiq yoki akkaunt chiqarilgan.")
    except Exception as e:
        await send_to_admin(session, f"⚠️ **{name}**: [{channel_id}] xatolik - {str(e)[:100]}")

async def run_client(session, session_str):
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            await send_to_admin(session, f"❌ Akkaunt seansi faol emas (Session revoked).")
            return

        me = await client.get_me()
        name = f"{me.first_name} {me.last_name or ''}".strip() or "Noma'lum"

        # Check existing memberships to avoid unnecessary errors
        # Pre-fetch entities only for the channels we are interested in.
        for ch_id in cache.channels_config.keys():
            try:
                entity = await client.get_entity(ch_id)
                cache.entities[ch_id] = entity.title
            except Exception:
                pass

        await send_to_admin(session, f"🚀 **{name}** ishga tushdi va kuzatmoqda!")
        print(f"[{name}] Monitoring started...")

        @client.on(events.NewMessage())
        async def handler(event):
            channel_id = event.chat_id
            comments = cache.channels_config.get(channel_id)
            
            if comments:
                # Random realistic delay
                await asyncio.sleep(random.uniform(0.1, 0.8))
                comment = random.choice(comments)
                asyncio.create_task(send_comment(session, client, name, channel_id, event.id, comment))

        await client.run_until_disconnected()

    except UserDeactivatedError:
        await send_to_admin(session, f"❌ **Akkaunt o'chirilgan (Banned by Telegram).**")
    except AuthKeyDuplicatedError:
        await send_to_admin(session, f"❌ **Sessiya dublikati (Boshqa joyda ochilgan).**")
    except Exception as e:
        await send_to_admin(session, f"🔴 **Kritik xatolik ({session_str[:10]}...):** {e}")
    finally:
        await client.disconnect()

async def cache_updater_loop():
    """Background task to keep cache fresh every minute"""
    while True:
        await update_cache()
        await asyncio.sleep(60)

async def main():
    await db.connect()
    await update_cache()
    
    accounts = await db.get_active_accounts()
    if not accounts:
        print("⚠️ Hech qanday faol akkaunt topilmadi.")
        return

    async with aiohttp.ClientSession() as session:
        # Background cache updater
        asyncio.create_task(cache_updater_loop())
        
        tasks = [asyncio.create_task(run_client(session, acc['session_string'])) for acc in accounts]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
