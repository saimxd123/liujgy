

from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes
from faker import Faker
import random
from difflib import get_close_matches

from logger import get_logger
from ui.emojis import PremiumEmoji as E
from utils.decorators import not_banned, log_command
from utils.lock_check import check_lock
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)


COUNTRIES_DB = {

    'pk': {'name': 'Pakistan', 'locale': 'en_PK', 'emoji': '🇵🇰', 'aliases': ['pakistan', 'paki', 'pk'], 'currency': 'PKR', 'phone_code': '+92', 'postal_format': '#####'},
    'in': {'name': 'India', 'locale': 'en_IN', 'emoji': '🇮🇳', 'aliases': ['india', 'ind', 'in'], 'currency': 'INR', 'phone_code': '+91', 'postal_format': '######'},
    'bd': {'name': 'Bangladesh', 'locale': 'bn_BD', 'emoji': '🇧🇩', 'aliases': ['bangladesh', 'bd'], 'currency': 'BDT', 'phone_code': '+880', 'postal_format': '####'},
    'lk': {'name': 'Sri Lanka', 'locale': 'si_LK', 'emoji': '🇱🇰', 'aliases': ['srilanka', 'sri lanka', 'lk'], 'currency': 'LKR', 'phone_code': '+94', 'postal_format': '#####'},
    'np': {'name': 'Nepal', 'locale': 'ne_NP', 'emoji': '🇳🇵', 'aliases': ['nepal', 'np'], 'currency': 'NPR', 'phone_code': '+977', 'postal_format': '#####'},
    

    'us': {'name': 'United States', 'locale': 'en_US', 'emoji': '🇺🇸', 'aliases': ['usa', 'us', 'america', 'united states'], 'currency': 'USD', 'phone_code': '+1', 'postal_format': '#####-####'},
    'ca': {'name': 'Canada', 'locale': 'en_CA', 'emoji': '🇨🇦', 'aliases': ['canada', 'ca'], 'currency': 'CAD', 'phone_code': '+1', 'postal_format': 'A#A #A#'},
    'mx': {'name': 'Mexico', 'locale': 'es_MX', 'emoji': '🇲🇽', 'aliases': ['mexico', 'mx'], 'currency': 'MXN', 'phone_code': '+52', 'postal_format': '#####'},
    

    'uk': {'name': 'United Kingdom', 'locale': 'en_GB', 'emoji': '🇬🇧', 'aliases': ['uk', 'united kingdom', 'britain', 'england', 'gb'], 'currency': 'GBP', 'phone_code': '+44', 'postal_format': 'AA# #AA'},
    'de': {'name': 'Germany', 'locale': 'de_DE', 'emoji': '🇩🇪', 'aliases': ['germany', 'de', 'deutschland'], 'currency': 'EUR', 'phone_code': '+49', 'postal_format': '#####'},
    'fr': {'name': 'France', 'locale': 'fr_FR', 'emoji': '🇫🇷', 'aliases': ['france', 'fr'], 'currency': 'EUR', 'phone_code': '+33', 'postal_format': '#####'},
    'it': {'name': 'Italy', 'locale': 'it_IT', 'emoji': '🇮🇹', 'aliases': ['italy', 'it'], 'currency': 'EUR', 'phone_code': '+39', 'postal_format': '#####'},
    'es': {'name': 'Spain', 'locale': 'es_ES', 'emoji': '🇪🇸', 'aliases': ['spain', 'es'], 'currency': 'EUR', 'phone_code': '+34', 'postal_format': '#####'},
    'pt': {'name': 'Portugal', 'locale': 'pt_PT', 'emoji': '🇵🇹', 'aliases': ['portugal', 'pt'], 'currency': 'EUR', 'phone_code': '+351', 'postal_format': '####-###'},
    'nl': {'name': 'Netherlands', 'locale': 'nl_NL', 'emoji': '🇳🇱', 'aliases': ['netherlands', 'holland', 'nl'], 'currency': 'EUR', 'phone_code': '+31', 'postal_format': '#### AA'},
    'se': {'name': 'Sweden', 'locale': 'sv_SE', 'emoji': '🇸🇪', 'aliases': ['sweden', 'se'], 'currency': 'SEK', 'phone_code': '+46', 'postal_format': '### ##'},
    'no': {'name': 'Norway', 'locale': 'no_NO', 'emoji': '🇳🇴', 'aliases': ['norway', 'no'], 'currency': 'NOK', 'phone_code': '+47', 'postal_format': '####'},
    'dk': {'name': 'Denmark', 'locale': 'da_DK', 'emoji': '🇩🇰', 'aliases': ['denmark', 'dk'], 'currency': 'DKK', 'phone_code': '+45', 'postal_format': '####'},
    'fi': {'name': 'Finland', 'locale': 'fi_FI', 'emoji': '🇫🇮', 'aliases': ['finland', 'fi'], 'currency': 'EUR', 'phone_code': '+358', 'postal_format': '#####'},
    'ie': {'name': 'Ireland', 'locale': 'en_IE', 'emoji': '🇮🇪', 'aliases': ['ireland', 'ie'], 'currency': 'EUR', 'phone_code': '+353', 'postal_format': '####'},
    'pl': {'name': 'Poland', 'locale': 'pl_PL', 'emoji': '🇵🇱', 'aliases': ['poland', 'pl'], 'currency': 'PLN', 'phone_code': '+48', 'postal_format': '##-###'},
    'ru': {'name': 'Russia', 'locale': 'ru_RU', 'emoji': '🇷🇺', 'aliases': ['russia', 'ru'], 'currency': 'RUB', 'phone_code': '+7', 'postal_format': '######'},
    'gr': {'name': 'Greece', 'locale': 'el_GR', 'emoji': '🇬🇷', 'aliases': ['greece', 'gr'], 'currency': 'EUR', 'phone_code': '+30', 'postal_format': '### ##'},
    'tr': {'name': 'Turkey', 'locale': 'tr_TR', 'emoji': '🇹🇷', 'aliases': ['turkey', 'tr'], 'currency': 'TRY', 'phone_code': '+90', 'postal_format': '#####'},
    

    'cn': {'name': 'China', 'locale': 'zh_CN', 'emoji': '🇨🇳', 'aliases': ['china', 'cn', 'prc'], 'currency': 'CNY', 'phone_code': '+86', 'postal_format': '######'},
    'jp': {'name': 'Japan', 'locale': 'ja_JP', 'emoji': '🇯🇵', 'aliases': ['japan', 'jp'], 'currency': 'JPY', 'phone_code': '+81', 'postal_format': '###-####'},
    'kr': {'name': 'South Korea', 'locale': 'ko_KR', 'emoji': '🇰🇷', 'aliases': ['korea', 'kr', 'south korea'], 'currency': 'KRW', 'phone_code': '+82', 'postal_format': '#####'},
    'ph': {'name': 'Philippines', 'locale': 'en_PH', 'emoji': '🇵🇭', 'aliases': ['philippines', 'ph'], 'currency': 'PHP', 'phone_code': '+63', 'postal_format': '####'},
    'vn': {'name': 'Vietnam', 'locale': 'vi_VN', 'emoji': '🇻🇳', 'aliases': ['vietnam', 'vn'], 'currency': 'VND', 'phone_code': '+84', 'postal_format': '######'},
    'th': {'name': 'Thailand', 'locale': 'th_TH', 'emoji': '🇹🇭', 'aliases': ['thailand', 'th'], 'currency': 'THB', 'phone_code': '+66', 'postal_format': '#####'},
    'id': {'name': 'Indonesia', 'locale': 'id_ID', 'emoji': '🇮🇩', 'aliases': ['indonesia', 'id'], 'currency': 'IDR', 'phone_code': '+62', 'postal_format': '#####'},
    'sa': {'name': 'Saudi Arabia', 'locale': 'ar_SA', 'emoji': '🇸🇦', 'aliases': ['saudi', 'saudi arabia', 'ksa', 'sa'], 'currency': 'SAR', 'phone_code': '+966', 'postal_format': '#####'},
    'ae': {'name': 'UAE', 'locale': 'ar_AE', 'emoji': '🇦🇪', 'aliases': ['uae', 'united arab emirates', 'ae'], 'currency': 'AED', 'phone_code': '+971', 'postal_format': '#####'},
    'my': {'name': 'Malaysia', 'locale': 'en_US', 'emoji': '🇲🇾', 'aliases': ['malaysia', 'my', 'malesia', 'malay'], 'currency': 'MYR', 'phone_code': '+60', 'postal_format': '#####', 'cities': ['Kuala Lumpur', 'George Town', 'Johor Bahru', 'Ipoh', 'Kuching', 'Kota Kinabalu', 'Shah Alam', 'Malacca City']},
    'sg': {'name': 'Singapore', 'locale': 'en_US', 'emoji': '🇸🇬', 'aliases': ['singapore', 'sg', 'sing'], 'currency': 'SGD', 'phone_code': '+65', 'postal_format': '######', 'cities': ['Singapore', 'Jurong East', 'Woodlands', 'Tampines', 'Bedok', 'Ang Mo Kio']},
    

    'ng': {'name': 'Nigeria', 'locale': 'en_NG', 'emoji': '🇳🇬', 'aliases': ['nigeria', 'ng'], 'currency': 'NGN', 'phone_code': '+234', 'postal_format': '######'},
    'za': {'name': 'South Africa', 'locale': 'en_ZA', 'emoji': '🇿🇦', 'aliases': ['south africa', 'za', 'rsa'], 'currency': 'ZAR', 'phone_code': '+27', 'postal_format': '####'},
    'eg': {'name': 'Egypt', 'locale': 'ar_EG', 'emoji': '🇪🇬', 'aliases': ['egypt', 'eg'], 'currency': 'EGP', 'phone_code': '+20', 'postal_format': '#####'},
    'ke': {'name': 'Kenya', 'locale': 'en_KE', 'emoji': '🇰🇪', 'aliases': ['kenya', 'ke'], 'currency': 'KES', 'phone_code': '+254', 'postal_format': '#####'},
    'gh': {'name': 'Ghana', 'locale': 'en_GH', 'emoji': '🇬🇭', 'aliases': ['ghana', 'gh'], 'currency': 'GHS', 'phone_code': '+233', 'postal_format': '#####'},
    'ma': {'name': 'Morocco', 'locale': 'ar_MA', 'emoji': '🇲🇦', 'aliases': ['morocco', 'ma'], 'currency': 'MAD', 'phone_code': '+212', 'postal_format': '#####'},
    

    'br': {'name': 'Brazil', 'locale': 'pt_BR', 'emoji': '🇧🇷', 'aliases': ['brazil', 'br'], 'currency': 'BRL', 'phone_code': '+55', 'postal_format': '#####-###'},
    'ar': {'name': 'Argentina', 'locale': 'es_AR', 'emoji': '🇦🇷', 'aliases': ['argentina', 'ar'], 'currency': 'ARS', 'phone_code': '+54', 'postal_format': '####'},
    'co': {'name': 'Colombia', 'locale': 'es_CO', 'emoji': '🇨🇴', 'aliases': ['colombia', 'co'], 'currency': 'COP', 'phone_code': '+57', 'postal_format': '######'},
    'cl': {'name': 'Chile', 'locale': 'es_CL', 'emoji': '🇨🇱', 'aliases': ['chile', 'cl'], 'currency': 'CLP', 'phone_code': '+56', 'postal_format': '#######'},
    'pe': {'name': 'Peru', 'locale': 'es_PE', 'emoji': '🇵🇪', 'aliases': ['peru', 'pe'], 'currency': 'PEN', 'phone_code': '+51', 'postal_format': '#####'},
    

    'au': {'name': 'Australia', 'locale': 'en_AU', 'emoji': '🇦🇺', 'aliases': ['australia', 'au'], 'currency': 'AUD', 'phone_code': '+61', 'postal_format': '####'},
    'nz': {'name': 'New Zealand', 'locale': 'en_NZ', 'emoji': '🇳🇿', 'aliases': ['new zealand', 'nz'], 'currency': 'NZD', 'phone_code': '+64', 'postal_format': '####'},
}


