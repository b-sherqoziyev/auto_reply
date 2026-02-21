import os
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(DATABASE_URL)
            await self.init_db()

    async def init_db(self):
        async with self.pool.acquire() as conn:
            # Accounts table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    session_string TEXT UNIQUE NOT NULL,
                    name TEXT,
                    phone TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Channels table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id SERIAL PRIMARY KEY,
                    channel_id BIGINT UNIQUE NOT NULL,
                    name TEXT,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            # Comments table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id SERIAL PRIMARY KEY,
                    channel_id BIGINT REFERENCES channels(channel_id) ON DELETE CASCADE,
                    text TEXT NOT NULL
                )
            ''')

    # Account operations
    async def add_account(self, session_string, name=None, phone=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO accounts (session_string, name, phone) VALUES ($1, $2, $3) ON CONFLICT (session_string) DO NOTHING",
                session_string, name, phone
            )

    async def get_active_accounts(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT session_string, name FROM accounts WHERE is_active = TRUE")

    async def toggle_account(self, account_id, status: bool):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE accounts SET is_active = $1 WHERE id = $2", status, account_id)

    # Channel operations
    async def add_channel(self, channel_id, name=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO channels (channel_id, name) VALUES ($1, $2) ON CONFLICT (channel_id) DO NOTHING",
                channel_id, name
            )

    async def get_active_channels(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT channel_id, name FROM channels WHERE is_active = TRUE")

    # Comment operations
    async def add_comment(self, channel_id, text):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO comments (channel_id, text) VALUES ($1, $2)", channel_id, text)

    async def get_comments_for_channel(self, channel_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT text FROM comments WHERE channel_id = $1", channel_id)
            return [row['text'] for row in rows]

    async def get_all_config(self):
        """Fetches all channels and their comments for in-memory caching"""
        async with self.pool.acquire() as conn:
            channels = await conn.fetch("SELECT channel_id FROM channels WHERE is_active = TRUE")
            config = {}
            for ch in channels:
                channel_id = ch['channel_id']
                comments = await self.get_comments_for_channel(channel_id)
                if comments:
                    config[channel_id] = comments
            return config

db = Database()
