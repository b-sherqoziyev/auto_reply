import os
import asyncio
import aiohttp
import random
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

channels = {
    -1001337701474: ["Zo'r", "Ha", "🧒🏿", "Siuu"],  # inline
    -1002460046152: ["Ha", "Zo'r", "Keldim", "🧒🏿", "Siuu"],  # futbolishee
    -1002421347022: ["Zo'r", "Ha"],  # bekorchi
    -1002331884910: ["Zo'r", "Ha", "Efuzmobile nomr 1", "🧒🏿", "Siuu"],  # efuzmobile
    -1002423336133: ["Zo'r", "Ha", "Efootball next nomr 1", "🧒🏿", "Siuu"],  # efootball next
    -1002739674759: ["Zo'r", "Ha", "Zico nomr 1", "🧒🏿", "Siuu"],  # Zico
    -1001974475685: ["Ha", "Zo'r", "🧒🏿", "Siuu", "Oligarch nomr 1", "Efootballpageuz nomr 1"],  # efootball page
    -1001449117896: ["ha", "🧒🏿", "Siuu"],  # stock
    -1001666463882: ["ha", "eng zo'r kanal", "Siuu"],  # private cr7
    -1001171062015: ["ha", "🧒🏿", "Siuu"]  # aslam
}


def load_sessions():
    sessions = []
    i = 1
    while True:
        key = f"STRING_SESSION{i}"
        value = os.getenv(key)
        if not value:
            break
        sessions.append(value)
        i += 1
    return sessions


async def send_to_bot(session, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                print(f"⚠️ Log yuborishda xato: {resp.status}")
    except Exception as e:
        print(f"⚠️ Log yuborilmadi: {e}")


async def send_comment(session, client, name, channel_id, post_id, channel_name, comment):
    try:
        await client.send_message(entity=channel_id, message=comment, comment_to=post_id)
        text = f"💬 {name} → {channel_name}\n📨 {comment}"
        print(text)
        await send_to_bot(session, text)
    except FloodWaitError as e:
        await send_to_bot(session, f"⏳ {name}: FloodWait {e.seconds}s kutyapti.")
        await asyncio.sleep(e.seconds + 5)
    except Exception as e:
        await send_to_bot(session, f"⚠️ {name}: komment yozishda xato - {e}")


async def run_client(session, session_str):
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    name = me.first_name or me.username or "Noma’lum"

    await send_to_bot(session, f"✅ {name} ishga tushdi!")
    print(f"{name} ishga tushdi!")

    @client.on(events.NewMessage(chats=list(channels.keys())))
    async def handler(event):
        try:
            await asyncio.sleep(random.uniform(0.5, 2))
            channel_id = event.chat_id
            entity = await client.get_entity(channel_id)
            channel_name = entity.title
            comment = random.choice(channels[channel_id])
            asyncio.create_task(send_comment(session, client, name, channel_id, event.id, channel_name, comment))
        except Exception as e:
            await send_to_bot(session, f"⚠️ {name}: xatolik - {e}")

    await client.run_until_disconnected()


async def main():
    sessions = load_sessions()
    if not sessions:
        print("⚠️ Hech qanday STRING_SESSION topilmadi.")
        return

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(run_client(session, s)) for s in sessions]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
