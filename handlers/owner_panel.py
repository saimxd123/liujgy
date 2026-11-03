"""
Owner Panel — manages:
  - pvt_gc_link (secret charged-card forward GC)
  - public_gc_link
  - log_gc_link
  - public_channel_link
  - required join channels
  - extra API URLs
"""

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database.db import (
    get_bot_setting, set_bot_setting,
    get_required_channels, add_required_channel, remove_required_channel,
    get_extra_api_urls, add_extra_api_url, remove_extra_api_url,
    get_all_api_urls_db,
)
from utils.decorators import owner_only, log_command
from logger import get_logger
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)


# ─── Owner Panel Main ───────────────────────────────────────────────────────

def _owner_panel_text() -> str:
    pvt  = get_bot_setting("pvt_gc_link") or "❌ Not set"
    pub  = get_bot_setting("public_gc_link") or "❌ Not set"
    logs = get_bot_setting("log_gc_link") or "❌ Not set"
    chan = get_bot_setting("public_channel_link") or "❌ Not set"
    apis = get_all_api_urls_db()
    req  = get_required_channels()

    api_list  = "\n".join(f"  {i+1}. <code>{u}</code>" for i, u in enumerate(apis))
    req_list  = "\n".join(f"  {i+1}. {c['title']} (@{c['username']})" for i, c in enumerate(req)) or "  None"

    return f"""
{E.SHIELD} <b>𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 — 𝑶𝑾𝑵𝑬𝑹 𝑷𝑨𝑵𝑬𝑳</b>
━━━━━━━━━━━━━━━━━━

🔒 <b>Pvt GC (Charged Fwd)</b> ↬ <code>{pvt}</code>
👥 <b>Public GC</b>           ↬ <code>{pub}</code>
📋 <b>Log GC</b>              ↬ <code>{logs}</code>
📢 <b>Public Channel</b>      ↬ <code>{chan}</code>

━━━━━━━━━━━━━━━━━━
🔑 <b>Required Join Channels:</b>
{req_list}

━━━━━━━━━━━━━━━━━━
🌐 <b>API URLs:</b>
{api_list}

━━━━━━━━━━━━━━━━━━
<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


def _owner_panel_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔒 Set Pvt GC",      callback_data="op_setlink:pvt_gc_link",      style="danger"),
            InlineKeyboardButton("👥 Set Public GC",   callback_data="op_setlink:public_gc_link",   style="primary"),
        ],
        [
            InlineKeyboardButton("📋 Set Log GC",      callback_data="op_setlink:log_gc_link",      style="primary"),
            InlineKeyboardButton("📢 Set Channel",     callback_data="op_setlink:public_channel_link", style="primary"),
        ],
        [
            InlineKeyboardButton("➕ Add Req Channel", callback_data="op_addreqch",  style="success"),
            InlineKeyboardButton("➖ Rm Req Channel",  callback_data="op_rmreqch",   style="danger"),
        ],
        [
            InlineKeyboardButton("🌐 Add API URL",     callback_data="op_addapi",    style="success"),
            InlineKeyboardButton("🗑 Remove API URL",  callback_data="op_rmapi",     style="danger"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh",         callback_data="op_refresh",   style="primary"),
            InlineKeyboardButton("✖ Close",            callback_data="op_close",     style="danger"),
        ],
    ])


@owner_only
@log_command
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show owner panel: /opanel"""
    await update.message.reply_text(
        _owner_panel_text(),
        parse_mode="HTML",
        reply_markup=_owner_panel_buttons(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ─── Callbacks ──────────────────────────────────────────────────────────────

LINK_LABELS = {
    "pvt_gc_link":        "🔒 Private GC (charged card forward)",
    "public_gc_link":     "👥 Public GC",
    "log_gc_link":        "📋 Log GC",
    "public_channel_link":"📢 Public Channel",
}

# We store pending operations in context.user_data
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != OWNER_ID:
        await query.answer("Owner only.", show_alert=True)
        return

    data = query.data

    if data == "op_refresh":
        await query.edit_message_text(
            _owner_panel_text(), parse_mode="HTML",
            reply_markup=_owner_panel_buttons(),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer("Refreshed.")

    elif data == "op_close":
        await query.message.delete()
        await query.answer()

    elif data.startswith("op_setlink:"):
        key = data.split(":", 1)[1]
        label = LINK_LABELS.get(key, key)
        context.user_data["op_pending"] = {"action": "setlink", "key": key}
        await query.edit_message_text(
            f"🔗 <b>Send the link for:</b> <i>{label}</i>\n\n"
            f"Send the full Telegram link (e.g. <code>https://t.me/+xxxx</code>)\n"
            f"Send /cancel to abort.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer()

    elif data == "op_addapi":
        context.user_data["op_pending"] = {"action": "addapi"}
        await query.edit_message_text(
            "🌐 <b>Send the new API base URL to add:</b>\n"
            "Example: <code>https://check2.yzio.app</code>\n"
            "Usage stays the same: <code>/shopify?site=...&cc=...&proxy=...</code>\n"
            "Send /cancel to abort.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer()

    elif data == "op_rmapi":
        urls = get_all_api_urls_db()
        if len(urls) <= 1:
            await query.answer("Only the primary API URL is set — nothing extra to remove.", show_alert=True)
            return
        extras = get_extra_api_urls()
        btns = [[InlineKeyboardButton(f"🗑 {u[:40]}", callback_data=f"op_rmapi_confirm:{u[:80]}", style="danger")] for u in extras]
        btns.append([InlineKeyboardButton("✖ Cancel", callback_data="op_refresh", style="primary")])
        await query.edit_message_text(
            "🗑 <b>Select API URL to remove:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(btns),
        )
        await query.answer()

    elif data.startswith("op_rmapi_confirm:"):
        url = data.split(":", 1)[1]
        remove_extra_api_url(url)
        await query.edit_message_text(
            _owner_panel_text(), parse_mode="HTML",
            reply_markup=_owner_panel_buttons(),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer(f"Removed: {url[:30]}", show_alert=True)

    elif data == "op_addreqch":
        context.user_data["op_pending"] = {"action": "addreqch"}
        await query.edit_message_text(
            "➕ <b>Add Required Join Channel</b>\n\n"
            "Send in format: <code>chat_id|@username|Title</code>\n"
            "Example: <code>-1001234567890|mychannel|My Channel</code>\n"
            "Send /cancel to abort.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer()

    elif data == "op_rmreqch":
        channels = get_required_channels()
        if not channels:
            await query.answer("No required channels configured.", show_alert=True)
            return
        btns = [[InlineKeyboardButton(f"🗑 {c['title']}", callback_data=f"op_rmreqch_confirm:{c['chat_id']}", style="danger")] for c in channels]
        btns.append([InlineKeyboardButton("✖ Cancel", callback_data="op_refresh", style="primary")])
        await query.edit_message_text(
            "🗑 <b>Select channel to remove:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(btns),
        )
        await query.answer()

    elif data.startswith("op_rmreqch_confirm:"):
        chat_id = int(data.split(":", 1)[1])
        remove_required_channel(chat_id)
        await query.edit_message_text(
            _owner_panel_text(), parse_mode="HTML",
            reply_markup=_owner_panel_buttons(),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await query.answer("Channel removed.", show_alert=True)


async def owner_panel_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for pending owner operations."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        return
    pending = context.user_data.get("op_pending")
    if not pending:
        return

    text = update.message.text.strip()
    if text == "/cancel":
        context.user_data.pop("op_pending", None)
        await update.message.reply_text("❌ Cancelled.", parse_mode="HTML")
        return

    action = pending["action"]

    if action == "setlink":
        key = pending["key"]
        set_bot_setting(key, text)
        context.user_data.pop("op_pending", None)
        label = LINK_LABELS.get(key, key)
        await update.message.reply_text(
            f"✅ <b>{label}</b> set to:\n<code>{text}</code>",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    elif action == "addapi":
        if not text.startswith("http"):
            await update.message.reply_text("❌ URL must start with http/https.", parse_mode="HTML")
            return
        ok = add_extra_api_url(text)
        context.user_data.pop("op_pending", None)
        if ok:
            await update.message.reply_text(f"✅ API URL added:\n<code>{text}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("⚠️ URL already exists.", parse_mode="HTML")

    elif action == "addreqch":
        try:
            parts = text.split("|")
            if len(parts) < 3:
                raise ValueError
            chat_id = int(parts[0].strip())
            username = parts[1].strip().lstrip("@")
            title = parts[2].strip()
            add_required_channel(chat_id, username, title)
            context.user_data.pop("op_pending", None)
            await update.message.reply_text(
                f"✅ Required channel added:\n<b>{title}</b> (@{username})",
                parse_mode="HTML"
            )
        except Exception:
            await update.message.reply_text(
                "❌ Invalid format. Use: <code>chat_id|@username|Title</code>",
                parse_mode="HTML"
            )


def register_owner_panel(app: Application):
    from telegram.ext import MessageHandler, filters
    app.add_handler(CommandHandler("opanel", owner_panel))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern=r"^op_"))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.User(OWNER_ID) & ~filters.COMMAND,
        owner_panel_message_handler
    ), group=10)
    logger.info("Owner panel handlers registered.")
