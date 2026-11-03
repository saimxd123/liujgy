
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


TIMESTAMP_COLUMNS = [
    ("users", "premium_until"),
    ("keys", "expires_at"),
    ("payments", "created_at"),
    ("payments", "expires_at"),
    ("payments", "confirmed_at"),
    ("sites", "added_at"),
    ("sites", "last_checked"),
    ("site_health", "last_checked"),
    ("user_proxies", "added_at"),
    ("user_proxies", "last_tested"),
    ("groups", "added_at"),
    ("groups", "last_active"),
    ("premium_notifications", "sent_at"),
    ("check_history", "created_at"),
]


SERIAL_TABLES = [
    "check_history",
    "payments",
    "user_proxies",
    "sites",
    "redeemed_keys",
    "premium_notifications",
]

MIGRATION_VERSION_TS = '001_convert_timestamps'
MIGRATION_VERSION_SERIAL = '002_fix_serial_columns'




async def ensure_migration_table(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

async def is_migration_applied(pool, version: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM schema_migrations WHERE version = $1", version)
        return row is not None

async def mark_migration_applied(pool, version: str):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)




async def convert_timestamp_columns(pool):
    async with pool.acquire() as conn:
        for table, column in TIMESTAMP_COLUMNS:
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = $1
                )
            """, table)
            if not table_exists:
                logger.warning(f"Table {table} does not exist, skipping {column}")
                continue

            col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2
                )
            """, table, column)
            if not col_exists:
                logger.warning(f"Column {table}.{column} does not exist, skipping")
                continue

            data_type = await conn.fetchval("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2
            """, table, column)

            if data_type in ('timestamp without time zone', 'timestamp with time zone'):
                logger.info(f"{table}.{column} already has type {data_type}, skipping")
                continue

            logger.info(f"Converting {table}.{column} from {data_type} to TIMESTAMP")

            await conn.execute(f'UPDATE "{table}" SET "{column}" = NULL WHERE "{column}" = \'\'')
            try:
                await conn.execute(f'''
                    ALTER TABLE "{table}"
                    ALTER COLUMN "{column}" TYPE TIMESTAMP
                    USING "{column}"::TIMESTAMP
                ''')
                logger.info(f"Successfully converted {table}.{column} to TIMESTAMP")
            except Exception as e:
                error_msg = (f"Failed to convert {table}.{column} to TIMESTAMP: {e}. "
                             "Check for invalid timestamp strings in that column.")
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e




async def fix_serial_columns(pool):
    async with pool.acquire() as conn:
        for table in SERIAL_TABLES:

            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = $1
                )
            """, table)
            if not table_exists:
                logger.warning(f"Table {table} does not exist, skipping serial fix")
                continue


            col_info = await conn.fetchrow("""
                SELECT data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1 AND column_name = 'id'
            """, table)
            if not col_info:
                logger.warning(f"Table {table} has no 'id' column, skipping")
                continue

            data_type = col_info['data_type']
            column_default = col_info['column_default']


            if column_default and 'nextval' in column_default:
                logger.info(f"Table {table}.id already has a sequence default, skipping")
                continue


            if data_type not in ('integer', 'bigint'):
                logger.warning(f"Table {table}.id is {data_type}, not integer/bigint – skipping")
                continue

            logger.info(f"Fixing serial for table {table}.id")


            seq_name = f"{table}_id_seq"
            await conn.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}")


            max_id = await conn.fetchval(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
            if max_id == 0:
                await conn.execute(f"SELECT setval('{seq_name}', 1, false)")
            else:
                await conn.execute(f"SELECT setval('{seq_name}', {max_id}, true)")


            if col_info['is_nullable'] == 'YES':
                await conn.execute(f'ALTER TABLE "{table}" ALTER COLUMN id SET NOT NULL')

            await conn.execute(f'ALTER TABLE "{table}" ALTER COLUMN id SET DEFAULT nextval(\'{seq_name}\')')


            await conn.execute(f"ALTER SEQUENCE {seq_name} OWNED BY {table}.id")

            logger.info(f"Successfully fixed serial for table {table}.id")




async def run_migration(pool):
    await ensure_migration_table(pool)


    if await is_migration_applied(pool, MIGRATION_VERSION_TS):
        logger.info(f"Migration {MIGRATION_VERSION_TS} already applied, skipping.")
    else:
        logger.info(f"Applying migration {MIGRATION_VERSION_TS}...")
        await convert_timestamp_columns(pool)
        await mark_migration_applied(pool, MIGRATION_VERSION_TS)
        logger.info(f"Migration {MIGRATION_VERSION_TS} applied successfully.")


    if await is_migration_applied(pool, MIGRATION_VERSION_SERIAL):
        logger.info(f"Migration {MIGRATION_VERSION_SERIAL} already applied, skipping.")
    else:
        logger.info(f"Applying migration {MIGRATION_VERSION_SERIAL}...")
        await fix_serial_columns(pool)
        await mark_migration_applied(pool, MIGRATION_VERSION_SERIAL)
        logger.info(f"Migration {MIGRATION_VERSION_SERIAL} applied successfully.")