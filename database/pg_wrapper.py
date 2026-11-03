
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from .pg_db import db





async def add_user(user_id: int, first_name: str, username: str = None) -> bool:
    result = await db.execute(
        "INSERT INTO users (user_id, first_name, username) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO NOTHING",
        user_id, first_name, username
    )
    return result > 0

async def user_exists(user_id: int) -> bool:
    row = await db.fetchone("SELECT 1 FROM users WHERE user_id=$1", user_id)
    return row is not None

async def get_user(user_id: int):
    return await db.fetchone("SELECT * FROM users WHERE user_id=$1", user_id)

async def get_all_users():
    return await db.fetchall("SELECT * FROM users ORDER BY joined_at DESC")

async def get_total_users() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users") or 0

async def ban_user(user_id: int) -> bool:
    result = await db.execute("UPDATE users SET banned=1 WHERE user_id=$1", user_id)
    return result > 0

async def unban_user(user_id: int) -> bool:
    result = await db.execute("UPDATE users SET banned=0 WHERE user_id=$1", user_id)
    return result > 0

async def is_banned(user_id: int) -> bool:
    row = await db.fetchone("SELECT banned FROM users WHERE user_id=$1", user_id)
    return bool(row["banned"]) if row else False

async def get_banned_users():
    return await db.fetchall("SELECT * FROM users WHERE banned=1 ORDER BY joined_at DESC")

async def get_free_users():
    return await db.fetchall("SELECT * FROM users WHERE premium_until IS NULL ORDER BY joined_at DESC")





async def add_admin(user_id: int, added_by: int) -> bool:
    result = await db.execute(
        "INSERT INTO admins (user_id, added_by) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
        user_id, added_by
    )
    return result > 0

async def remove_admin(user_id: int) -> bool:
    result = await db.execute("DELETE FROM admins WHERE user_id=$1", user_id)
    return result > 0

async def is_admin(user_id: int) -> bool:
    row = await db.fetchone("SELECT 1 FROM admins WHERE user_id=$1", user_id)
    return row is not None

async def get_all_admins():
    return await db.fetchall("SELECT * FROM admins ORDER BY added_at DESC")

async def get_total_admins() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM admins") or 0





async def get_premium_until(user_id: int):
    row = await db.fetchone("SELECT premium_until FROM users WHERE user_id=$1", user_id)
    if not row or not row["premium_until"]:
        return None
    return row["premium_until"]

async def is_premium(user_id: int) -> bool:
    expires = await get_premium_until(user_id)
    return expires is not None and expires > datetime.now()

async def set_premium(user_id: int, expires: datetime) -> bool:
    result = await db.execute(
        "UPDATE users SET premium_until=$1 WHERE user_id=$2",
        expires, user_id
    )
    return result > 0

async def extend_premium(user_id: int, days: int) -> bool:
    current = await get_premium_until(user_id)
    now = datetime.now()
    expires = current if current and current > now else now
    return await set_premium(user_id, expires + timedelta(days=days))

async def remove_premium(user_id: int) -> bool:
    result = await db.execute("UPDATE users SET premium_until=NULL WHERE user_id=$1", user_id)
    return result > 0

async def get_total_premium() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL") or 0

async def get_premium_users():
    return await db.fetchall("SELECT * FROM users WHERE premium_until IS NOT NULL ORDER BY premium_until DESC")





async def create_key(key: str, days: int, redeem_limit: int, created_by: int) -> bool:
    result = await db.execute(
        "INSERT INTO keys (key, days, redeem_limit, created_by) VALUES ($1, $2, $3, $4)",
        key, days, redeem_limit, created_by
    )
    return result > 0

async def get_key(key: str):
    return await db.fetchone("SELECT * FROM keys WHERE key=$1", key)

async def key_exists(key: str) -> bool:
    return await get_key(key) is not None

async def delete_key(key: str) -> bool:
    result = await db.execute("DELETE FROM keys WHERE key=$1", key)
    return result > 0

async def get_all_keys():
    return await db.fetchall("SELECT * FROM keys ORDER BY created_at DESC")

