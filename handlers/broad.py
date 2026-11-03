

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, Application
from telegram.error import Forbidden, BadRequest, RetryAfter, TimedOut

from database.db import get_all_users, get_all_groups, is_admin
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from logger import get_logger
from ui.emojis import PremiumEmoji as E, ButtonEmoji as BE
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock

logger = get_logger(__name__)





SLEEP_TIME = 0.09
PROGRESS_EVERY = 10
MAX_RETRIES = 3


broadcast_tasks: Dict[str, asyncio.Task] = {}
broadcast_data: Dict[str, dict] = {}
broadcast_messages: Dict[str, dict] = {}






def detect_premium_emojis_in_text(text: str, entities: List) -> tuple:
    """
    Detect premium emojis in text and entities.
    Returns (clean_text, has_premium, premium_emoji_ids)
    """
    if not text:
        return text, False, []
    
    if not entities:
        return text, False, []
    
    premium_emoji_ids = []
    
    sorted_entities = sorted(entities, key=lambda e: e.offset, reverse=True)
    
    for entity in sorted_entities:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            premium_emoji_ids.append(entity.custom_emoji_id)
    
    return text, len(premium_emoji_ids) > 0, premium_emoji_ids


def detect_premium_emojis(message) -> tuple:
    """Detect premium emojis in a message."""
    if not message:
        return None, False, []
    
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    
    return detect_premium_emojis_in_text(text, entities)






def extract_reply_markup(message) -> Optional[InlineKeyboardMarkup]:
    """Extract inline keyboard markup from a message."""
    if not message:
        return None
    
    if hasattr(message, 'reply_markup') and message.reply_markup:
        return message.reply_markup
    

    if hasattr(message, 'reply_markup'):
        return message.reply_markup
    
    return None






def get_broadcast_buttons(broadcast_id: str, is_running: bool = False) -> InlineKeyboardMarkup:
    """Get styled buttons for broadcast control."""
    if is_running:

        buttons = [
            [
                InlineKeyboardButton(
                    text="Stop Broadcast",
                    callback_data=f"broad_stop_{broadcast_id}",
                    style="danger",
                    icon_custom_emoji_id=BE.CLOSE_EMOJI
                ),
            ]
        ]
    else:

        buttons = [
            [
                InlineKeyboardButton(
                    text="Yes (With Sound)",
                    callback_data=f"broad_notify_yes_{broadcast_id}",
                    style="success",
                    icon_custom_emoji_id=BE.APPROVED
                ),
                InlineKeyboardButton(
                    text="No (Silent)",
                    callback_data=f"broad_notify_no_{broadcast_id}",
                    style="danger",
                    icon_custom_emoji_id=BE.BAN
                ),
            ]
        ]
    
    return InlineKeyboardMarkup(buttons)






