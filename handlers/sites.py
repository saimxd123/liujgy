





import re
import io
import json
import asyncio
import aiohttp
import random
from datetime import datetime
from typing import List, Optional

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from database.db import (
    add_site,
    site_exists,
    get_all_sites,
    get_all_working_sites,
    delete_site,
    delete_all_sites,
    get_total_sites,
    get_user_proxies,
    get_random_user_proxy,
    is_admin,
)
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)





API_URL = "http://5.175.140.106:5000/shopii"
TEST_CARD = "4910149950579116|03|28|106"
MAX_PRICE = 5.00
MAX_RETRIES = 2
TIMEOUT = 50
MAX_CONCURRENT = 25





DEAD_GATEWAYS = [
    "Authorize.net",
    "AuthorizeNet",
    "authorize.net",
    "authorizenet",
    "Stripe",
    "stripe",
    "Stripe.com",
]

def is_dead_gateway(gateway: str) -> bool:
    """Check if a gateway is in the dead gateways list."""
    if not gateway:
        return False
    gateway_lower = gateway.lower()
    for dead in DEAD_GATEWAYS:
        if dead.lower() in gateway_lower:
            return True
    return False


def clean_url(url: str) -> Optional[str]:
    url = url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    if url.endswith("/"):
        url = url[:-1]
    return url


def extract_urls_from_text(text: str) -> List[str]:
    urls = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in re.split(r'[,\s]+', line):
            part = part.strip()
            if not part or part.startswith('#'):
                continue
            url = clean_url(part)
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def format_proxy_for_api(proxy: str) -> str:
    """Format proxy for API - ensure it has http:// prefix."""
    proxy = proxy.strip()
    if proxy.startswith(("http://", "https://")):
        return proxy
    return f"http://{proxy}"


async def check_site_with_api(site_url: str, proxy: str, card: str = TEST_CARD) -> dict:
    """Check a site using the API with a test card."""
    proxy_clean = format_proxy_for_api(proxy)

    params = {
        "site": site_url,
        "cc": card,
        "proxy": proxy_clean,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_URL, params=params) as resp:
                if resp.status != 200:
                    return {"working": False, "error": f"HTTP {resp.status}"}

                data = await resp.json()

                if not data:
                    return {"working": False, "error": "Empty response"}


                status = data.get("Status", False)
                response = data.get("Response", "")
                gateway = data.get("Gateway", "")
                price = float(data.get("Price", 0))
                proxy_status = data.get("Proxy", "live")
                currency = data.get("Currency", "USD")




                if gateway and is_dead_gateway(gateway):
                    logger.info(f"🚫 {site_url} → Dead gateway: {gateway}")
                    return {
                        "working": False,
                        "error": f"DEAD_GATEWAY: {gateway}",
                        "gateway": gateway,
                        "price": price,
                        "response": response,
                        "status": "dead_gateway",
                        "dead_gateway": True,
                        "currency": currency,
                    }


                if price > MAX_PRICE:
                    return {
                        "working": False,
                        "error": f"Price ${price:.2f} > ${MAX_PRICE:.2f}",
                        "price": price,
                        "gateway": gateway,
                        "response": response,
                        "status": status,
                        "over_price": True,
                        "currency": currency,
                    }


                if status is True:
                    return {
                        "working": True,
                        "gateway": gateway,
                        "price": price,
                        "response": response,
                        "status": status,
                        "time": data.get("Time", "0s"),
                        "currency": currency,
                    }
                else:

                    error_msg = response if response else status


                    if "attempt_token" in error_msg:
                        error_msg = "attempt_token"
                    elif "STORE_PASSWORD" in error_msg:
                        error_msg = "STORE_PASSWORD_PROTECTED"
                    elif "No response" in error_msg:
                        error_msg = "No response from products"
                    elif "Checkout failed" in error_msg:
                        error_msg = "Checkout failed"
                    elif "Cart failed" in error_msg:
                        error_msg = "Cart failed"
                    elif "timeout" in error_msg.lower():
                        error_msg = "Timeout"

                    return {
                        "working": False,
                        "error": error_msg,
                        "status": status,
                        "response": response,
                        "price": price,
                        "gateway": gateway,
                        "currency": currency,
                    }

    except asyncio.TimeoutError:
        return {"working": False, "error": "Timeout"}
    except Exception as e:
        return {"working": False, "error": str(e)[:50]}


