import sqlite3
import logging
from backend.config import DB_PATH as DB_FILE, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
from passlib.hash import pbkdf2_sha256

logger = logging.getLogger(__name__)


def get_connection():
    """获取原始数据库连接（服务层使用）。"""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """初始化数据库表结构和默认数据。应在应用启动时调用。"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stock_daily_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                price REAL,
                dividend_yield REAL,
                dividend_per_share REAL,
                update_time TEXT,
                UNIQUE(date, code)
            );

            CREATE TABLE IF NOT EXISTS market_indices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                value REAL,
                change_amount REAL,
                change_pct REAL,
                UNIQUE(date, symbol)
            );
        """)
        conn.commit()

        _ensure_column(conn, "stock_daily_metrics", "dividend_per_share", "REAL")
        _ensure_column(conn, "stock_daily_metrics", "update_time", "TEXT")

        if DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
            register_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)

        logger.info("Database initialized successfully")
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, col_type: str) -> None:
    """安全添加列（如已存在则跳过）。"""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
        logger.info(f"Added column {column} to {table}")
    except sqlite3.OperationalError:
        pass


def register_user(username: str, password: str) -> bool:
    """注册新用户，成功返回 True，用户已存在返回 False。"""
    password_hash = pbkdf2_sha256.hash(password)
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
        logger.info(f"User '{username}' created")
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate_user(username: str, password: str) -> bool:
    """验证用户名和密码。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False
        return pbkdf2_sha256.verify(password, row[0])
    finally:
        conn.close()
