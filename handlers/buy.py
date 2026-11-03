from telegram import Update, LinkPreviewOptions
from telegram.ext import CommandHandler, ContextTypes
from config import OWNER_USERNAME, OWNER_NAME
from ui.emojis import PremiumEmoji as E


async def handle_buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"""
{E.INFO} ⌠ 𝘽𝙐𝙔 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 ⌡
━━━━━━━━━━━━━━━━━━
To purchase premium, contact the owner directly:

<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
━━━━━━━━━━━━━━━━━━
""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def register_buy(app):
    app.add_handler(CommandHandler("buy", handle_buy_command))
