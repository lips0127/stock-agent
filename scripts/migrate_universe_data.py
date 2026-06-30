"""全市场舆情观测台 — SQLite → MySQL 数据搬运工具。

用法：
    # 1. 装 PyMySQL（仅在执行时需要，不写进 requirements.txt）
    pip install pymysql

    # 2. 导入 5 张表的 DDL
    mysql -u root -p stock_agent < scripts/migrate_universe_to_mysql.sql

    # 3. 跑数据搬运
    python scripts/migrate_universe_data.py \\
        --from stocks.db \\
        --to mysql://root:pwd@localhost:3306/stock_agent

策略：
    * 分表独立读 + 写，单表失败不影响其他表
    * 批量 INSERT（每批 500 行），用 MySQL 扩展的 executemany
    * 重复主键走 INSERT IGNORE（避免已存在行报错）
    * 进度日志到 stdout
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

TABLES = [
    "sentiment_universe_indices",
    "sentiment_universe_constituents",
    "sentiment_universe_jobs",
    "sentiment_universe_scores",
    "sentiment_universe_aggregates",
]

BATCH_SIZE = 500


def read_table(sqlite_path: str, table: str) -> tuple[list[str], list[tuple]]:
    """从 SQLite 读出整张表，返回 (列名, [(值...)])。"""
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        # 表还不存在（首次迁移）
        if "no such table" in str(e):
            return [], []
        raise
    finally:
        con.close()
    if not rows:
        return [], []
    cols = rows[0].keys()
    return list(cols), [tuple(r) for r in rows]


def write_table(mysql_url: str, table: str, cols: list[str], rows: list[tuple]) -> int:
    """把数据写入 MySQL；返回成功行数。"""
    if not rows:
        return 0
    try:
        import pymysql
    except ImportError:
        print("ERROR: 需要安装 pymysql: pip install pymysql", file=sys.stderr)
        sys.exit(2)

    # 解析 mysql://user:pwd@host:port/db
    from urllib.parse import urlparse
    u = urlparse(mysql_url)
    conn = pymysql.connect(
        host=u.hostname or "localhost",
        port=u.port or 3306,
        user=u.username,
        password=u.password,
        database=(u.path or "/").lstrip("/") or None,
        charset="utf8mb4",
        autocommit=False,
    )
    placeholders = ",".join(["%s"] * len(cols))
    col_list = ",".join(cols)
    sql = f"INSERT IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"

    n_ok = 0
    try:
        with conn.cursor() as cur:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                cur.executemany(sql, batch)
                n_ok += cur.rowcount
                print(f"  {table}: {n_ok}/{len(rows)}", end="\r", flush=True)
        conn.commit()
    finally:
        conn.close()
    print(f"  {table}: {n_ok}/{len(rows)} done")
    return n_ok


def main():
    ap = argparse.ArgumentParser(description="SQLite → MySQL 数据搬运（universe 5 表）")
    ap.add_argument("--from", dest="src", required=True,
                    help="SQLite 文件路径 (例如 stocks.db)")
    ap.add_argument("--to", dest="dst", required=True,
                    help="MySQL URL (例如 mysql://root:pwd@localhost:3306/stock_agent)")
    ap.add_argument("--tables", nargs="*", default=TABLES,
                    help=f"要迁移的表（默认全部 5 张）。可选：{TABLES}")
    ap.add_argument("--dry-run", action="store_true",
                    help="只读 SQLite 不写 MySQL（用于先看数据量）")
    args = ap.parse_args()

    src = args.src
    if not Path(src).exists():
        print(f"ERROR: SQLite 文件不存在: {src}", file=sys.stderr)
        sys.exit(1)

    print(f"Source: {src}")
    print(f"Target: {args.dst}")
    print(f"Mode:   {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print("-" * 60)

    t0 = time.time()
    totals = {}
    for table in args.tables:
        print(f"\n[{table}]")
        cols, rows = read_table(src, table)
        if not rows:
            print(f"  跳过（表为空或不存在）")
            totals[table] = 0
            continue
        print(f"  SQLite: {len(rows)} 行, {len(cols)} 列")
        if args.dry_run:
            totals[table] = len(rows)
            continue
        n = write_table(args.dst, table, cols, rows)
        totals[table] = n

    dt = time.time() - t0
    print("\n" + "=" * 60)
    print(f"完成。耗时 {dt:.1f}s")
    for t, n in totals.items():
        print(f"  {t}: {n} 行")
    grand = sum(totals.values())
    print(f"合计: {grand} 行")


if __name__ == "__main__":
    main()
