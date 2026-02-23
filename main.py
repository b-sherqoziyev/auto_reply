import os
import asyncio
import aiohttp
import random
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantRequest, LeaveChannelRequest
from telethon.tl.types import ChannelParticipantBanned
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
    restrictions = {} # {(session_str, channel_id): until_date}

cache = Cache()

async def update_cache():
    """Updates the in-memory cache from the database"""
    cache.channels_config = await db.get_all_config()
    
    # Load restrictions
    restrs = await db.get_all_restrictions()
    cache.restrictions = {(r['session_string'], r['channel_id']): r['until_date'] for r in restrs}
    
    print(f"🔄 Cache yangilandi: {len(cache.channels_config)} kanal, {len(cache.restrictions)} ta cheklov yuklandi.")

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
    # Resolve channel name first so it's available in success or error logs
    channel_name = cache.entities.get(channel_id)
    if not channel_name:
        try:
            entity = await client.get_entity(channel_id)
            channel_name = entity.title
            cache.entities[channel_id] = channel_name
        except Exception:
            channel_name = f"ID: {channel_id}"

    try:
        # Zero-latency: directly send using cached info
        await client.send_message(entity=channel_id, message=comment, comment_to=post_id)
        
        text = f"✅ **{name}** → {channel_name}\n💬 {comment}"
        print(text)
        asyncio.create_task(send_to_admin(session, text))
        
    except FloodWaitError as e:
        await send_to_admin(session, f"⏳ **{name}**: FloodWait ({e.seconds}s) @ {channel_name}. To'xtatildi.")
        await asyncio.sleep(e.seconds + 2)
    except ChatWriteForbiddenError:
        try:
            # Check the restriction reason and duration
            participant = await client(GetParticipantRequest(channel_id, 'me'))
            if hasattr(participant, 'participant') and isinstance(participant.participant, ChannelParticipantBanned):
                rights = participant.participant.banned_rights
                until = rights.until_date
                
                if until is None or (until.year > 2030): # Permanent or effectively permanent
                    await send_to_admin(session, f"🚫 **{name}**: {channel_name} dan umrbod haydalgan (Banned). Kanal tark etilmoqda...")
                    await client(LeaveChannelRequest(channel_id))
                else:
                    # Temporary restriction
                    formatted_date = until.strftime("%Y-%m-%d %H:%M")
                    await db.add_restriction(client.session.save(), channel_id, until)
                    await update_cache()
                    await send_to_admin(session, f"⏳ **{name}**: {channel_name} da yozish cheklangan. Muddati: `{formatted_date}` gacha.")
            else:
                await send_to_admin(session, f"🚫 **{name}**: {channel_name} da yozish taqiqlangan (Mute/Banned).")
        except Exception as e:
            await send_to_admin(session, f"🚫 **{name}**: {channel_name} da yozish taqiqlangan (Xatolik: {e})")
    except ChannelPrivateError:
        await send_to_admin(session, f"🔒 **{name}**: {channel_name} kanal yopiq yoki akkaunt chiqarilgan.")
    except Exception as e:
        await send_to_admin(session, f"⚠️ **{name}**: {channel_name} xatolik - {str(e)[:100]}")

async def run_client(session, session_str, account_index, total_accounts):
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            await send_to_admin(session, f"❌ Akkaunt seansi faol emas (Session revoked).")
            return

        me = await client.get_me()
        name = f"{me.first_name} {me.last_name or ''}".strip() or "Noma'lum"

        # Pre-fetch entities for current config
        for ch_id in cache.channels_config.keys():
            try:
                entity = await client.get_entity(ch_id)
                cache.entities[ch_id] = entity.title
            except Exception:
                pass

        await send_to_admin(session, f"🚀 **{name}** ishga tushdi (Idx: {account_index})!")
        print(f"[{name}] Monitoring started...")

        @client.on(events.NewMessage())
        async def handler(event):
            channel_id = event.chat_id
            comments = cache.channels_config.get(channel_id)
            
            if comments:
                # Check for active restriction in cache
                restriction_until = cache.restrictions.get((session_str, channel_id))
                if restriction_until:
                    # If restriction hasn't expired, skip
                    if restriction_until > datetime.now(restriction_until.tzinfo):
                        return
                    else:
                        # Expired: remove from cache (DB clean will happen on next update)
                        cache.restrictions.pop((session_str, channel_id), None)

                # ADVANCED ANTI-DETECTION: Seeded randomization per message
                # All running clients will generate the SAME random order for the SAME message ID
                rng = random.Random(event.id)
                order = list(range(total_accounts))
                rng.shuffle(order)
                
                # Determine this account's position in the current post's queue
                my_pos = order.index(account_index)
                
                if my_pos == 0:
                    total_delay = 0 # This post's sniper
                else:
                    # Staggered delay based on position
                    base_delay = my_pos * 0.5 
                    human_jitter = random.uniform(0.1, 0.4) 
                    total_delay = base_delay + human_jitter
                
                if total_delay > 0:
                    await asyncio.sleep(total_delay)
                
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
        
        # Start accounts with their index and total count
        tasks = [
            asyncio.create_task(run_client(session, acc['session_string'], idx, len(accounts))) 
            for idx, acc in enumerate(accounts)
        ]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
