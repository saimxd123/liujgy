

import re
import asyncio
import aiohttp
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from typing import Dict, List, Set, Optional
import time
from datetime import datetime, timedelta

from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)





RATE_LIMIT_SECONDS = 3
CACHE_DURATION_SECONDS = 300
MAX_CONCURRENT_REQUESTS = 10





CMS_PATTERNS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js|shopify\.cdn|shopifycloud\.com',
    'BigCommerce': r'cdn\.bigcommerce\.com|bigcommerce\.com|bc-static\.com',
    'Wix': r'static\.parastorage\.com|wix\.com|wixstatic\.com',
    'Squarespace': r'static1\.squarespace\.com|squarespace-cdn\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/|wc-ajax|woocommerce\.js',
    'Magento': r'static/version\d+/frontend/|magento/|Magento\.js',
    'WordPress': r'wp-content|wp-includes/|wp-json/|wordpress\.js',
    'PrestaShop': r'prestashop\.js|prestashop/|presta\.js',
    'OpenCart': r'catalog/view/theme|opencart/|route=common/home',
    'Joomla': r'media/jui|joomla\.js|joomla\.javascript/|com_content',
    'Drupal': r'sites/all/modules|drupal\.js/|drupal\.css',
    'Laravel': r'laravel\.js|livewire\.js|/vendor/laravel/',
    'React': r'react\.js|react-dom\.js|__react|root\.jsx',
    'Vue': r'vue\.js|vue\.min\.js|__vue__|v-bind',
    'Angular': r'angular\.js|ng-app|ng-controller|angular-core',
    'Svelte': r'svelte\.js|svelte-internal|__svelte',
    'Next.js': r'_next/static|next\.js|__NEXT_DATA__',
    'Nuxt.js': r'_nuxt/|nuxt\.js|__NUXT__',
    'Gatsby': r'gatsby\.js|__GATSBY__|gatsby-plugin',
    'Custom CMS': r'(?:<meta name="generator" content="([^"]+)")'
}





PAYMENT_GATEWAYS = {
    'PayPal': r'paypal\.com|paypal\.js|paypalobjects\.com|paypal-button',
    'Stripe': r'stripe\.com|stripe\.js|js\.stripe\.com|pk_(live|test)_',
    'Braintree': r'braintree\.com|braintree\.js|braintree-',
    'Square': r'square\.com|squareup\.com|square-',
    'Authorize.Net': r'authorize\.net|authorizenet\.com|accept\.js',
    'Shopify': r'shopify\.com|shopify\.js|checkout\.shopify',
    'WooCommerce': r'woocommerce\.js|wc-|woocommerce-payments',
    'Magento': r'magento/checkout|magento-payment',
    'Razorpay': r'razorpay\.com|razorpay\.js|rzp\.io',
    'PayU': r'payu\.com|payu\.in|payu\.co|payu\.js',
    'Adyen': r'adyen\.com|adyen\.js|checkout\.adyen',
    'Checkout.com': r'checkout\.com|checkout\.js|cko\.js',
    'Klarna': r'klarna\.com|klarna\.js|klarna-checkout',
    'Afterpay': r'afterpay\.com|afterpay\.js|afterpay-payments',
    'Affirm': r'affirm\.com|affirm\.js|affirm-payments',
    'Mollie': r'mollie\.com|mollie\.js|mollie-payments',
    'Paddle': r'paddle\.com|paddle\.js|paddle-payments',
    'Recurly': r'recurly\.com|recurly\.js|recurly-payments',
    'Chargify': r'chargify\.com|chargify\.js',
    'Revolut': r'revolut\.com|revolut\.js|revolut-payments',
    'Apple Pay': r'apple\.com/apple-pay|applepay|apple-pay',
    'Google Pay': r'google\.com/pay|googlepay|google-pay',
    'Samsung Pay': r'samsung\.com/pay|samsungpay|samsung-pay',
    'Cash App': r'cash\.app|cashapp|cash-app',
    'Skrill': r'skrill\.com|skrill\.js|skrill-payments',
    'Neteller': r'neteller\.com|neteller\.js|neteller-payments',
    'Payoneer': r'payoneer\.com|payoneer\.js',
    'Paytm': r'paytm\.com|paytm\.in|paytm\.js|paytm-payments',
    'PhonePe': r'phonepe\.com|phonepe\.in|phonepe\.js',
    'Mercado Pago': r'mercadopago\.com|mercadopago\.com\.br|mp\.js',
    'PagSeguro': r'pagseguro\.com|pagseguro\.uol|pagseguro\.js',
    'Yandex.Checkout': r'yandex\.ru/checkout|yandex\.js',
    'PayFort': r'payfort\.com|payfort\.js|payfort-',
    'BitPay': r'bitpay\.com|bitpay\.js|bitpay-payments',
    'Coinbase Commerce': r'coinbase\.com/commerce|coinbase-commerce',
    'CoinGate': r'coingate\.com|coingate\.js|coingate-payments',
    'CoinPayments': r'coinpayments\.net|coinpayments\.js',
    'OpenNode': r'opennode\.com|opennode\.js',
    'NowPayments': r'nowpayments\.io|nowpayments\.js',
    'G2A Pay': r'pay\.g2a\.com|g2a-pay',
    'FastSpring': r'fastspring\.com|fastspring\.js',
    'Bambora': r'bambora\.com|bambora\.js',
    'Checkout24': r'checkout24\.de|checkout24\.js',
    'Eway': r'eway\.com\.au|eway\.js',
    'Worldpay': r'worldpay\.com|worldpay\.js|worldpay-payments',
    'Fiserv': r'fiserv\.com|fiserv\.js|fiserv-payments',
    'Global Payments': r'globalpayments\.com|globalpayments\.js',
    'Nuvei': r'nuvei\.com|nuvei\.js|nuvei-payments',
    'SafeCharge': r'safecharge\.com|safecharge\.js',
    'Credorax': r'credorax\.com|credorax\.js',
    'iPay': r'ipay\.com|ipay\.js|ipay-payments',
}