async def get_total_keys() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM keys") or 0

async def get_unused_keys() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM keys WHERE redeemed_count = 0") or 0

async def increase_redeem(key: str) -> bool:
    result = await db.execute(
        "UPDATE keys SET redeemed_count = redeemed_count + 1 WHERE key=$1",
        key
    )
    return result > 0

async def add_redeem(key: str, user_id: int) -> bool:
    result = await db.execute(
        "INSERT INTO redeemed_keys (key, user_id) VALUES ($1, $2) ON CONFLICT (key, user_id) DO NOTHING",
        key, user_id
    )
    return result > 0

async def already_redeemed(key: str, user_id: int) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM redeemed_keys WHERE key=$1 AND user_id=$2",
        key, user_id
    )
    return row is not None

async def can_redeem(key: str) -> bool:
    row = await get_key(key)
    if not row:
        return False
    return row["redeemed_count"] < row["redeem_limit"]

async def get_total_redeems() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM redeemed_keys") or 0

async def set_key_expiry(key: str, expires_at: datetime) -> bool:
    result = await db.execute(
        "UPDATE keys SET expires_at=$1 WHERE key=$2",
        expires_at, key
    )
    return result > 0

async def delete_expired_keys() -> int:
    now = datetime.now()
    expired = await db.fetchall(
        "SELECT key FROM keys WHERE expires_at IS NOT NULL AND expires_at < $1",
        now
    )
    
    if not expired:
        return 0
    
    count = 0
    for row in expired:
        key = row["key"]
        await db.execute("DELETE FROM keys WHERE key=$1", key)
        await db.execute("DELETE FROM redeemed_keys WHERE key=$1", key)
        count += 1
    
    if count > 0:
        logger.info(f"Deleted {count} expired keys")
    
    return count





async def add_site(url: str, gateway: str = "", price: float = 0, status: str = "Working", added_by: int = 0):
    result = await db.execute(
        """INSERT INTO sites (url, gateway, price, status, added_by, added_at, last_checked) 
           VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (url) DO NOTHING""",
        url, gateway, price, status, added_by, datetime.now(), datetime.now()
    )
    return result > 0

async def site_exists(url: str) -> bool:
    row = await db.fetchone("SELECT 1 FROM sites WHERE url=$1", url)
    return row is not None

async def get_site(url: str):
    return await db.fetchone("SELECT * FROM sites WHERE url=$1", url)

async def get_all_sites():
    return await db.fetchall("SELECT * FROM sites ORDER BY id DESC")

async def get_all_working_sites():
    return await db.fetchall("SELECT * FROM sites WHERE status='Working' ORDER BY id DESC")

async def get_total_sites() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM sites") or 0

async def update_site(url: str, gateway: str, price: float, status: str):
    await db.execute(
        "UPDATE sites SET gateway=$1, price=$2, status=$3, last_checked=$4 WHERE url=$5",
        gateway, price, status, datetime.now(), url
    )

async def delete_site(url: str) -> bool:
    result = await db.execute("DELETE FROM sites WHERE url=$1", url)
    return result > 0

async def delete_all_sites():
    await db.execute("DELETE FROM sites")

async def get_random_site() -> Optional[str]:
    row = await db.fetchone("SELECT url FROM sites WHERE status='Working' ORDER BY RANDOM() LIMIT 1")
    return row["url"] if row else None





async def add_user_proxy(user_id: int, proxy: str) -> bool:
    result = await db.execute(
        "INSERT INTO user_proxies (user_id, proxy) VALUES ($1, $2) ON CONFLICT (user_id, proxy) DO NOTHING",
        user_id, proxy
    )
    return result > 0

async def get_user_proxies(user_id: int):
    return await db.fetchall(
        "SELECT * FROM user_proxies WHERE user_id=$1 ORDER BY id DESC",
        user_id
    )

async def get_user_active_proxies(user_id: int):
    return await db.fetchall(
        "SELECT * FROM user_proxies WHERE user_id=$1 AND status='active' ORDER BY id DESC",
        user_id
    )

