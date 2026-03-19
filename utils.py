import sqlite3
import datetime
import logging
import json
import os
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple, Any
import re
import config

# Try to import psycopg 3
try:
    import psycopg
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, wait_exponential
except ImportError:
    psycopg = None

DB_NAME = "history.db"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def extract_tweet_id(url: str) -> str:
    """
    Extract tweet ID from various input formats.
    Supports:
    - Standard URLs: x.com/user/status/123456
    - Intent URLs: twitter.com/intent/tweet?in_reply_to=123456
    - Intent URLs: x.com/intent/like?tweet_id=123456
    - Raw IDs: 1234567890123456789
    """
    # 1. Check for standard status URL (most common)
    # Matches: .../status/123456...
    status_match = re.search(r'/status/(\d+)', url)
    if status_match:
        return status_match.group(1)
        
    # 2. Check for intent URL (in_reply_to parameter)
    # Matches: ...in_reply_to=123456...
    intent_match = re.search(r'in_reply_to=(\d+)', url)
    if intent_match:
        return intent_match.group(1)

    # 3. Check for intent URL (tweet_id parameter)
    # Matches: ...tweet_id=123456...
    tweet_id_match = re.search(r'tweet_id=(\d+)', url)
    if tweet_id_match:
        return tweet_id_match.group(1)
        
    # 4. Check if the input is just a raw ID (sequence of 15-20 digits)
    # We use a range 15-20 to be safe for past/future IDs
    if re.match(r'^\d{15,20}$', url.strip()):
        return url.strip()
        
    raise ValueError(f"Could not extract Tweet ID from: {url}")


pg_pool = None

def init_pool():
    global pg_pool
    db_url = os.getenv("DATABASE_URL")
    if db_url and psycopg:
        try:
            # psycopg 3 connection pool implementation
            pg_pool = ConnectionPool(
                conninfo=db_url,
                min_size=1, 
                max_size=20,
                timeout=10,  # seconds to wait for a connection from the pool
                max_idle=300, # Discard connections idle for more than 5 minutes
                reconnect_timeout=10.0,
                kwargs={"row_factory": dict_row,
                        "connect_timeout": 10}  # TCP-level connect timeout
            )
            # Test that we can actually get a working connection
            with pg_pool.connection(timeout=5) as test_conn:
                test_conn.execute("SELECT 1")
            logger.info("PostgreSQL Connection Pool Initialized (with idle management)")
        except Exception as e:
            logger.error(f"Failed to init Postgres pool: {e}. Falling back to SQLite.")
            pg_pool = None

def get_db_type():
    # Only return postgres if we successfully established a pool
    return "postgres" if pg_pool else "sqlite"

def get_placeholder():
    return "%s" if get_db_type() == "postgres" else "?"