def detect_frameworks(html: str) -> List[str]:
    """Detect JavaScript frameworks."""
    frameworks = []
    
    if re.search(r'react\.js|react-dom\.js|__react', html, re.IGNORECASE):
        frameworks.append('React')
    if re.search(r'vue\.js|vue\.min\.js|__vue__', html, re.IGNORECASE):
        frameworks.append('Vue.js')
    if re.search(r'angular\.js|ng-app|ng-controller', html, re.IGNORECASE):
        frameworks.append('Angular')
    if re.search(r'svelte\.js|__svelte', html, re.IGNORECASE):
        frameworks.append('Svelte')
    if re.search(r'_next/static|next\.js|__NEXT_DATA__', html, re.IGNORECASE):
        frameworks.append('Next.js')
    if re.search(r'_nuxt/|nuxt\.js|__NUXT__', html, re.IGNORECASE):
        frameworks.append('Nuxt.js')
    if re.search(r'gatsby\.js|__GATSBY__', html, re.IGNORECASE):
        frameworks.append('Gatsby')
    if re.search(r'jquery\.js|jquery-|jQuery', html, re.IGNORECASE):
        frameworks.append('jQuery')
    if re.search(r'bootstrap\.css|bootstrap\.js|bootstrap-', html, re.IGNORECASE):
        frameworks.append('Bootstrap')
    if re.search(r'tailwind\.css|tailwindcss', html, re.IGNORECASE):
        frameworks.append('Tailwind CSS')
    
    return frameworks


def detect_analytics(html: str) -> List[str]:
    """Detect analytics/tracking tools."""
    analytics = []
    

    if re.search(r'google-analytics\.com|gtag|ga\.js|ga\(', html, re.IGNORECASE):
        analytics.append('Google Analytics')
    if re.search(r'googletagmanager\.com|gtm\.js', html, re.IGNORECASE):
        analytics.append('GTM')
    if re.search(r'facebook\.com/tr|fbq\(', html, re.IGNORECASE):
        analytics.append('Facebook Pixel')
    if re.search(r'analytics\.stripe\.com|stripe-analytics', html, re.IGNORECASE):
        analytics.append('Stripe Analytics')
    if re.search(r'hotjar\.com|hotjar\.js', html, re.IGNORECASE):
        analytics.append('Hotjar')
    if re.search(r'clarity\.ms|clarity\.js', html, re.IGNORECASE):
        analytics.append('Microsoft Clarity')
    if re.search(r'mixpanel\.com|mixpanel\.js', html, re.IGNORECASE):
        analytics.append('Mixpanel')
    if re.search(r'intercom\.com|intercom\.js', html, re.IGNORECASE):
        analytics.append('Intercom')
    
    return analytics


