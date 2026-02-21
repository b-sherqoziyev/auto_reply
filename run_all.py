import asyncio
from admin_bot import admin_bot_main
from main import main as userbot_main

async def start_everything():
    print("🚀 Loyihani to'liq ishga tushirish (Admin Bot + Userbot)...")
    await asyncio.gather(
        admin_bot_main(),
        userbot_main()
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_everything())
    except KeyboardInterrupt:
        print("🛑 To'xtatildi.")