ALL_ALIASES = {}
for code, data in COUNTRIES_DB.items():
    for alias in data['aliases']:
        ALL_ALIASES[alias.lower()] = code


def detect_country(user_input):
    """Smart auto-detection with typo handling"""
    if not user_input:
        return 'us'
    
    user_input = user_input.lower().strip()
    

    if user_input in ALL_ALIASES:
        return ALL_ALIASES[user_input]
    

    for alias, code in ALL_ALIASES.items():
        if user_input in alias or alias in user_input:
            return code
    

    matches = get_close_matches(user_input, list(ALL_ALIASES.keys()), n=1, cutoff=0.6)
    if matches:
        return ALL_ALIASES[matches[0]]
    
    return None


def generate_postal_code(country_code):
    """Generate valid postal code based on country format"""
    country_data = COUNTRIES_DB.get(country_code, COUNTRIES_DB['pk'])
    format_str = country_data.get('postal_format', '#####')
    
    postal = ''
    for char in format_str:
        if char == '#':
            postal += str(random.randint(0, 9))
        elif char == 'A':
            postal += random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        elif char == 'a':
            postal += random.choice('abcdefghijklmnopqrstuvwxyz')
        else:
            postal += char
    
    return postal


def generate_phone(country_code):
    """Generate realistic phone number with country code"""
    country_data = COUNTRIES_DB.get(country_code, COUNTRIES_DB['pk'])
    
    formats = {
        'pk': f"{country_data['phone_code']} 3{random.randint(0,9)}{random.randint(0,9)}-{random.randint(1000000, 9999999)}",
        'us': f"{country_data['phone_code']} ({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}",
        'uk': f"{country_data['phone_code']} {random.randint(7000, 7999)} {random.randint(100000, 999999)}",
        'in': f"{country_data['phone_code']} {random.randint(60000, 99999)} {random.randint(10000, 99999)}",
        'de': f"{country_data['phone_code']} {random.randint(100, 999)} {random.randint(1000000, 9999999)}",
        'fr': f"{country_data['phone_code']} {random.randint(1, 9)}{random.randint(0, 9)} {random.randint(10, 99)} {random.randint(10, 99)} {random.randint(10, 99)} {random.randint(10, 99)}",
        'jp': f"{country_data['phone_code']} {random.randint(10, 99)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'cn': f"{country_data['phone_code']} {random.randint(10, 99)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'au': f"{country_data['phone_code']} {random.randint(2, 9)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
        'ca': f"{country_data['phone_code']} ({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}",
        'br': f"{country_data['phone_code']} ({random.randint(10, 99)}) {random.randint(90000, 99999)}-{random.randint(1000, 9999)}",
        'ng': f"{country_data['phone_code']} 80{random.randint(10, 99)}-{random.randint(1000, 9999)}",
        'bd': f"{country_data['phone_code']} 1{random.randint(0,9)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'ph': f"{country_data['phone_code']} 9{random.randint(10, 99)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'ae': f"{country_data['phone_code']} {random.randint(50, 59)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
        'sa': f"{country_data['phone_code']} 5{random.randint(0,9)}{random.randint(0,9)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
        'ru': f"{country_data['phone_code']} ({random.randint(900, 999)}) {random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(10, 99)}",
        'tr': f"{country_data['phone_code']} {random.randint(500, 599)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
        'my': f"{country_data['phone_code']} {random.randint(10, 19)}-{random.randint(100, 999)} {random.randint(1000, 9999)}",
        'sg': f"{country_data['phone_code']} {random.randint(8000, 9999)} {random.randint(1000, 9999)}",
        'vn': f"{country_data['phone_code']} {random.randint(90, 99)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
        'th': f"{country_data['phone_code']} {random.randint(80, 99)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}",
        'id': f"{country_data['phone_code']} {random.randint(81, 89)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'kr': f"{country_data['phone_code']} {random.randint(10, 11)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'il': f"{country_data['phone_code']} {random.randint(50, 59)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}",
        'ir': f"{country_data['phone_code']} {random.randint(900, 999)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
        'za': f"{country_data['phone_code']} {random.randint(70, 79)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
        'eg': f"{country_data['phone_code']} {random.randint(100, 199)} {random.randint(1000, 9999)}",
        'ke': f"{country_data['phone_code']} 7{random.randint(10, 99)} {random.randint(100000, 999999)}",
        'gh': f"{country_data['phone_code']} {random.randint(20, 29)} {random.randint(1000, 9999)}",
        'ma': f"{country_data['phone_code']} 6{random.randint(0,9)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
        'ar': f"{country_data['phone_code']} {random.randint(10, 19)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
        'co': f"{country_data['phone_code']} 3{random.randint(0,9)}0 {random.randint(1000, 9999)}",
        'cl': f"{country_data['phone_code']} 9 {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
        'pe': f"{country_data['phone_code']} 9{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
        'nz': f"{country_data['phone_code']} {random.randint(20, 29)} {random.randint(100, 999)} {random.randint(1000, 9999)}",
    }
    
    return formats.get(country_code, f"{country_data['phone_code']} {random.randint(10000000, 99999999)}")


def generate_email(name):
    """Generate professional email from name"""
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'protonmail.com', 
               'icloud.com', 'mail.com', 'yandex.com', 'zoho.com']
    
    name_parts = name.lower().split()
    first = name_parts[0]
    last = name_parts[-1] if len(name_parts) > 1 else first
    
    formats = [
        f"{first}.{last}@{random.choice(domains)}",
        f"{first}{last}@{random.choice(domains)}",
        f"{first}_{last}@{random.choice(domains)}",
        f"{first}{random.randint(1, 99)}@{random.choice(domains)}",
        f"{first[0]}{last}@{random.choice(domains)}",
    ]
    
    return random.choice(formats)


def generate_identity(country_code='pk'):
    """Generate clean fake identity"""
    country_data = COUNTRIES_DB.get(country_code, COUNTRIES_DB['pk'])
    

    try:
        fake = Faker(country_data['locale'])
    except:
        fake = Faker('en_US')
    

    name = fake.name()
    gender = random.choice(['Male', 'Female'])
    dob = fake.date_of_birth(minimum_age=18, maximum_age=70).strftime('%Y-%m-%d')
    

    if 'cities' in country_data and country_data['cities']:
        city = random.choice(country_data['cities'])
        street = fake.street_address()
        state = fake.state() if hasattr(fake, 'state') else city
    else:
        street = fake.street_address()
        city = fake.city()
        state = fake.state() if hasattr(fake, 'state') else fake.city()
    
    postal = generate_postal_code(country_code)
    

    phone = generate_phone(country_code)
    email = generate_email(name)
    
    return {
        'full_name': name,
        'gender': gender,
        'date_of_birth': dob,
        'street_address': street,
        'city': city,
        'state': state,
        'postal_code': postal,
        'phone': phone,
        'email': email,
        'country': f"{country_data['name']} {country_data['emoji']}",
        'country_code': country_code.upper(),
        'currency': country_data['currency'],
        'phone_code': country_data['phone_code']
    }


@check_lock
@not_banned
@log_command
async def fake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate fake identity for a country."""
    user = update.effective_user
    

    user_input = ' '.join(context.args) if context.args else ''
    
    if not user_input:

        all_countries = []
        for code, data in COUNTRIES_DB.items():
            all_countries.append(f"• <code>{code}</code> - {data['name']} {data['emoji']}")
        

        chunk_size = 20
        chunks = [all_countries[i:i+chunk_size] for i in range(0, len(all_countries), chunk_size)]
        
        text = f"""
{E.INFO} ⌠ 𝙁𝘼𝙆𝙀 𝙄𝘿𝙀𝙉𝙏𝙄𝙏𝙔 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/fake &lt;country&gt;</code>

<b>Examples:</b>
<code>/fake pakistan</code>
<code>/fake us</code>
<code>/fake uk</code>
<code>/fake malaysia</code>
<code>/fake malesia</code>  ← Auto-corrects!

<b>Supported Countries ({len(COUNTRIES_DB)} total):</b>
{chr(10).join(all_countries)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    detected_code = detect_country(user_input)
    
    if not detected_code:

        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝘾𝙊𝙐𝙉𝙏𝙍𝙔 𝙉𝙊𝙏 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Could not detect country from "<code>{user_input}</code>"

<b>Try:</b>
<code>/fake pakistan</code>
<code>/fake us</code>
<code>/fake uk</code>

Use <code>/fake</code> alone to see all <code>{len(COUNTRIES_DB)}</code> countries.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    identity = generate_identity(detected_code)
    

    text = f"""
{E.CAR} ⌠ 𝙁𝘼𝙆𝙀 𝙄𝘿𝙀𝙉𝙏𝙄𝙏𝙔 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Full Name</b> ➠ <code>{identity['full_name']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Gender</b> ➠ <code>{identity['gender']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>DOB</b> ➠ <code>{identity['date_of_birth']}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Street</b> ➠ <code>{identity['street_address']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>City</b> ➠ <code>{identity['city']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>State</b> ➠ <code>{identity['state']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Postal</b> ➠ <code>{identity['postal_code']}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Phone</b> ➠ <code>{identity['phone']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Email</b> ➠ <code>{identity['email']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Country</b> ➠ <code>{identity['country']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Currency</b> ➠ <code>{identity['currency']}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
    logger.info(f"/fake {detected_code} -> {user.id}")


@check_lock
@not_banned
@log_command
async def fakehelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help for fake identity generator with all countries."""
    

    all_countries = []
    for code, data in COUNTRIES_DB.items():
        all_countries.append(f"• <code>{code}</code> - {data['name']} {data['emoji']}")
    
    text = f"""
{E.INFO} ⌠ 𝙁𝘼𝙆𝙀 𝙄𝘿 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙊𝙍 𝙃𝙀𝙇𝙋 ⌡
━━━━━━━━━━━━━━━━━━
<b>Command:</b> <code>/fake &lt;country&gt;</code>

<b>Examples:</b>
<code>/fake pakistan</code>
<code>/fake us</code>
<code>/fake uk</code>
<code>/fake malaysia</code>
<code>/fake malesia</code>  ← Auto-corrects typos!

<b>Supported Countries ({len(COUNTRIES_DB)} total):</b>
{chr(10).join(all_countries)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


def register_fake(app: Application):
    """Register fake identity generator commands."""
    app.add_handler(CommandHandler("fake", fake))
    app.add_handler(CommandHandler("fakehelp", fakehelp))
    logger.info("✅ Fake identity generator handlers registered.")