def detect_security_headers(headers: Dict) -> Dict:
    """Detect security headers."""
    security = {}
    
    if headers.get('X-Frame-Options'):
        security['X-Frame-Options'] = headers.get('X-Frame-Options')
    if headers.get('Content-Security-Policy'):
        security['CSP'] = '✅ Present'
    if headers.get('X-Content-Type-Options'):
        security['X-Content-Type-Options'] = '✅ Present'
    if headers.get('Strict-Transport-Security'):
        security['HSTS'] = '✅ Present'
    if headers.get('Referrer-Policy'):
        security['Referrer-Policy'] = '✅ Present'
    
    return security


def detect_email(html: str) -> Optional[str]:
    """Extract email from HTML."""
    patterns = [
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        r'[a-zA-Z0-9._%+-]+\s*\[at\]\s*[a-zA-Z0-9.-]+\s*\[dot\]\s*[a-zA-Z]{2,}'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            email = match.group(0)

            email = email.replace('[at]', '@').replace('[dot]', '.').replace(' ', '')
            return email
    return None


def detect_phone(html: str) -> Optional[str]:
    """Extract phone number from HTML."""
    patterns = [
        r'\+?\d{1,3}[\s.-]?\(?\d{2,3}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}',
        r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(0)
    return None


def detect_social_links(html: str) -> Dict:
    """Detect social media links."""
    social = {}
    
    if re.search(r'facebook\.com/', html, re.IGNORECASE):
        social['Facebook'] = '✅'
    if re.search(r'twitter\.com/|x\.com/', html, re.IGNORECASE):
        social['Twitter/X'] = '✅'
    if re.search(r'instagram\.com/', html, re.IGNORECASE):
        social['Instagram'] = '✅'
    if re.search(r'youtube\.com/', html, re.IGNORECASE):
        social['YouTube'] = '✅'
    if re.search(r'linkedin\.com/', html, re.IGNORECASE):
        social['LinkedIn'] = '✅'
    if re.search(r'tiktok\.com/', html, re.IGNORECASE):
        social['TikTok'] = '✅'
    if re.search(r'pinterest\.com/', html, re.IGNORECASE):
        social['Pinterest'] = '✅'
    if re.search(r'reddit\.com/', html, re.IGNORECASE):
        social['Reddit'] = '✅'
    if re.search(r'discord\.(com|gg)/', html, re.IGNORECASE):
        social['Discord'] = '✅'
    if re.search(r'telegram\.org/', html, re.IGNORECASE):
        social['Telegram'] = '✅'
    if re.search(r'whatsapp\.com/', html, re.IGNORECASE):
        social['WhatsApp'] = '✅'
    if re.search(r'github\.com/', html, re.IGNORECASE):
        social['GitHub'] = '✅'
    
    return social


def get_page_stats(html: str) -> Dict:
    """Get page statistics."""
    soup = BeautifulSoup(html, 'html.parser')
    
    return {
        'images': len(soup.find_all('img')),
        'links': len(soup.find_all('a')),
        'scripts': len(soup.find_all('script')),
        'styles': len(soup.find_all('link', rel='stylesheet')),
        'forms': len(soup.find_all('form')),
        'paragraphs': len(soup.find_all('p')),
        'headings': len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])),
        'meta_tags': len(soup.find_all('meta')),
    }






_shared_session = None
domain_cache = {}
concurrent_requests = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)


async def get_shared_session():
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        connector = aiohttp.TCPConnector(limit=50, force_close=True)
        timeout = aiohttp.ClientTimeout(total=30)
        _shared_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _shared_session






