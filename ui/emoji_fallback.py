

from telegram import User





CUSTOM_EMOJIS = {

    "success": "5039844895779455925",
    "error": "5039665997506675838",
    "warning": "6044260346984665434",
    "info": "6043995137049104461",
    

    "back": "6046496457282819707",
    "close": "6043931300950184015",
    "refresh": "6044262726396546853",
    

    "profile": "5978784790327856236",
    "search": "5893382531037794941",
    "gates": "6044262726396546853",
    "pricing": "6044260346984665434",
    "group": "6043995137049104461",
    "updates": "6044184811394831904",
    "dev": "6138834878302524958",
    "support": "6230927657257668107",
    "admin": "5197288647275071607",
    "users": "5893365724830765382",
    "premium": "5895652322469482989",
    "keys": "5893442248263078309",
    "stats": "5215327832040811010",
    "report": "5902016123972358349",
    "proxies": "6044184811394831904",
    "sites": "5893102202817352158",
    

    "add": "5893382531037794941",
    "delete": "5256143829672672750",
    "view": "5893365724830765382",
    "generate": "5895652322469482989",
    "copy": "5893442248263078309",
    "approve": "5978692057688968853",
    "download": "6041705726206808304",
    "fire": "6044260346984665434",
}





STANDARD_EMOJIS = {

    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    

    "back": "⬅️",
    "close": "❌",
    "refresh": "🔄",
    

    "profile": "👤",
    "search": "🔍",
    "gates": "⚡",
    "pricing": "💰",
    "group": "👥",
    "updates": "📢",
    "dev": "👨‍💻",
    "support": "🆘",
    "admin": "🛡️",
    "users": "👥",
    "premium": "⭐",
    "keys": "🔑",
    "stats": "📊",
    "report": "📄",
    "proxies": "🌐",
    "sites": "🌍",
    

    "add": "➕",
    "delete": "🗑️",
    "view": "👁️",
    "generate": "🔑",
    "copy": "📋",
    "approve": "✅",
    "download": "📥",
    "fire": "🔥",
}


def is_premium_user(user: User) -> bool:
    """Check if user has Telegram Premium."""
    try:
        return getattr(user, 'is_premium', False)
    except:
        return False


def get_emoji(user: User, key: str, fallback: str = None) -> str:
    """
    Get emoji - uses custom emoji ID if user has Premium, otherwise standard emoji.
    
    Args:
        user: Telegram User object
        key: Emoji key from CUSTOM_EMOJIS
        fallback: Optional fallback string if key not found
    
    Returns:
        str: Custom emoji ID (with tags) or standard emoji
    """
    is_premium = is_premium_user(user)
    
    if is_premium and key in CUSTOM_EMOJIS:
        emoji_id = CUSTOM_EMOJIS[key]
        return f'<tg-emoji emoji-id="{emoji_id}"> </tg-emoji>'
    

    if key in STANDARD_EMOJIS:
        return STANDARD_EMOJIS[key]
    
    return fallback or ""


def get_emoji_for_button(user: User, key: str) -> tuple:
    """
    Get emoji for button - returns (text, custom_emoji_id).
    
    Returns:
        tuple: (display_text, custom_emoji_id or None)
    """
    is_premium = is_premium_user(user)
    
    if is_premium and key in CUSTOM_EMOJIS:

        emoji_id = CUSTOM_EMOJIS[key]
        return "", emoji_id
    

    if key in STANDARD_EMOJIS:
        return STANDARD_EMOJIS[key], None
    
    return "", None






class Emoji:
    """Context manager for emoji access."""
    
    def __init__(self, user: User):
        self.user = user
        self._premium = is_premium_user(user)
    
    def get(self, key: str, fallback: str = None) -> str:
        return get_emoji(self.user, key, fallback)
    
    def __getattr__(self, key: str) -> str:
        return self.get(key)


