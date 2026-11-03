

from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID
from logger import get_logger
from database.db import is_banned, is_admin, is_premium

logger = get_logger(__name__)






def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id != OWNER_ID:
            logger.warning(f"Owner denied -> {user.id}")
            await update.effective_message.reply_text("❌ Owner only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper






def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id == OWNER_ID:
            return await func(update, context, *args, **kwargs)
        if not is_admin(user.id):
            logger.warning(f"Admin denied -> {user.id}")
            await update.effective_message.reply_text("❌ Admin only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper






def premium_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not is_premium(user.id):
            logger.info(f"Premium denied -> {user.id}")
            await update.effective_message.reply_text("👑 Premium required.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper






def not_banned(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if is_banned(user.id):
            logger.warning(f"Banned user blocked -> {user.id}")
            await update.effective_message.reply_text("🚫 You are banned.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper






def log_command(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        logger.info(f"{func.__name__} | {user.id} | @{user.username}")
        return await func(update, context, *args, **kwargs)
    return wrapper