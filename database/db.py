
import asyncio
import asyncpg
import random
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, List, Dict
import os
import threading

from config import DATABASE_URL, USE_POSTGRES
from logger import get_logger
from .migration import run_migration

logger = get_logger(__name__)




def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            pass
        raise ValueError(f"Could not parse timestamp string: {value}")
    return value




def to_datetime(value):
    """Convert a value (datetime or string) to datetime, or return None."""
    return _to_datetime(value)





_pool = None
_db_loop = None
_db_loop_thread = None
_db_loop_ready = threading.Event()
_db_loop_lock = threading.Lock()

def _db_loop_worker():
    global _db_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _db_loop = loop
    _db_loop_ready.set()
    loop.run_forever()

def _get_db_loop():
    global _db_loop_thread
    if _db_loop is None:
        with _db_loop_lock:
            if _db_loop is None:
                _db_loop_ready.clear()
                _db_loop_thread = threading.Thread(
                    target=_db_loop_worker,
                    name="postgres-db-loop",
                    daemon=True,
                )
                _db_loop_thread.start()
        _db_loop_ready.wait()
    return _db_loop

def _run_sync(coro):
    if threading.current_thread() is _db_loop_thread:
        raise RuntimeError("Synchronous DB wrapper called from the DB event-loop thread")
    future = asyncio.run_coroutine_threadsafe(coro, _get_db_loop())
    return future.result()

async def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set. Cannot use PostgreSQL.")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=20,
            command_timeout=60,
            max_inactive_connection_lifetime=600,
        )
        await _init_tables(_pool)
        logger.info("PostgreSQL pool created")
    return _pool

async def _init_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                premium_until TIMESTAMP,
                banned INTEGER DEFAULT 0,
                credits BIGINT DEFAULT 0
            )
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits BIGINT DEFAULT 0")
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
                last_tested TIMESTAMP
            )
        """)
        await _ensure_user_proxies_unique(conn)

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
                ('shopify', 1), ('shopify_mass', 1),
                ('stripe_auth', 1), ('stripe_auth_mass', 1),
                ('stripe_charge', 1), ('stripe_charge_mass', 1),
                ('stripe_auth2', 1),  ('stripe_auth2_mass', 1)
            ON CONFLICT (gate_name) DO NOTHING
        """)
        # Owner-configurable links and channels
        await conn.execute("""
            INSERT INTO bot_settings (key, value) VALUES
                ('pvt_gc_link', ''),
                ('public_gc_link', ''),
                ('log_gc_link', ''),
                ('public_channel_link', ''),
                ('extra_api_urls', '')
            ON CONFLICT (key) DO NOTHING
        """)
        # Required-join channels (stored as JSON array of {chat_id, username, title})
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                username TEXT,
                title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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
        await run_migration(pool)
        logger.info("PostgreSQL tables initialized")

async def _ensure_user_proxies_unique(conn):
    """Add the unique constraint on (user_id, proxy) if it doesn't exist."""
    exists = await conn.fetchval("""
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_proxies'
          AND constraint_type = 'UNIQUE'
          AND constraint_name = 'user_proxies_user_id_proxy_key'
    """)
    if exists:
        return
    await conn.execute("""
        DELETE FROM user_proxies a
        USING user_proxies b
        WHERE a.id > b.id
          AND a.user_id = b.user_id
          AND a.proxy = b.proxy
    """)
    await conn.execute("""
        ALTER TABLE user_proxies
        ADD CONSTRAINT user_proxies_user_id_proxy_key
        UNIQUE (user_id, proxy)
    """)
    logger.info("Added unique constraint on user_proxies(user_id, proxy)")

def sync_wrapper(async_func):
    def wrapper(*args, **kwargs):
        return _run_sync(async_func(*args, **kwargs))
    return wrapper




async def _add_user(user_id: int, first_name: str, username: str = None) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO NOTHING",
            user_id, first_name, username
        )
        return result.startswith("INSERT") or "ON CONFLICT DO NOTHING" in result