def detect_cms(html: str) -> str:
    for cms, pattern in CMS_PATTERNS.items():
        if re.search(pattern, html, re.IGNORECASE):
            if cms == 'Custom CMS':
                match = re.search(pattern, html, re.IGNORECASE)
                return match.group(1) or "Custom CMS"
            return cms
    return "Unknown / Custom"


def detect_gateways(html: str) -> str:
    detected = []
    for gateway, pattern in PAYMENT_GATEWAYS.items():
        if re.search(pattern, html, re.IGNORECASE):
            detected.append(gateway)
    return ", ".join(detected) if detected else "None Detected"


def detect_captcha(html: str) -> str:
    html_lower = html.lower()
    if "hcaptcha" in html_lower:
        return "✅ hCaptcha"
    elif "recaptcha" in html_lower or "g-recaptcha" in html_lower:
        return "✅ reCAPTCHA"
    elif "captcha" in html_lower:
        return "✅ Generic CAPTCHA"
    return "❌ No CAPTCHA"


def detect_cloudflare(html: str, headers: Dict = None, status: int = None) -> str:
    if headers is None:
        headers = {}
    
    cloudflare_indicators = [
        'cloudflare', 'cf-ray', 'cf-cache-status', 'cf-browser-verification',
        '__cfduid', 'cf_chl_', 'checking your browser', 'enable javascript and cookies'
    ]
    
    lower_keys = [k.lower() for k in headers.keys()]
    if 'cf-ray' in lower_keys or 'cloudflare' in headers.get('Server', '').lower():
        if any(indicator in html.lower() for indicator in ['just a moment', 'checking your browser']):
            return "⚠️ Cloudflare (Verification Required)"
        return "⚠️ Cloudflare Present"
    return "❌ None"


def detect_3ds(html: str) -> str:
    patterns = ['3d secure', 'verified by visa', 'mastercard securecode', '3ds', '3ds2']
    for pattern in patterns:
        if re.search(pattern, html, re.IGNORECASE):
            return "✅ 3DS Detected"
    return "❌ No 3DS (2D)"


def detect_graphql(html: str) -> str:
    if re.search(r'/graphql|apollo-client|query\s*\{|mutation\s*\{', html, re.IGNORECASE):
        return "✅ GraphQL"
    return "❌ No GraphQL"


def detect_ssl(url: str) -> str:
    if url.startswith("https://"):
        return "✅ HTTPS (SSL)"
    return "⚠️ HTTP (No SSL)"


def detect_page_title(html: str) -> str:
    match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        return title[:50] + "..." if len(title) > 50 else title
    return "No Title"


def detect_description(html: str) -> str:
    match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE | re.DOTALL)
    if match:
        desc = match.group(1).strip()
        return desc[:60] + "..." if len(desc) > 60 else desc
    return "No Description"


def detect_server(headers: Dict) -> str:
    server = headers.get('Server', '')
    if server:
        return server[:30]
    return "Unknown"






async def fetch_site(url: str):
    session = await get_shared_session()
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    domain = urlparse(url).netloc
    

    if domain in domain_cache:
        cache_entry = domain_cache[domain]
        if datetime.now() - cache_entry["timestamp"] < timedelta(seconds=CACHE_DURATION_SECONDS):
            logger.info(f"Using cached result for {domain}")
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"], cache_entry.get("response_time", 0)
    
    if domain in concurrent_requests:
        while domain in concurrent_requests:
            await asyncio.sleep(0.5)
        if domain in domain_cache:
            cache_entry = domain_cache[domain]
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"], cache_entry.get("response_time", 0)
    
    concurrent_requests.add(domain)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    
    try:
        async with semaphore:
            start_time = time.time()
            async with session.get(url, headers=headers, timeout=15) as resp:
                text = await resp.text()
                status = resp.status
                resp_headers = dict(resp.headers)
                response_time = round((time.time() - start_time) * 1000)
                
                domain_cache[domain] = {
                    "status": status,
                    "html": text,
                    "headers": resp_headers,
                    "timestamp": datetime.now(),
                    "response_time": response_time
                }
                return status, text, resp_headers, response_time
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching {url}")
        return None, None, None, None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None, None, None, None
    finally:
        concurrent_requests.discard(domain)






