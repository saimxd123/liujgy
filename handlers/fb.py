



import io
import asyncio
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from telegram import (
    Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup,
    MessageEntity, InputMediaPhoto, InputMediaVideo
)
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.error import BadRequest

from database.db import is_admin, get_all_admins
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E, ButtonEmoji as BE
from ui.buttons import back_close_buttons
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)





FEEDBACK_CHANNEL_ID = -1003970590776


pending_feedbacks = {}

# Telegram sends each item of an album as a separate update. Keep a short-lived
# cache so replying to any item with /fb can forward the complete album.
media_group_cache: Dict[tuple, Dict[int, Dict[str, Any]]] = {}
MEDIA_GROUP_CACHE_SECONDS = 600


def _cache_media_group_message(message) -> None:
    media_group_id = getattr(message, "media_group_id", None)
    if not media_group_id or not message.chat:
        return

    if message.photo:
        item = {
            "type": "photo",
            "file_id": message.photo[-1].file_id,
            "message_id": message.message_id,
            "caption": message.caption or "",
            "caption_entities": message.caption_entities or [],
        }
    elif message.video:
        item = {
            "type": "video",
            "file_id": message.video.file_id,
            "message_id": message.message_id,
            "caption": message.caption or "",
            "caption_entities": message.caption_entities or [],
        }
    else:
        return

    key = (message.chat.id, media_group_id)
    group = media_group_cache.setdefault(key, {})
    group[message.message_id] = item


async def cache_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message:
        _cache_media_group_message(message)


def _cleanup_media_group_cache() -> None:
    # Telegram albums contain at most 10 media items. Keep only the latest
    # 10 entries for each cached group to avoid unbounded memory growth.
    for key, group in list(media_group_cache.items()):
        if len(group) > 10:
            for mid in sorted(group)[:-10]:
                group.pop(mid, None)
        if not group:
            media_group_cache.pop(key, None)


def _get_feedback_media_items(reply) -> List[Dict[str, Any]]:
    """Return the complete cached photo/video album containing reply."""
    media_group_id = getattr(reply, "media_group_id", None)
    if not media_group_id:
        if reply.photo:
            return [{"type": "photo", "file_id": reply.photo[-1].file_id,
                     "message_id": reply.message_id, "caption": reply.caption or "",
                     "caption_entities": reply.caption_entities or []}]
        if reply.video:
            return [{"type": "video", "file_id": reply.video.file_id,
                     "message_id": reply.message_id, "caption": reply.caption or "",
                     "caption_entities": reply.caption_entities or []}]
        return []

    key = (reply.chat.id, media_group_id)
    group = media_group_cache.get(key, {})
    if not group:
        return _get_feedback_media_items_without_group(reply)
    return [group[mid] for mid in sorted(group)]


def _get_feedback_media_items_without_group(reply) -> List[Dict[str, Any]]:
    if reply.photo:
        return [{"type": "photo", "file_id": reply.photo[-1].file_id,
                 "message_id": reply.message_id, "caption": reply.caption or "",
                 "caption_entities": reply.caption_entities or []}]
    if reply.video:
        return [{"type": "video", "file_id": reply.video.file_id,
                 "message_id": reply.message_id, "caption": reply.caption or "",
                 "caption_entities": reply.caption_entities or []}]
    return []


def _media_items_to_input(items: List[Dict[str, Any]], caption: Optional[str] = None):
    media = []
    for index, item in enumerate(items):
        # Keep the feedback caption only on the first album item. This avoids
        # re-parsing user-provided captions as HTML on every media item.
        item_caption = caption if index == 0 and caption else None
        kwargs = {"media": item["file_id"]}
        if item_caption:
            kwargs["caption"] = item_caption
            kwargs["parse_mode"] = "HTML"
        if item["type"] == "video":
            media.append(InputMediaVideo(**kwargs))
        else:
            media.append(InputMediaPhoto(**kwargs))
    return media


def _feedback_caption(message_text: str) -> str:
    return message_text or "--"


def _utf16_to_py_index(text: str, offset: int) -> int:
    """Convert Telegram UTF-16 entity offsets to Python string indices."""
    if offset <= 0:
        return 0
    raw = text.encode("utf-16-le")
    byte_offset = min(offset * 2, len(raw))
    return len(raw[:byte_offset].decode("utf-16-le", errors="ignore"))


