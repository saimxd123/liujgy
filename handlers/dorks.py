

import asyncio
import re
import html as _html_mod
from urllib.parse import quote_plus, urlparse
from typing import List, Optional

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from database.db import is_premium, is_gate_enabled, get_user_proxies
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from utils.decorators import not_banned, log_command
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)





MAX_PAGES = 5
PAGE_DELAY = 1.2
REQ_TIMEOUT = 30


BLOCKED_DOMAINS = {

    "facebook.com", "fb.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "pinterest.com", "tiktok.com", "reddit.com", "snapchat.com",
    "telegram.org", "t.me", "whatsapp.com", "discord.com", "tumblr.com",
    "quora.com", "vk.com", "weibo.com",

    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    "rumble.com", "bitchute.com",

    "play.google.com", "apps.apple.com", "apple.com", "microsoft.com",

    "amazon.com", "amazon.co.uk", "amazon.in", "amazon.de", "amazon.fr",
    "amazon.ca", "amazon.com.au", "amazon.com.br", "amazon.es", "amazon.it",
    "amazon.co.jp", "amazon.com.mx", "amazon.sg", "amazon.ae",
    "ebay.com", "ebay.co.uk", "aliexpress.com", "etsy.com", "walmart.com",
    "wish.com", "shopify.com", "alibaba.com",

    "github.com", "stackoverflow.com", "medium.com", "dev.to",
    "gitlab.com", "bitbucket.org", "codepen.io",

    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "baidu.com",
    "yandex.com", "aol.com", "ask.com",

    "wikipedia.org", "wikimedia.org", "wikidata.org", "wiktionary.org",
    "bbc.com", "bbc.co.uk", "cnn.com", "nytimes.com", "reuters.com",
    "techcrunch.com", "theguardian.com", "forbes.com", "bloomberg.com",

    "cloudflare.com", "wordpress.com", "blogger.com", "wix.com",
    "squarespace.com", "weebly.com", "godaddy.com",
}

SHORT_SLD = {"co", "com", "org", "net", "gov", "edu", "ac", "me", "ne", "or"}


def _root_domain(url: str) -> str:
    """Extract registrable root domain."""
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] in SHORT_SLD:
            return ".".join(parts[-3:])
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return url


def _is_blocked(root: str) -> bool:
    if any(root == bd or root.endswith("." + bd) for bd in BLOCKED_DOMAINS):
        return True
    return False


def _extract_urls(html: str) -> List[str]:
    """Extract URLs from Brave Search HTML."""
    seen_href = set()
    urls = []

    for href in re.findall(r'href=["\']?(https?://[^"\'>\s]+)', html):
        href = _html_mod.unescape(href)
        if "brave.com" in href:
            href = href.split("?")[0]
        if href.endswith((".css", ".js", ".woff2", ".woff", ".png", ".jpg", ".svg", ".ico")):
            continue
        if href not in seen_href:
            seen_href.add(href)
            urls.append(href)

    return urls


async def scrape_dork_async(query: str, proxy: str = None, max_pages: int = MAX_PAGES) -> List[str]:
    """Scrape Brave Search for dork results."""
    all_urls = []
    seen_domains = set()
    q_enc = quote_plus(query)

    logger.info(f"[DORK] Starting: {query} max_pages={max_pages}")

    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        logger.error("curl_cffi not installed")
        return []

    async with AsyncSession(impersonate="chrome131") as session:
        for page in range(max_pages):
            if page == 0:
                url = f"https://search.brave.com/search?q={q_enc}&source=desktop"
            else:
                url = f"https://search.brave.com/search?q={q_enc}&offset={page * 10}&spellcheck=0"

            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "accept-encoding": "gzip, deflate",
                "accept-language": "en-US,en;q=0.6",
                "priority": "u=0, i",
                "sec-ch-ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-user": "?1",
                "sec-gpc": "1",
                "upgrade-insecure-requests": "1",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            }

            if page == 0:
                headers["sec-fetch-site"] = "none"
            else:
                headers["referer"] = f"https://search.brave.com/search?q={q_enc}&source=desktop"
                headers["sec-fetch-site"] = "same-origin"

            kwargs = {"headers": headers, "timeout": REQ_TIMEOUT}
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}

            try:
                resp = await session.get(url, **kwargs)
                html = resp.text

                if resp.status_code == 429:
                    logger.warning("[DORK] Rate-limited by Brave")
                    break
                if resp.status_code != 200:
                    logger.warning(f"[DORK] Non-200 on page {page + 1}: {resp.status_code}")
                    break

                raw_urls = _extract_urls(html)
                new_added = 0

                for u in raw_urls:
                    root = _root_domain(u)
                    if _is_blocked(root):
                        continue
                    if root in seen_domains:
                        continue
                    seen_domains.add(root)
                    all_urls.append(u)
                    new_added += 1

                logger.info(f"[DORK] Page {page + 1}: +{new_added} new (total {len(all_urls)})")

                if new_added == 0 and page > 0:
                    break

            except Exception as exc:
                logger.warning(f"[DORK] Page {page + 1} error: {exc}")
                break

            if page < max_pages - 1:
                await asyncio.sleep(PAGE_DELAY)

    return all_urls






