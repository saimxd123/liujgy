


import asyncio
from datetime import datetime, timedelta
from telegram import Bot, LinkPreviewOptions
from telegram.constants import ParseMode

from logger import get_logger
from database import (
    is_premium_notification_sent,
    mark_premium_notification_sent,
)
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)



_scheduled_tasks = {}


def _key(user_id: int, notification_type: str):
    return (int(user_id), notification_type)


def cancel_premium_notifications(user_id: int):
    """Cancel all pending premium notifications for a user."""
    user_id = int(user_id)
    for notification_type in ("24h", "1h", "expired"):
        task = _scheduled_tasks.pop(_key(user_id, notification_type), None)
        if task and not task.done():
            task.cancel()


def _cancel_one(user_id: int, notification_type: str):
    task = _scheduled_tasks.pop(_key(user_id, notification_type), None)
    if task and not task.done():
        task.cancel()


async def send_premium_activation_message(bot: Bot, user_id: int, expiry_date: datetime):
    expiry_str = expiry_date.strftime("%d %b %Y %H:%M")
    text = f"""
{E.SUCCESS} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.STAR} <b>You are now a Premium User!</b>

{E.CALENDAR} <b>Expires:</b> <code>{expiry_str}</code>

{E.THUNDER} Use <code>/cmds</code> to see all available commands.

<b>Premium Features:</b>
• {E.CARD} Mass checks
• {E.FLY} No rate limits
• {E.SEARCH} Scraper access
• {E.STAR} Priority support
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML,
                               link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:
        logger.error(f"Failed to send premium activation to {user_id}: {e}")


async def send_premium_expiry_reminder(bot: Bot, user_id: int, expiry_date: datetime, hours_left: int):
    notification_type = "24h" if hours_left == 24 else "1h"
    if notification_type == "24h":
        title = "𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙀𝙓𝙋𝙄𝙍𝙔 𝙒𝘼𝙍𝙉𝙄𝙉𝙂 (24𝙝)"
        emoji = E.WARNING
        message = "Your premium subscription will expire in <b>24 hours</b>."
    else:
        title = "𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙀𝙓𝙋𝙄𝙍𝙔 𝙒𝘼𝙍𝙉𝙄𝙉𝙂 (1𝙝)"
        emoji = E.ERROR
        message = "Your premium subscription will expire in <b>1 hour</b>!"

    try:
        if is_premium_notification_sent(user_id, notification_type):
            return
    except Exception as e:
        logger.error(f"Error checking notification state for {user_id}: {e}")
        return

    expiry_str = expiry_date.strftime("%d %b %Y %H:%M")
    text = f"""
{emoji} ⌠ {title} ⌡
━━━━━━━━━━━━━━━━━━
{message}

{E.CALENDAR} <b>Expires:</b> <code>{expiry_str}</code>

{E.INFO} Please contact admin to reactivate:
<a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML,
                               link_preview_options=LinkPreviewOptions(is_disabled=True))
        mark_premium_notification_sent(user_id, notification_type)
    except Exception as e:
        logger.error(f"Failed to send {notification_type} premium reminder to {user_id}: {e}")


async def send_premium_expired_message(bot: Bot, user_id: int, force: bool = False):
    notification_type = "expired"
    try:
        if not force and is_premium_notification_sent(user_id, notification_type):
            return
    except Exception as e:
        logger.error(f"Error checking expired notification state for {user_id}: {e}")
        return

    text = f"""
{E.ERROR} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙀𝙓𝙋𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.CLOSE} Your premium subscription has <b>expired</b>.

{E.INFO} Your account has been reverted to free tier.

<b>To reactivate:</b>
• Contact admin: <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
• Use <code>/plan</code> to view pricing and get access
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML,
                               link_preview_options=LinkPreviewOptions(is_disabled=True))
        mark_premium_notification_sent(user_id, notification_type)
    except Exception as e:
        logger.error(f"Failed to send expired message to {user_id}: {e}")


async def _scheduled_notification(bot: Bot, user_id: int, expiry_date: datetime, notification_type: str):
    target = {
        "24h": expiry_date - timedelta(hours=24),
        "1h": expiry_date - timedelta(hours=1),
        "expired": expiry_date,
    }[notification_type]

    try:
        delay = (target - datetime.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)


        current_task = _scheduled_tasks.get(_key(user_id, notification_type))
        if current_task is not asyncio.current_task():
            return

        from database import get_premium_until, is_premium
        current_expiry = get_premium_until(user_id)


        if notification_type == "expired":
            if current_expiry != expiry_date or is_premium(user_id):
                return
            await send_premium_expired_message(bot, user_id)
        else:


            if not current_expiry or current_expiry != expiry_date or not is_premium(user_id):
                return
            await send_premium_expiry_reminder(bot, user_id, expiry_date,
                                               24 if notification_type == "24h" else 1)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.error(f"Scheduled premium notification failed for {user_id}/{notification_type}: {e}", exc_info=True)
    finally:
        if _scheduled_tasks.get(_key(user_id, notification_type)) is asyncio.current_task():
            _scheduled_tasks.pop(_key(user_id, notification_type), None)


def schedule_premium_notifications(bot: Bot, user_id: int, expiry_date: datetime):
    """Calculate and schedule 24h, 1h and expiry notifications immediately."""
    cancel_premium_notifications(user_id)
    now = datetime.now()
    for notification_type, target in (
        ("24h", expiry_date - timedelta(hours=24)),
        ("1h", expiry_date - timedelta(hours=1)),
        ("expired", expiry_date),
    ):

        if target <= now:
            continue
        task = asyncio.create_task(
            _scheduled_notification(bot, int(user_id), expiry_date, notification_type)
        )
        _scheduled_tasks[_key(user_id, notification_type)] = task

    logger.info(f"Premium notifications scheduled for {user_id}; expiry={expiry_date.isoformat()}")


async def restore_premium_notification_schedules(bot: Bot):
    """Restore schedules in a background retry loop; DB outages do not block the bot."""
    retry_delay = 30
    while True:
        try:
            logger.info("Restoring premium notification schedules in background...")
            """Restore schedules once after startup; no periodic expiry scanning."""
            try:
                from database import get_all_users, get_premium_until
                users = get_all_users()
                restored = 0
                for user in users:
                    user_id = user["user_id"]
                    expiry = get_premium_until(user_id)
                    if expiry and expiry > datetime.now():
                        schedule_premium_notifications(bot, user_id, expiry)
                        restored += 1
                logger.info(f"Restored premium notification schedules for {restored} users")
            except Exception as e:
                logger.error(f"Failed to restore premium notification schedules: {e}", exc_info=True)
            
            
            logger.info("Premium notification schedules restored successfully.")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Premium schedule restore unavailable; retrying in %s seconds: %s", retry_delay, exc)
            try:
                await asyncio.sleep(retry_delay)
            except asyncio.CancelledError:
                raise

def start_premium_notification_worker(bot: Bot):
    """Start the one-time startup restore. There is no periodic checker."""
    asyncio.create_task(restore_premium_notification_schedules(bot))
    logger.info("Premium notification scheduler started (event-based; no periodic expiry scan)")
