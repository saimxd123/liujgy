

from functools import wraps
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)
from telegram.ext import ContextTypes

from database.db import is_banned
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID


logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)






GROUP_ID = -1003961477688
GROUP_USERNAME = "+Y1hpddJIEPw1ZGVl"

CHANNEL_ID = -1004311992962
CHANNEL_USERNAME = "oggyproo"

LOGS_CHAT_ID = -1003970590776
LOGS_CHAT_USERNAME = "OGGYxLOGS"

def _get_required_channels_dynamic():
    """Get owner-configured required channels from DB."""
    try:
        from database.db import get_required_channels
        return get_required_channels()
    except Exception:
        return []

FORCE_JOIN_IMAGE = "OGGY.jpg"






class ButtonEmoji:
    GROUP = "6043995137049104461"
    CHANNEL = "6044184811394831904"
    CHECK = "6044262726396546853"
    LOGS = "6044260346984665434"






async def safe_get_member(bot, chat_id: int, user_id: int):
    """Return Telegram membership status safely."""

    if user_id == OWNER_ID:
        logger.debug("Owner %s bypassing join check", user_id)
        return "creator"

    try:
        member = await bot.get_chat_member(chat_id, user_id)

        logger.debug(
            "User %s in %s: %s",
            user_id,
            chat_id,
            member.status,
        )

        return member.status

    except Exception as exc:
        logger.warning(
            "Failed to get member %s in %s: %s",
            user_id,
            chat_id,
            exc,
        )
        return None


async def is_user_joined(bot, user_id: int) -> bool:
    """
    Check whether the user is a member of:
    - group
    - channel
    - logs chat
    """

    if user_id == OWNER_ID:
        return True

    valid_statuses = (
        "member",
        "administrator",
        "creator",
    )


    group_status = await safe_get_member(
        bot,
        GROUP_ID,
        user_id,
    )

    if group_status not in valid_statuses:
        logger.warning(
            "User %s NOT in group (%s)",
            user_id,
            group_status,
        )
        return False


    channel_status = await safe_get_member(
        bot,
        CHANNEL_ID,
        user_id,
    )

    if channel_status not in valid_statuses:
        logger.warning(
            "User %s NOT in channel (%s)",
            user_id,
            channel_status,
        )
        return False


    logs_status = await safe_get_member(
        bot,
        LOGS_CHAT_ID,
        user_id,
    )

    if logs_status not in valid_statuses:
        logger.warning(
            "User %s NOT in logs chat (%s)",
            user_id,
            logs_status,
        )
        return False

    # Check owner-added required channels
    for ch in _get_required_channels_dynamic():
        ch_status = await safe_get_member(bot, ch["chat_id"], user_id)
        if ch_status not in valid_statuses:
            logger.warning("User %s NOT in required channel %s (%s)", user_id, ch["title"], ch_status)
            return False

    logger.info("User %s is in group, channel & logs chat", user_id)
    return True






def get_force_join_buttons():
    """Create force-join inline keyboard."""

    buttons = [
        [
            InlineKeyboardButton(
                text="Join Group",
                url=f"https://t.me/{GROUP_USERNAME}",
                style="primary",
                icon_custom_emoji_id=ButtonEmoji.GROUP,
            ),
            InlineKeyboardButton(
                text="Join Channel",
                url=f"https://t.me/{CHANNEL_USERNAME}",
                style="primary",
                icon_custom_emoji_id=ButtonEmoji.CHANNEL,
            ),
        ],
        [
            InlineKeyboardButton(
                text="Join Logs Chat",
                url=f"https://t.me/{LOGS_CHAT_USERNAME}",
                style="primary",
                icon_custom_emoji_id=ButtonEmoji.LOGS,
            ),
        ],
    ]

    # Add owner-configured required channels
    for ch in _get_required_channels_dynamic():
        uname = ch.get("username", "")
        title = ch.get("title", "Join Channel")
        if uname:
            url = f"https://t.me/{uname}" if not uname.startswith("+") else f"https://t.me/{uname}"
            buttons.append([
                InlineKeyboardButton(
                    text=f"Join {title}",
                    url=url,
                    style="primary",
                    icon_custom_emoji_id=ButtonEmoji.CHANNEL,
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text="I have joined",
            callback_data="check_joined",
            style="success",
            icon_custom_emoji_id=ButtonEmoji.CHECK,
        ),
    ])

    return InlineKeyboardMarkup(buttons)