@check_lock
@not_banned
@log_command
@rate_limit("gate")
async def handle_dorks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dorks command - Brave Search dork scraper."""
    user = update.effective_user
    user_id = user.id


    if not is_premium(user_id):
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙍𝙀𝙌𝙐𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} /dorks is only available for premium users.

Use /redeem to activate your premium key.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            f"""
{E.INFO} ⌠ 𝘿𝙊𝙍𝙆 𝙎𝙀𝘼𝙍𝘾𝙃 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/dorks &lt;keyword&gt;</code>

<b>Examples:</b>
<code>/dorks "inurl:checkout stripe"</code>
<code>/dorks "site:shopify.com checkout"</code>
<code>/dorks "stripe checkout"</code>

<b>What it does:</b>
• Searches Brave Search
• Filters out big platforms
• Returns unique domains
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    query = " ".join(args)
    max_pages = 5


    if len(args) > 1 and args[-1].isdigit():
        max_pages = min(int(args[-1]), 10)
        query = " ".join(args[:-1])

    progress = await update.message.reply_text(
        f"""
{E.FLY} ⌠ 𝘿𝙊𝙍𝙆𝙄𝙉𝙂 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Query</b> ↬ <code>{query}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Pages</b> ↬ <code>{max_pages}</code>
<i>Searching Brave...</i>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    async def background():
        try:

            proxies_data = get_user_proxies(user_id)
            proxy = None
            for p in proxies_data:
                if p.get("status") == "active":
                    proxy = p["proxy"]
                    break
            if not proxy and proxies_data:
                proxy = proxies_data[0]["proxy"] if proxies_data else None

            results = await scrape_dork_async(query, proxy, max_pages)

            if not results:
                await progress.edit_text(
                    f"""
{E.WARNING} ⌠ 𝙉𝙊 𝙍𝙀𝙎𝙐𝙇𝙏𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} No results found for <code>{query}</code>

<b>Possible reasons:</b>
• No matching sites
• Brave blocked the request
• Try a different query
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return


            result_text = f"""
{E.SEARCH} ⌠ 𝘿𝙊𝙍𝙆 𝙍𝙀𝙎𝙐𝙇𝙏𝙎 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Query</b> ↬ <code>{query}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Found</b> ↬ <code>{len(results)}</code> domains
━━━━━━━━━━━━━━━━━━
"""


            display_results = results[:20]
            for i, url in enumerate(display_results, 1):
                result_text += f"{i}. <code>{url}</code>\n"

            if len(results) > 20:
                result_text += f"\n<i>... and {len(results) - 20} more results</i>"

            result_text += f"""
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


            if len(result_text) > 4096:
                import io
                file = io.BytesIO(result_text.encode('utf-8'))
                file.name = f"dork_results_{query[:20]}.txt"
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file,
                    caption=f"✅ Dork Results: {len(results)} domains",
                )
                await progress.delete()
            else:
                await progress.edit_text(
                    result_text,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )


            import io
            file = io.BytesIO("\n".join(results).encode('utf-8'))
            file.name = f"dork_{query[:20]}.txt"
            await context.bot.send_document(
                chat_id=user_id,
                document=file,
                caption=f"📄 {len(results)} domains from <code>{query}</code>",
                parse_mode="HTML"
            )

        except ImportError:
            await progress.edit_text(
                f"""
{E.ERROR} ⌠ 𝙈𝙄𝙎𝙎𝙄𝙉𝙂 𝘿𝙀𝙋𝙀𝙉𝘿𝙀𝙉𝘾𝙔 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Please install curl_cffi:
<code>pip install curl_cffi</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception as e:
            logger.error(f"Dorks error: {e}")
            await progress.edit_text(
                f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:200]}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )

    asyncio.create_task(background())






def register_dorks(app):
    """Register dorks command."""
    app.add_handler(CommandHandler("dork", handle_dorks_command))
    logger.info("✅ /dorks registered (Brave Search Dorker)")