async def get_random_user_proxy(user_id: int) -> Optional[str]:
    row = await db.fetchone(
        "SELECT proxy FROM user_proxies WHERE user_id=$1 AND status='active' ORDER BY RANDOM() LIMIT 1",
        user_id
    )
    return row["proxy"] if row else None

async def delete_user_proxy(proxy_id: int, user_id: int) -> bool:
    result = await db.execute(
        "DELETE FROM user_proxies WHERE id=$1 AND user_id=$2",
        proxy_id, user_id
    )
    return result > 0

async def delete_all_user_proxies(user_id: int) -> bool:
    result = await db.execute(
        "DELETE FROM user_proxies WHERE user_id=$1",
        user_id
    )
    return result > 0

async def update_user_proxy_status(proxy_id: int, status: str) -> bool:
    result = await db.execute(
        "UPDATE user_proxies SET status=$1, last_tested=$2 WHERE id=$3",
        status, datetime.now(), proxy_id
    )
    return result > 0

async def update_user_proxy_response_time(proxy_id: int, response_time: float) -> bool:
    result = await db.execute(
        "UPDATE user_proxies SET response_time=$1 WHERE id=$2",
        response_time, proxy_id
    )
    return result > 0

async def get_total_user_proxies(user_id: int) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM user_proxies WHERE user_id=$1",
        user_id
    ) or 0

async def get_total_user_active_proxies(user_id: int) -> int:
    return await db.fetchval(
        "SELECT COUNT(*) FROM user_proxies WHERE user_id=$1 AND status='active'",
        user_id
    ) or 0





async def is_gate_enabled(gate_name: str) -> bool:
    row = await db.fetchone("SELECT enabled FROM gate_status WHERE gate_name=$1", gate_name)
    if row is None:
        return True
    return bool(row["enabled"])

async def set_gate_enabled(gate_name: str, enabled: bool) -> bool:
    result = await db.execute(
        "UPDATE gate_status SET enabled=$1 WHERE gate_name=$2",
        1 if enabled else 0, gate_name
    )
    return result > 0

async def get_all_gate_status() -> list:
    return await db.fetchall("SELECT * FROM gate_status ORDER BY gate_name")





async def is_bot_locked() -> bool:
    row = await db.fetchone("SELECT value FROM bot_settings WHERE key='locked'")
    if not row:
        return False
    return row["value"] == "true"

async def set_bot_lock(locked: bool) -> bool:
    result = await db.execute(
        "UPDATE bot_settings SET value=$1 WHERE key='locked'",
        "true" if locked else "false"
    )
    return result > 0

async def get_speed() -> int:
    row = await db.fetchone("SELECT value FROM bot_settings WHERE key='speed'")
    if not row:
        return 7
    try:
        return int(row["value"])
    except ValueError:
        return 7

async def set_speed(threads: int) -> bool:
    result = await db.execute(
        "UPDATE bot_settings SET value=$1 WHERE key='speed'",
        str(threads)
    )
    return result > 0



async def get_msh_speed() -> int:
    row = await db.fetchone("SELECT value FROM bot_settings WHERE key='msh_speed'")
    if not row:
        return 10
    try:
        return int(row["value"])
    except ValueError:
        return 10

async def set_msh_speed(speed: int) -> bool:
    result = await db.execute(
        "UPDATE bot_settings SET value=$1 WHERE key='msh_speed'",
        str(speed)
    )
    return result > 0

async def is_auto_health_enabled() -> bool:
    row = await db.fetchone("SELECT value FROM bot_settings WHERE key='auto_health'")
    if not row:
        return False
    return row["value"] == "true"

async def set_auto_health(enabled: bool) -> bool:
    result = await db.execute(
        "UPDATE bot_settings SET value=$1 WHERE key='auto_health'",
        "true" if enabled else "false"
    )
    return result > 0