@contextmanager
def get_db_connection():
    conn = None
    try:
        # Use Pool if available
        if pg_pool:
            with pg_pool.connection(timeout=10) as pg_conn:
                yield pg_conn
                pg_conn.commit()
            return  # connection is automatically returned to pool
        # Fallback to SQLite
        else:
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass # Connection likely already closed
        raise e
    finally:
        if conn and not pg_pool:
            conn.close() # Close SQLite only

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def init_db():
    """Initialize the database with necessary tables."""
    db_type = get_db_type()
    
    # DDL Differences
    if db_type == "postgres":
        primary_key = "SERIAL PRIMARY KEY"
        text_type = "TEXT"
        timestamp_default = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    else:
        primary_key = "INTEGER PRIMARY KEY AUTOINCREMENT"
        text_type = "TEXT"
        timestamp_default = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"

    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Users Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS users (
                id {primary_key},
                username {text_type} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                credits INTEGER DEFAULT 50,
                referral_code {text_type} UNIQUE,
                referred_by INTEGER,
                created_at {timestamp_default},
                FOREIGN KEY (referred_by) REFERENCES users(id)
            )
        ''')

        # Migration: Add credits, referral_code, referred_by columns if not exists
        try:
            c.execute("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 50")
            if pg_pool: conn.commit()
            logger.info("Migrated: Added credits column to users table")
        except Exception:
            if pg_pool: conn.rollback()
            
        try:
            c.execute("ALTER TABLE users ADD COLUMN referral_code TEXT UNIQUE")
            if pg_pool: conn.commit()
            logger.info("Migrated: Added referral_code column to users table")
        except Exception:
            if pg_pool: conn.rollback()
            
        try:
            c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER REFERENCES users(id)")
            if pg_pool: conn.commit()
            logger.info("Migrated: Added referred_by column to users table")
        except Exception:
            if pg_pool: conn.rollback()



        # History Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS history (
                id {primary_key},
                user_id INTEGER,
                tweet_id {text_type} NOT NULL,
                tweet_text {text_type},
                reply_text {text_type} NOT NULL,
                status {text_type} DEFAULT 'posted',
                timestamp {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Migration: Add tweet_text to history if it doesn't exist (SQLite only mostly, Postgres handles differently)
        if db_type == "sqlite":
            try:
                c.execute("SELECT tweet_text FROM history LIMIT 1")
            except sqlite3.OperationalError:
                logger.info("Migrating history table: adding tweet_text column")
                c.execute("ALTER TABLE history ADD COLUMN tweet_text TEXT")
        else:
            # Postgres check column
            try:
                c.execute("SELECT tweet_text FROM history LIMIT 1")
            except psycopg.Error:
                conn.rollback()
                logger.info("Migrating history table: adding tweet_text column")
                c.execute("ALTER TABLE history ADD COLUMN tweet_text TEXT")
                conn.commit()
        
        # Queue Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS queue (
                id {primary_key},
                user_id INTEGER,
                tweet_id {text_type} NOT NULL,
                tweet_text {text_type},
                reply_text {text_type} NOT NULL,
                created_at {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Stats Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS stats (
                id {primary_key},
                user_id INTEGER,
                date DATE NOT NULL,
                count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                scraped_count INTEGER DEFAULT 0,
                generated_count INTEGER DEFAULT 0,
                UNIQUE(user_id, date),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Migration: Add new stats columns if they don't exist
        try:
            c.execute("SELECT scraped_count FROM stats LIMIT 1")
        except (sqlite3.OperationalError, psycopg.Error if psycopg else Exception):
            if pg_pool: conn.rollback()
            logger.info("Migrating stats table: adding scraped_count and generated_count")
            try:
                c.execute("ALTER TABLE stats ADD COLUMN scraped_count INTEGER DEFAULT 0")
                c.execute("ALTER TABLE stats ADD COLUMN generated_count INTEGER DEFAULT 0")
                if pg_pool: conn.commit()
            except Exception as e:
                logger.error(f"Migration failed: {e}")
                if pg_pool: conn.rollback()

        # Settings Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                posting_credentials {text_type},
                scraping_credentials {text_type},
                gemini_api_key {text_type},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Logs Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS logs (
                id {primary_key},
                user_id INTEGER,
                message {text_type} NOT NULL,
                level {text_type} DEFAULT 'INFO',
                timestamp {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Transactions Table
        c.execute(f'''
            CREATE TABLE IF NOT EXISTS transactions (
                id {primary_key},
                user_id INTEGER,
                reference {text_type} UNIQUE NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                credits_added INTEGER NOT NULL,
                status {text_type} DEFAULT 'pending',
                created_at {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        logger.info("Database initialized successfully.")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def get_user(username: str) -> Optional[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT * FROM users WHERE username = {ph}", (username,))
        row = c.fetchone()
        if row:
            # Handle both Postgres RealDictCursor and SQLite sqlite3.Row
            return dict(row)
    return None

import secrets
import string

def generate_referral_code(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))

def get_user_by_referral_code(code: str) -> Optional[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT * FROM users WHERE referral_code = {ph}", (code,))
        row = c.fetchone()
        if row:
            return dict(row)
    return None

def create_user(username: str, password: str, referred_by: Optional[int] = None):
    password_hash = get_password_hash(password)
    referral_code = generate_referral_code()
    
    # Ensure unique referral code (basic retry)
    for _ in range(5):
        if not get_user_by_referral_code(referral_code):
            break
        referral_code = generate_referral_code()

    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        # Initial credits = 50
        c.execute(f"INSERT INTO users (username, password_hash, credits, referral_code, referred_by) VALUES ({ph}, {ph}, 50, {ph}, {ph})", 
                  (username, password_hash, referral_code, referred_by))

def get_user_referrals(user_id: int) -> List[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT id, username, created_at FROM users WHERE referred_by = {ph} ORDER BY created_at DESC", (user_id,))
        rows = c.fetchall()
        return [dict(row) for row in rows]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def get_user_credits(user_id: int) -> int:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT credits FROM users WHERE id = {ph}", (user_id,))
        row = c.fetchone()
        return row['credits'] if row else 0

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def deduct_credits(user_id: int, amount: int) -> bool:
    """
    Deduct credits from user. Returns True if successful, False if insufficient funds.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        # Check balance first
        c.execute(f"SELECT credits FROM users WHERE id = {ph}", (user_id,))
        row = c.fetchone()
        if not row or row['credits'] < amount:
            return False
            
        # Deduct
        c.execute(f"UPDATE users SET credits = credits - {amount} WHERE id = {ph}", (user_id,))
        return True

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def add_credits(username: str, amount: int) -> bool:
    """
    Add credits to a user by username.
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        # Check if user exists first to be safe, or just update
        # Use LOWER() for case-insensitive matching
        c.execute(f"UPDATE users SET credits = credits + {amount} WHERE LOWER(username) = LOWER({ph})", (username,))
        return c.rowcount > 0

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def create_transaction(user_id: int, reference: str, amount: float, credits_added: int) -> bool:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        try:
            c.execute(f"INSERT INTO transactions (user_id, reference, amount, credits_added, status) VALUES ({ph}, {ph}, {ph}, {ph}, 'pending')",
                      (user_id, reference, amount, credits_added))
            return True
        except Exception as e:
            logger.error(f"Error creating transaction: {e}")
            return False

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def complete_transaction(reference: str) -> Optional[Dict]:
    """Marks transaction as completed and returns it if successful"""
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        # Check if already completed
        c.execute(f"SELECT * FROM transactions WHERE reference = {ph}", (reference,))
        tx_row = c.fetchone()
        
        if not tx_row:
            return None
            
        tx = dict(tx_row)
        if tx['status'] == 'completed':
            return tx # Already processed
            
        # Update transaction status
        c.execute(f"UPDATE transactions SET status = 'completed' WHERE reference = {ph}", (reference,))
        
        if c.rowcount > 0:
            # Add credits to user
            c.execute(f"UPDATE users SET credits = credits + {ph} WHERE id = {ph}", (tx['credits_added'], tx['user_id']))
            return tx
            
        return None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type(psycopg.OperationalError) if psycopg else lambda e: False,
    reraise=True
)
def add_log(message: str, level: str = "INFO", user_id: Optional[int] = None):
    if level == "ERROR":
        logger.error(f"[{user_id}] {message}")
    elif level == "WARNING":
        logger.warning(f"[{user_id}] {message}")
    else:
        logger.info(f"[{user_id}] {message}")
        
    if user_id is None:
        return 

    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"INSERT INTO logs (user_id, message, level) VALUES ({ph}, {ph}, {ph})", (user_id, message, level))

def get_recent_logs(limit: int = 50, user_id: Optional[int] = None) -> List[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        if user_id:
            c.execute(f"SELECT * FROM logs WHERE user_id = {ph} ORDER BY timestamp DESC LIMIT {ph}", (user_id, limit))
        else:
            c.execute(f"SELECT * FROM logs ORDER BY timestamp DESC LIMIT {ph}", (limit,))
        rows = c.fetchall()
        results = []
        for row in rows:
            if hasattr(row, 'keys'):
                results.append(dict(row))
            else:
                results.append(dict(row))
        return results[::-1] 

def get_setting(key: str, default: Any = None, user_id: int = None) -> Any:
    settings = load_settings(user_id)
    return settings.get(key, default)

def save_setting(key: str, value: Any, user_id: int):
    settings = load_settings(user_id)
    settings[key] = value
    save_settings_to_db(settings, user_id)

def increment_reply_count(user_id: int):
    update_stats(True, user_id)

def get_queue(user_id: Optional[int] = None) -> List[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        if user_id:
            c.execute(f"SELECT * FROM queue WHERE user_id = {ph} ORDER BY created_at DESC", (user_id,))
        else:
            c.execute("SELECT * FROM queue ORDER BY created_at DESC")
        rows = c.fetchall()
        results = []
        for row in rows:
            if hasattr(row, 'keys'):
                results.append(dict(row))
            else:
                results.append(dict(row))
        return results

def add_to_queue(tweet_id: str, tweet_text: str, reply_text: str, user_id: Optional[int] = None) -> int:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        if get_db_type() == "postgres":
            # For PostgreSQL, use RETURNING clause
            c.execute(
                f"INSERT INTO queue (tweet_id, tweet_text, reply_text, user_id) VALUES ({ph}, {ph}, {ph}, {ph}) RETURNING id",
                (tweet_id, tweet_text, reply_text, user_id)
            )
            return c.fetchone()['id']
        else:
            # For SQLite, use lastrowid
            c.execute(
                f"INSERT INTO queue (tweet_id, tweet_text, reply_text, user_id) VALUES ({ph}, {ph}, {ph}, {ph})",
                (tweet_id, tweet_text, reply_text, user_id)
            )
            return c.lastrowid

def remove_from_queue(queue_id: int, user_id: int) -> bool:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"DELETE FROM queue WHERE id = {ph} AND user_id = {ph}", (queue_id, user_id))
        return c.rowcount > 0

def update_stats(success: bool, user_id: int):
    today = datetime.date.today()
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        if get_db_type() == "postgres":
            insert_sql = f"INSERT INTO stats (user_id, date, count, success_count) VALUES ({ph}, {ph}, 0, 0) ON CONFLICT (user_id, date) DO NOTHING"
        else:
            insert_sql = f"INSERT OR IGNORE INTO stats (user_id, date, count, success_count) VALUES ({ph}, {ph}, 0, 0)"
            
        c.execute(insert_sql, (user_id, today))
        
        if success:
            c.execute(
                f"UPDATE stats SET count = count + 1, success_count = success_count + 1 WHERE user_id = {ph} AND date = {ph}",
                (user_id, today)
            )
        else:
            c.execute(
                f"UPDATE stats SET count = count + 1 WHERE user_id = {ph} AND date = {ph}",
                (user_id, today)
            )

def increment_scraped_count(user_id: int, amount: int = 1):
    update_stats_metric("scraped_count", amount, user_id)

def increment_generated_count(user_id: int, amount: int = 1):
    update_stats_metric("generated_count", amount, user_id)

def update_stats_metric(column: str, amount: int, user_id: int):
    today = datetime.date.today()
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        # Ensure row exists
        if get_db_type() == "postgres":
            insert_sql = f"INSERT INTO stats (user_id, date, count, success_count, scraped_count, generated_count) VALUES ({ph}, {ph}, 0, 0, 0, 0) ON CONFLICT (user_id, date) DO NOTHING"
        else:
            insert_sql = f"INSERT OR IGNORE INTO stats (user_id, date, count, success_count, scraped_count, generated_count) VALUES ({ph}, {ph}, 0, 0, 0, 0)"
            
        c.execute(insert_sql, (user_id, today))
        
        # Update metric
        c.execute(
            f"UPDATE stats SET {column} = {column} + {ph} WHERE user_id = {ph} AND date = {ph}",
            (amount, user_id, today)
        )

def get_stats(user_id: int) -> Dict:
    today = datetime.date.today()
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT * FROM stats WHERE user_id = {ph} AND date = {ph}", (user_id, today))
        row = c.fetchone()
        if row:
            if hasattr(row, 'keys'):
                return dict(row)
            return dict(row)
        return {"count": 0, "success_count": 0, "scraped_count": 0, "generated_count": 0}

def get_all_user_stats() -> List[Dict]:
    """Admin: Get usage stats for all users."""
    with get_db_connection() as conn:
        c = conn.cursor()
        # Join users and stats to get usernames and aggregated totals
        # Note: We sum up ALL time stats for the dashboard table
        sql = """
            SELECT 
                u.username, 
                u.credits,
                COALESCE(SUM(s.scraped_count), 0) as total_scraped,
                COALESCE(SUM(s.generated_count), 0) as total_generated,
                COALESCE(SUM(s.success_count), 0) as total_posted
            FROM users u
            LEFT JOIN stats s ON u.id = s.user_id
            GROUP BY u.username, u.credits
            ORDER BY total_posted DESC
        """
        c.execute(sql)
        rows = c.fetchall()
        results = []
        for row in rows:
            results.append(dict(row) if hasattr(row, 'keys') else dict(row))
        return results

def get_daily_stats(user_id: int, days: int = 7) -> List[Dict]:
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days-1)
    
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(
            f"SELECT * FROM stats WHERE user_id = {ph} AND date >= {ph} ORDER BY date ASC", 
            (user_id, start_date)
        )
        rows = c.fetchall()
        
        stats_map = {}
        for row in rows:
            row_dict = dict(row) if hasattr(row, 'keys') else dict(row)
            date_key = str(row_dict['date'])
            stats_map[date_key] = row_dict
        result = []
        
        for i in range(days):
            d = start_date + datetime.timedelta(days=i)
            date_str = d.isoformat() 
            
            if date_str in stats_map:
                result.append(stats_map[date_str])
            else:
                result.append({
                    "date": date_str,
                    "count": 0,
                    "success_count": 0
                })
        return result

def add_history(tweet_id: str, reply_text: str, status: str, user_id: int, tweet_text: str = None):
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(
            f"INSERT INTO history (user_id, tweet_id, reply_text, status, tweet_text) VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
            (user_id, tweet_id, reply_text, status, tweet_text)
        )

def get_history(limit: int = 50, user_id: Optional[int] = None) -> List[Dict]:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        if user_id:
            c.execute(f"SELECT * FROM history WHERE user_id = {ph} ORDER BY timestamp DESC LIMIT {ph}", (user_id, limit))
        else:
            c.execute(f"SELECT * FROM history ORDER BY timestamp DESC LIMIT {ph}", (limit,))
        rows = c.fetchall()
        results = []
        for row in rows:
            if hasattr(row, 'keys'):
                results.append(dict(row))
            else:
                results.append(dict(row))
        return results

def load_settings(user_id: int) -> Dict:
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        c.execute(f"SELECT * FROM settings WHERE user_id = {ph}", (user_id,))
        row = c.fetchone()
        if row:
            # Handle row access for DictCursor vs standard
            row_data = dict(row) if hasattr(row, 'keys') else dict(row)
            
            return {
                "posting_credentials": json.loads(row_data['posting_credentials']) if row_data.get('posting_credentials') else {},
                "scraping_credentials": json.loads(row_data['scraping_credentials']) if row_data.get('scraping_credentials') else [],
                "gemini_api_key": row_data['gemini_api_key'] if row_data.get('gemini_api_key') else ""
            }
        return {}

def save_settings_to_db(settings: Dict, user_id: int):
    posting_json = json.dumps(settings.get("posting_credentials", {}))
    scraping_json = json.dumps(settings.get("scraping_credentials", []))
    gemini_key = settings.get("gemini_api_key", "")
    
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        if get_db_type() == "postgres":
            sql = f"""
                INSERT INTO settings (user_id, posting_credentials, scraping_credentials, gemini_api_key) 
                VALUES ({ph}, {ph}, {ph}, {ph})
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    posting_credentials = EXCLUDED.posting_credentials,
                    scraping_credentials = EXCLUDED.scraping_credentials,
                    gemini_api_key = EXCLUDED.gemini_api_key
            """
        else:
            sql = f"INSERT OR REPLACE INTO settings (user_id, posting_credentials, scraping_credentials, gemini_api_key) VALUES ({ph}, {ph}, {ph}, {ph})"
            
        c.execute(sql, (user_id, posting_json, scraping_json, gemini_key))

def get_scraping_credentials(user_id: Optional[int] = None) -> List[Dict]:
    creds_pool = []
    
    # 1. ALWAYS add the system-level TwitterAPI.io key first (available to all users)
    system_twitterapiio_key = config.TWITTERAPI_IO_KEY
    if system_twitterapiio_key:
        creds_pool.append({"api_key": system_twitterapiio_key})

    # 2. If user_id provided, APPEND their personal scraping credentials from DB
    if user_id:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                ph = get_placeholder()
                c.execute(f"SELECT scraping_credentials FROM settings WHERE user_id = {ph}", (user_id,))
                row = c.fetchone()
                
                if row:
                    row_dict = dict(row) if hasattr(row, 'keys') else dict(row)
                    if row_dict.get('scraping_credentials'):
                        try:
                            creds = json.loads(row_dict['scraping_credentials'])
                            if isinstance(creds, list):
                                creds_pool.extend(creds)
                        except: pass
        except Exception as e:
            logger.error(f"Error reading credentials: {e}")
            
    return creds_pool

# Tweet content cache functions for batch processing
def cache_tweet_content(tweet_id: str, content: str):
    """Cache tweet content to avoid redundant API calls."""
    # Simple in-memory cache using a table
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        if get_db_type() == "postgres":
            # Create cache table if it doesn't exist
            c.execute("""
                CREATE TABLE IF NOT EXISTS tweet_cache (
                    tweet_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Insert or update
            c.execute(f"""
                INSERT INTO tweet_cache (tweet_id, content) 
                VALUES ({ph}, {ph})
                ON CONFLICT (tweet_id) 
                DO UPDATE SET content = EXCLUDED.content, cached_at = CURRENT_TIMESTAMP
            """, (tweet_id, content))
        else:
            # SQLite
            c.execute("""
                CREATE TABLE IF NOT EXISTS tweet_cache (
                    tweet_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute(f"INSERT OR REPLACE INTO tweet_cache (tweet_id, content) VALUES ({ph}, {ph})", 
                     (tweet_id, content))

def get_cached_tweet_content(tweet_id: str) -> Optional[str]:
    """Retrieve cached tweet content if available."""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            ph = get_placeholder()
            c.execute(f"SELECT content FROM tweet_cache WHERE tweet_id = {ph}", (tweet_id,))
            row = c.fetchone()
            if row:
                return row['content'] if hasattr(row, 'keys') else row[0]
    except:
        # Table might not exist yet
        pass
    return None

def has_user_processed(user_id: int, tweet_id: str) -> bool:
    """Check if a user has already processed a specific tweet."""
    with get_db_connection() as conn:
        c = conn.cursor()
        ph = get_placeholder()
        
        # Check in both queue and history
        c.execute(f"SELECT 1 FROM queue WHERE user_id = {ph} AND tweet_id = {ph} LIMIT 1", 
                 (user_id, tweet_id))
        if c.fetchone():
            return True
            
        c.execute(f"SELECT 1 FROM history WHERE user_id = {ph} AND tweet_id = {ph} LIMIT 1", 
                 (user_id, tweet_id))
        if c.fetchone():
            return True
            
    return False