async def broadcast_worker(
    bot,
    status_msg,
    user_ids: List[int],
    reply_to_message: Optional[Any] = None,
    message_text: str = None,
    parse_mode: str = None,
    disable_notification: bool = False,
    has_premium: bool = False,
    broadcast_id: str = None,
    chat_id: int = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
):
    """Background worker for broadcasting messages with buttons."""
    sent = 0
    failed = 0
    blocked = 0
    errors = 0
    total = len(user_ids)
    last_update = 0
    failed_users = []
    blocked_users = []
    pinned_messages = []
    
    start_time = datetime.now()
    

    use_copy = reply_to_message is not None
    
    for index, user_id in enumerate(user_ids, start=1):
        retries = 0
        success = False
        sent_message = None
        
        while retries < MAX_RETRIES and not success:
            try:
                if use_copy and reply_to_message:

                    sent_message = await reply_to_message.copy(
                        chat_id=user_id,
                        parse_mode=parse_mode,
                        disable_notification=disable_notification,
                        reply_markup=reply_markup,
                    )
                else:

                    sent_message = await bot.send_message(
                        chat_id=user_id,
                        text=message_text or "",
                        parse_mode=parse_mode,
                        disable_notification=disable_notification,
                        reply_markup=reply_markup,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
                
                sent += 1
                success = True
                

                try:
                    if sent_message:
                        await bot.pin_chat_message(
                            chat_id=user_id,
                            message_id=sent_message.message_id,
                            disable_notification=disable_notification,
                        )
                        pinned_messages.append(user_id)
                except Exception as e:
                    logger.debug(f"Could not pin message for {user_id}: {e}")
                
            except Forbidden:
                blocked += 1
                blocked_users.append(user_id)
                success = True
            except RetryAfter as e:
                retry_after = e.retry_after
                logger.warning(f"Flood wait {retry_after}s for {user_id}")
                await asyncio.sleep(min(retry_after + 1, 60))
                retries += 1
            except (TimedOut, BadRequest) as e:
                logger.warning(f"Error sending to {user_id}: {e}")
                retries += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Unexpected error for {user_id}: {e}")
                errors += 1
                failed_users.append(user_id)
                success = True
            
            if not success:
                errors += 1
                failed_users.append(user_id)
        
        await asyncio.sleep(SLEEP_TIME)
        

        if index - last_update >= PROGRESS_EVERY or index == total:
            last_update = index
            elapsed = (datetime.now() - start_time).seconds
            

            stop_buttons = get_broadcast_buttons(broadcast_id, is_running=True)
            
            try:
                await status_msg.edit_text(
                    f"""
{E.FLY} <b>Broadcasting...</b>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Total</b>       ↬ <code>{total}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Sent</b>        ↬ <code>{sent}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Blocked</b>     ↬ <code>{blocked}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Errors</b>      ↬ <code>{errors}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Pinned</b>      ↬ <code>{len(pinned_messages)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Progress</b>    ↬ <code>{index}/{total}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Time</b>        ↬ <code>{elapsed}s</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    reply_markup=stop_buttons,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception:
                pass
    

    elapsed = (datetime.now() - start_time).seconds
    elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"
    
    notification_status = "🔇 Silent" if disable_notification else "🔔 With Sound"
    pin_status = "📌 Pinned" if len(pinned_messages) > 0 else "❌ Not Pinned"
    button_status = "✅ Yes" if reply_markup else "❌ No"
    
    summary = f"""
{E.SUCCESS} <b>Broadcast Completed!</b>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Total</b>        ↬ <code>{total}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>✅ Sent</b>        ↬ <code>{sent}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>🚫 Blocked</b>     ↬ <code>{blocked}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>⚠️ Errors</b>      ↬ <code>{errors}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>📌 Pinned</b>      ↬ <code>{len(pinned_messages)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>📊 Success Rate</b> ↬ <code>{((sent / total) * 100):.1f}%</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>⏱️ Time</b>        ↬ <code>{elapsed_str}</code>
━━━━━━━━━━━━━━━━━━
{'📨 <b>Method</b> ↬ Copy' if use_copy else '📝 <b>Method</b> ↬ Text'}
{'✨ <b>Premium Emojis</b> ↬ ' + ('✅ Detected' if has_premium else '❌ Not detected')}
{'🔔 <b>Notifications</b> ↬ ' + notification_status}
{'📌 <b>Pin Status</b> ↬ ' + pin_status}
{'🔘 <b>Buttons</b> ↬ ' + button_status}

{'🚫 <b>Blocked Users</b> ↬ ' + str(blocked_users[:5]) + ('...' if len(blocked_users) > 5 else '') if blocked_users else ''}
{'⚠️ <b>Failed Users</b> ↬ ' + str(failed_users[:5]) + ('...' if len(failed_users) > 5 else '') if failed_users else ''}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    
    try:
        await status_msg.edit_text(
            summary,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    except Exception as e:
        logger.error(f"Failed to update final status: {e}")
    
    logger.info(f"Broadcast completed: {sent}/{total} sent, {blocked} blocked, {errors} errors, {len(pinned_messages)} pinned in {elapsed_str}")
    

    if broadcast_id and broadcast_id in broadcast_data:
        del broadcast_data[broadcast_id]
    if broadcast_id and broadcast_id in broadcast_messages:
        del broadcast_messages[broadcast_id]
    if chat_id and chat_id in broadcast_tasks:
        del broadcast_tasks[chat_id]






@check_lock
@admin_only
@log_command
async def broad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Broadcast message to all users and groups.
    Detects premium emojis and preserves inline buttons.
    Shows styled buttons for notification choice.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id
    

    if chat_id in broadcast_tasks and not broadcast_tasks[chat_id].done():
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙍𝙐𝙉𝙉𝙄𝙉𝙂 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} A broadcast is already running.

Use the stop button below to stop it.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    reply_to_message = None
    message_text = None
    has_premium = False
    clean_text = None
    reply_markup = None
    

    if update.message.reply_to_message:
        reply_to_message = update.message.reply_to_message
        clean_text, has_premium, _ = detect_premium_emojis(reply_to_message)
        if not clean_text:
            clean_text = reply_to_message.text or reply_to_message.caption or ""
        

        reply_markup = extract_reply_markup(reply_to_message)
        if reply_markup:
            logger.info(f"📋 Found inline buttons in reply message")
    

    if context.args:
        message_text = " ".join(context.args)
        clean_text = message_text
        _, has_premium, _ = detect_premium_emojis(update.message)
    

    if not reply_to_message and not message_text:
        await update.message.reply_text(
            f"""
{E.INFO} ⌠ 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙐𝙎𝘼𝙂𝙀 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>

<b>📨 REPLY TO A MESSAGE:</b>
<code>/broad</code> (reply to any message)
• Hides sender name (looks like bot sent it)
• Premium emojis will be detected
• <b>Inline buttons will be preserved!</b>

<b>📝 SEND TEXT:</b>
<code>/broad &lt;message&gt;</code>
<b>Example:</b>
<code>/broad Hello everyone! 👋</code>

<b>Note:</b> Premium emojis will be detected
and preserved as normal emojis.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    try:
        users = get_all_users()
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        users = []
    

    user_ids = []
    
    for u in users:
        if not u:
            continue
        
        if isinstance(u, dict):
            if 'user_id' in u:
                user_ids.append(u['user_id'])
            elif 'id' in u:
                user_ids.append(u['id'])
        elif isinstance(u, (tuple, list)):
            if len(u) > 0:
                try:
                    user_ids.append(int(u[0]))
                except (ValueError, TypeError):
                    pass
        elif hasattr(u, 'keys'):
            try:
                row_dict = dict(u)
                if 'user_id' in row_dict:
                    user_ids.append(row_dict['user_id'])
                elif 'id' in row_dict:
                    user_ids.append(row_dict['id'])
            except:
                pass
        elif isinstance(u, int):
            user_ids.append(u)
    
    user_ids = list(set([uid for uid in user_ids if isinstance(uid, int) and uid > 0]))
    
    if not user_ids:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙉𝙊 𝙍𝙀𝘾𝙄𝙋𝙄𝙀𝙉𝙏𝙎 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
📝 No users found in database.

👥 Users in DB: <code>{len(users)}</code>

<b>Solution:</b>
Users need to use <code>/start</code> to be added.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    broadcast_id = f"broad_{chat_id}_{int(datetime.now().timestamp())}"
    
    broadcast_data[broadcast_id] = {
        "user_ids": user_ids,
        "reply_to_message": reply_to_message,
        "message_text": message_text,
        "has_premium": has_premium,
        "html_content": clean_text,
        "user_ids_count": len(user_ids),
        "chat_id": chat_id,
        "reply_markup": reply_markup,
    }
    

    preview_text = message_text or "📨 [Replying to a message]"
    if len(preview_text) > 100:
        preview_text = preview_text[:100] + "..."
    
    button_status = "✅ Yes" if reply_markup else "❌ No"
    
    buttons = get_broadcast_buttons(broadcast_id, is_running=False)
    
    await update.message.reply_text(
        f"""
{E.INFO} ⌠ 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙋𝙍𝙀𝙑𝙄𝙀𝙒 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Recipients</b>   ↬ <code>{len(user_ids)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Premium</b>      ↬ {'✅ Detected' if has_premium else '❌ Not detected'}
<a href='https://t.me/oggyproo'>⊀</a> <b>Buttons</b>      ↬ {button_status}
<a href='https://t.me/oggyproo'>⊀</a> <b>Message</b>       ↬ <code>{preview_text}</code>
━━━━━━━━━━━━━━━━━━
<b>Choose notification preference:</b>

✅ <b>Yes</b> - Users will hear sound/vibration
🔴 <b>No</b>  - Silent broadcast (no sound)

<i>Click a button to start broadcasting.</i>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        reply_markup=buttons,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )






async def broadcast_notification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle notification toggle for broadcast."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    



    if data.startswith("broad_stop_"):
        broadcast_id = data.replace("broad_stop_", "")
        

        if chat_id in broadcast_tasks:
            task = broadcast_tasks[chat_id]
            if not task.done():
                task.cancel()
                

                await query.edit_message_text(
                    f"""
{E.SUCCESS} ⌠ 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙎𝙏𝙊𝙋𝙋𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Broadcast has been stopped.

Use /broad to start a new one.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                

                if chat_id in broadcast_tasks:
                    del broadcast_tasks[chat_id]
                if broadcast_id in broadcast_data:
                    del broadcast_data[broadcast_id]
                if broadcast_id in broadcast_messages:
                    del broadcast_messages[broadcast_id]
            else:
                await query.edit_message_text(
                    f"{E.INFO} Broadcast already completed.",
                    parse_mode="HTML"
                )

                if chat_id in broadcast_tasks:
                    del broadcast_tasks[chat_id]
                if broadcast_id in broadcast_data:
                    del broadcast_data[broadcast_id]
                if broadcast_id in broadcast_messages:
                    del broadcast_messages[broadcast_id]
        else:
            await query.edit_message_text(
                f"""
{E.INFO} ⌠ 𝙉𝙊 𝘼𝘾𝙏𝙄𝙑𝙀 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} No active broadcast to stop.

The broadcast may have already completed.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )

            if broadcast_id in broadcast_data:
                del broadcast_data[broadcast_id]
            if broadcast_id in broadcast_messages:
                del broadcast_messages[broadcast_id]
        return
    



    parts = data.split("_")
    
    if len(parts) < 4:
        await query.edit_message_text(
            f"{E.ERROR} Invalid broadcast data.",
            parse_mode="HTML"
        )
        return
    
    notification_type = parts[2]
    broadcast_id = "_".join(parts[3:])
    

    b_data = broadcast_data.get(broadcast_id)
    if not b_data:
        await query.edit_message_text(
            f"""
{E.ERROR} ⌠ 𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝘿𝘼𝙏𝘼 𝙀𝙓𝙋𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Broadcast session expired.

Please use <code>/broad</code> again.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    disable_notification = notification_type == "no"
    notification_text = "🔇 Silent (No Sound)" if disable_notification else "🔔 Enabled (With Sound)"
    



    stop_buttons = get_broadcast_buttons(broadcast_id, is_running=True)
    

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"""
{E.FLY} <b>Broadcasting...</b>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Recipients</b>   ↬ <code>{b_data['user_ids_count']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Premium</b>      ↬ {'✅ Detected' if b_data['has_premium'] else '❌ Not detected'}
<a href='https://t.me/oggyproo'>⊀</a> <b>Buttons</b>      ↬ {'✅ Yes' if b_data.get('reply_markup') else '❌ No'}
<a href='https://t.me/oggyproo'>⊀</a> <b>Notifications</b> ↬ {notification_text}
━━━━━━━━━━━━━━━━━━
<i>Broadcasting in background...</i>
<i>Use the stop button below to cancel.</i>

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        reply_markup=stop_buttons,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    

    broadcast_messages[broadcast_id] = {
        "status_msg": status_msg,
        "chat_id": chat_id,
    }
    



    task = asyncio.create_task(
        broadcast_worker(
            bot=context.bot,
            status_msg=status_msg,
            user_ids=b_data['user_ids'],
            reply_to_message=b_data['reply_to_message'],
            message_text=b_data['html_content'] or b_data['message_text'],
            parse_mode=None,
            disable_notification=disable_notification,
            has_premium=b_data['has_premium'],
            broadcast_id=broadcast_id,
            chat_id=chat_id,
            reply_markup=b_data.get('reply_markup'),
        )
    )
    

    broadcast_tasks[chat_id] = task
    

    def cleanup_task(task):
        if chat_id in broadcast_tasks:
            del broadcast_tasks[chat_id]
        if broadcast_id in broadcast_data:
            del broadcast_data[broadcast_id]
        if broadcast_id in broadcast_messages:
            del broadcast_messages[broadcast_id]
    
    task.add_done_callback(cleanup_task)






def register_broad(app: Application):
    """Register broadcast command handlers."""
    app.add_handler(CommandHandler("broad", broad))
    app.add_handler(CallbackQueryHandler(broadcast_notification_callback, pattern=r"^broad_(notify_yes|notify_no|stop)_"))
    logger.info("✅ Broadcast handlers registered.")