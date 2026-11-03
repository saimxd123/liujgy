


import re
import io
import time
import asyncio
import aiohttp
import traceback
from datetime import datetime
from typing import List, Tuple, Optional
from urllib.parse import quote, unquote

from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes, CommandHandler

from database.db import (
    add_user_proxy,
    get_user_proxies,
    get_user_active_proxies,
    delete_user_proxy,
    delete_all_user_proxies,
    update_user_proxy_status,
    update_user_proxy_response_time,
    get_total_user_proxies,
    get_total_user_active_proxies,
    is_admin,
    get_all_global_proxies,
    get_total_proxies,
    get_total_active_proxies,
    clear_all_proxies,
)
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)

USER_MAX_PROXIES = 9999
ADMIN_MAX_PROXIES = 9999




TEST_ENDPOINT = "https://api.ipify.org"
CONNECTION_TIMEOUT = 15
TOTAL_TIMEOUT = 20
MAX_CONCURRENT_TESTS = 20
RETRY_DELAY = 0.2





def parse_proxy(proxy: str) -> Optional[dict]:
    """
    Parse ANY proxy format and return structured data with a clean formatted string.
    
    SUPPORTS:
    1. user:pass@host:port
    2. host:port:user:pass
    3. host:port
    4. user:pass@host (defaults port 8080)
    5. protocol://user:pass@host:port
    6. protocol://host:port:user:pass
    7. host:port:user:pass:protocol (custom)
    8. BrightData format: host:port:username:password
    9. ProxyMesh format: username:password@host:port
    10. Luminati format: username:password@host:port
    11. Any custom format with special characters
    12. Double @@ (strips the extra @)
    13. Mixed formats with and without protocols
    14. IPv4 and IPv6 addresses
    15. Domain names with subdomains
    """
    if not proxy or not proxy.strip():
        return None
    
    proxy = proxy.strip().replace(" ", "")
    



    protocol = "http"
    proxy_without_protocol = proxy
    
    protocol_pattern = r'^(https?|socks4|socks5)://'
    if re.match(protocol_pattern, proxy):
        protocol_match = re.match(protocol_pattern, proxy)
        protocol = protocol_match.group(1)
        proxy_without_protocol = re.sub(protocol_pattern, '', proxy)
    



    parts = proxy_without_protocol.split(':')
    

    if len(parts) == 4 and '@' not in proxy_without_protocol:
        host, port, username, password = parts

        if '.' in host or ':' in host or host.replace('.', '').replace('-', '').isdigit():

            user_enc = quote(username, safe='')
            pw_enc = quote(password, safe='')
            
            return {
                "protocol": protocol,
                "username": username,
                "password": password,
                "host": host,
                "port": port,
                "formatted": f"{protocol}://{user_enc}:{pw_enc}@{host}:{port}"
            }
    



    if '@' in proxy_without_protocol:

        auth_part, host_part = proxy_without_protocol.split('@', 1)
        

        host_part = host_part.lstrip('@')
        

        if ':' in auth_part:
            username, password = auth_part.split(':', 1)
        else:

            username = auth_part
            password = ''
        

        if ':' in host_part:
            host, port = host_part.split(':', 1)
        else:
            host = host_part
            port = "8080"
        

        user_enc = quote(username, safe='')
        pw_enc = quote(password, safe='')
        
        return {
            "protocol": protocol,
            "username": username,
            "password": password,
            "host": host,
            "port": port,
            "formatted": f"{protocol}://{user_enc}:{pw_enc}@{host}:{port}"
        }
    



    if ':' in proxy_without_protocol and '@' not in proxy_without_protocol:

        if len(parts) == 2:
            host, port = parts
            return {
                "protocol": protocol,
                "username": None,
                "password": None,
                "host": host,
                "port": port,
                "formatted": f"{protocol}://{host}:{port}"
            }
        

        host_port_match = re.search(r'([a-zA-Z0-9\-\.]+):(\d+)', proxy_without_protocol)
        if host_port_match:
            host = host_port_match.group(1)
            port = host_port_match.group(2)

            remaining = proxy_without_protocol.replace(f"{host}:{port}", '').strip(':')
            if remaining and ':' in remaining:

                cred_parts = remaining.split(':')
                if len(cred_parts) >= 2:
                    username = cred_parts[0]
                    password = ':'.join(cred_parts[1:])
                    user_enc = quote(username, safe='')
                    pw_enc = quote(password, safe='')
                    return {
                        "protocol": protocol,
                        "username": username,
                        "password": password,
                        "host": host,
                        "port": port,
                        "formatted": f"{protocol}://{user_enc}:{pw_enc}@{host}:{port}"
                    }
            else:

                return {
                    "protocol": protocol,
                    "username": None,
                    "password": None,
                    "host": host,
                    "port": port,
                    "formatted": f"{protocol}://{host}:{port}"
                }
    



    if '.' in proxy_without_protocol and ':' not in proxy_without_protocol:
        return {
            "protocol": protocol,
            "username": None,
            "password": None,
            "host": proxy_without_protocol,
            "port": "8080",
            "formatted": f"{protocol}://{proxy_without_protocol}:8080"
        }
    



    ipv6_pattern = r'^\[([a-fA-F0-9:]+)\]:(\d+)$'
    ipv6_match = re.match(ipv6_pattern, proxy_without_protocol)
    if ipv6_match:
        host = ipv6_match.group(1)
        port = ipv6_match.group(2)
        return {
            "protocol": protocol,
            "username": None,
            "password": None,
            "host": host,
            "port": port,
            "formatted": f"{protocol}://[{host}]:{port}"
        }
    



    

    if '@@' in proxy_without_protocol:
        fixed = proxy_without_protocol.replace('@@', '@')
        return parse_proxy(f"{protocol}://{fixed}")
    

    if not proxy.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return parse_proxy(f"http://{proxy}")
    

    logger.warning(f"Could not parse proxy: {proxy}")
    return None

