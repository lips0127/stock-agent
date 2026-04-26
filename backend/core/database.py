"""数据库核心模块 — SQLite 连接管理 + 表初始化 + 用户认证。"""

import os
import logging
import sqlite3
from passlib.hash import pbkdf2_sha256
from pathlib import Path
from contextlib import contextmanager

from backend.config import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD

logger = logging.getLogger(__name__)

_DB_PATH = Path(os.environ.get("CACHE_DIR", str(Path(__file__).resolve().parent.parent.parent))) / "stocks.db"


def _get_db_path():
    return str(_DB_PATH)


@contextmanager
def get_connection():
    """获取 SQLite 连接，使用后自动提交。"""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_pool():
    """SQLite 不需要连接池，保留接口兼容性。"""
    pass


def init_db():
    """初始化数据库表结构（幂等操作）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS py_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                price REAL,
                dividend_yield REAL,
                dividend_per_share REAL,
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, code)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_indices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                value REAL,
                change_amount REAL,
                change_pct REAL,
                UNIQUE(date, symbol)
            )
        """)
        # 索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sdm_date ON stock_daily_metrics(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sdm_code_date ON stock_daily_metrics(code, date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mi_date ON market_indices(date)")

        _create_default_admin(conn)


def _create_default_admin(conn):
    if not DEFAULT_ADMIN_USER or not DEFAULT_ADMIN_PASSWORD:
        return

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM py_users")
    if cur.fetchone()[0] > 0:
        return

    register_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)


def register_user(username: str, password: str) -> bool:
    password_hash = pbkdf2_sha256.hash(password)
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO py_users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"User already exists: {username}")
        return False


def authenticate_user(username: str, password: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash FROM py_users WHERE username = ?",
            (username,),
        )
        user = cur.fetchone()

    if not user:
        return None

    if not pbkdf2_sha256.verify(password, user["password_hash"]):
        return None

    return {"user_id": user["id"], "username": user["username"]}