def _command_text_and_entities(message) -> tuple[str, List[MessageEntity]]:
    """Extract /fb arguments without losing Telegram custom-emoji entities."""
    source = message.text or ""
    if not source:
        return "", []

    parts = source.split(None, 1)
    if len(parts) == 1:
        return "", []

    command = parts[0]
    text = parts[1]
    base_py = len(command)
    base_utf16 = len(command.encode("utf-16-le")) // 2
    entities = []

    for entity in (message.entities or []):
        if entity.type != "custom_emoji" or not entity.custom_emoji_id:
            continue
        if entity.offset < base_utf16:
            continue
        relative_offset = entity.offset - base_utf16
        py_start = _utf16_to_py_index(text, relative_offset)
        py_end = _utf16_to_py_index(text, relative_offset + entity.length)
        entities.append(MessageEntity(
            type=entity.type,
            offset=relative_offset,
            length=entity.length,
            custom_emoji_id=entity.custom_emoji_id,
        ))

    return text, entities






def detect_premium_emojis_in_text(text: str, entities: List[MessageEntity]) -> tuple:
    """
    Detect premium emojis in text and entities.
    Returns (rich_text, has_premium, premium_emoji_ids)
    where rich_text is the text with <tg-emoji> tags inserted.
    """
    if not text:
        return text, False, []

    if not entities:
        return text, False, []

    premium_emoji_ids = []
    sorted_entities = sorted(entities, key=lambda e: e.offset, reverse=True)
    rich_text = text
    for entity in sorted_entities:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            premium_emoji_ids.append(entity.custom_emoji_id)
            start = _utf16_to_py_index(text, entity.offset)
            end = _utf16_to_py_index(text, entity.offset + entity.length)
            emoji_text = text[start:end]
            tag = f'<tg-emoji emoji-id="{entity.custom_emoji_id}">{emoji_text}</tg-emoji>'
            rich_text = rich_text[:start] + tag + rich_text[end:]

    return rich_text, len(premium_emoji_ids) > 0, premium_emoji_ids


def detect_premium_emojis(message) -> tuple:
    """Detect premium emojis in a message."""
    if not message:
        return "", False, []

    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    return detect_premium_emojis_in_text(text, entities)