def normalize_proxy(proxy: str) -> str:
    """
    Normalize ANY proxy format to the correct format with URL-encoded credentials.
    This is the main function you should call.
    """
    parsed = parse_proxy(proxy)
    if parsed and parsed["formatted"]:
        return parsed["formatted"]
    

    if not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
        return f"http://{proxy}"
    
    return proxy

def extract_proxies_from_text(text: str) -> List[str]:
    """Extract proxies from text with intelligent parsing."""
    proxies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        

        for part in re.split(r'[,\s\n]+', line):
            part = part.strip()
            if not part or part.startswith('#'):
                continue
            

            parsed = parse_proxy(part)
            if parsed:
                proxies.append(part)
            else:


                proxy_match = re.search(r'([a-zA-Z0-9\-\.]+):(\d+)(?::([^:]+))?(?::([^:]+))?', part)
                if proxy_match:
                    host = proxy_match.group(1)
                    port = proxy_match.group(2)
                    username = proxy_match.group(3) if proxy_match.group(3) else ''
                    password = proxy_match.group(4) if proxy_match.group(4) else ''
                    
                    if username and password:
                        proxy_candidate = f"{username}:{password}@{host}:{port}"
                    else:
                        proxy_candidate = f"{host}:{port}"
                    
                    parsed = parse_proxy(proxy_candidate)
                    if parsed:
                        proxies.append(proxy_candidate)
    
    return proxies





