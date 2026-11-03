from database.db import is_premium
from config import OWNER_USERNAME, OWNER_NAME
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes
from ui.emojis import PremiumEmoji as E


def get_user_current_tier(user_id: int) -> str:
    """Return 'Premium' or 'Trial'."""
    if is_premium(user_id):
        return "Premium"
    return "Trial"


def _plans_text() -> str:
    return f"""
{E.STAR} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙋𝙇𝘼𝙉𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.CALANDER} <b>2 Days</b>  ➜ <code>$2.00</code>
{E.CALANDER} <b>7 Days</b>  ➜ <code>$7.00</code>
{E.CALANDER} <b>15 Days</b> ➜ <code>$14.00</code>
{E.CALANDER} <b>30 Days</b> ➜ <code>$25.00</code>
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href="https://t.me/{OWNER_USERNAME}">{OWNER_NAME}</a>
"""


def plans_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="💳 Buy Premium",
                url=f"https://t.me/{OWNER_USERNAME}",
            )
        ],
    ])


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium plans and a direct contact button."""
    await update.message.reply_text(
        _plans_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=plans_buttons(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def register_plans(app):
    app.add_handler(CommandHandler(["plan", "plans"], plans_command))
