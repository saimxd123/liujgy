
import asyncpg
import os
import json
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, List, Dict
from pathlib import Path

from config import DATABASE_URL, logger
from .migration import run_migration

class Database:
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'pool'):
            self.pool = None
            self.connected = False
    
    async def connect(self):
        """Create connection pool to PostgreSQL"""
        if self.connected and self.pool:
            return
        
        db_url = DATABASE_URL or os.getenv('DATABASE_URL', 'postgresql://localhost/mark_bot')
        
        try:
            self.pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=20,
                command_timeout=60,
                max_inactive_connection_lifetime=300
            )
            self.connected = True
            logger.info(f"Connected to PostgreSQL: {db_url}")
            

            await self.init_tables()
        except Exception as e:
            logger.exception("PostgreSQL connection failed")
            raise
    
    async def init_tables(self):
        """Create all tables if they don't exist"""
        async with self.pool.acquire() as conn:

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    premium_until TIMESTAMP,
                    banned INTEGER DEFAULT 0
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS keys (
                    key TEXT PRIMARY KEY,
                    days INTEGER,
                    redeem_limit INTEGER,
                    redeemed_count INTEGER DEFAULT 0,
                    created_by BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS redeemed_keys (
                    id SERIAL PRIMARY KEY,
                    key TEXT,
                    user_id BIGINT,
                    redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(key, user_id)
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sites (
                    id SERIAL PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    gateway TEXT,
                    price REAL DEFAULT 0,
                    status TEXT DEFAULT 'Working',
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS site_health (
                    site_url TEXT PRIMARY KEY,
                    last_checked TIMESTAMP,
                    failures INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 1.0,
                    total_checks INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'unknown'
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_proxies (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    proxy TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    response_time REAL DEFAULT 0,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_tested TIMESTAMP,
                    UNIQUE(user_id, proxy)
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            

            await conn.execute("""
                INSERT INTO bot_settings (key, value) VALUES 
                    ('locked', 'false'),
                    ('speed', '7'),
                    ('auto_health', 'false'),
                    ('msh_speed', '10')
                ON CONFLICT (key) DO NOTHING
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS check_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    card_number TEXT,
                    bin TEXT,
                    status TEXT,
                    message TEXT,
                    gateway TEXT,
                    time_taken REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_check_history_user_id ON check_history(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_check_history_created_at ON check_history(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_check_history_status ON check_history(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_check_history_gateway ON check_history(gateway)")
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gate_status (
                    gate_name TEXT PRIMARY KEY,
                    enabled INTEGER DEFAULT 1
                )
            """)
            

            await conn.execute("""
                INSERT INTO gate_status (gate_name, enabled) VALUES 
                    ('shopify', 1),
                    ('shopify_mass', 1),
                    ('stripe_auth', 1),
                    ('stripe_auth_mass', 1),
                ON CONFLICT (gate_name) DO NOTHING
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id BIGINT PRIMARY KEY,
                    title TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP
                )
            """)
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    address TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    tx_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    confirmed_at TIMESTAMP
                )
            """)
            
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at)")
            

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS premium_notifications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    notification_type TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, notification_type)
                )
            """)
            

            await run_migration(self.pool)
            
            logger.info("All tables initialized successfully")
    



    def _to_datetime(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError(f"Could not parse timestamp string: {value}")
        return value
    
    async def execute(self, query: str, *args) -> int:
        """Execute a query and return rows affected"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *args)

            if result:
                parts = result.split()
                if len(parts) == 2 and parts[0].upper() in ('UPDATE', 'DELETE', 'INSERT'):
                    return int(parts[1])
            return 0
    
    async def executemany(self, query: str, params: List[tuple]) -> None:
        """Execute many queries in batch"""
        async with self.pool.acquire() as conn:
            await conn.executemany(query, params)
    
    async def fetchone(self, query: str, *args) -> Optional[dict]:
        """Fetch a single row as dict"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def fetchall(self, query: str, *args) -> List[dict]:
        """Fetch all rows as list of dicts"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def fetchval(self, query: str, *args) -> Any:
        """Fetch a single value"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def close(self):
        """Close the connection pool"""
        if self.pool:
            await self.pool.close()
            self.connected = False
            logger.info("Database pool closed")




    async def get_premium_until(self, user_id: int):
        row = await self.fetchone("SELECT premium_until FROM users WHERE user_id=$1", user_id)
        if row and row["premium_until"]:
            return self._to_datetime(row["premium_until"])
        return None

    async def is_premium(self, user_id: int) -> bool:
        expires = await self.get_premium_until(user_id)
        return expires is not None and expires > datetime.now()

    async def extend_premium(self, user_id: int, days: int) -> bool:
        current = await self.get_premium_until(user_id)
        now = datetime.now()
        expires = current if current and current > now else now
        return await self.set_premium(user_id, expires + timedelta(days=days))

    async def get_premium_expiry(self, user_id: int):
        row = await self.fetchone("SELECT premium_until FROM users WHERE user_id=$1", user_id)
        if row and row["premium_until"]:
            return self._to_datetime(row["premium_until"])
        return None




db = Database()