async def check_site_with_retry(site_url: str, proxies: List[str]) -> dict:
    """
    Check a site with intelligent retries.
    
    Retryable errors (proxy issues):
    - attempt_token: Proxy can't get checkout token
    - STORE_PASSWORD_PROTECTED: Proxy is blocked
    - Timeout: Network issue
    - HTTP: Network issue
    - Checkout failed: Proxy issue
    - Cart failed: Proxy issue
    
    Non-retryable errors (site is dead):
    - No response from products: Not a Shopify store
    - Empty response: Site is dead
    - DEAD_GATEWAY: Gateway is Authorize.net or Stripe (NOT retryable)
    """
    last_error = None
    used_proxies = set()
    last_result = None
    

    retryable_patterns = [
        "attempt_token",
        "Timeout",
        "HTTP",
        "STORE_PASSWORD",
        "Checkout failed",
        "Cart failed",
        "connection",
        "timed out",
        "timeout"
    ]
    
    for attempt in range(MAX_RETRIES + 1):

        available = [p for p in proxies if p not in used_proxies]
        if not available:
            logger.warning(f"⚠️ No more unused proxies for {site_url}")
            break
        
        proxy = random.choice(available)
        used_proxies.add(proxy)
        
        result = await check_site_with_api(site_url, proxy)
        last_result = result
        



        if result.get("dead_gateway", False):
            logger.info(f"🚫 {site_url} → Dead gateway, not retrying")
            return result
        
        if result.get("working"):
            logger.info(f"✅ {site_url} WORKING on attempt {attempt+1}")
            return result
        
        error = result.get("error", "")
        last_error = error
        

        if result.get("over_price", False):
            return result
        

        is_retryable = any(pattern in error for pattern in retryable_patterns)
        
        if is_retryable:
            if attempt < MAX_RETRIES:
                logger.info(f"🔄 {site_url} → {error}, retrying with different proxy ({attempt+1}/{MAX_RETRIES})...")
                continue
            else:
                logger.warning(f"❌ {site_url} failed all {MAX_RETRIES+1} attempts: {error}")
                return result
        else:

            if "No response from products" in error or "Empty response" in error:
                return {"working": False, "error": "DEAD_STORE", "status": "dead"}
            return result
    
    return last_result or {"working": False, "error": f"Failed after {MAX_RETRIES + 1} attempts: {last_error}"}






@check_lock
@admin_only
@log_command
async def addsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add sites via reply to text/file or args."""
    admin = update.effective_user
    admin_id = admin.id

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

<b>Single site:</b>
<code>/addsite https://example.com</code>

<b>Multiple sites:</b>
<code>/addsite https://site1.com https://site2.com</code>

<b>From file:</b>
Reply to a .txt file with sites (one per line)

<b>From reply:</b>
Reply to a message containing sites""",
            parse_mode="HTML"
        )
        return

    urls = extract_urls_from_text(text)
    if not urls:
        await update.message.reply_text(f"{E.ERROR} No valid URLs found.", parse_mode="HTML")
        return

    proxies_data = get_user_proxies(admin_id)
    proxies = [p["proxy"] for p in proxies_data if p["status"] == "active"]
    if not proxies:
        proxies = [p["proxy"] for p in proxies_data]
    
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No proxies found. Add a proxy first with /proxy", parse_mode="HTML")
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Checking {len(urls)} sites in background...\n\n⏳ You can continue using the bot.",
        parse_mode="HTML"
    )

    asyncio.create_task(run_addsite_bg(urls, proxies, admin_id, progress, update, context))


