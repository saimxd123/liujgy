

import time
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from database.db import is_premium
from logger import get_logger

logger = get_logger(__name__)


FREE_COOLDOWN = 10
PREMIUM_COOLDOWN = 5


_last_command_time = {}


def rate_limit(command_type: str = "gate"):
    """
    Rate limit decorator.
    
    Args:
        command_type: 'gate' (10s cooldown for free) or 'mass' (blocked for free)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            user_id = user.id


            premium = is_premium(user_id)


            if command_type == "mass" and not premium:
                await update.message.reply_text(
               "Level Up Required " 
               "Activate premium to unlock this feature."
                )
                return


            if not premium and command_type != "mass":
                current_time = time.time()
                key = f"{user_id}:{func.__name__}"

                if key in _last_command_time:
                    elapsed = current_time - _last_command_time[key]
                    if elapsed < FREE_COOLDOWN:
                        remaining = int(FREE_COOLDOWN - elapsed)
                        await update.message.reply_text(
                            f"⏳ <b>Please wait {remaining} seconds</b>\n\n"
                            f"Free users have a {FREE_COOLDOWN}s cooldown.\n"
                            f"Upgrade to premium for unlimited access."
                        )
                        return

                _last_command_time[key] = current_time

            logger.info(f"{func.__name__} | {user_id} | Premium: {premium}")

            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


def clear_rate_limit(user_id: int = None):
    """Clear rate limit for a user (e.g., when they upgrade to premium)."""
    global _last_command_time
    if user_id:
        keys_to_remove = [k for k in _last_command_time.keys() if k.startswith(f"{user_id}:")]
        for k in keys_to_remove:
            del _last_command_time[k]
    else:
        _last_command_time.clear()