add_user = sync_wrapper(_add_user)

async def _user_exists(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM users WHERE user_id=$1", user_id)
        return row is not None
user_exists = sync_wrapper(_user_exists)

async def _get_user(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
get_user = sync_wrapper(_get_user)

async def _get_all_users():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users ORDER BY joined_at DESC")
get_all_users = sync_wrapper(_get_all_users)

async def _get_total_users() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM users")
        return val or 0
get_total_users = sync_wrapper(_get_total_users)

async def _ban_user(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET banned=1 WHERE user_id=$1", user_id)
        return result == "UPDATE 1"
ban_user = sync_wrapper(_ban_user)

async def _unban_user(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET banned=0 WHERE user_id=$1", user_id)
        return result == "UPDATE 1"
unban_user = sync_wrapper(_unban_user)

async def _is_banned(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT banned FROM users WHERE user_id=$1", user_id)
        return bool(row["banned"]) if row else False
is_banned = sync_wrapper(_is_banned)

async def _get_banned_users():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users WHERE banned=1 ORDER BY joined_at DESC")
get_banned_users = sync_wrapper(_get_banned_users)

async def _get_free_users():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users WHERE premium_until IS NULL OR premium_until <= NOW() ORDER BY joined_at DESC")
get_free_users = sync_wrapper(_get_free_users)




async def _add_admin(user_id: int, added_by: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO admins (user_id, added_by) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
            user_id, added_by
        )
        return result.startswith("INSERT") or "ON CONFLICT" in result
add_admin = sync_wrapper(_add_admin)

async def _remove_admin(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM admins WHERE user_id=$1", user_id)
        return result == "DELETE 1"
remove_admin = sync_wrapper(_remove_admin)

async def _is_admin(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM admins WHERE user_id=$1", user_id)
        return row is not None
is_admin = sync_wrapper(_is_admin)

async def _get_all_admins():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM admins ORDER BY added_at DESC")
get_all_admins = sync_wrapper(_get_all_admins)

async def _get_total_admins() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM admins")
        return val or 0
get_total_admins = sync_wrapper(_get_total_admins)




async def _get_premium_until(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT premium_until FROM users WHERE user_id=$1", user_id)
        if row and row["premium_until"]:
            return _to_datetime(row["premium_until"])
        return None
get_premium_until = sync_wrapper(_get_premium_until)

async def _is_premium(user_id: int) -> bool:
    expires = await _get_premium_until(user_id)
    return expires is not None and expires > datetime.now()
is_premium = sync_wrapper(_is_premium)

async def _set_premium(user_id: int, expires: datetime) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET premium_until=$1 WHERE user_id=$2", expires, user_id)
        return result == "UPDATE 1"
set_premium = sync_wrapper(_set_premium)

async def _extend_premium(user_id: int, days: int) -> bool:
    current = await _get_premium_until(user_id)
    now = datetime.now()
    expires = current if current and current > now else now
    return await _set_premium(user_id, expires + timedelta(days=days))
extend_premium = sync_wrapper(_extend_premium)

async def _remove_premium(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET premium_until=NULL WHERE user_id=$1", user_id)
        return result == "UPDATE 1"
remove_premium = sync_wrapper(_remove_premium)

async def _get_total_premium() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until > NOW()")
        return val or 0
get_total_premium = sync_wrapper(_get_total_premium)

async def _get_premium_users():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users WHERE premium_until IS NOT NULL AND premium_until > NOW() ORDER BY premium_until ASC")
get_premium_users = sync_wrapper(_get_premium_users)




async def _create_key(key: str, days: int, redeem_limit: int, created_by: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO keys (key, days, redeem_limit, redeemed_count, created_by) VALUES ($1, $2, $3, 0, $4)",
            key, days, redeem_limit, created_by
        )
        return result.startswith("INSERT")
create_key = sync_wrapper(_create_key)

async def _get_key(key: str):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM keys WHERE key=$1", key)
get_key = sync_wrapper(_get_key)

async def _key_exists(key: str) -> bool:
    return await _get_key(key) is not None
key_exists = sync_wrapper(_key_exists)

async def _delete_key(key: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM keys WHERE key=$1", key)
        return result == "DELETE 1"
delete_key = sync_wrapper(_delete_key)

async def _get_all_keys():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM keys ORDER BY created_at DESC")
get_all_keys = sync_wrapper(_get_all_keys)

async def _get_total_keys() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM keys")
        return val or 0
get_total_keys = sync_wrapper(_get_total_keys)

async def _get_unused_keys() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM keys WHERE COALESCE(redeemed_count, 0) = 0")
        return val or 0
get_unused_keys = sync_wrapper(_get_unused_keys)

async def _increase_redeem(key: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE keys SET redeemed_count = COALESCE(redeemed_count, 0) + 1 WHERE key=$1", key)
        return result == "UPDATE 1"
increase_redeem = sync_wrapper(_increase_redeem)

async def _add_redeem(key: str, user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS redeemed_keys_key_user_unique
                ON redeemed_keys (key, user_id)
            """)
        except Exception:
            try:
                await conn.execute("""
                    DELETE FROM redeemed_keys a
                    USING redeemed_keys b
                    WHERE a.key = b.key AND a.user_id = b.user_id AND a.id > b.id
                """)
                await conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS redeemed_keys_key_user_unique
                    ON redeemed_keys (key, user_id)
                """)
            except Exception:
                pass
        result = await conn.execute(
            "INSERT INTO redeemed_keys (key, user_id) VALUES ($1, $2) ON CONFLICT (key, user_id) DO NOTHING",
            key, user_id
        )
        return result.startswith("INSERT") or "ON CONFLICT" in result
add_redeem = sync_wrapper(_add_redeem)

async def _already_redeemed(key: str, user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM redeemed_keys WHERE key=$1 AND user_id=$2", key, user_id)
        return row is not None
already_redeemed = sync_wrapper(_already_redeemed)

async def _can_redeem(key: str) -> bool:
    row = await _get_key(key)
    if not row:
        return False
    redeemed_count = row["redeemed_count"] if row["redeemed_count"] is not None else 0
    redeem_limit = row["redeem_limit"]
    return redeem_limit is not None and redeemed_count < redeem_limit
can_redeem = sync_wrapper(_can_redeem)

async def _get_total_redeems() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM redeemed_keys")
        return val or 0
get_total_redeems = sync_wrapper(_get_total_redeems)

async def _set_key_expiry(key: str, expires_at: datetime) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE keys SET expires_at=$1 WHERE key=$2", expires_at, key)
        return result == "UPDATE 1"
set_key_expiry = sync_wrapper(_set_key_expiry)

async def _delete_expired_keys() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        expired = await conn.fetch("SELECT key FROM keys WHERE expires_at IS NOT NULL AND expires_at < $1", datetime.now())
        count = 0
        for row in expired:
            key = row["key"]
            await conn.execute("DELETE FROM keys WHERE key=$1", key)
            await conn.execute("DELETE FROM redeemed_keys WHERE key=$1", key)
            count += 1
        if count:
            logger.info(f"Deleted {count} expired keys")
        return count
delete_expired_keys = sync_wrapper(_delete_expired_keys)




async def _add_site(url: str, gateway: str = "", price: float = 0, status: str = "Working", added_by: int = 0):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """INSERT INTO sites (url, gateway, price, status, added_by, added_at, last_checked) 
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (url) DO NOTHING""",
            url, gateway, price, status, added_by, datetime.now(), datetime.now()
        )
        return result.startswith("INSERT") or "ON CONFLICT" in result
add_site = sync_wrapper(_add_site)

async def _site_exists(url: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM sites WHERE url=$1", url)
        return row is not None
site_exists = sync_wrapper(_site_exists)

async def _get_site(url: str):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM sites WHERE url=$1", url)
get_site = sync_wrapper(_get_site)

async def _get_all_sites():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM sites ORDER BY id DESC")
get_all_sites = sync_wrapper(_get_all_sites)

async def _get_all_working_sites():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM sites WHERE status='Working' ORDER BY id DESC")
get_all_working_sites = sync_wrapper(_get_all_working_sites)

async def _get_total_sites() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM sites")
        return val or 0
get_total_sites = sync_wrapper(_get_total_sites)

async def _update_site(url: str, gateway: str, price: float, status: str):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sites SET gateway=$1, price=$2, status=$3, last_checked=$4 WHERE url=$5",
            gateway, price, status, datetime.now(), url
        )
update_site = sync_wrapper(_update_site)

async def _delete_site(url: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM sites WHERE url=$1", url)
        return result == "DELETE 1"
delete_site = sync_wrapper(_delete_site)

async def _delete_all_sites():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sites")
delete_all_sites = sync_wrapper(_delete_all_sites)

async def _get_random_site():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT url FROM sites WHERE status='Working' ORDER BY RANDOM() LIMIT 1")
        return row["url"] if row else None
get_random_site = sync_wrapper(_get_random_site)




async def _add_user_proxy(user_id: int, proxy: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO user_proxies (user_id, proxy) VALUES ($1, $2) ON CONFLICT (user_id, proxy) DO NOTHING",
            user_id, proxy
        )
        return result.startswith("INSERT") or "ON CONFLICT" in result
add_user_proxy = sync_wrapper(_add_user_proxy)

async def _get_user_proxies(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM user_proxies WHERE user_id=$1 ORDER BY id DESC", user_id)
get_user_proxies = sync_wrapper(_get_user_proxies)

async def _get_user_active_proxies(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM user_proxies WHERE user_id=$1 AND status='active' ORDER BY id DESC", user_id)
get_user_active_proxies = sync_wrapper(_get_user_active_proxies)

async def _get_random_user_proxy(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT proxy FROM user_proxies WHERE user_id=$1 AND status='active' ORDER BY RANDOM() LIMIT 1", user_id)
        return row["proxy"] if row else None
get_random_user_proxy = sync_wrapper(_get_random_user_proxy)

async def _delete_user_proxy(proxy_id: int, user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM user_proxies WHERE id=$1 AND user_id=$2", proxy_id, user_id)
        return result == "DELETE 1"
delete_user_proxy = sync_wrapper(_delete_user_proxy)

async def _delete_all_user_proxies(user_id: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM user_proxies WHERE user_id=$1", user_id)
        return result.startswith("DELETE")
delete_all_user_proxies = sync_wrapper(_delete_all_user_proxies)

async def _update_user_proxy_status(proxy_id: int, status: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE user_proxies SET status=$1, last_tested=$2 WHERE id=$3",
            status, datetime.now(), proxy_id
        )
        return result == "UPDATE 1"
update_user_proxy_status = sync_wrapper(_update_user_proxy_status)

async def _update_user_proxy_response_time(proxy_id: int, response_time: float) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE user_proxies SET response_time=$1 WHERE id=$2",
            response_time, proxy_id
        )
        return result == "UPDATE 1"
update_user_proxy_response_time = sync_wrapper(_update_user_proxy_response_time)

async def _get_total_user_proxies(user_id: int) -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM user_proxies WHERE user_id=$1", user_id)
        return val or 0
get_total_user_proxies = sync_wrapper(_get_total_user_proxies)

async def _get_total_user_active_proxies(user_id: int) -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM user_proxies WHERE user_id=$1 AND status='active'", user_id)
        return val or 0
get_total_user_active_proxies = sync_wrapper(_get_total_user_active_proxies)




async def _bulk_add_user_proxies(user_id: int, proxies: list) -> int:
    if not proxies:
        return 0
    pool = await _get_pool()
    async with pool.acquire() as conn:
        inserted = 0
        batch_size = 1000
        for i in range(0, len(proxies), batch_size):
            batch = proxies[i:i+batch_size]
            placeholders = []
            params = []
            for idx, proxy in enumerate(batch):
                placeholders.append(f"(${idx*2+1}, ${idx*2+2})")
                params.extend([user_id, proxy])
            query = f"""
                INSERT INTO user_proxies (user_id, proxy)
                VALUES {', '.join(placeholders)}
                ON CONFLICT (user_id, proxy) DO NOTHING
            """
            result = await conn.execute(query, *params)
            parts = result.split()
            if len(parts) == 3:
                inserted += int(parts[2])
        return inserted
def bulk_add_user_proxies(user_id: int, proxies: list) -> int:
    return _run_sync(_bulk_add_user_proxies(user_id, proxies))




async def _bulk_update_user_proxy_results(updates: list) -> int:
    if not updates:
        return 0
    pool = await _get_pool()
    async with pool.acquire() as conn:
        updated = 0
        batch_size = 1000
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i+batch_size]
            placeholders = []
            params = []
            for idx, (proxy_id, status, response_time) in enumerate(batch):
                placeholders.append(f"(${idx*3+1}, ${idx*3+2}, ${idx*3+3})")
                params.extend([proxy_id, status, response_time])
            query = f"""
                UPDATE user_proxies
                SET status = data.status,
                    response_time = data.response_time,
                    last_tested = NOW()
                FROM (VALUES {', '.join(placeholders)}) AS data(id, status, response_time)
                WHERE user_proxies.id = data.id
            """
            result = await conn.execute(query, *params)
            parts = result.split()
            if len(parts) == 2:
                updated += int(parts[1])
        return updated
def bulk_update_user_proxy_results(updates: list) -> int:
    return _run_sync(_bulk_update_user_proxy_results(updates))




async def _bulk_delete_user_proxies(user_id: int, proxy_ids: list) -> int:
    if not proxy_ids:
        return 0
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if user_id is not None:
            result = await conn.execute(
                "DELETE FROM user_proxies WHERE id = ANY($1::int[]) AND user_id = $2",
                proxy_ids, user_id
            )
        else:
            result = await conn.execute(
                "DELETE FROM user_proxies WHERE id = ANY($1::int[])",
                proxy_ids
            )
        parts = result.split()
        return int(parts[1]) if len(parts) == 2 else 0
def bulk_delete_user_proxies(user_id: int, proxy_ids: list) -> int:
    return _run_sync(_bulk_delete_user_proxies(user_id, proxy_ids))




bulk_mark_user_proxy_results = bulk_update_user_proxy_results




async def _is_gate_enabled(gate_name: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT enabled FROM gate_status WHERE gate_name=$1", gate_name)
        return bool(row["enabled"]) if row else True
is_gate_enabled = sync_wrapper(_is_gate_enabled)

async def _set_gate_enabled(gate_name: str, enabled: bool) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE gate_status SET enabled=$1 WHERE gate_name=$2",
            1 if enabled else 0, gate_name
        )
        return result == "UPDATE 1"
set_gate_enabled = sync_wrapper(_set_gate_enabled)

async def _get_all_gate_status():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM gate_status ORDER BY gate_name")
get_all_gate_status = sync_wrapper(_get_all_gate_status)




async def _is_bot_locked() -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='locked'")
        return row and row["value"] == "true"
is_bot_locked = sync_wrapper(_is_bot_locked)

async def _set_bot_lock(locked: bool) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE bot_settings SET value=$1 WHERE key='locked'", "true" if locked else "false")
        return result == "UPDATE 1"
set_bot_lock = sync_wrapper(_set_bot_lock)

async def _get_speed() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='speed'")
        if not row:
            return 7
        try:
            return int(row["value"])
        except ValueError:
            return 7
get_speed = sync_wrapper(_get_speed)

async def _set_speed(threads: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE bot_settings SET value=$1 WHERE key='speed'", str(threads))
        return result == "UPDATE 1"
set_speed = sync_wrapper(_set_speed)

async def _get_msh_speed() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='msh_speed'")
        if not row:
            return 10
        try:
            return int(row["value"])
        except ValueError:
            return 10
get_msh_speed = sync_wrapper(_get_msh_speed)

async def _set_msh_speed(speed: int) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE bot_settings SET value=$1 WHERE key='msh_speed'", str(speed))
        return result == "UPDATE 1"
set_msh_speed = sync_wrapper(_set_msh_speed)

async def _is_auto_health_enabled() -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='auto_health'")
        return row and row["value"] == "true"
is_auto_health_enabled = sync_wrapper(_is_auto_health_enabled)

async def _set_auto_health(enabled: bool) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE bot_settings SET value=$1 WHERE key='auto_health'", "true" if enabled else "false")
        return result == "UPDATE 1"
set_auto_health = sync_wrapper(_set_auto_health)




async def _log_check(user_id: int, card: str, status: str, message: str, gateway: str, time_taken: float):
    card_number = card.split('|')[0] if '|' in card else card
    bin_num = card_number[:6] if card_number else ""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO check_history 
               (user_id, card_number, bin, status, message, gateway, time_taken) 
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            user_id, card_number, bin_num, status, message, gateway, time_taken
        )
log_check = sync_wrapper(_log_check)

async def _get_user_activity_24h(user_id: int) -> dict:
    cutoff = datetime.now() - timedelta(hours=24)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, COUNT(*) as count FROM check_history WHERE user_id = $1 AND created_at > $2 GROUP BY status",
            user_id, cutoff
        )
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    for row in rows:
        status = row["status"].lower() if row["status"] else ""
        count = row["count"]
        result["total"] += count
        if status in ("charged", "charge", "order_paid", "paid"):
            result["charged"] += count
        elif status in ("approved", "approve", "live", "ccn", "authenticate_successful"):
            result["approved"] += count
        elif status in ("declined", "dead", "decline", "rejected", "failed"):
            result["declined"] += count
        else:
            result["errors"] += count
    return result
get_user_activity_24h = sync_wrapper(_get_user_activity_24h)

async def _get_user_all_time_stats(user_id: int) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, COUNT(*) as count FROM check_history WHERE user_id = $1 GROUP BY status",
            user_id
        )
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    for row in rows:
        status = row["status"].lower() if row["status"] else ""
        count = row["count"]
        result["total"] += count
        if status in ("charged", "charge", "order_paid", "paid"):
            result["charged"] += count
        elif status in ("approved", "approve", "live", "ccn", "authenticate_successful"):
            result["approved"] += count
        elif status in ("declined", "dead", "decline", "rejected", "failed"):
            result["declined"] += count
        else:
            result["errors"] += count
    return result
get_user_all_time_stats = sync_wrapper(_get_user_all_time_stats)




async def _mark_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO premium_notifications (user_id, notification_type) VALUES ($1, $2) ON CONFLICT (user_id, notification_type) DO NOTHING",
            user_id, notification_type
        )
        return result.startswith("INSERT") or "ON CONFLICT" in result
mark_premium_notification_sent = sync_wrapper(_mark_premium_notification_sent)

async def _is_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM premium_notifications WHERE user_id=$1 AND notification_type=$2",
            user_id, notification_type
        )
        return row is not None
is_premium_notification_sent = sync_wrapper(_is_premium_notification_sent)

async def _get_user_premium_notifications(user_id: int) -> List[str]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT notification_type FROM premium_notifications WHERE user_id=$1",
            user_id
        )
        return [row["notification_type"] for row in rows]
get_user_premium_notifications = sync_wrapper(_get_user_premium_notifications)

async def _clear_old_premium_notifications(days: int = 30):
    cutoff = datetime.now() - timedelta(days=days)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM premium_notifications WHERE sent_at < $1", cutoff)
clear_old_premium_notifications = sync_wrapper(_clear_old_premium_notifications)

async def _get_users_premium_expiring_in_range(hours_min: int, hours_max: int) -> List[dict]:
    now = datetime.now()
    expiry_min = now + timedelta(hours=hours_min)
    expiry_max = now + timedelta(hours=hours_max)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, first_name, username, premium_until FROM users 
               WHERE premium_until IS NOT NULL AND premium_until >= $1 AND premium_until < $2""",
            expiry_min, expiry_max
        )
        return [dict(row) for row in rows]
get_users_premium_expiring_in_range = sync_wrapper(_get_users_premium_expiring_in_range)

async def _get_users_premium_expired_today() -> List[dict]:
    now = datetime.now()
    expiry_start = now - timedelta(hours=24)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, first_name, username, premium_until FROM users 
               WHERE premium_until IS NOT NULL AND premium_until >= $1 AND premium_until < $2""",
            expiry_start, now
        )
        return [dict(row) for row in rows]
get_users_premium_expired_today = sync_wrapper(_get_users_premium_expired_today)

async def _get_users_premium_active() -> List[dict]:
    now = datetime.now()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, first_name, username, premium_until FROM users WHERE premium_until IS NOT NULL AND premium_until > $1",
            now
        )
        return [dict(row) for row in rows]
get_users_premium_active = sync_wrapper(_get_users_premium_active)

async def _get_premium_expiry(user_id: int):
    row = await _get_user(user_id)
    if row and row["premium_until"]:
        return _to_datetime(row["premium_until"])
    return None
get_premium_expiry = sync_wrapper(_get_premium_expiry)

async def _get_user_current_tier(user_id: int) -> str:
    return "Premium" if await _is_premium(user_id) else "Trial"
get_user_current_tier = sync_wrapper(_get_user_current_tier)




async def _get_all_groups():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM groups ORDER BY added_at DESC")
get_all_groups = sync_wrapper(_get_all_groups)

async def _get_total_groups() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM groups")
        return val or 0
get_total_groups = sync_wrapper(_get_total_groups)




async def _get_total_banned() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM users WHERE banned=1")
        return val or 0
get_total_banned = sync_wrapper(_get_total_banned)

async def _get_total_proxies() -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT COUNT(*) FROM user_proxies")
        return val or 0
get_total_proxies = sync_wrapper(_get_total_proxies)




def update_user_identity(user_id: int, first_name: str, username: str = None) -> bool:
    async def _update():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET first_name=$1, username=$2 WHERE user_id=$3",
                first_name or "User", username, user_id
            )
            return result == "UPDATE 1"
    return _run_sync(_update())

def get_or_create_user(user_id: int, username: str = None):
    user = get_user(user_id)
    if user:
        tier = "Premium" if is_premium(user_id) else "Free"
        return user["username"], user["joined_at"], tier, get_user_credits(user_id)
    add_user(user_id, "User", username)
    return username, datetime.now(), "Free", get_user_credits(user_id)

def update_user_credits(user_id: int, amount: int) -> bool:
    async def _update():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET credits=COALESCE(credits, 0)+$1 WHERE user_id=$2",
                amount, user_id
            )
            return result == "UPDATE 1"
    return _run_sync(_update())

def get_user_credits(user_id: int) -> int | float:
    user = get_user(user_id)
    if not user:
        return 0
    return int(user.get("credits") or 0) if hasattr(user, "get") else int(user["credits"] or 0)

def clear_all_user_proxies() -> int:
    async def _clear():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM user_proxies")
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 else 0
    return _run_sync(_clear())

def clear_all_sites() -> int:
    async def _clear():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM sites")
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 else 0
    return _run_sync(_clear())

def clear_all_premium() -> int:
    async def _clear():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("UPDATE users SET premium_until=NULL WHERE premium_until IS NOT NULL")
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 else 0
    return _run_sync(_clear())

def clear_all_admins() -> int:
    async def _clear():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM admins")
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 else 0
    return _run_sync(_clear())

def get_all_global_proxies():
    return get_all_proxies_with_owners()

def get_total_active_proxies() -> int:
    async def _count():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT COUNT(*) FROM user_proxies WHERE status='active'")
            return val or 0
    return _run_sync(_count())

def get_total_dead_proxies() -> int:
    async def _count():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT COUNT(*) FROM user_proxies WHERE status='dead'")
            return val or 0
    return _run_sync(_count())

def clear_all_proxies() -> int:
    async def _clear():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM user_proxies")
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 else 0
    return _run_sync(_clear())

def get_proxy_by_id(proxy_id: int):
    async def _get():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM user_proxies WHERE id=$1", proxy_id)
    return _run_sync(_get())

def delete_proxy_by_id(proxy_id: int) -> bool:
    async def _del():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM user_proxies WHERE id=$1", proxy_id)
            return result == "DELETE 1"
    return _run_sync(_del())

def get_proxies_by_user(user_id: int):
    return get_user_proxies(user_id)

def get_proxies_by_status(status: str):
    async def _get():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM user_proxies WHERE status=$1 ORDER BY user_id, id DESC", status)
    return _run_sync(_get())

def update_proxy_status(proxy_id: int, status: str) -> bool:
    async def _upd():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_proxies SET status=$1, last_tested=$2 WHERE id=$3",
                status, datetime.now(), proxy_id
            )
            return result == "UPDATE 1"
    return _run_sync(_upd())

def get_all_proxies_with_owners():
    async def _get():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch("""
                SELECT up.*, u.user_id as owner_id, u.first_name, u.username
                FROM user_proxies up
                LEFT JOIN users u ON up.user_id = u.user_id
                ORDER BY up.user_id, up.id DESC
            """)
    return _run_sync(_get())







# ─── Owner-configurable links / settings ───────────────────────────────────

def get_bot_setting(key: str) -> str:
    async def _get():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key=$1", key)
            return row["value"] if row else ""
    return _run_sync(_get())

def set_bot_setting(key: str, value: str) -> bool:
    async def _set():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=$2",
                key, value
            )
            return True
    return _run_sync(_set())

# ─── Required channels ──────────────────────────────────────────────────────

def get_required_channels() -> list:
    async def _get():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM required_channels ORDER BY id")
            return [dict(r) for r in rows]
    return _run_sync(_get())

def add_required_channel(chat_id: int, username: str, title: str) -> bool:
    async def _add():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO required_channels (chat_id, username, title) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                chat_id, username, title
            )
            return True
    return _run_sync(_add())

def remove_required_channel(chat_id: int) -> bool:
    async def _rm():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM required_channels WHERE chat_id=$1", chat_id)
            return "DELETE 1" in result
    return _run_sync(_rm())

# ─── Extra API URLs ──────────────────────────────────────────────────────────

def get_extra_api_urls() -> list:
    raw = get_bot_setting("extra_api_urls")
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]

def add_extra_api_url(url: str) -> bool:
    existing = get_extra_api_urls()
    if url in existing:
        return False
    existing.append(url)
    set_bot_setting("extra_api_urls", ",".join(existing))
    return True

def remove_extra_api_url(url: str) -> bool:
    existing = get_extra_api_urls()
    if url not in existing:
        return False
    existing.remove(url)
    set_bot_setting("extra_api_urls", ",".join(existing))
    return True

def get_all_api_urls_db() -> list:
    """Primary URL + owner-added extras."""
    from config import API_BASE_URL
    urls = [API_BASE_URL]
    for u in get_extra_api_urls():
        if u not in urls:
            urls.append(u)
    return urls

# ─── Gate helpers for toggle panel ──────────────────────────────────────────

def get_gate_status_all() -> dict:
    """Return {gate_name: bool} dict for all gates."""
    rows = get_all_gate_status()
    return {r["gate_name"]: bool(r["enabled"]) for r in rows}

def toggle_gate_status(gate_name: str) -> bool:
    """Toggle a gate's enabled state. Returns new state."""
    current = is_gate_enabled(gate_name)
    new_state = not current
    set_gate_enabled(gate_name, new_state)
    return new_state