async def run_addsite_bg(urls, proxies, admin_id, progress, update, context):
    """Background task for adding sites."""
    total = len(urls)
    checked = 0
    added = 0
    failed = 0
    duplicates = 0
    over_price = 0
    dead_gateway = 0
    results = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def check_one(url):
        nonlocal checked, added, failed, duplicates, over_price, dead_gateway
        
        if site_exists(url):
            duplicates += 1
            return {"url": url, "status": "Duplicate", "gateway": "", "price": 0}
        
        result = await check_site_with_retry(url, proxies)
        



        if result.get("dead_gateway", False):
            dead_gateway += 1
            failed += 1
            return {
                "url": url,
                "status": "Dead Gateway",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "response": result.get("response", ""),
                "error": f"DEAD_GATEWAY: {result.get('gateway', 'Unknown')}"
            }
        
        if result.get("over_price", False):
            over_price += 1
            failed += 1
            return {
                "url": url,
                "status": "Over Price",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "response": result.get("response", ""),
                "error": f"${result.get('price', 0):.2f} > ${MAX_PRICE:.2f}"
            }
        
        if result.get("working"):
            add_site(
                url=url,
                gateway=result.get("gateway", ""),
                price=result.get("price", 0),
                status="Working",
                added_by=admin_id,
            )
            added += 1
            return {
                "url": url,
                "status": "Working",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "response": result.get("response", ""),
            }
        else:
            failed += 1
            return {
                "url": url,
                "status": "Dead",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "error": result.get("error", "Unknown"),
                "response": result.get("response", ""),
            }

    async def worker(url):
        nonlocal checked
        async with semaphore:
            result = await check_one(url)
            checked += 1
            results.append(result)
            
            if checked % 10 == 0 or checked == total:
                try:
                    await progress.edit_text(
                        f"""{E.FLY} Checking sites...
Progress: {checked}/{total}
{E.SUCCESS} Added: {added}
{E.ERROR} Dead: {failed}
{E.WARNING} Duplicates: {duplicates}
💰 Over ${MAX_PRICE:.2f}: {over_price}
🚫 Dead Gateways: {dead_gateway}""",
                        parse_mode="HTML"
                    )
                except:
                    pass

    tasks = [worker(url) for url in urls]
    await asyncio.gather(*tasks)


    file_content = "SITE SCAN REPORT\n"
    file_content += "=" * 60 + "\n"
    file_content += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    file_content += f"Total: {total}\n"
    file_content += f"✅ Added: {added}\n"
    file_content += f"❌ Dead: {failed}\n"
    file_content += f"⚠️ Duplicates: {duplicates}\n"
    file_content += f"💰 Over ${MAX_PRICE:.2f}: {over_price}\n"
    file_content += f"🚫 Dead Gateways: {dead_gateway}\n"
    file_content += "=" * 60 + "\n\n"
    file_content += "SITE | RESPONSE | GATEWAY | PRICE\n"
    file_content += "-" * 60 + "\n"

    for r in results:
        if r["status"] == "Working":
            price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
            file_content += f"{r['url']} | {r['response'][:30]} | {r['gateway']} | {price_str}\n"
        elif r["status"] == "Duplicate":
            file_content += f"{r['url']} | DUPLICATE | N/A | N/A\n"
        elif r["status"] == "Over Price":
            price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
            file_content += f"{r['url']} | OVER_PRICE | {r['gateway']} | {price_str}\n"
        elif r["status"] == "Dead Gateway":
            price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
            file_content += f"{r['url']} | DEAD_GATEWAY | {r['gateway']} | {price_str}\n"
        else:
            file_content += f"{r['url']} | {r['error'][:30]} | {r['gateway']} | N/A\n"

    report_file = io.BytesIO(file_content.encode('utf-8'))
    report_file.name = f"site_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    await update.message.reply_document(
        document=report_file,
        caption=f"""
{E.REPORT} Site Scan Complete
{E.SUCCESS} Added: {added} | {E.ERROR} Dead: {failed} | {E.WARNING} Duplicates: {duplicates} | 💰 Over ${MAX_PRICE:.2f}: {over_price} | 🚫 Dead Gateways: {dead_gateway}

{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML"
    )
    report_file.close()

    await progress.delete()
    logger.info(f"Site scan: {added} added, {failed} failed, {dead_gateway} dead gateways by {admin_id}")






@check_lock
@log_command
async def testsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test ALL sites in the database. Owner only. Deletes dead sites."""
    user = update.effective_user
    user_id = user.id


    if user_id != OWNER_ID:
        await update.message.reply_text(
            f"{E.ERROR} <b>Permission Denied</b>\n\nThis command is only for the owner.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    sites = get_all_sites()
    if not sites:
        await update.message.reply_text(f"{E.INFO} No sites in database.", parse_mode="HTML")
        return

    proxies_data = get_user_proxies(user_id)
    proxies = [p["proxy"] for p in proxies_data if p["status"] == "active"]
    if not proxies:
        proxies = [p["proxy"] for p in proxies_data]
    
    if not proxies:
        await update.message.reply_text(f"{E.ERROR} No proxies found. Add a proxy first with /proxy", parse_mode="HTML")
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Testing <b>{len(sites)}</b> sites in background...\n\n⏳ You can continue using the bot.",
        parse_mode="HTML"
    )

    asyncio.create_task(run_testsite_bg(sites, proxies, progress, update, context))


