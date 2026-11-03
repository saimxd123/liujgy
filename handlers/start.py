

from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes
from config import START_PHOTO, OWNER_ID, OWNER_USERNAME, OWNER_NAME
from logger import get_logger
from database.db import add_user, user_exists, get_user, is_admin, is_banned
from ui.buttons import home_buttons
from ui.emojis import PremiumEmoji as E
from forcejoin import force_join
from utils.lock_check import check_lock
from core.callbacks import Callback

logger = get_logger(__name__)


@force_join
@check_lock
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id




    if context.args and context.args[0].startswith("redeem_"):
        from handlers.redeem import redeem
        key = context.args[0].replace("redeem_", "")
        context.args = [key]
        await redeem(update, context)
        return

    if is_banned(user_id):
        await update.message.reply_text(
            f"""
<blockquote><b>{E.CLOSE} You Are Banned</b></blockquote>

You have been banned from using this bot.

If you believe this is a mistake, please contact support.

{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if not user_exists(user.id):
        add_user(user.id, user.first_name, user.username)
        logger.info(f"New user -> {user.id}")

    is_user_admin = user.id == OWNER_ID or is_admin(user.id)

    text = f"""
{E.CAR} 𝑾𝑬𝑳𝑪𝑶𝑴𝑬 𝑻𝑶 <a href='https://t.me/{OWNER_USERNAME}'>𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻!</a>
━━━━━━━━━━━━━━━━━━
{E.FLY} <a href='https://t.me/{OWNER_USERNAME}'>𝑬𝒏𝒋𝒐𝒚 𝒃𝒍𝒂𝒛𝒊𝒏𝒈 𝒔𝒑𝒆𝒆𝒅𝒔</a>
           <a href='https://t.me/{OWNER_USERNAME}'>𝒔𝒎𝒂𝒓𝒕 𝒓𝒆𝒕𝒓𝒊𝒆𝒔, 𝑨𝒄𝒄𝒖𝒓𝒂𝒄𝒚</a>
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>𝐎𝐰𝐧𝐞𝐫</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await update.message.reply_photo(
        photo=START_PHOTO,
        caption=text,
        parse_mode="HTML",
        reply_markup=home_buttons(is_admin=is_user_admin),
    )

    logger.info(f"/start -> {user.id}")






async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show commands page."""
    user = update.effective_user
    

    class FakeQuery:
        def __init__(self, user):
            self.from_user = user
            self.data = Callback.COMMANDS
            self.message = update.message
            self.id = "fake"
        
        async def edit_message_caption(self, **kwargs):

            await update.message.reply_text(
                text=kwargs.get("caption", ""),
                parse_mode=kwargs.get("parse_mode", "HTML"),
                reply_markup=kwargs.get("reply_markup"),
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        
        async def answer(self, *args, **kwargs):
            pass
    
    from ui.pages import commands_page
    fake_query = FakeQuery(user)
    await commands_page(fake_query)






def register_start(app: Application):
    """Register start and commands handlers."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cmds", cmds_command))
    app.add_handler(CommandHandler("cmd", cmds_command))
    app.add_handler(CommandHandler("commands", cmds_command))
    logger.info("Start & Commands handlers registered.")