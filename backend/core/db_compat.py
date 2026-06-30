"""SQL 方言适配 — 当前 SQLite，未来 MySQL 8.0+。

设计目的：让「universe」5 张新表的 upsert / DDL 写成单一路径，
迁到 MySQL 时只改这一个模块。

- `BACKEND` 在模块加载时检测：优先 pymysql，回落 sqlite3
- `upsert_sql()` 返回当前方言的 UPSERT 语句 + 参数占位符（? vs %s）
- `placeholder()` 给单值占位符

注意：本模块的 dialect 切换**只影响本任务新增的 5 张表**。
现有 14 张表里也有 `INSERT OR REPLACE`（如 `upsert_top_picks`），
未来迁移时单独改那些位置。
"""

import logging
import sqlite3  # noqa: F401  -- 永远 import，确认 SQLite 可用

logger = logging.getLogger(__name__)

try:
    import pymysql  # noqa: F401
    _HAS_MYSQL = True
except ImportError:
    _HAS_MYSQL = False

BACKEND: str = "mysql" if _HAS_MYSQL else "sqlite"
logger.info(f"db_compat: 当前后端 = {BACKEND}")


def placeholder() -> str:
    """单个参数占位符：sqlite 用 ?，mysql 用 %s。"""
    return "?" if BACKEND == "sqlite" else "%s"


def placeholders(n: int) -> str:
    """n 个参数占位符。"""
    return ",".join([placeholder()] * n)


def upsert_sql(table: str,
               cols: list[str],
               conflict_cols: list[str],
               update_cols: list[str] | None = None) -> str:
    """生成当前方言的 UPSERT 语句。

    Args:
        table: 表名
        cols: 所有要插入的列
        conflict_cols: 唯一键列（决定何时触发 ON CONFLICT/DUPLICATE KEY）
        update_cols: 冲突时要更新的列；默认 = cols

    Returns:
        SQL 字符串（参数顺序与 cols 一致）
    """
    update_cols = update_cols or cols
    col_list = ",".join(cols)
    ph = placeholders(len(cols))

    if BACKEND == "sqlite":
        # INSERT OR REPLACE 不区分 update_cols（直接整行替换）
        return f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({ph})"

    # MySQL: INSERT ... ON DUPLICATE KEY UPDATE
    updates = ",".join(f"{c}=VALUES({c})" for c in update_cols)
    return (f"INSERT INTO {table} ({col_list}) "
            f"VALUES ({ph}) ON DUPLICATE KEY UPDATE {updates}")


def is_sqlite() -> bool:
    return BACKEND == "sqlite"


def is_mysql() -> bool:
    return BACKEND == "mysql"