async def run_testsite_bg(sites, proxies, progress, update, context):
    """Background task for testing all sites. Deletes dead sites."""
    total = len(sites)
    checked = 0
    working = 0
    dead = 0
    dead_gateway = 0
    deleted_count = 0
    results = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = datetime.now()

    async def check_one(site_data):
        nonlocal checked, working, dead, dead_gateway, deleted_count
        url = site_data["url"]
        
        result = await check_site_with_retry(url, proxies)
        



        if result.get("dead_gateway", False):
            dead_gateway += 1
            dead += 1

            delete_site(url)
            deleted_count += 1
            return {
                "url": url,
                "status": "Dead Gateway (deleted)",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "error": f"DEAD_GATEWAY: {result.get('gateway', 'Unknown')}",
                "response": result.get("response", ""),
            }
        
        if result.get("working"):
            working += 1
            return {
                "url": url,
                "status": "Working",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "response": result.get("response", ""),
            }
        else:
            dead += 1

            delete_site(url)
            deleted_count += 1
            return {
                "url": url,
                "status": "Dead (deleted)",
                "gateway": result.get("gateway", ""),
                "price": result.get("price", 0),
                "error": result.get("error", "Unknown"),
                "response": result.get("response", ""),
            }

    async def worker(site_data):
        nonlocal checked
        async with semaphore:
            result = await check_one(site_data)
            checked += 1
            results.append(result)
            
            if checked % 10 == 0 or checked == total:
                elapsed = (datetime.now() - start_time).seconds
                try:
                    await progress.edit_text(
                        f"{E.FLY} Testing sites...\n"
                        f"Progress: {checked}/{total}\n"
                        f"{E.SUCCESS} Working: {working}\n"
                        f"{E.ERROR} Dead (deleted): {dead}\n"
                        f"🚫 Dead Gateways (deleted): {dead_gateway}\n"
                        f"🗑️ Deleted: {deleted_count}\n"
                        f"⏱️ Time: {elapsed}s",
                        parse_mode="HTML"
                    )
                except:
                    pass

    tasks = [worker(site) for site in sites]
    await asyncio.gather(*tasks)


    file_content = "SITE TEST REPORT (Dead sites deleted)\n"
    file_content += "=" * 60 + "\n"
    file_content += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    file_content += f"Total: {total}\n"
    file_content += f"✅ Working: {working}\n"
    file_content += f"❌ Dead (deleted): {dead}\n"
    file_content += f"🚫 Dead Gateways (deleted): {dead_gateway}\n"
    file_content += f"🗑️ Total Deleted: {deleted_count}\n"
    file_content += "=" * 60 + "\n\n"
    file_content += "SITE | RESPONSE | GATEWAY | PRICE | STATUS\n"
    file_content += "-" * 60 + "\n"

    for r in results:
        if r["status"] == "Working":
            price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
            file_content += f"{r['url']} | {r['response'][:30]} | {r['gateway']} | {price_str} | ✅ WORKING\n"
        else:
            price_str = f"${r['price']:.2f}" if r['price'] else "N/A"
            file_content += f"{r['url']} | {r['response'][:30] if r.get('response') else r.get('error', '')[:30]} | {r['gateway']} | {price_str} | ❌ DELETED\n"

    report_file = io.BytesIO(file_content.encode('utf-8'))
    report_file.name = f"site_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    elapsed = (datetime.now() - start_time).seconds
    elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"

    await update.message.reply_document(
        document=report_file,
        caption=f"""
{E.REPORT} <b>Site Test Complete</b>
━━━━━━━━━━━━━━━━━━
{E.SUCCESS} Working: {working}
{E.ERROR} Dead (deleted): {dead}
🚫 Dead Gateways (deleted): {dead_gateway}
🗑️ Total Deleted: {deleted_count}
{E.CARD} Total: {total}
⏱️ Time: {elapsed_str}

{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML"
    )
    report_file.close()

    await progress.delete()
    logger.info(f"Site test complete: {working} working, {deleted_count} deleted, {dead_gateway} dead gateways in {elapsed_str}")






@check_lock
@log_command
async def getsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export sites - choose between clean URLs or detailed info. Owner only."""
    user = update.effective_user
    user_id = user.id


    if user_id != OWNER_ID:
        await update.message.reply_text(
            f"{E.ERROR} <b>Permission Denied</b>\n\nThis command is only for the owner.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Clean URLs", callback_data="getsite_clean"),
            InlineKeyboardButton("📊 Detailed Info", callback_data="getsite_detailed"),
        ],
        [InlineKeyboardButton("✖ Cancel", callback_data="getsite_cancel")]
    ])

    await update.message.reply_text(
        f"""
{E.SITES} <b>Export Sites</b>
━━━━━━━━━━━━━━━━━━
Choose export format:

• <b>Clean URLs</b> – only site URLs (one per line)
• <b>Detailed Info</b> – site | gateway | price | status
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def getsite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle export choice."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "getsite_cancel":
        await query.edit_message_text("❌ Export cancelled.", parse_mode="HTML")
        return

    sites = get_all_sites()
    if not sites:
        await query.edit_message_text(f"{E.INFO} No sites found.", parse_mode="HTML")
        return

    working_sites = get_all_working_sites()

    if data == "getsite_clean":

        content = "\n".join([site['url'] for site in sites])
        filename = f"urls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        caption = f"""
{E.SITES} <b>Clean URLs Export</b>
━━━━━━━━━━━━━━━━━━
Total: {len(sites)} | Working: {len(working_sites)}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    else:
        content = "SITE | GATEWAY | PRICE | STATUS\n"
        content += "-" * 60 + "\n"
        for site in sites:
            price = site.get('price', 0)
            price_str = f"${price:.2f}" if price else "N/A"
            gateway = site.get('gateway', 'N/A')
            status = site.get('status', 'Unknown')
            content += f"{site['url']} | {gateway} | {price_str} | {status}\n"
        filename = f"sites_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        caption = f"""
{E.SITES} <b>Detailed Sites Export</b>
━━━━━━━━━━━━━━━━━━
Total: {len(sites)} | Working: {len(working_sites)}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    file = io.BytesIO(content.encode('utf-8'))
    file.name = filename

    await query.edit_message_text("⏳ Generating file...")
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=file,
        caption=caption,
        parse_mode="HTML"
    )
    file.close()
    await query.delete_message()






