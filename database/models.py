

SCHEMA = """

-- ==========================================
-- USERS
-- ==========================================
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    premium_until TEXT,
    banned INTEGER DEFAULT 0
);

-- ==========================================
-- ADMINS
-- ==========================================
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- KEYS (Premium Keys)
-- ==========================================
CREATE TABLE IF NOT EXISTS keys (
    key TEXT PRIMARY KEY,
    days INTEGER,
    redeem_limit INTEGER,
    redeemed_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT
);

-- ==========================================
-- REDEEMED KEYS
-- ==========================================
CREATE TABLE IF NOT EXISTS redeemed_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    user_id INTEGER,
    redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(key, user_id)
);

-- ==========================================
-- SITES (GLOBAL — Admin Only)
-- ==========================================
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    gateway TEXT,
    price REAL DEFAULT 0,
    status TEXT DEFAULT 'Working',
    added_by INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP
);

-- ==========================================
-- SITE HEALTH (Tracking site performance)
-- ==========================================
CREATE TABLE IF NOT EXISTS site_health (
    site_url TEXT PRIMARY KEY,
    last_checked TIMESTAMP,
    failures INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 1.0,
    total_checks INTEGER DEFAULT 0,
    status TEXT DEFAULT 'unknown'
);

-- ==========================================
-- USER PROXIES (Per User)
-- ==========================================
CREATE TABLE IF NOT EXISTS user_proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    proxy TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    response_time REAL DEFAULT 0,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_tested TIMESTAMP,
    UNIQUE(user_id, proxy)
);

-- ==========================================
-- BOT SETTINGS
-- ==========================================
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Insert default settings
INSERT OR IGNORE INTO bot_settings (key, value) VALUES
    ('locked', 'false'),
    ('speed', '7'),
    ('auto_health', 'false'),
    ('msh_speed', '10');

-- ==========================================
-- CHECK HISTORY (For user stats)
-- ==========================================
CREATE TABLE IF NOT EXISTS check_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    card_number TEXT,
    bin TEXT,
    status TEXT,
    message TEXT,
    gateway TEXT,
    time_taken REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_check_history_user_id ON check_history(user_id);
CREATE INDEX IF NOT EXISTS idx_check_history_created_at ON check_history(created_at);
CREATE INDEX IF NOT EXISTS idx_check_history_status ON check_history(status);
CREATE INDEX IF NOT EXISTS idx_check_history_gateway ON check_history(gateway);

-- ==========================================
-- GATE STATUS (Toggle gates on/off)
-- ==========================================
CREATE TABLE IF NOT EXISTS gate_status (
    gate_name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1
);

-- Insert default gates with enabled=1
INSERT OR IGNORE INTO gate_status (gate_name, enabled) VALUES
    ('shopify', 1),
    ('shopify_mass', 1),
    ('stripe_auth', 1),
    ('stripe_auth_mass', 1);   -- ✅ NO TRAILING COMMA

-- ==========================================
-- GROUPS
-- ==========================================
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP
);

-- ==========================================
-- PAYMENTS (For /buy command)
-- ==========================================
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    tx_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    confirmed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at);

-- ==========================================
-- PREMIUM NOTIFICATIONS (Track sent notifications)
-- ==========================================
CREATE TABLE IF NOT EXISTS premium_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    notification_type TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, notification_type)
);

"""