def format_gate_response(
    url: str, 
    cms: str, 
    gateways: str, 
    captcha: str,
    cloudflare: str, 
    security: str, 
    graphql: str,
    status_code: int, 
    title: str, 
    description: str,
    server: str, 
    ssl: str, 
    user: str, 
    tier: str,
    response_time: int = None,
    frameworks: List[str] = None,
    analytics: List[str] = None,
    security_headers: Dict = None,
    social_links: Dict = None,
    email: str = None,
    phone: str = None,
    page_stats: Dict = None
) -> str:
    domain = urlparse(url).netloc
    

    if status_code == 200:
        status_display = f"✅ Online ({status_code})"
    elif status_code in [301, 302, 303, 307, 308]:
        status_display = f"🔄 Redirect ({status_code})"
    elif 400 <= status_code < 500:
        status_display = f"⚠️ Client Error ({status_code})"
    elif 500 <= status_code < 600:
        status_display = f"❌ Server Error ({status_code})"
    else:
        status_display = f"ℹ️ {status_code}"
    

    frameworks_text = ", ".join(frameworks) if frameworks else "None Detected"
    

    analytics_text = ", ".join(analytics) if analytics else "None Detected"
    

    social_text = ""
    if social_links:
        social_links_list = [f"{name} {emoji}" for name, emoji in social_links.items()]
        social_text = "\n".join([f"  ▸ {link}" for link in social_links_list]) if social_links_list else "  ▸ None"
    else:
        social_text = "  ▸ None"
    

    security_text = ""
    if security_headers:
        security_text = "\n".join([f"  ▸ {k}: {v}" for k, v in security_headers.items()])
    else:
        security_text = "  ▸ None"
    

    stats_text = ""
    if page_stats:
        stats_text = f"""
<a href='https://t.me/oggyproo'>⊀</a> <b>Images</b>     ↬ {page_stats['images']}
<a href='https://t.me/oggyproo'>⊀</a> <b>Links</b>       ↬ {page_stats['links']}
<a href='https://t.me/oggyproo'>⊀</a> <b>Scripts</b>      ↬ {page_stats['scripts']}
<a href='https://t.me/oggyproo'>⊀</a> <b>Styles</b>       ↬ {page_stats['styles']}
<a href='https://t.me/oggyproo'>⊀</a> <b>Forms</b>        ↬ {page_stats['forms']}
<a href='https://t.me/oggyproo'>⊀</a> <b>Meta Tags</b>    ↬ {page_stats['meta_tags']}"""
    

    time_text = f"{response_time}ms" if response_time else "N/A"
    
    return f"""
<b>𝐒𝐢𝐭𝐞 𝐋𝐨𝐨𝐤𝐮𝐩 𝐑𝐞𝐬𝐮𝐥𝐭𝐬</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐒𝐢𝐭𝐞</b> ➭ <code>{domain}</code>
<b>𝐒𝐭𝐚𝐭𝐮𝐬</b> ➭ {status_display}
<b>𝐓𝐢𝐦𝐞</b> ➭ {time_text}
<b>𝐓𝐢𝐭𝐥𝐞</b> ➭ <code>{title}</code>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐂𝐌𝐒</b> ➭ {cms}
<b>𝐅𝐫𝐚𝐦𝐞𝐰𝐨𝐫𝐤𝐬</b> ➭ {frameworks_text}
<b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲𝐬</b> ➭ {gateways}
<b>𝐀𝐧𝐚𝐥𝐲𝐭𝐢𝐜𝐬</b> ➭ {analytics_text}
<b>𝐒𝐞𝐫𝐯𝐞𝐫</b> ➭ {server}
<b>𝐒𝐒𝐋</b> ➭ {ssl}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲</b> ➭ {security}
<b>𝐂𝐚𝐩𝐭𝐜𝐡𝐚</b> ➭ {captcha}
<b>𝐂𝐥𝐨𝐮𝐝𝐟𝐥𝐚𝐫𝐞</b> ➭ {cloudflare}
<b>𝐆𝐫𝐚𝐩𝐡𝐐𝐋</b> ➭ {graphql}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐃𝐞𝐬𝐜𝐫𝐢𝐩𝐭𝐢𝐨𝐧</b> ➭ <i>{description}</i>
<b>𝐄𝐦𝐚𝐢𝐥</b> ➭ {email or 'None Detected'}
<b>𝐏𝐡𝐨𝐧𝐞</b> ➭ {phone or 'None Detected'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐏𝐚𝐠𝐞 𝐒𝐭𝐚𝐭𝐬</b>
{stats_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲 𝐇𝐞𝐚𝐝𝐞𝐫𝐬</b>
{security_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐒𝐨𝐜𝐢𝐚𝐥 𝐋𝐢𝐧𝐤𝐬</b>
{social_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>𝐔𝐬𝐞𝐫</b> ➭ {user} [{tier}]
<b>𝐃𝐞𝐯</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""






@check_lock
@rate_limit("gate")
async def handle_gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze a website and detect CMS, gateways, security features."""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "User"
    

    try:
        from plans import get_user_current_tier
        tier = get_user_current_tier(user_id)
    except:
        tier = "Free"
    
    if not context.args:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>𝐌𝐢𝐬𝐬𝐢𝐧𝐠 𝐔𝐑𝐋</b>