def force_join(func):

    @wraps(func)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args,
        **kwargs,
    ):
        user = update.effective_user

        if not user:
            logger.warning("Force join called without effective user")
            return

        user_id = user.id





        try:
            banned = is_banned(user_id)
        except Exception as exc:
            logger.error(
                "Failed to check ban status for %s: %s",
                user_id,
                exc,
            )
            banned = False

        if banned:
            logger.warning(
                "Banned user blocked: %s",
                user_id,
            )

            banned_text = f"""
<blockquote><b>🚫 You Are Banned</b></blockquote>

You have been banned from using this bot.

If you believe this is a mistake, please contact support:

<b>Dev</b> ➠ <a href="https://t.me/{OWNER_USERNAME}">{OWNER_NAME}</a>
"""

            message = update.effective_message

            if message:
                try:
                    await message.reply_text(
                        banned_text,
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(
                            is_disabled=True
                        ),
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not send banned message to %s: %s",
                        user_id,
                        exc,
                    )

            return





        if user_id == OWNER_ID:
            return await func(
                update,
                context,
                *args,
                **kwargs,
            )





        message = update.effective_message

        is_start_command = (
            message is not None
            and bool(message.text)
            and message.text.startswith("/start")
        )

        if is_start_command:

            joined = await is_user_joined(
                context.bot,
                user_id,
            )

            if not joined:

                caption_text = (
                    "❌ <b>Unlock access to the bot by joining</b>\n"
                    "our channel, group, and logs chat 👇\n\n"
                    "🔒 <b>All features are restricted.</b>\n"
                    "✅ <b>Join all to unlock.</b>\n\n"
                    f"<b>Dev</b> ➠ "
                    f"<a href='https://t.me/{OWNER_USERNAME}'>"
                    f"{OWNER_NAME}</a>"
                )

                if not message:
                    return





                try:
                    await message.reply_photo(
                        photo=FORCE_JOIN_IMAGE,
                        caption=caption_text,
                        parse_mode="HTML",
                        reply_markup=get_force_join_buttons(),
                    )

                except Exception as exc:
                    logger.error(
                        "Failed to send force join image to %s: %s",
                        user_id,
                        exc,
                    )





                    try:
                        await message.reply_text(
                            caption_text,
                            parse_mode="HTML",
                            reply_markup=get_force_join_buttons(),
                            link_preview_options=LinkPreviewOptions(
                                is_disabled=True
                            ),
                        )

                    except Exception as fallback_exc:
                        logger.warning(
                            "Failed to send force join fallback to %s: %s",
                            user_id,
                            fallback_exc,
                        )

                return





        return await func(
            update,
            context,
            *args,
            **kwargs,
        )

    return wrapper






async def check_joined_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle the 'I have joined' callback."""

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    user_id = user.id







    if user_id == OWNER_ID:

        try:
            await query.edit_message_caption(
                caption=(
                    "✨ <b>Welcome Owner!</b>\n\n"
                    "🎉 You have full access to the bot.\n\n"
                    f"<b>Dev</b> ➠ "
                    f"<a href='https://t.me/{OWNER_USERNAME}'>"
                    f"{OWNER_NAME}</a>"
                ),
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(
                    is_disabled=True
                ),
            )

        except Exception as exc:
            logger.debug(
                "Could not edit owner force-join message: %s",
                exc,
            )

        return





    try:
        banned = is_banned(user_id)
    except Exception as exc:
        logger.error(
            "Failed to check ban status for %s: %s",
            user_id,
            exc,
        )
        banned = False

    if banned:

        banned_text = f"""
<blockquote><b>🚫 You Are Banned</b></blockquote>

You have been banned from using this bot.

If you believe this is a mistake, please contact support.

<b>Dev</b> ➠ <a href="https://t.me/{OWNER_USERNAME}">{OWNER_NAME}</a>
"""

        try:
            await query.edit_message_caption(
                caption=banned_text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(
                    is_disabled=True
                ),
            )

        except Exception as exc:
            logger.debug(
                "Could not edit banned message for %s: %s",
                user_id,
                exc,
            )

        return





    logger.info(
        "Checking force-join status for user %s",
        user_id,
    )

    joined = await is_user_joined(
        context.bot,
        user_id,
    )





    if joined:

        try:
            await query.edit_message_caption(
                caption=(
                    "✨ <b>Welcome!</b>\n\n"
                    "🎉 You have successfully joined the "
                    "group, channel, and logs chat.\n"
                    "🚀 Enjoy using the bot!\n\n"
                    f"<b>Dev</b> ➠ "
                    f"<a href='https://t.me/{OWNER_USERNAME}'>"
                    f"{OWNER_NAME}</a>"
                ),
                parse_mode="HTML",
                reply_markup=None,
                link_preview_options=LinkPreviewOptions(
                    is_disabled=True
                ),
            )

        except Exception as exc:
            logger.debug(
                "Could not edit successful join message for %s: %s",
                user_id,
                exc,
            )

        return





    try:
        await query.edit_message_caption(
            caption=(
                "❌ <b>You still need to join all!</b>\n\n"
                "Please join the group, channel, and logs chat, "
                "then click 'I have joined' again."
            ),
            parse_mode="HTML",
            reply_markup=get_force_join_buttons(),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            ),
        )

    except Exception as exc:
        logger.debug(
            "Could not edit failed join message for %s: %s",
            user_id,
            exc,
        )






__all__ = [
    "force_join",
    "check_joined_callback",
    "is_user_joined",
    "safe_get_member",
    "get_force_join_buttons",
]