from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 27620089
API_HASH = "5108a02b13715f247a66127db0f178ea"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n💾 String Session:")
    print(session_string)
    print("\n⚠️ Ushbu ma'lumotni hech kimga bermang!")