async def log_check(user_id: int, card: str, status: str, message: str, gateway: str, time_taken: float):
    card_number = card.split('|')[0] if '|' in card else card
    bin_num = card_number[:6] if card_number else ""
    
    await db.execute(
        """INSERT INTO check_history 
           (user_id, card_number, bin, status, message, gateway, time_taken) 
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        user_id, card_number, bin_num, status, message, gateway, time_taken
    )

async def get_user_activity_24h(user_id: int) -> dict:
    cutoff = datetime.now() - timedelta(hours=24)
    
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    
    rows = await db.fetchall(
        """SELECT status, COUNT(*) as count 
           FROM check_history 
           WHERE user_id = $1 AND created_at > $2 
           GROUP BY status""",
        user_id, cutoff
    )
    
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

async def get_user_all_time_stats(user_id: int) -> dict:
    result = {"total": 0, "charged": 0, "approved": 0, "declined": 0, "errors": 0}
    
    rows = await db.fetchall(
        """SELECT status, COUNT(*) as count 
           FROM check_history 
           WHERE user_id = $1 
           GROUP BY status""",
        user_id
    )
    
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





async def mark_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    result = await db.execute(
        "INSERT INTO premium_notifications (user_id, notification_type) VALUES ($1, $2) ON CONFLICT (user_id, notification_type) DO NOTHING",
        user_id, notification_type
    )
    return result > 0

async def is_premium_notification_sent(user_id: int, notification_type: str) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM premium_notifications WHERE user_id=$1 AND notification_type=$2",
        user_id, notification_type
    )
    return row is not None

async def get_user_premium_notifications(user_id: int) -> List[str]:
    rows = await db.fetchall(
        "SELECT notification_type FROM premium_notifications WHERE user_id=$1",
        user_id
    )
    return [row["notification_type"] for row in rows]

async def clear_old_premium_notifications(days: int = 30):
    cutoff = datetime.now() - timedelta(days=days)
    await db.execute(
        "DELETE FROM premium_notifications WHERE sent_at < $1",
        cutoff
    )

async def get_users_premium_expiring_in_range(hours_min: int, hours_max: int) -> List[dict]:
    now = datetime.now()
    expiry_min = now + timedelta(hours=hours_min)
    expiry_max = now + timedelta(hours=hours_max)
    
    return await db.fetchall(
        """SELECT user_id, first_name, username, premium_until 
           FROM users 
           WHERE premium_until IS NOT NULL 
           AND premium_until >= $1 
           AND premium_until < $2""",
        expiry_min, expiry_max
    )

async def get_users_premium_expired_today() -> List[dict]:
    now = datetime.now()
    expiry_start = now - timedelta(hours=24)
    
    return await db.fetchall(
        """SELECT user_id, first_name, username, premium_until 
           FROM users 
           WHERE premium_until IS NOT NULL 
           AND premium_until >= $1 
           AND premium_until < $2""",
        expiry_start, now
    )

async def get_users_premium_active() -> List[dict]:
    now = datetime.now()
    
    return await db.fetchall(
        """SELECT user_id, first_name, username, premium_until 
           FROM users 
           WHERE premium_until IS NOT NULL 
           AND premium_until > $1""",
        now
    )

async def get_premium_expiry(user_id: int):
    row = await db.fetchone(
        "SELECT premium_until FROM users WHERE user_id=$1",
        user_id
    )
    return row["premium_until"] if row else None

async def get_user_current_tier(user_id: int) -> str:
    if await is_premium(user_id):
        return "Premium"
    return "Trial"





async def get_all_groups():
    return await db.fetchall("SELECT * FROM groups ORDER BY added_at DESC")

async def get_total_groups() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM groups") or 0





async def get_total_banned() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE banned=1") or 0

async def get_total_proxies() -> int:
    return await db.fetchval("SELECT COUNT(*) FROM user_proxies") or 0





def sync_wrapper(async_func):
    """Convert async function to sync for backward compatibility"""
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        if loop.is_running():

            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(async_func(*args, **kwargs))
            finally:
                new_loop.close()
        else:
            return loop.run_until_complete(async_func(*args, **kwargs))
    return wrapper


add_user_sync = sync_wrapper(add_user)
user_exists_sync = sync_wrapper(user_exists)
get_user_sync = sync_wrapper(get_user)
