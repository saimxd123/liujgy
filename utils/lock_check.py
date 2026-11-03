

from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from database.db import is_bot_locked
from config import OWNER_ID
from logger import get_logger

logger = get_logger(__name__)


def check_lock(func):
    """Decorator to check if bot is locked before executing command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        if not update.effective_user:
            return await func(update, context, *args, **kwargs)
        
        user_id = update.effective_user.id
        

        if user_id == OWNER_ID:
            return await func(update, context, *args, **kwargs)
        

        if update.message and update.message.text:
            text = update.message.text
            if text.startswith("/lock") or text.startswith("/unlock"):
                return await func(update, context, *args, **kwargs)
        

        if is_bot_locked():
            if update.message:
                await update.message.reply_text(
                    f"""<b>🔒 Bot is in Lock Mode</b>

Bot is currently under maintenance by the owner.

Please wait until it's unlocked.

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/oggyproo'>𝑶𝑮𝑮𝒀</a>""",
                    parse_mode="HTML"
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "🔒 Bot is locked. Try again later.",
                    show_alert=True
                )
            return
        
        return await func(update, context, *args, **kwargs)
    return wrapper