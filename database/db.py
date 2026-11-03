import asyncio
import random
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any

import aiosqlite

from config import DATABASE_URL
from logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════
def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        raise ValueError(f"Could not parse timestamp string: {value}")
    return value


def to_datetime(value):
    return _to_datetime(value)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dt_str(value) -> str:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


# ═══════════════════════════════════════════════════════════
# DB loop thread (same pattern as before)
# ═══════════════════════════════════════════════════════════
_pool: aiosqlite.Connection | None = None
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
                    name="sqlite-db-loop",
                    daemon=True,
                )
                _db_loop_thread.start()
        _db_loop_ready.wait()
    return _db_loop


def _run_sync(coro):
    if threading.current_thread() is _db_loop_thread:
        raise RuntimeError("Sync DB wrapper called from DB loop thread")
    future = asyncio.run_coroutine_threadsafe(coro, _get_db_loop())
    return future.result()


def sync_wrapper(async_func):
    def wrapper(*args, **kwargs):
        return _run_sync(async_func(*args, **kwargs))
    return wrapper


# ═══════════════════════════════════════════════════════════
# Connection + tables
# ═══════════════════════════════════════════════════════════
def _resolve_sqlite_path() -> str:
    url = (DATABASE_URL or "").strip()
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "", 1)
    if url.startswith(("postgres://", "postgresql://")):
        logger.warning(
            "Postgres URL detected but only SQLite is enabled in this build. "
            "Falling back to ./bot.db"
        )
        return "bot.db"
    if url:
        return "bot.db"
    return "bot.db"


async def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    path = _resolve_sqlite_path()
    _pool = await aiosqlite.connect(path)
    _pool.row_factory = aiosqlite.Row
    await _init_tables()
    logger.info(f"SQLite ready: {path}")
    return _pool


