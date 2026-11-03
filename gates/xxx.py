

from utils.rate_limit import rate_limit
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)


@rate_limit("gate")
async def handle_xxx_command(update, context):
    user = update.effective_user
    
    await update.message.reply_text(
        f"""
<pre><a href='https://t.me/Fuckyoubitxch'>⩙</a> <b>𝑮𝒂𝒕𝒆</b></pre>

{E.FLY} This gate is coming soon.

⌬ <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML"
    )