def generate_feedback_id() -> str:
    import random
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def get_action_keyboard(feedback_id: str) -> InlineKeyboardMarkup:
    """Action buttons for admins."""
    buttons = [
        [
            InlineKeyboardButton(
                text="Approve",
                callback_data=f"fb_approve_{feedback_id}",
                icon_custom_emoji_id=BE.APPROVED,
                style="success"
            ),
            InlineKeyboardButton(
                text="Reject",
                callback_data=f"fb_reject_{feedback_id}",
                icon_custom_emoji_id=BE.BAN,
                style="danger"
            ),
        ],
        [
            InlineKeyboardButton(
                text="Close",
                callback_data=f"fb_close_{feedback_id}",
                icon_custom_emoji_id=BE.CLOSE_EMOJI,
                style="danger"
            )
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_channel_button() -> InlineKeyboardMarkup:
    """Inline button for channel posts."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="MA̸𝑹K",
                url="https://t.me/OggyPrimeBot",
                icon_custom_emoji_id=BE.HIIT,
                style="primary"
            )
        ]
    ])


async def _edit_admin_message(query, text, parse_mode="HTML", reply_markup=None):
    """
    Edit a callback message safely, handling both text and media messages.
    If the message has a caption (photo/video), use edit_message_caption.
    If it has text, use edit_message_text.
    Otherwise, send a new message and delete the old one.
    """
    if not query.message:
        return

    try:
        if query.message.text is not None:
            await query.edit_message_text(
                text, parse_mode=parse_mode, reply_markup=reply_markup
            )
        elif query.message.caption is not None:
            await query.edit_message_caption(
                caption=text, parse_mode=parse_mode, reply_markup=reply_markup
            )
        else:

            await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            try:
                await query.message.delete()
            except Exception as e:
                logger.warning(f"Could not delete non-editable message: {e}")
    except BadRequest as e:

        if "Message is not modified" in str(e):
            pass
        else:
            raise






@check_lock
@rate_limit("gate")
async def fb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fb - Send feedback with text, photo, video, or full media album."""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    username = user.username or "Unknown"
    msg = update.message

    photo_file_id = None
    media_items: List[Dict[str, Any]] = []
    rich_text = ""
    text = ""
    has_premium = False
    is_media = False

    if context.args:
        text, command_entities = _command_text_and_entities(msg)
        rich_text, has_premium, _ = detect_premium_emojis_in_text(text, command_entities)
    elif msg.reply_to_message:
        reply = msg.reply_to_message
        if reply.text:
            rich_text, has_premium, _ = detect_premium_emojis(reply)
            text = reply.text
        elif reply.photo or reply.video:
            media_items = _get_feedback_media_items(reply)
            is_media = bool(media_items)
            text = reply.caption or ""
            rich_text, has_premium, _ = detect_premium_emojis(reply)
            if media_items:
                photo_file_id = media_items[0]["file_id"] if media_items[0]["type"] == "photo" else None
        else:
            text = reply.text or reply.caption or ""
            rich_text, has_premium, _ = detect_premium_emojis(reply)
    else:
        if msg.text:
            parts = msg.text.split(maxsplit=1)
            text = parts[1] if len(parts) > 1 else ""
            rich_text, has_premium, _ = detect_premium_emojis(msg)
        elif msg.photo or msg.video:
            media_items = _get_feedback_media_items(msg)
            is_media = bool(media_items)
            text = msg.caption or ""
            rich_text, has_premium, _ = detect_premium_emojis(msg)
            if media_items:
                photo_file_id = media_items[0]["file_id"] if media_items[0]["type"] == "photo" else None
        else:
            text = ""
            rich_text = ""

    if not text and not media_items:
        await msg.reply_text(
            f"{E.INFO} <b>Send Feedback</b>\n\n"
            "Usage:\n"
            f"• <code>/fb Your feedback</code>\n"
            f"• Reply to a photo/video with <code>/fb</code>\n"
            f"• Reply to any photo/video in an album with <code>/fb</code>\n"
            f"• Send a photo/video with <code>/fb</code> in caption\n\n"
            "Admins will review it.",
            parse_mode="HTML"
        )
        return

    _cleanup_media_group_cache()
    fid = generate_feedback_id()

    pending_feedbacks[fid] = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "text": text or "--",
        "rich_text": rich_text or text or "--",
        "has_premium": has_premium,
        "is_photo": bool(media_items),
        "is_media": is_media,
        "photo_file_id": photo_file_id,
        "media_items": media_items,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "chat_id": msg.chat.id,
        "message_id": msg.message_id,
    }

    await msg.reply_text(
        f"{E.SUCCESS} <b>Feedback Sent!</b>\n\n"
        f"{E.BOX} <b>ID:</b> <code>{fid}</code>\n"
        f"{E.INFO} Admins will review it shortly.",
        parse_mode="HTML"
    )

    admins = get_all_admins()
    admin_ids = [OWNER_ID]
    for admin in admins:
        if hasattr(admin, 'keys'):
            admin = dict(admin)
        if admin.get('user_id'):
            admin_ids.append(admin['user_id'])
    admin_ids = list(set(admin_ids))

    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a>"
    admin_text = (
        f"{E.USER} <b>User:</b> {user_link}\n"
        f"{E.BOX} <b>UID:</b> <code>{user_id}</code>\n"
        f"{E.NOTE} <b>Message:</b>\n"
        f"{pending_feedbacks[fid]['rich_text']}\n"
    )

    for aid in admin_ids:
        try:
            if media_items:
                album = _media_items_to_input(media_items, admin_text)
                if len(album) == 1:
                    item = media_items[0]
                    if item["type"] == "video":
                        await context.bot.send_video(chat_id=aid, video=item["file_id"], caption=admin_text,
                                                     parse_mode="HTML")
                    else:
                        await context.bot.send_photo(chat_id=aid, photo=item["file_id"], caption=admin_text,
                                                     parse_mode="HTML")
                else:
                    await context.bot.send_media_group(chat_id=aid, media=album)
                    await context.bot.send_message(chat_id=aid, text=admin_text, parse_mode="HTML",
                                                   reply_markup=get_action_keyboard(fid),
                                                   link_preview_options=LinkPreviewOptions(is_disabled=True))
                    continue

                # Telegram media messages can carry the moderation controls directly.
                # Use a separate compact control message so the same code also works
                # for videos and for albums where send_media_group has no reply_markup.
                await context.bot.send_message(
                    chat_id=aid,
                    text=f"{E.INFO} <b>Feedback controls</b>",
                    parse_mode="HTML",
                    reply_markup=get_action_keyboard(fid),
                )
            else:
                await context.bot.send_message(
                    chat_id=aid,
                    text=admin_text,
                    parse_mode="HTML",
                    reply_markup=get_action_keyboard(fid),
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
        except Exception as e:
            # If an album was sent, the separate moderation message is the reliable
            # control surface. For single media, resend a compact control message if
            # adding the keyboard to the media failed.
            logger.error(f"Failed to send feedback to admin {aid}: {e}")
            if media_items:
                try:
                    await context.bot.send_message(
                        chat_id=aid,
                        text=admin_text,
                        parse_mode="HTML",
                        reply_markup=get_action_keyboard(fid),
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
                except Exception as e2:
                    logger.error(f"Failed to send feedback controls to admin {aid}: {e2}")

    logger.info(f"Feedback {fid} from {user_id} ({len(media_items)} media items)")



async def fb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin actions (approve/reject/close)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    first_name = query.from_user.first_name


    if user_id != OWNER_ID and not is_admin(user_id):
        await query.answer("⛔ Only admins can manage feedback", show_alert=True)
        return

    parts = data.split("_")
    if len(parts) < 3:
        return

    action = parts[1]
    fid = parts[2]

    feedback = pending_feedbacks.get(fid)
    if not feedback:
        await query.answer("⏰ Feedback not found or already processed", show_alert=True)
        return

    if feedback.get("status") != "pending":
        await query.answer(f"⚠️ Already {feedback.get('status')}", show_alert=True)
        return

    if action == "close":
        await query.message.delete()
        await query.answer("Closed")
        return


    fb_user_id = feedback["user_id"]
    fb_first = feedback["first_name"]
    fb_username = feedback["username"]
    fb_text = feedback.get("text", "")
    fb_rich_text = feedback.get("rich_text", fb_text)
    is_photo = feedback.get("is_photo", False)
    photo_file_id = feedback.get("photo_file_id")

    if action == "approve":
        feedback["status"] = "approved"


        caption = (
            f"{E.USER} <b>User:</b> {fb_first} (@{fb_username})\n"
            f"{E.BOX} <b>UID:</b> <code>{fb_user_id}</code>\n"
            f"{E.NOTE} <b>Message:</b>\n"
            f"{fb_rich_text}"
        )

        try:
            media_items = feedback.get("media_items") or []
            if media_items:
                if len(media_items) == 1:
                    item = media_items[0]
                    if item["type"] == "video":
                        sent_messages = [await context.bot.send_video(
                            chat_id=FEEDBACK_CHANNEL_ID, video=item["file_id"],
                            caption=caption, parse_mode="HTML"
                        )]
                    else:
                        sent_messages = [await context.bot.send_photo(
                            chat_id=FEEDBACK_CHANNEL_ID, photo=item["file_id"],
                            caption=caption, parse_mode="HTML"
                        )]
                else:
                    sent_messages = await context.bot.send_media_group(
                        chat_id=FEEDBACK_CHANNEL_ID,
                        media=_media_items_to_input(media_items, caption)
                    )

                # Albums cannot have an inline keyboard attached to the whole
                # send_media_group call. Put the button in a compact follow-up
                # message with an upward arrow, so the published album remains intact.
                await context.bot.send_message(
                    chat_id=FEEDBACK_CHANNEL_ID,
                    text="⬆️",
                    reply_markup=get_channel_button()
                )
                sent = sent_messages[0]
            else:
                sent = await context.bot.send_message(
                    chat_id=FEEDBACK_CHANNEL_ID,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=get_channel_button(),
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )


            try:
                await context.bot.pin_chat_message(
                    chat_id=FEEDBACK_CHANNEL_ID,
                    message_id=sent.message_id,
                    disable_notification=False
                )
                logger.info(f"Feedback {fid} pinned in channel")
            except Exception as e:
                logger.warning(f"Could not pin feedback {fid}: {e} (permission issue)")


            await context.bot.send_message(
                chat_id=fb_user_id,
                text=f"{E.APPROVED} <b>Feedback Approved!</b>\n\n"
                     f"{E.BOX} <b>ID:</b> <code>{fid}</code>\n"
                     f"Your feedback has been published.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to forward feedback {fid} to channel: {e}")
            await query.answer("❌ Failed to publish to channel", show_alert=True)
            return


        await _edit_admin_message(
            query,
            f"{E.APPROVED} <b>Feedback Approved</b>\n"
            f"{E.USER} User: {fb_first} (ID: {fb_user_id})\n"
            f"{E.NOTE} Feedback: {fb_text}\n"
            f"Published and pinned.",
            reply_markup=None
        )
        await query.answer("✅ Approved and published!")

    elif action == "reject":
        feedback["status"] = "rejected"


        try:
            await context.bot.send_message(
                chat_id=fb_user_id,
                text=f"{E.DECLINED} <b>Feedback Not Approved</b>\n\n"
                     f"{E.BOX} <b>ID:</b> <code>{fid}</code>\n"
                     f"Your feedback was not approved.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {fb_user_id}: {e}")


        await _edit_admin_message(
            query,
            f"{E.DECLINED} <b>Feedback Rejected</b>\n"
            f"{E.USER} User: {fb_first} (ID: {fb_user_id})\n"
            f"{E.NOTE} Feedback: {fb_text}\n"
            f"Rejected by {first_name}.",
            reply_markup=None
        )
        await query.answer("❌ Rejected")


    for fid, fdata in list(pending_feedbacks.items()):
        if fdata.get("status") != "pending":
            try:
                ts = datetime.fromisoformat(fdata.get("timestamp", ""))
                if (datetime.now() - ts).days > 7:
                    del pending_feedbacks[fid]
            except:
                pass


def register_fb(app):
    """Register feedback handlers."""
    app.add_handler(CommandHandler("fb", fb_command))
    app.add_handler(CallbackQueryHandler(fb_callback, pattern=r"^fb_"))
    logger.info("✅ /fb registered")