━━━━━━━━━━━━━━━━━━
<b>𝐔𝐬𝐚𝐠𝐞:</b>
<code>/gate example.com</code>

<b>𝐄𝐱𝐚𝐦𝐩𝐥𝐞:</b>
<code>/gate shopify.com</code>
━━━━━━━━━━━━━━━━━━
<b>𝐃𝐞𝐯</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    url = context.args[0]
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    progress = await update.message.reply_text(
        f"""
{E.FLY} <b>𝐒𝐜𝐚𝐧𝐧𝐢𝐧𝐠...</b>
━━━━━━━━━━━━━━━━━━
<b>𝐔𝐑𝐋</b> ➭ <code>{url}</code>
<i>Analyzing website...</i>
━━━━━━━━━━━━━━━━━━
<b>𝐃𝐞𝐯</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
    try:
        status_code, html, headers, response_time = await fetch_site(url)
        
        if status_code is None:
            await progress.edit_text(
                f"""
{E.ERROR} <b>𝐅𝐚𝐢𝐥𝐞𝐝 𝐓𝐨 𝐅𝐞𝐭𝐜𝐡</b>
━━━━━━━━━━━━━━━━━━
Could not fetch the site. Please check the URL and try again.
━━━━━━━━━━━━━━━━━━
<b>𝐃𝐞𝐯</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            return
        

        cms = detect_cms(html)
        gateways = detect_gateways(html)
        captcha = detect_captcha(html)
        cloudflare = detect_cloudflare(html, headers, status_code)
        security = detect_3ds(html)
        graphql = detect_graphql(html)
        ssl = detect_ssl(url)
        title = detect_page_title(html)
        description = detect_description(html)
        server = detect_server(headers)
        

        frameworks = detect_frameworks(html)
        analytics = detect_analytics(html)
        security_headers = detect_security_headers(headers)
        social_links = detect_social_links(html)
        email = detect_email(html)
        phone = detect_phone(html)
        page_stats = get_page_stats(html)
        

        user_display = f"@{username}" if username else user.first_name or "User"
        
        response = format_gate_response(
            url, cms, gateways, captcha,
            cloudflare, security, graphql,
            status_code, title, description,
            server, ssl, user_display, tier,
            response_time, frameworks, analytics,
            security_headers, social_links,
            email, phone, page_stats
        )
        
        await progress.edit_text(
            response,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        
    except Exception as e:
        logger.error(f"Gate command error: {e}")
        
        error_msg = str(e)
        if "Brotli" in error_msg or "brotli" in error_msg:
            error_msg = "Brotli compression not supported. Please install brotli: pip install brotli"
        
        await progress.edit_text(
            f"""
{E.ERROR} <b>𝐄𝐫𝐫𝐨𝐫</b>
━━━━━━━━━━━━━━━━━━
{error_msg}
━━━━━━━━━━━━━━━━━━
<b>𝐃𝐞𝐯</b> ➭ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )