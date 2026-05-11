"""数据库核心模块 — SQLite 连接管理 + 表初始化 + 用户认证。"""

import os
import uuid
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
    except Exception as e:
        logger.warning(f"数据库操作异常，执行 rollback: {e}", exc_info=True)
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
        # 开启 WAL 模式，支持并发读写
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
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
                scan_type TEXT,
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

        cur.execute("CREATE TABLE IF NOT EXISTS scan_tasks ("
                    "id TEXT PRIMARY KEY,"
                    "type TEXT NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'pending',"
                    "total INTEGER DEFAULT 0,"
                    "done INTEGER DEFAULT 0,"
                    "result_count INTEGER,"
                    "error_message TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_tasks_status ON scan_tasks(status)")

        # 舆情监控配置
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_config ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "stock_name TEXT DEFAULT '',"
                    "forum_type TEXT NOT NULL DEFAULT 'eastmoney',"
                    "enabled INTEGER NOT NULL DEFAULT 1,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, forum_type))"
        )
        # 迁移：为旧表添加 stock_name 列
        try:
            cur.execute("ALTER TABLE sentiment_config ADD COLUMN stock_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # 论坛帖子缓存
        cur.execute("CREATE TABLE IF NOT EXISTS forum_posts ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "forum_type TEXT NOT NULL,"
                    "title TEXT,"
                    "content TEXT,"
                    "author TEXT,"
                    "post_time TEXT,"
                    "url TEXT UNIQUE,"
                    "fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_forum_posts_code ON forum_posts(stock_code, forum_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_forum_posts_time ON forum_posts(post_time)")
        # 情绪评分结果
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_scores ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "forum_type TEXT NOT NULL,"
                    "date TEXT NOT NULL,"
                    "sentiment TEXT NOT NULL,"
                    "score REAL NOT NULL,"
                    "post_count INTEGER DEFAULT 0,"
                    "summary TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, forum_type, date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_code ON sentiment_scores(stock_code, date)")

        # 迁移：为已有表添加 scan_type 列
        try:
            cur.execute("ALTER TABLE stock_daily_metrics ADD COLUMN scan_type TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在



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

def create_scan_task(task_type: str) -> str:
    """创建扫描任务，返回 task_id。"""
    task_id = str(uuid.uuid4())[:8]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scan_tasks (id, type, status) VALUES (?, ?, 'running')",
            (task_id, task_type),
        )
    return task_id


def update_scan_task(task_id: str, status: str = None, done: int = None,
                     total: int = None, result_count: int = None, error_message: str = None):
    """更新扫描任务进度。"""
    fields = []
    values = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if done is not None:
        fields.append("done = ?")
        values.append(done)
    if total is not None:
        fields.append("total = ?")
        values.append(total)
    if result_count is not None:
        fields.append("result_count = ?")
        values.append(result_count)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(task_id)
    sql = "UPDATE scan_tasks SET " + ", ".join(fields) + " WHERE id = ?"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)


def get_scan_task(task_id: str) -> dict | None:
    """获取单个任务信息。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scan_tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def get_all_scan_tasks(limit: int = 20) -> list:
    """获取所有任务（按创建时间倒序）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM scan_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


# ── 舆情监控配置 CRUD ──

def get_sentiment_configs() -> list:
    """获取所有启用的舆情监控配置。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM sentiment_config WHERE enabled=1 ORDER BY stock_code"
        )
        return [dict(r) for r in cur.fetchall()]


def add_sentiment_config(stock_code: str, forum_type: str = "eastmoney",
                         stock_name: str = "") -> dict | None:
    """新增监控配置，返回创建的记录。"""
    stock_code = str(stock_code).strip().zfill(6)
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO sentiment_config
                   (stock_code, stock_name, forum_type, enabled)
                   VALUES (?, ?, ?, 1)""",
                (stock_code, stock_name, forum_type),
            )
            if cur.lastrowid:
                cur.execute("SELECT * FROM sentiment_config WHERE id=?", (cur.lastrowid,))
                return dict(cur.fetchone())
    except Exception as e:
        logger.warning(f"新增监控配置失败: {e}")
    return None


def delete_sentiment_config(config_id: int) -> bool:
    """删除监控配置（物理删除）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sentiment_config WHERE id=?", (config_id,))
        return cur.rowcount > 0