async def _init_tables():
    conn = _pool
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            premium_until TEXT,
            banned INTEGER DEFAULT 0,
            credits INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            days INTEGER,
            redeem_limit INTEGER,
            redeemed_count INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS redeemed_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            user_id INTEGER,
            redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(key, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            gateway TEXT,
            price REAL DEFAULT 0,
            status TEXT DEFAULT 'Working',
            added_by INTEGER,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_checked TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS site_health (
            site_url TEXT PRIMARY KEY,
            last_checked TEXT,
            failures INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 1.0,
            total_checks INTEGER DEFAULT 0,
            status TEXT DEFAULT 'unknown'
        )""",
        """CREATE TABLE IF NOT EXISTS user_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            proxy TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            response_time REAL DEFAULT 0,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_tested TEXT,
            UNIQUE(user_id, proxy)
        )""",
        """CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_number TEXT,
            bin TEXT,
            status TEXT,
            message TEXT,
            gateway TEXT,
            time_taken REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS gate_status (
            gate_name TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            username TEXT,
            title TEXT,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_active TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            address TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            tx_hash TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            confirmed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS premium_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, notification_type)
        )""",
    ]
    for sql in stmts:
        await conn.execute(sql)

    # ensure credits column for old DBs
    try:
        await conn.execute("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 0")
    except Exception:
        pass

    # indexes
    for idx in (
        "CREATE INDEX IF NOT EXISTS idx_check_history_user_id ON check_history(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_check_history_created_at ON check_history(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_check_history_status ON check_history(status)",
        "CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
    ):
        await conn.execute(idx)

    # seed defaults
    defaults = {
        "locked": "false",
        "speed": "7",
        "auto_health": "false",
        "msh_speed": "10",
        "pvt_gc_link": "",
        "public_gc_link": "",
        "log_gc_link": "",
        "public_channel_link": "",
        "extra_api_urls": "",
    }
    for k, v in defaults.items():
        await conn.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
            (k, v),
        )

    for g in (
        "shopify", "shopify_mass",
        "stripe_auth", "stripe_auth_mass",
        "stripe_charge", "stripe_charge_mass",
        "stripe_auth2", "stripe_auth2_mass",
    ):
        await conn.execute(
            "INSERT OR IGNORE INTO gate_status (gate_name, enabled) VALUES (?, 1)",
            (g,),
        )

    await conn.commit()


# cached flag so every update doesn't hit the DB
_locked_cache = {"value": False}


async def _load_locked_cache():
    conn = await _get_pool()
    async with conn.execute("SELECT value FROM bot_settings WHERE key='locked'") as cur:
        row = await cur.fetchone()
    _locked_cache["value"] = bool(row and row["value"] == "true")


async def _init_db_impl():
    await _get_pool()
    await _load_locked_cache()


async def init_db():
    """Call once at startup."""
    _run_sync(_init_db_impl())
    logger.info("Database initialized")


# ═══════════════════════════════════════════════════════════
# Low-level helpers
# ═══════════════════════════════════════════════════════════
async def _fetchone(sql: str, params: tuple = ()):
    conn = await _get_pool()
    async with conn.execute(sql, params) as cur:
        return await cur.fetchone()


async def _fetchall(sql: str, params: tuple = ()):
    conn = await _get_pool()
    async with conn.execute(sql, params) as cur:
        return await cur.fetchall()


async def _execute(sql: str, params: tuple = ()):
    conn = await _get_pool()
    cur = await conn.execute(sql, params)
    await conn.commit()
    return cur


# ═══════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════
async def _add_user(user_id: int, first_name: str, username: str = None) -> bool:
    cur = await _execute(
        "INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
        (user_id, first_name, username),
    )
    return cur.rowcount > 0
add_user = sync_wrapper(_add_user)


async def _user_exists(user_id: int) -> bool:
    row = await _fetchone("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    return row is not None
user_exists = sync_wrapper(_user_exists)


async def _get_user(user_id: int):
    return await _fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
get_user = sync_wrapper(_get_user)


async def _get_all_users():
    return await _fetchall("SELECT * FROM users ORDER BY joined_at DESC")
get_all_users = sync_wrapper(_get_all_users)


async def _get_total_users() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM users")
    return int(row["c"]) if row else 0
get_total_users = sync_wrapper(_get_total_users)


async def _ban_user(user_id: int) -> bool:
    cur = await _execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
    return cur.rowcount > 0
ban_user = sync_wrapper(_ban_user)


async def _unban_user(user_id: int) -> bool:
    cur = await _execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
    return cur.rowcount > 0
unban_user = sync_wrapper(_unban_user)


async def _is_banned(user_id: int) -> bool:
    row = await _fetchone("SELECT banned FROM users WHERE user_id=?", (user_id,))
    return bool(row["banned"]) if row else False
is_banned = sync_wrapper(_is_banned)


async def _get_banned_users():
    return await _fetchall("SELECT * FROM users WHERE banned=1 ORDER BY joined_at DESC")
get_banned_users = sync_wrapper(_get_banned_users)


async def _get_free_users():
    return await _fetchall(
        "SELECT * FROM users WHERE premium_until IS NULL "
        "OR premium_until <= datetime('now','localtime') "
        "ORDER BY joined_at DESC"
    )
get_free_users = sync_wrapper(_get_free_users)


# ═══════════════════════════════════════════════════════════
# Admins
# ═══════════════════════════════════════════════════════════
async def _add_admin(user_id: int, added_by: int) -> bool:
    cur = await _execute(
        "INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)",
        (user_id, added_by),
    )
    return cur.rowcount > 0
add_admin = sync_wrapper(_add_admin)


async def _remove_admin(user_id: int) -> bool:
    cur = await _execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    return cur.rowcount > 0
remove_admin = sync_wrapper(_remove_admin)


async def _is_admin(user_id: int) -> bool:
    row = await _fetchone("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    return row is not None
is_admin = sync_wrapper(_is_admin)


async def _get_all_admins():
    return await _fetchall("SELECT * FROM admins ORDER BY added_at DESC")
get_all_admins = sync_wrapper(_get_all_admins)


async def _get_total_admins() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM admins")
    return int(row["c"]) if row else 0
get_total_admins = sync_wrapper(_get_total_admins)


# ═══════════════════════════════════════════════════════════
# Premium
# ═══════════════════════════════════════════════════════════
async def _get_premium_until(user_id: int):
    row = await _fetchone("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
    if row and row["premium_until"]:
        return _to_datetime(row["premium_until"])
    return None
get_premium_until = sync_wrapper(_get_premium_until)


async def _is_premium(user_id: int) -> bool:
    expires = await _get_premium_until(user_id)
    return expires is not None and expires > datetime.now()
is_premium = sync_wrapper(_is_premium)


async def _set_premium(user_id: int, expires: datetime) -> bool:
    cur = await _execute(
        "UPDATE users SET premium_until=? WHERE user_id=?",
        (_dt_str(expires), user_id),
    )
    return cur.rowcount > 0
set_premium = sync_wrapper(_set_premium)


async def _extend_premium(user_id: int, days: int) -> bool:
    current = await _get_premium_until(user_id)
    now = datetime.now()
    expires = current if current and current > now else now
    return await _set_premium(user_id, expires + timedelta(days=days))
extend_premium = sync_wrapper(_extend_premium)


async def _remove_premium(user_id: int) -> bool:
    cur = await _execute(
        "UPDATE users SET premium_until=NULL WHERE user_id=?",
        (user_id,),
    )
    return cur.rowcount > 0
remove_premium = sync_wrapper(_remove_premium)


async def _get_total_premium() -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS c FROM users "
        "WHERE premium_until IS NOT NULL AND premium_until > datetime('now','localtime')"
    )
    return int(row["c"]) if row else 0
get_total_premium = sync_wrapper(_get_total_premium)


async def _get_premium_users():
    return await _fetchall(
        "SELECT * FROM users WHERE premium_until IS NOT NULL "
        "AND premium_until > datetime('now','localtime') ORDER BY premium_until ASC"
    )
get_premium_users = sync_wrapper(_get_premium_users)


# ═══════════════════════════════════════════════════════════
# Keys
# ═══════════════════════════════════════════════════════════
async def _create_key(key: str, days: int, redeem_limit: int, created_by: int) -> bool:
    cur = await _execute(
        "INSERT INTO keys (key, days, redeem_limit, redeemed_count, created_by) "
        "VALUES (?, ?, ?, 0, ?)",
        (key, days, redeem_limit, created_by),
    )
    return cur.rowcount > 0
create_key = sync_wrapper(_create_key)


async def _get_key(key: str):
    return await _fetchone("SELECT * FROM keys WHERE key=?", (key,))
get_key = sync_wrapper(_get_key)


async def _key_exists(key: str) -> bool:
    return await _get_key(key) is not None
key_exists = sync_wrapper(_key_exists)


async def _delete_key(key: str) -> bool:
    cur = await _execute("DELETE FROM keys WHERE key=?", (key,))
    return cur.rowcount > 0
delete_key = sync_wrapper(_delete_key)


async def _get_all_keys():
    return await _fetchall("SELECT * FROM keys ORDER BY created_at DESC")
get_all_keys = sync_wrapper(_get_all_keys)


async def _get_total_keys() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM keys")
    return int(row["c"]) if row else 0
get_total_keys = sync_wrapper(_get_total_keys)


async def _get_unused_keys() -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS c FROM keys WHERE COALESCE(redeemed_count,0)=0"
    )
    return int(row["c"]) if row else 0
get_unused_keys = sync_wrapper(_get_unused_keys)


async def _increase_redeem(key: str) -> bool:
    cur = await _execute(
        "UPDATE keys SET redeemed_count=COALESCE(redeemed_count,0)+1 WHERE key=?",
        (key,),
    )
    return cur.rowcount > 0
increase_redeem = sync_wrapper(_increase_redeem)


async def _add_redeem(key: str, user_id: int) -> bool:
    try:
        cur = await _execute(
            "INSERT INTO redeemed_keys (key, user_id) VALUES (?, ?)",
            (key, user_id),
        )
        return cur.rowcount > 0
    except Exception:
        return False
add_redeem = sync_wrapper(_add_redeem)


async def _already_redeemed(key: str, user_id: int) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM redeemed_keys WHERE key=? AND user_id=?",
        (key, user_id),
    )
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
    row = await _fetchone("SELECT COUNT(*) AS c FROM redeemed_keys")
    return int(row["c"]) if row else 0
get_total_redeems = sync_wrapper(_get_total_redeems)


async def _set_key_expiry(key: str, expires_at: datetime) -> bool:
    cur = await _execute(
        "UPDATE keys SET expires_at=? WHERE key=?",
        (_dt_str(expires_at), key),
    )
    return cur.rowcount > 0
set_key_expiry = sync_wrapper(_set_key_expiry)


async def _delete_expired_keys() -> int:
    now = _now_str()
    rows = await _fetchall(
        "SELECT key FROM keys WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )
    conn = await _get_pool()
    count = 0
    for r in rows:
        await conn.execute("DELETE FROM keys WHERE key=?", (r["key"],))
        await conn.execute("DELETE FROM redeemed_keys WHERE key=?", (r["key"],))
        count += 1
    await conn.commit()
    if count:
        logger.info(f"Deleted {count} expired keys")
    return count
delete_expired_keys = sync_wrapper(_delete_expired_keys)


# ═══════════════════════════════════════════════════════════
# Sites
# ═══════════════════════════════════════════════════════════
async def _add_site(url: str, gateway: str = "", price: float = 0,
                    status: str = "Working", added_by: int = 0) -> bool:
    cur = await _execute(
        "INSERT OR IGNORE INTO sites (url, gateway, price, status, added_by, added_at, last_checked) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (url, gateway, price, status, added_by, _now_str(), _now_str()),
    )
    return cur.rowcount > 0
add_site = sync_wrapper(_add_site)


async def _site_exists(url: str) -> bool:
    row = await _fetchone("SELECT 1 FROM sites WHERE url=?", (url,))
    return row is not None
site_exists = sync_wrapper(_site_exists)


async def _get_site(url: str):
    return await _fetchone("SELECT * FROM sites WHERE url=?", (url,))
get_site = sync_wrapper(_get_site)


async def _get_all_sites():
    return await _fetchall("SELECT * FROM sites ORDER BY id DESC")
get_all_sites = sync_wrapper(_get_all_sites)


async def _get_all_working_sites():
    return await _fetchall("SELECT * FROM sites WHERE status='Working' ORDER BY id DESC")
get_all_working_sites = sync_wrapper(_get_all_working_sites)


async def _get_total_sites() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM sites")
    return int(row["c"]) if row else 0
get_total_sites = sync_wrapper(_get_total_sites)


async def _update_site(url: str, gateway: str, price: float, status: str):
    await _execute(
        "UPDATE sites SET gateway=?, price=?, status=?, last_checked=? WHERE url=?",
        (gateway, price, status, _now_str(), url),
    )
update_site = sync_wrapper(_update_site)


async def _delete_site(url: str) -> bool:
    cur = await _execute("DELETE FROM sites WHERE url=?", (url,))
    return cur.rowcount > 0
delete_site = sync_wrapper(_delete_site)


async def _delete_all_sites():
    await _execute("DELETE FROM sites")
delete_all_sites = sync_wrapper(_delete_all_sites)


async def _get_random_site():
    row = await _fetchone(
        "SELECT url FROM sites WHERE status='Working' ORDER BY RANDOM() LIMIT 1"
    )
    return row["url"] if row else None
get_random_site = sync_wrapper(_get_random_site)


# ═══════════════════════════════════════════════════════════
# Proxies
# ═══════════════════════════════════════════════════════════
async def _add_user_proxy(user_id: int, proxy: str) -> bool:
    cur = await _execute(
        "INSERT OR IGNORE INTO user_proxies (user_id, proxy) VALUES (?, ?)",
        (user_id, proxy),
    )
    return cur.rowcount > 0
add_user_proxy = sync_wrapper(_add_user_proxy)


async def _get_user_proxies(user_id: int):
    return await _fetchall(
        "SELECT * FROM user_proxies WHERE user_id=? ORDER BY id DESC", (user_id,)
    )
get_user_proxies = sync_wrapper(_get_user_proxies)


async def _get_user_active_proxies(user_id: int):
    return await _fetchall(
        "SELECT * FROM user_proxies WHERE user_id=? AND status='active' ORDER BY id DESC",
        (user_id,),
    )
get_user_active_proxies = sync_wrapper(_get_user_active_proxies)


async def _get_random_user_proxy(user_id: int):
    row = await _fetchone(
        "SELECT proxy FROM user_proxies WHERE user_id=? AND status='active' "
        "ORDER BY RANDOM() LIMIT 1",
        (user_id,),
    )
    return row["proxy"] if row else None
get_random_user_proxy = sync_wrapper(_get_random_user_proxy)


async def _delete_user_proxy(proxy_id: int, user_id: int) -> bool:
    cur = await _execute(
        "DELETE FROM user_proxies WHERE id=? AND user_id=?",
        (proxy_id, user_id),
    )
    return cur.rowcount > 0
delete_user_proxy = sync_wrapper(_delete_user_proxy)


async def _delete_all_user_proxies(user_id: int) -> bool:
    cur = await _execute("DELETE FROM user_proxies WHERE user_id=?", (user_id,))
    return cur.rowcount > 0
delete_all_user_proxies = sync_wrapper(_delete_all_user_proxies)


async def _update_user_proxy_status(proxy_id: int, status: str) -> bool:
    cur = await _execute(
        "UPDATE user_proxies SET status=?, last_tested=? WHERE id=?",
        (status, _now_str(), proxy_id),
    )
    return cur.rowcount > 0
update_user_proxy_status = sync_wrapper(_update_user_proxy_status)


async def _update_user_proxy_response_time(proxy_id: int, response_time: float) -> bool:
    cur = await _execute(
        "UPDATE user_proxies SET response_time=? WHERE id=?",
        (response_time, proxy_id),
    )
    return cur.rowcount > 0
update_user_proxy_response_time = sync_wrapper(_update_user_proxy_response_time)


async def _get_total_user_proxies(user_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS c FROM user_proxies WHERE user_id=?", (user_id,)
    )
    return int(row["c"]) if row else 0
get_total_user_proxies = sync_wrapper(_get_total_user_proxies)


async def _get_total_user_active_proxies(user_id: int) -> int:
    row = await _fetchone(
        "SELECT COUNT(*) AS c FROM user_proxies WHERE user_id=? AND status='active'",
        (user_id,),
    )
    return int(row["c"]) if row else 0
get_total_user_active_proxies = sync_wrapper(_get_total_user_active_proxies)


async def _bulk_add_user_proxies(user_id: int, proxies: list) -> int:
    if not proxies:
        return 0
    conn = await _get_pool()
    data = [(user_id, p) for p in proxies]
    await conn.executemany(
        "INSERT OR IGNORE INTO user_proxies (user_id, proxy) VALUES (?, ?)", data
    )
    await conn.commit()
    return len(data)


def bulk_add_user_proxies(user_id: int, proxies: list) -> int:
    return _run_sync(_bulk_add_user_proxies(user_id, proxies))


async def _bulk_update_user_proxy_results(updates: list) -> int:
    if not updates:
        return 0
    conn = await _get_pool()
    count = 0
    now = _now_str()
    for proxy_id, status, response_time in updates:
        cur = await conn.execute(
            "UPDATE user_proxies SET status=?, response_time=?, last_tested=? WHERE id=?",
            (status, response_time, now, proxy_id),
        )
        count += cur.rowcount
    await conn.commit()
    return count


def bulk_update_user_proxy_results(updates: list) -> int:
    return _run_sync(_bulk_update_user_proxy_results(updates))


async def _bulk_delete_user_proxies(user_id, proxy_ids: list) -> int:
    if not proxy_ids:
        return 0
    conn = await _get_pool()
    placeholders = ",".join("?" * len(proxy_ids))
    if user_id is not None:
        cur = await conn.execute(
            f"DELETE FROM user_proxies WHERE id IN ({placeholders}) AND user_id=?",
            (*proxy_ids, user_id),
        )
    else:
        cur = await conn.execute(
            f"DELETE FROM user_proxies WHERE id IN ({placeholders})", tuple(proxy_ids)
        )
    await conn.commit()
    return cur.rowcount


def bulk_delete_user_proxies(user_id, proxy_ids: list) -> int:
    return _run_sync(_bulk_delete_user_proxies(user_id, proxy_ids))


bulk_mark_user_proxy_results = bulk_update_user_proxy_results


# ═══════════════════════════════════════════════════════════
# Gates
# ═══════════════════════════════════════════════════════════
async def _is_gate_enabled(gate_name: str) -> bool:
    row = await _fetchone(
        "SELECT enabled FROM gate_status WHERE gate_name=?", (gate_name,)
    )
    return bool(row["enabled"]) if row else True
is_gate_enabled = sync_wrapper(_is_gate_enabled)


async def _set_gate_enabled(gate_name: str, enabled: bool) -> bool:
    cur = await _execute(
        "UPDATE gate_status SET enabled=? WHERE gate_name=?",
        (1 if enabled else 0, gate_name),
    )
    return cur.rowcount > 0
set_gate_enabled = sync_wrapper(_set_gate_enabled)


async def _get_all_gate_status():
    return await _fetchall("SELECT * FROM gate_status ORDER BY gate_name")
get_all_gate_status = sync_wrapper(_get_all_gate_status)


def get_gate_status_all() -> dict:
    rows = get_all_gate_status() or []
    return {r["gate_name"]: bool(r["enabled"]) for r in rows}


def toggle_gate_status(gate_name: str) -> bool:
    new_state = not is_gate_enabled(gate_name)
    set_gate_enabled(gate_name, new_state)
    return new_state


# ═══════════════════════════════════════════════════════════
# Bot settings (lock, speed, etc.)
# ═══════════════════════════════════════════════════════════
def is_bot_locked() -> bool:
    return _locked_cache["value"]


async def _is_bot_locked() -> bool:
    row = await _fetchone("SELECT value FROM bot_settings WHERE key='locked'")
    return bool(row and row["value"] == "true")
# keep async version accessible too
_is_bot_locked_async = _is_bot_locked


async def _set_bot_lock(locked: bool) -> bool:
    cur = await _execute(
        "UPDATE bot_settings SET value=? WHERE key='locked'",
        ("true" if locked else "false",),
    )
    _locked_cache["value"] = locked
    return cur.rowcount > 0
set_bot_lock = sync_wrapper(_set_bot_lock)


async def _get_speed() -> int:
    row = await _fetchone("SELECT value FROM bot_settings WHERE key='speed'")
    if not row:
        return 7
    try:
        return int(row["value"])
    except (ValueError, TypeError):
        return 7
get_speed = sync_wrapper(_get_speed)


async def _set_speed(threads: int) -> bool:
    cur = await _execute(
        "UPDATE bot_settings SET value=? WHERE key='speed'", (str(threads),)
    )
    return cur.rowcount > 0
set_speed = sync_wrapper(_set_speed)


async def _get_msh_speed() -> int:
    row = await _fetchone("SELECT value FROM bot_settings WHERE key='msh_speed'")
    if not row:
        return 10
    try:
        return int(row["value"])
    except (ValueError, TypeError):
        return 10
get_msh_speed = sync_wrapper(_get_msh_speed)


async def _set_msh_speed(speed: int) -> bool:
    cur = await _execute(
        "UPDATE bot_settings SET value=? WHERE key='msh_speed'", (str(speed),)
    )
    return cur.rowcount > 0
set_msh_speed = sync_wrapper(_set_msh_speed)


async def _is_auto_health_enabled() -> bool:
    row = await _fetchone("SELECT value FROM bot_settings WHERE key='auto_health'")
    return bool(row and row["value"] == "true")
is_auto_health_enabled = sync_wrapper(_is_auto_health_enabled)


async def _set_auto_health(enabled: bool) -> bool:
    cur = await _execute(
        "UPDATE bot_settings SET value=? WHERE key='auto_health'",
        ("true" if enabled else "false",),
    )
    return cur.rowcount > 0
set_auto_health = sync_wrapper(_set_auto_health)


# ═══════════════════════════════════════════════════════════
# Check history
# ═══════════════════════════════════════════════════════════
async def _log_check(user_id: int, card: str, status: str, message: str,
                     gateway: str, time_taken: float):
    card_number = card.split("|")[0] if "|" in card else card
    bin_num = card_number[:6] if card_number else ""
    await _execute(
        "INSERT INTO check_history "
        "(user_id, card_number, bin, status, message, gateway, time_taken) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, card_number, bin_num, status, message, gateway, time_taken),
    )
log_check = sync_wrapper(_log_check)


def _classify_status(status: str) -> str:
    s = (status or "").lower()
    if s in ("charged", "charge", "order_paid", "paid"):
        return "charged"
    if s in ("approved", "approve", "live", "ccn", "authenticate_successful"):
        return "approved"
    if s in ("declined", "dead", "decline", "rejected", "failed"):
        return "declined"
    return "errors"


async def _get_user_activity_24h(user_id: int) -> dict:
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    rows = await _fetchall(
        "SELECT status, COUNT(*) AS c FROM check_history "
        "WHERE user_id=? AND created_at > ? GROUP BY status",
        (user_id, cutoff),
    )
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    for r in rows:
        c = int(r["c"])
        result["total"] += c
        result[_classify_status(r["status"])] += c
    return result
get_user_activity_24h = sync_wrapper(_get_user_activity_24h)


async def _get_user_all_time_stats(user_id: int) -> dict:
    rows = await _fetchall(
        "SELECT status, COUNT(*) AS c FROM check_history WHERE user_id=? GROUP BY status",
        (user_id,),
    )
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    for r in rows:
        c = int(r["c"])
        result["total"] += c
        result[_classify_status(r["status"])] += c
    return result
get_user_all_time_stats = sync_wrapper(_get_user_all_time_stats)


# ═══════════════════════════════════════════════════════════
# Premium notifications
# ═══════════════════════════════════════════════════════════
async def _mark_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    cur = await _execute(
        "INSERT OR IGNORE INTO premium_notifications (user_id, notification_type) "
        "VALUES (?, ?)",
        (user_id, notification_type),
    )
    return cur.rowcount > 0
mark_premium_notification_sent = sync_wrapper(_mark_premium_notification_sent)


async def _is_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    row = await _fetchone(
        "SELECT 1 FROM premium_notifications WHERE user_id=? AND notification_type=?",
        (user_id, notification_type),
    )
    return row is not None
is_premium_notification_sent = sync_wrapper(_is_premium_notification_sent)


async def _get_user_premium_notifications(user_id: int) -> List[str]:
    rows = await _fetchall(
        "SELECT notification_type FROM premium_notifications WHERE user_id=?",
        (user_id,),
    )
    return [r["notification_type"] for r in rows]
get_user_premium_notifications = sync_wrapper(_get_user_premium_notifications)


async def _clear_old_premium_notifications(days: int = 30):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    await _execute("DELETE FROM premium_notifications WHERE sent_at < ?", (cutoff,))
clear_old_premium_notifications = sync_wrapper(_clear_old_premium_notifications)


async def _get_users_premium_expiring_in_range(hours_min: int, hours_max: int) -> List[dict]:
    now = datetime.now()
    lo = (now + timedelta(hours=hours_min)).strftime("%Y-%m-%d %H:%M:%S")
    hi = (now + timedelta(hours=hours_max)).strftime("%Y-%m-%d %H:%M:%S")
    rows = await _fetchall(
        "SELECT user_id, first_name, username, premium_until FROM users "
        "WHERE premium_until IS NOT NULL AND premium_until >= ? AND premium_until < ?",
        (lo, hi),
    )
    return [dict(r) for r in rows]
get_users_premium_expiring_in_range = sync_wrapper(_get_users_premium_expiring_in_range)


async def _get_users_premium_expired_today() -> List[dict]:
    now = datetime.now()
    lo = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    hi = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = await _fetchall(
        "SELECT user_id, first_name, username, premium_until FROM users "
        "WHERE premium_until IS NOT NULL AND premium_until >= ? AND premium_until < ?",
        (lo, hi),
    )
    return [dict(r) for r in rows]
get_users_premium_expired_today = sync_wrapper(_get_users_premium_expired_today)


async def _get_users_premium_active() -> List[dict]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = await _fetchall(
        "SELECT user_id, first_name, username, premium_until FROM users "
        "WHERE premium_until IS NOT NULL AND premium_until > ?",
        (now,),
    )
    return [dict(r) for r in rows]
get_users_premium_active = sync_wrapper(_get_users_premium_active)


async def _get_premium_expiry(user_id: int):
    row = await _fetchone("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
    if row and row["premium_until"]:
        return _to_datetime(row["premium_until"])
    return None
get_premium_expiry = sync_wrapper(_get_premium_expiry)


async def _get_user_current_tier(user_id: int) -> str:
    return "Premium" if await _is_premium(user_id) else "Trial"
get_user_current_tier = sync_wrapper(_get_user_current_tier)


# ═══════════════════════════════════════════════════════════
# Groups / misc counters
# ═══════════════════════════════════════════════════════════
async def _get_all_groups():
    return await _fetchall("SELECT * FROM groups ORDER BY added_at DESC")
get_all_groups = sync_wrapper(_get_all_groups)


async def _get_total_groups() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM groups")
    return int(row["c"]) if row else 0
get_total_groups = sync_wrapper(_get_total_groups)


async def _get_total_banned() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM users WHERE banned=1")
    return int(row["c"]) if row else 0
get_total_banned = sync_wrapper(_get_total_banned)


async def _get_total_proxies() -> int:
    row = await _fetchone("SELECT COUNT(*) AS c FROM user_proxies")
    return int(row["c"]) if row else 0
get_total_proxies = sync_wrapper(_get_total_proxies)


# ═══════════════════════════════════════════════════════════
# Sync helpers
# ═══════════════════════════════════════════════════════════
def update_user_identity(user_id: int, first_name: str, username: str = None) -> bool:
    async def _update():
        cur = await _execute(
            "UPDATE users SET first_name=?, username=? WHERE user_id=?",
            (first_name or "User", username, user_id),
        )
        return cur.rowcount > 0
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
        cur = await _execute(
            "UPDATE users SET credits=COALESCE(credits,0)+? WHERE user_id=?",
            (amount, user_id),
        )
        return cur.rowcount > 0
    return _run_sync(_update())


def get_user_credits(user_id: int):
    user = get_user(user_id)
    if not user:
        return 0
    try:
        return int(user["credits"] or 0)
    except (KeyError, IndexError, TypeError):
        return 0


def clear_all_user_proxies() -> int:
    async def _clear():
        cur = await _execute("DELETE FROM user_proxies")
        return cur.rowcount
    return _run_sync(_clear())


def clear_all_sites() -> int:
    async def _clear():
        cur = await _execute("DELETE FROM sites")
        return cur.rowcount
    return _run_sync(_clear())


def clear_all_premium() -> int:
    async def _clear():
        cur = await _execute(
            "UPDATE users SET premium_until=NULL WHERE premium_until IS NOT NULL"
        )
        return cur.rowcount
    return _run_sync(_clear())


def clear_all_admins() -> int:
    async def _clear():
        cur = await _execute("DELETE FROM admins")
        return cur.rowcount
    return _run_sync(_clear())


def get_all_global_proxies():
    return get_all_proxies_with_owners()


def get_total_active_proxies() -> int:
    async def _c():
        row = await _fetchone(
            "SELECT COUNT(*) AS c FROM user_proxies WHERE status='active'"
        )
        return int(row["c"]) if row else 0
    return _run_sync(_c())


def get_total_dead_proxies() -> int:
    async def _c():
        row = await _fetchone(
            "SELECT COUNT(*) AS c FROM user_proxies WHERE status='dead'"
        )
        return int(row["c"]) if row else 0
    return _run_sync(_c())


def clear_all_proxies() -> int:
    return clear_all_user_proxies()


def get_proxy_by_id(proxy_id: int):
    async def _g():
        return await _fetchone("SELECT * FROM user_proxies WHERE id=?", (proxy_id,))
    return _run_sync(_g())


def delete_proxy_by_id(proxy_id: int) -> bool:
    async def _d():
        cur = await _execute("DELETE FROM user_proxies WHERE id=?", (proxy_id,))
        return cur.rowcount > 0
    return _run_sync(_d())


def get_proxies_by_user(user_id: int):
    return get_user_proxies(user_id)


def get_proxies_by_status(status: str):
    async def _g():
        return await _fetchall(
            "SELECT * FROM user_proxies WHERE status=? ORDER BY user_id, id DESC",
            (status,),
        )
    return _run_sync(_g())


def update_proxy_status(proxy_id: int, status: str) -> bool:
    return update_user_proxy_status(proxy_id, status)


def get_all_proxies_with_owners():
    async def _g():
        return await _fetchall("""
            SELECT up.*, u.user_id AS owner_id, u.first_name, u.username
            FROM user_proxies up
            LEFT JOIN users u ON up.user_id = u.user_id
            ORDER BY up.user_id, up.id DESC
        """)
    return _run_sync(_g())


# ═══════════════════════════════════════════════════════════
# Owner-configurable settings
# ═══════════════════════════════════════════════════════════
def get_bot_setting(key: str) -> str:
    async def _g():
        row = await _fetchone("SELECT value FROM bot_settings WHERE key=?", (key,))
        return row["value"] if row else ""
    return _run_sync(_g())


def set_bot_setting(key: str, value: str) -> bool:
    async def _s():
        await _execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        return True
    return _run_sync(_s())


# ═══════════════════════════════════════════════════════════
# Required channels
# ═══════════════════════════════════════════════════════════
def get_required_channels() -> list:
    async def _g():
        rows = await _fetchall("SELECT * FROM required_channels ORDER BY id")
        return [dict(r) for r in rows]
    return _run_sync(_g())


def add_required_channel(chat_id: int, username: str, title: str) -> bool:
    async def _a():
        await _execute(
            "INSERT INTO required_channels (chat_id, username, title) VALUES (?, ?, ?)",
            (chat_id, username, title),
        )
        return True
    return _run_sync(_a())


def remove_required_channel(chat_id: int) -> bool:
    async def _r():
        cur = await _execute(
            "DELETE FROM required_channels WHERE chat_id=?", (chat_id,)
        )
        return cur.rowcount > 0
    return _run_sync(_r())


# ═══════════════════════════════════════════════════════════
# Extra API URLs
# ═══════════════════════════════════════════════════════════
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
    try:
        from config import API_BASE_URL
        urls = [API_BASE_URL] if API_BASE_URL else []
    except (ImportError, AttributeError):
        urls = []
    for u in get_extra_api_urls():
        if u not in urls:
            urls.append(u)
    return urls