async def test_proxy(proxy: str) -> Tuple[bool, float]:
    """Test a single proxy using the single endpoint."""
    proxy_clean = normalize_proxy(proxy)
    

    masked_proxy = proxy_clean
    if '@' in masked_proxy:
        parts = masked_proxy.split('@')
        if len(parts) == 2:
            masked_proxy = f"***@{parts[1]}"
    
    logger.debug(f"Testing proxy: {masked_proxy}")
    

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        start = time.time()
        timeout = aiohttp.ClientTimeout(
            total=CONNECTION_TIMEOUT,
            connect=CONNECTION_TIMEOUT,
            sock_connect=CONNECTION_TIMEOUT,
            sock_read=CONNECTION_TIMEOUT
        )
        

        connector = aiohttp.TCPConnector(
            ssl=False,
            force_close=True,
            enable_cleanup_closed=True
        )
        
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            trust_env=False,
            headers=headers
        ) as session:
            async with session.get(
                TEST_ENDPOINT,
                proxy=proxy_clean,
                ssl=False,
                timeout=timeout,
            ) as resp:
                if resp.status == 200:
                    await resp.text()
                    elapsed = time.time() - start
                    logger.debug(f"Proxy {masked_proxy} OK in {elapsed:.2f}s")
                    return True, elapsed
                else:
                    logger.debug(f"Proxy {masked_proxy} returned status {resp.status}")
                    
    except asyncio.TimeoutError:
        logger.debug(f"Proxy {masked_proxy} timeout")
    except aiohttp.ClientProxyConnectionError as e:
        logger.debug(f"Proxy {masked_proxy} connection error: {e}")
    except aiohttp.ClientHttpProxyError as e:
        logger.debug(f"Proxy {masked_proxy} HTTP proxy error: {e}")
    except aiohttp.ClientConnectorError as e:
        logger.debug(f"Proxy {masked_proxy} connector error: {e}")
    except Exception as e:
        logger.debug(f"Proxy {masked_proxy} error: {type(e).__name__}: {e}")
    
    return False, 0