@check_lock
@admin_only
@log_command
async def rmsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a specific site by URL."""
    if len(context.args) != 1:
        await update.message.reply_text(
            f"{E.INFO} Usage: <code>/rmsite &lt;url&gt;</code>",
            parse_mode="HTML"
        )
        return

    url = clean_url(context.args[0])
    if not url:
        await update.message.reply_text(f"{E.ERROR} Invalid URL.", parse_mode="HTML")
        return

    if not site_exists(url):
        await update.message.reply_text(f"{E.ERROR} Site not found.", parse_mode="HTML")
        return

    delete_site(url)
    total = get_total_sites()

    await update.message.reply_text(
        f"{E.SUCCESS} Site deleted!\nRemaining: {total}\n\n{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML"
    )






@check_lock
@admin_only
@log_command
async def clearsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all sites (Admin only)."""
    sites = get_all_sites()
    if not sites:
        await update.message.reply_text(f"{E.INFO} No sites to delete.", parse_mode="HTML")
        return

    delete_all_sites()

    await update.message.reply_text(
        f"{E.SUCCESS} All sites deleted! ({len(sites)} removed)\n\n{E.LINK} <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>",
        parse_mode="HTML"
    )






def register_sites(app):
    app.add_handler(CommandHandler("addsite", addsite_command))
    app.add_handler(CommandHandler("ts", testsite_command))
    app.add_handler(CommandHandler("getsite", getsite_command))
    app.add_handler(CallbackQueryHandler(getsite_callback, pattern=r"^getsite_"))
    app.add_handler(CommandHandler("rmsite", rmsite_command))
    app.add_handler(CommandHandler("clearsites", clearsites_command))
    logger.info("Sites handlers registered.")