async def test_proxies_batch(proxies: List[str], progress_callback=None) -> List[Tuple[str, bool, float]]:
    """Test multiple proxies in parallel with batch control."""
    results = []
    total = len(proxies)
    
    batch_size = 10
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TESTS)
    
    async def test_one(proxy: str):
        async with semaphore:
            is_working, elapsed = await test_proxy(proxy)
            return proxy, is_working, elapsed
    
    for i in range(0, total, batch_size):
        batch = proxies[i:i + batch_size]
        tasks = [test_one(proxy) for proxy in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in batch_results:
            if isinstance(result, Exception):
                results.append((None, False, 0))
            else:
                results.append(result)
        
        if progress_callback:
            processed = min(i + batch_size, total)
            await progress_callback(processed, total)
        
        if i + batch_size < total:
            await asyncio.sleep(RETRY_DELAY)
    
    return results





@check_lock
@rate_limit("gate")
async def proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add proxy via reply to text/file or args."""
    user = update.effective_user
    user_id = user.id

    is_user_admin = is_admin(user_id) or user_id == OWNER_ID
    MAX_PROXIES = ADMIN_MAX_PROXIES if is_user_admin else USER_MAX_PROXIES

    text = ""

    if update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.document:
            file_name = reply.document.file_name or ""
            if file_name.lower().endswith((".txt", ".csv", ".text")):
                try:
                    file = await context.bot.get_file(reply.document.file_id)
                    file_content = await file.download_as_bytearray()
                    text = file_content.decode('utf-8', errors='ignore')
                except Exception as e:
                    await update.message.reply_text(f"{E.ERROR} Failed to read file: {str(e)}", parse_mode="HTML")
                    return
            else:
                await update.message.reply_text(f"{E.ERROR} Please send a .txt file.", parse_mode="HTML")
                return
        elif reply.text:
            text = reply.text
        elif reply.caption:
            text = reply.caption

    elif update.message.document:
        file_name = update.message.document.file_name or ""
        if file_name.lower().endswith((".txt", ".csv", ".text")):
            try:
                file = await context.bot.get_file(update.message.document.file_id)
                file_content = await file.download_as_bytearray()
                text = file_content.decode('utf-8', errors='ignore')
            except Exception as e:
                await update.message.reply_text(f"{E.ERROR} Failed to read file: {str(e)}", parse_mode="HTML")
                return
        else:
            await update.message.reply_text(f"{E.ERROR} Please send a .txt file.", parse_mode="HTML")
            return

    if context.args and not text:
        text = " ".join(context.args)

    if not text:
        await update.message.reply_text(
            f"""{E.INFO} <b>𝙐𝙨𝙖𝙜𝙚:</b>

<b>Single proxy:</b>
<code>/proxy user:pass@host:port</code>

<b>Multiple proxies:</b>
<code>/proxy proxy1 proxy2 proxy3</code>

<b>From file:</b>
Reply to a .txt file with proxies

<b>Supported formats:</b>
• user:pass@host:port
• host:port:user:pass
• host:port
• protocol://user:pass@host:port
• BrightData format: host:port:username:password
• Any other format will be auto-detected""",
            parse_mode="HTML"
        )
        return

    raw_proxies = extract_proxies_from_text(text)
    if not raw_proxies:
        await update.message.reply_text(f"{E.ERROR} No valid proxies found.", parse_mode="HTML")
        return

    existing = get_user_proxies(user_id)
    existing_proxies = [p["proxy"] for p in existing]
    
    max_add = MAX_PROXIES - len(existing)
    if max_add <= 0:
        await update.message.reply_text(
            f"""{E.WARNING} <b>𝙋𝙧𝙤𝙭𝙮 𝙇𝙞𝙢𝙞𝙩 𝙍𝙚𝙖𝙘𝙝𝙚𝙙</b>
Maximum {MAX_PROXIES} proxies per user.

Use /rmproxy to remove some.""",
            parse_mode="HTML"
        )
        return

    if len(raw_proxies) > max_add:
        raw_proxies = raw_proxies[:max_add]
        await update.message.reply_text(f"{E.WARNING} Only {max_add} proxies can be added.", parse_mode="HTML")

    proxies = []
    invalid = []
    for p in raw_proxies:
        normalized = normalize_proxy(p)
        if normalized and parse_proxy(normalized):
            proxies.append(normalized)
        else:
            invalid.append(p)

    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No valid proxy formats found.", parse_mode="HTML")
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Testing {len(proxies)} proxies...\n0/{len(proxies)}",
        parse_mode="HTML"
    )

    asyncio.create_task(run_proxy_test(proxies, existing_proxies, invalid, user_id, progress, update, context))


async def run_proxy_test(proxies, existing_proxies, invalid, user_id, progress, update, context):
    """Background task for testing and adding proxies - balanced."""
    total = len(proxies)
    successful = []
    failed = []
    
    async def update_progress(processed, total):
        try:
            await progress.edit_text(
                f"{E.FLY} Testing {total} proxies...\n{processed}/{total}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Progress update failed: {e}")
    
    results = await test_proxies_batch(proxies, update_progress)
    
    for proxy, is_working, response_time in results:
        if is_working:
            if proxy in existing_proxies:
                failed.append((proxy, "Already exists"))
            else:
                success = add_user_proxy(user_id, proxy)
                if success:
                    successful.append((proxy, response_time))
                else:
                    failed.append((proxy, "DB error"))
        else:
            failed.append((proxy, "Dead"))

    result_text = f"""
📄 𝙋𝙧𝙤𝙭𝙮 𝙏𝙚𝙨𝙩 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚

✅ Successful: {len(successful)}
⚠️ Failed: {len(failed)}
"""

    if invalid:
        result_text += f"\n❌ Invalid formats: {len(invalid)}"

    result_text += f"""

Total: {get_total_user_proxies(user_id)}
Active: {get_total_user_active_proxies(user_id)}

🔗 𝐃𝐞𝐯 ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


    try:
        await progress.edit_text(result_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to edit progress message: {e}")

        await update.message.reply_text(result_text, parse_mode="HTML")





@check_lock
@rate_limit("gate")
async def testproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test proxies in background – dead proxies are automatically deleted.
    
    - OWNER: Tests and deletes ALL dead proxies from entire database
    - Regular users: Tests and deletes ONLY their own dead proxies
    """
    user = update.effective_user
    user_id = user.id


    is_owner = user_id == OWNER_ID
    
    if is_owner:

        proxies = get_all_global_proxies()
        mode = "🌍 GLOBAL"
    else:

        proxies = get_user_proxies(user_id)
        mode = "👤 USER"
    
    if not proxies:
        await update.message.reply_text(
            f"{E.INFO} No proxies found in {'database' if is_owner else 'your pool'}.",
            parse_mode="HTML"
        )
        return


    total_count = len(proxies)
    
    msg = await update.message.reply_text(
        f"{E.FLY} {mode} Testing {total_count} proxies...\n0/{total_count}\n\n"
        f"{'🗑️ Will delete ALL dead proxies from database' if is_owner else '🗑️ Will delete your dead proxies only'}",
        parse_mode="HTML"
    )


    asyncio.create_task(run_proxy_test_bg(proxies, msg, user_id, delete_dead=True, is_owner=is_owner))


async def run_proxy_test_bg(proxies, msg, user_id, delete_dead=True, is_owner=False):
    """Background task for testing proxies - deletes dead proxies.
    
    - If is_owner=True: Deletes dead proxies from ALL users
    - If is_owner=False: Deletes dead proxies ONLY for the specific user
    """
    total = len(proxies)
    proxy_list = [p["proxy"] for p in proxies]
    
    async def update_progress(processed, total):
        try:
            await msg.edit_text(
                f"{E.FLY} {'🌍 GLOBAL' if is_owner else '👤 USER'} Testing {total} proxies...\n{processed}/{total}\n\n"
                f"{'🗑️ Deleting ALL dead proxies from database' if is_owner else '🗑️ Deleting your dead proxies only'}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Progress update failed: {e}")
    
    results = await test_proxies_batch(proxy_list, update_progress)
    
    active_count = 0
    deleted_count = 0
    failed_to_delete = 0
    

    for i, (proxy, is_working, response_time) in enumerate(results):
        if i < len(proxies):
            proxy_data = proxies[i]
            proxy_id = proxy_data["id"]
            proxy_user_id = proxy_data.get("user_id", user_id)
            
            if is_working:
                active_count += 1
                update_user_proxy_status(proxy_id, "active")
                update_user_proxy_response_time(proxy_id, response_time)
            else:
                if delete_dead:
                    if is_owner:


                        if delete_user_proxy(proxy_id, proxy_user_id):
                            deleted_count += 1
                        else:
                            failed_to_delete += 1
                    else:

                        if delete_user_proxy(proxy_id, user_id):
                            deleted_count += 1
                        else:
                            failed_to_delete += 1
                else:

                    update_user_proxy_status(proxy_id, "dead")


    if is_owner:

        total_proxies = get_total_proxies()
        active_proxies = get_total_active_proxies()
    else:

        total_proxies = get_total_user_proxies(user_id)
        active_proxies = get_total_user_active_proxies(user_id)

    result_text = (
        f"{E.REPORT} <b>Proxy Test Complete</b>\n\n"
        f"{'🌍' if is_owner else '👤'} <b>Mode:</b> {'Global Database' if is_owner else 'Your Pool'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Tested:</b> {total}\n"
        f"{E.SUCCESS} <b>Active:</b> {active_count}\n"
        f"{E.ERROR} <b>Dead:</b> {total - active_count}\n"
        f"{E.CLOSE} <b>Deleted:</b> {deleted_count}\n"
    )
    
    if failed_to_delete > 0:
        result_text += f"⚠️ <b>Failed to delete:</b> {failed_to_delete}\n"
    
    result_text += f"\n📈 <b>Remaining in {'database' if is_owner else 'your pool'}:</b> {total_proxies}\n"
    result_text += f"{E.STAR} <b>Active in {'database' if is_owner else 'your pool'}:</b> {active_proxies}\n\n"
    result_text += f"{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"


    try:
        await msg.edit_text(result_text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to edit progress message: {e}")

        await msg.reply_text(result_text, parse_mode="HTML")





@check_lock
@rate_limit("gate")
async def getproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export proxies as .txt file.
    
    - OWNER: Gets ALL proxies from entire database
    - Regular users: Gets ONLY their own proxies
    """
    user = update.effective_user
    user_id = user.id


    is_owner = user_id == OWNER_ID
    
    if is_owner:

        proxies = get_all_global_proxies()
        mode = "🌍 GLOBAL DATABASE"
    else:

        proxies = get_user_proxies(user_id)
        mode = "👤 YOUR POOL"

    if not proxies:
        await update.message.reply_text(
            f"{E.INFO} No proxies found in {'database' if is_owner else 'your pool'}.",
            parse_mode="HTML"
        )
        return


    proxy_strings = [p["proxy"] for p in proxies]
    content = "\n".join(proxy_strings)
    

    file = io.BytesIO(content.encode('utf-8'))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if is_owner:
        file_name = f"all_proxies_global_{timestamp}.txt"
        caption = f"{E.GLOBE} <b>All Proxies - Global Database</b>\n\n📊 Total: {len(proxies)}\n"
    else:
        file_name = f"proxies_{user_id}_{timestamp}.txt"
        caption = f"{E.USER} <b>Your Proxies</b>\n\n📊 Total: {len(proxies)}\n"
    
    caption += f"\n{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    
    file.name = file_name

    await update.message.reply_document(
        document=file,
        caption=caption,
        parse_mode="HTML"
    )
    file.close()





@check_lock
@rate_limit("gate")
async def rmproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a specific proxy by ID.
    
    - OWNER: Can remove ANY proxy by ID from the database
    - Regular users: Can only remove their own proxies
    """
    user = update.effective_user
    user_id = user.id
    is_owner = user_id == OWNER_ID

    if len(context.args) != 1:
        await update.message.reply_text(
            f"{E.INFO} Usage: <code>/rmproxy &lt;id&gt;</code>\n\nUse /getproxy to see IDs.",
            parse_mode="HTML"
        )
        return

    try:
        proxy_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid ID.", parse_mode="HTML")
        return


    if not is_owner:
        user_proxies = get_user_proxies(user_id)
        proxy_ids = [p["id"] for p in user_proxies]
        if proxy_id not in proxy_ids:
            await update.message.reply_text(
                f"{E.ERROR} Proxy not found in your pool.",
                parse_mode="HTML"
            )
            return
    

    success = delete_user_proxy(proxy_id, user_id if not is_owner else None)

    if not success:
        await update.message.reply_text(
            f"{E.ERROR} Proxy not found or couldn't be deleted.",
            parse_mode="HTML"
        )
        return


    if is_owner:
        total = get_total_proxies()
        pool_label = "database"
    else:
        total = get_total_user_proxies(user_id)
        pool_label = "pool"

    await update.message.reply_text(
        f"{E.SUCCESS} Proxy deleted!\n"
        f"📊 Remaining in {pool_label}: {total}\n\n"
        f"{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML"
    )





@check_lock
@rate_limit("gate")
async def clearproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all proxies.
    
    - OWNER: Clears ALL proxies from entire database
    - Regular users: Clears ONLY their own proxies
    """
    user = update.effective_user
    user_id = user.id
    is_owner = user_id == OWNER_ID

    if is_owner:


        if len(context.args) == 1 and context.args[0].lower() == "confirm":
            count = clear_all_proxies()
            await update.message.reply_text(
                f"{E.WARNING} <b>⚠️ GLOBAL CLEAR COMPLETE</b>\n\n"
                f"🗑️ All proxies cleared from database: {count} removed\n\n"
                f"{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
                parse_mode="HTML"
            )
        else:

            total = get_total_proxies()
            await update.message.reply_text(
                f"{E.WARNING} <b>⚠️ DANGEROUS ACTION</b>\n\n"
                f"This will delete ALL proxies from the entire database ({total} proxies).\n\n"
                f"<b>To confirm:</b> <code>/clearproxy confirm</code>\n\n"
                f"{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
                parse_mode="HTML"
            )
        return


    proxies = get_user_proxies(user_id)
    if not proxies:
        await update.message.reply_text(
            f"{E.INFO} No proxies in your pool to delete.",
            parse_mode="HTML"
        )
        return

    count = len(proxies)
    delete_all_user_proxies(user_id)

    await update.message.reply_text(
        f"{E.SUCCESS} All your proxies deleted! ({count} removed)\n\n"
        f"{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML"
    )





def register_proxy(app):
    app.add_handler(CommandHandler("proxy", proxy_command))
    app.add_handler(CommandHandler("tp", testproxy_command))
    app.add_handler(CommandHandler("getproxy", getproxy_command))
    app.add_handler(CommandHandler("rmproxy", rmproxy_command))
    app.add_handler(CommandHandler("clearproxy", clearproxy_command))
    logger.info("✅ Proxy handlers registered.")