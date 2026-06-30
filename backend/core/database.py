"""数据库核心模块 — SQLite 连接管理 + 表初始化 + 用户认证。"""

import os
import re
import uuid
import logging
import sqlite3
from datetime import datetime
from passlib.hash import pbkdf2_sha256
from pathlib import Path
from contextlib import contextmanager

from backend.config import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
from backend.core.db_compat import upsert_sql, placeholder, placeholders

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

        # 迁移：标题真实性审计字段（v1, 2026-06-04）
        for col, ddl in [
            ("actual_title", "TEXT"),
            ("title_match", "INTEGER"),
            ("title_verified_at", "TIMESTAMP"),
            ("audit_status", "TEXT"),
            ("audit_note", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        cur.execute("CREATE INDEX IF NOT EXISTS idx_forum_posts_audit ON forum_posts(stock_code, audit_status)")
        # 情绪评分结果（v3, 2026-06-06：四分类 + 标签分布 + 信号）
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_scores ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "forum_type TEXT NOT NULL,"
                    "date TEXT NOT NULL,"
                    "sentiment TEXT NOT NULL,"
                    "score REAL NOT NULL,"
                    "post_count INTEGER DEFAULT 0,"
                    "summary TEXT,"
                    "bullish_n INTEGER DEFAULT 0,"
                    "bearish_n INTEGER DEFAULT 0,"
                    "neutral_n INTEGER DEFAULT 0,"
                    "noise_n INTEGER DEFAULT 0,"
                    "signals_json TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, forum_type, date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_code ON sentiment_scores(stock_code, date)")
        # 迁移：给旧表加新列
        for col, ddl in [
            ("bullish_n", "INTEGER DEFAULT 0"),
            ("bearish_n", "INTEGER DEFAULT 0"),
            ("neutral_n", "INTEGER DEFAULT 0"),
            ("noise_n", "INTEGER DEFAULT 0"),
            ("signals_json", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE sentiment_scores ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass

        # 帖子级 LLM 标签（v3, 2026-06-06）：用于时序回填 + 后续精细分析
        # 每条 forum_posts 同一 (code, post_id, date) 只存最新一次分析的标签
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_post_labels ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "post_id INTEGER NOT NULL,"
                    "forum_type TEXT NOT NULL DEFAULT 'eastmoney',"
                    "date TEXT NOT NULL,"
                    "label INTEGER NOT NULL,"  # 1 / 0 / -1 / 99
                    "model TEXT,"
                    "raw_response TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, post_id, date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_post_labels_code_date ON sentiment_post_labels(stock_code, date)")

        # 热门股自动发现池（v3, 2026-06-06）：每日按成交额 top N 写入
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_top_picks ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "stock_name TEXT DEFAULT '',"
                    "rank INTEGER NOT NULL,"
                    "amount REAL,"                # 当日成交额（元）
                    "source TEXT NOT NULL DEFAULT 'volume_top100',"
                    "auto_added INTEGER DEFAULT 0,"  # 1=已自动加入 sentiment_config
                    "snapshot_date TEXT NOT NULL,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, snapshot_date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_top_picks_date ON sentiment_top_picks(snapshot_date, rank)")

        # 时序因子（v3, 2026-06-06）：EMA / 极端情绪检测结果
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_indicators ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "stock_code TEXT NOT NULL,"
                    "date TEXT NOT NULL,"
                    "score REAL NOT NULL,"            # 当日 score
                    "ema3 REAL,"                       # 3 日 EMA
                    "ema5 REAL,"                       # 5 日 EMA
                    "bullish_ma30 REAL,"              # bullish 30 日均值
                    "bullish_std30 REAL,"             # bullish 30 日 std
                    "bearish_ma30 REAL,"              # bearish 30 日均值
                    "bearish_std30 REAL,"             # bearish 30 日 std
                    "panic_signal INTEGER DEFAULT 0,"  # 1=触发非理性恐慌
                    "euphoria_signal INTEGER DEFAULT 0,"  # 1=触发非理性狂热
                    "momentum_cross INTEGER DEFAULT 0,"  # 1=EMA3 上穿 EMA5
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(stock_code, date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_indicators_code_date ON sentiment_indicators(stock_code, date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_indicators_panic ON sentiment_indicators(date, panic_signal)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_indicators_euphoria ON sentiment_indicators(date, euphoria_signal)")

        # 舆情帖子过滤规则白名单
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_filters ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "filter_key TEXT NOT NULL UNIQUE,"
                    "filter_type TEXT NOT NULL DEFAULT 'title_keyword',"
                    "description TEXT,"
                    "enabled INTEGER DEFAULT 1,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        _init_sentiment_filters(conn)

        # ── 净值管理系统表 ──────────────────────────────

        # 参与方表
        cur.execute("CREATE TABLE IF NOT EXISTS nav_parties ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "code TEXT UNIQUE NOT NULL,"
                    "name TEXT NOT NULL,"
                    "description TEXT,"
                    "initial_shares REAL DEFAULT 0,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        # 银证转账记录表
        cur.execute("CREATE TABLE IF NOT EXISTS nav_transfers ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "date TEXT NOT NULL,"
                    "party_code TEXT NOT NULL,"
                    "amount REAL NOT NULL,"
                    "direction TEXT NOT NULL CHECK(direction IN ('IN', 'OUT')),"
                    "nav_at_time REAL NOT NULL,"
                    "shares_delta REAL NOT NULL,"
                    "note TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "FOREIGN KEY (party_code) REFERENCES nav_parties(code))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_transfers_date ON nav_transfers(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_transfers_party ON nav_transfers(party_code)")

        # 净值历史记录表
        cur.execute("CREATE TABLE IF NOT EXISTS nav_records ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "record_date TEXT NOT NULL UNIQUE,"
                    "total_asset REAL NOT NULL,"
                    "total_shares REAL NOT NULL,"
                    "nav REAL NOT NULL,"
                    "note TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        # 持仓快照表
        cur.execute("CREATE TABLE IF NOT EXISTS nav_positions ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "snapshot_date TEXT NOT NULL,"
                    "symbol TEXT NOT NULL,"
                    "name TEXT,"
                    "quantity REAL,"
                    "avg_cost REAL,"
                    "current_price REAL,"
                    "market_value REAL,"
                    "source TEXT DEFAULT 'manual',"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(snapshot_date, symbol))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_positions_date ON nav_positions(snapshot_date)")

        # ── 量化交易系统表 ──────────────────────────────

        cur.execute("CREATE TABLE IF NOT EXISTS strategies ("
                    "id TEXT PRIMARY KEY,"
                    "name TEXT NOT NULL,"
                    "strategy_class TEXT NOT NULL,"
                    "params_json TEXT,"
                    "symbols_json TEXT,"
                    "timeframes_json TEXT,"
                    "enabled INTEGER DEFAULT 0,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        cur.execute("CREATE TABLE IF NOT EXISTS historical_bars ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "symbol TEXT NOT NULL,"
                    "timeframe TEXT NOT NULL,"
                    "bar_time TEXT NOT NULL,"
                    "open REAL, high REAL, low REAL, close REAL,"
                    "volume REAL, amount REAL,"
                    "UNIQUE(symbol, timeframe, bar_time))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hb_symbol_tf ON historical_bars(symbol, timeframe)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hb_time ON historical_bars(bar_time)")

        cur.execute("CREATE TABLE IF NOT EXISTS signals ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "strategy_id TEXT NOT NULL,"
                    "symbol TEXT NOT NULL,"
                    "direction TEXT NOT NULL,"
                    "strength REAL DEFAULT 1.0,"
                    "reason TEXT,"
                    "bar_time TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        cur.execute("CREATE TABLE IF NOT EXISTS orders ("
                    "id TEXT PRIMARY KEY,"
                    "strategy_id TEXT,"
                    "symbol TEXT NOT NULL,"
                    "side TEXT NOT NULL,"
                    "quantity REAL NOT NULL,"
                    "price REAL,"
                    "order_type TEXT NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'CREATED',"
                    "filled_qty REAL DEFAULT 0,"
                    "filled_price REAL,"
                    "commission REAL DEFAULT 0,"
                    "error_message TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")

        cur.execute("CREATE TABLE IF NOT EXISTS positions ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "strategy_id TEXT,"
                    "symbol TEXT NOT NULL,"
                    "quantity REAL NOT NULL,"
                    "avg_cost REAL NOT NULL,"
                    "current_price REAL,"
                    "unrealized_pnl REAL,"
                    "realized_pnl REAL DEFAULT 0,"
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        cur.execute("CREATE TABLE IF NOT EXISTS portfolio_snapshots ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "date TEXT NOT NULL,"
                    "strategy_id TEXT,"
                    "total_value REAL,"
                    "cash REAL,"
                    "positions_value REAL,"
                    "daily_pnl REAL,"
                    "cumulative_pnl REAL,"
                    "daily_return REAL,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        cur.execute("CREATE TABLE IF NOT EXISTS backtest_runs ("
                    "id TEXT PRIMARY KEY,"
                    "strategy_name TEXT NOT NULL,"
                    "start_date TEXT NOT NULL,"
                    "end_date TEXT NOT NULL,"
                    "initial_capital REAL,"
                    "final_value REAL,"
                    "total_return REAL,"
                    "annual_return REAL,"
                    "sharpe_ratio REAL,"
                    "max_drawdown REAL,"
                    "win_rate REAL,"
                    "total_trades INTEGER,"
                    "params_json TEXT,"
                    "status TEXT DEFAULT 'running',"
                    "error_message TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )

        cur.execute("CREATE TABLE IF NOT EXISTS backtest_trades ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "backtest_id TEXT NOT NULL,"
                    "symbol TEXT,"
                    "side TEXT,"
                    "entry_time TEXT,"
                    "exit_time TEXT,"
                    "entry_price REAL,"
                    "exit_price REAL,"
                    "quantity REAL,"
                    "pnl REAL,"
                    "pnl_pct REAL)"
        )

        # 迁移：为已有表添加 scan_type 列
        try:
            cur.execute("ALTER TABLE stock_daily_metrics ADD COLUMN scan_type TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在

        # ── 知乎大V监控表 ──────────────────────────────

        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_users ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "url_token TEXT UNIQUE NOT NULL,"
                    "display_name TEXT,"
                    "avatar_url TEXT,"
                    "headline TEXT,"
                    "follower_count INTEGER DEFAULT 0,"
                    "enabled INTEGER DEFAULT 1,"
                    "email_notify INTEGER DEFAULT 1,"
                    "last_checked_at TIMESTAMP,"
                    "last_notified_at TIMESTAMP,"
                    "last_error TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_zhihu_users_enabled ON zhihu_users(enabled)")

        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_posts ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "url_token TEXT NOT NULL,"
                    "post_id TEXT NOT NULL,"
                    "post_type TEXT NOT NULL,"
                    "title TEXT,"
                    "excerpt TEXT,"
                    "content_text TEXT,"
                    "url TEXT UNIQUE,"
                    "voteup_count INTEGER DEFAULT 0,"
                    "comment_count INTEGER DEFAULT 0,"
                    "created_at_original TIMESTAMP,"
                    "fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_zhp_token_time ON zhihu_posts(url_token, created_at_original DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_zhp_post_id ON zhihu_posts(post_id)")

        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_analyses ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "post_id TEXT NOT NULL,"
                    "url_token TEXT NOT NULL,"
                    "stance TEXT,"
                    "stance_assets TEXT,"
                    "sectors TEXT,"
                    "summary TEXT,"
                    "action_suggestion TEXT,"
                    "key_points TEXT,"
                    "confidence INTEGER DEFAULT 50,"
                    "raw_response TEXT,"
                    "model_name TEXT,"
                    "analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(post_id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_zha_token ON zhihu_analyses(url_token)")

        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_email_subscriptions ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "email TEXT UNIQUE NOT NULL,"
                    "url_tokens TEXT DEFAULT '[]',"
                    "enabled INTEGER DEFAULT 1,"
                    "verified INTEGER DEFAULT 0,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_email_log ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "email TEXT NOT NULL,"
                    "subject TEXT,"
                    "url_token TEXT,"
                    "post_ids TEXT,"
                    "status TEXT NOT NULL,"
                    "error_message TEXT,"
                    "sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_zhel_email ON zhihu_email_log(email, sent_at DESC)")

        # SMTP 配置表（单行，id=1）
        cur.execute("CREATE TABLE IF NOT EXISTS zhihu_smtp_settings ("
                    "id INTEGER PRIMARY KEY CHECK(id = 1),"
                    "smtp_host TEXT,"
                    "smtp_port INTEGER DEFAULT 465,"
                    "smtp_user TEXT,"
                    "smtp_password TEXT,"
                    "smtp_from TEXT,"
                    "smtp_use_ssl INTEGER DEFAULT 1,"
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        # ── VIX 恐慌指数 + 恐惧贪婪综合指数 日频快照（v3, 2026-06-04） ──
        cur.execute("CREATE TABLE IF NOT EXISTS vix_history ("
                    "date TEXT PRIMARY KEY,"
                    # 主体：50ETF 期权隐含波动率
                    "iv_50etf REAL,"
                    "pcr REAL,"                    # Put/Call Ratio
                    # 已实现波动率（沪深 300 + 中证 1000）
                    "rv_hs300 REAL,"               # Realized Vol HS300
                    "rv_zz1000 REAL,"
                    "rv_blended REAL,"
                    # 情绪面
                    "north_net REAL,"              # 北向资金净流入（亿）
                    "margin_balance REAL,"         # 融资融券余额（亿）
                    "limit_up_count INTEGER,"
                    "limit_down_count INTEGER,"
                    # 合成
                    "vix REAL,"                    # 主指数：IV 主力，RV 修正
                    "fear_greed REAL,"             # 恐惧贪婪综合指数 0-100
                    "regime TEXT,"                # 旧版 5 档（保留兼容）
                    "components_json TEXT,"        # 各成分明细 JSON
                    "computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        # 迁移：v2 现货位置 + 合成评分（2026-06-04）
        for col, ddl in [
            ("spot_close",          "REAL"),
            ("spot_ma60_dev",       "REAL"),
            ("spot_mom_5d",         "REAL"),
            ("spot_mom_20d",        "REAL"),
            ("spot_new_high_ratio", "REAL"),
            ("composite_score",     "REAL"),
            ("composite_regime",    "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE vix_history ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass

        # 迁移：v5 多 ETF QVIX + PCR + Z-Score + composite_percentile（2026-06-09）
        for col, ddl in [
            ("iv_300etf",            "REAL"),
            ("iv_500etf",            "REAL"),
            ("iv_cyb",               "REAL"),
            ("iv_kcb",               "REAL"),
            ("pcr_volume",           "REAL"),
            ("pcr_oi",               "REAL"),
            ("pcr_call_volume",      "INTEGER"),
            ("pcr_put_volume",       "INTEGER"),
            ("pcr_source",           "TEXT"),
            ("vix_zscore",           "REAL"),
            ("vix_source",           "TEXT"),
            ("composite_percentile", "REAL"),
            ("margin_source",        "TEXT"),
            ("limit_source",         "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE vix_history ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # 迁移：v7.0 construct-truth 恐惧贪婪（2026-06-29）
        # 与 v6.1 fear_greed 并存，同屏对比；fear_truth_v7=100 最恐，fear_greed_v7=100 最贪
        for col, ddl in [
            ("fear_truth_v7",      "REAL"),
            ("fear_greed_v7",      "REAL"),
            ("comp_drawdown_v7",   "REAL"),
            ("comp_breadth_v7",    "REAL"),
            ("comp_iv_surge_v7",   "REAL"),
            ("comp_iv_level_v7",   "REAL"),
            ("regime_v7",          "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE vix_history ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # ── 全市场舆情观测台（v4, 2026-06-06）──
        # 5 张新表：sentiment_universe_indices / constituents / jobs / scores / aggregates
        # DDL 用 SQLite 语法；MySQL 8.0+ 等价 DDL 见 scripts/migrate_universe_to_mysql.sql
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_universe_indices ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "code TEXT NOT NULL UNIQUE,"
                    "name TEXT NOT NULL,"
                    "akshare_symbol TEXT,"
                    "akshare_method TEXT NOT NULL DEFAULT 'csindex',"
                    "akshare_filter TEXT,"
                    "enabled INTEGER NOT NULL DEFAULT 1,"
                    "priority INTEGER NOT NULL DEFAULT 100,"
                    "description TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_universe_constituents ("
                    "index_code TEXT NOT NULL,"
                    "stock_code TEXT NOT NULL,"
                    "stock_name TEXT,"
                    "weight REAL,"
                    "snapshot_date TEXT NOT NULL,"
                    "PRIMARY KEY (index_code, stock_code, snapshot_date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_unc_code_date "
                    "ON sentiment_universe_constituents(stock_code, snapshot_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_unc_index_date "
                    "ON sentiment_universe_constituents(index_code, snapshot_date)")
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_universe_jobs ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "index_code TEXT NOT NULL,"
                    "scheduled_date TEXT NOT NULL,"
                    "total_stocks INTEGER NOT NULL DEFAULT 0,"
                    "completed_stocks INTEGER NOT NULL DEFAULT 0,"
                    "failed_stocks INTEGER NOT NULL DEFAULT 0,"
                    "skipped_stocks INTEGER NOT NULL DEFAULT 0,"
                    "status TEXT NOT NULL DEFAULT 'pending',"
                    "started_at TIMESTAMP,"
                    "completed_at TIMESTAMP,"
                    "error_message TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(index_code, scheduled_date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_uj_date "
                    "ON sentiment_universe_jobs(scheduled_date, status)")
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_universe_scores ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "index_code TEXT NOT NULL,"
                    "stock_code TEXT NOT NULL,"
                    "forum_type TEXT NOT NULL DEFAULT 'eastmoney',"
                    "date TEXT NOT NULL,"
                    "score REAL,"
                    "sentiment TEXT,"
                    "bullish_n INTEGER DEFAULT 0,"
                    "bearish_n INTEGER DEFAULT 0,"
                    "neutral_n INTEGER DEFAULT 0,"
                    "noise_n INTEGER DEFAULT 0,"
                    "panic_signal INTEGER DEFAULT 0,"
                    "euphoria_signal INTEGER DEFAULT 0,"
                    "momentum_cross INTEGER DEFAULT 0,"
                    "ema3 REAL,"
                    "ema5 REAL,"
                    "source TEXT NOT NULL DEFAULT 'universe_crawl',"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "UNIQUE(index_code, stock_code, date))"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_uus_code_date "
                    "ON sentiment_universe_scores(stock_code, date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_uus_index_date "
                    "ON sentiment_universe_scores(index_code, date)")
        cur.execute("CREATE TABLE IF NOT EXISTS sentiment_universe_aggregates ("
                    "index_code TEXT NOT NULL,"
                    "date TEXT NOT NULL,"
                    "total_stocks INTEGER NOT NULL,"
                    "analyzed_stocks INTEGER NOT NULL DEFAULT 0,"
                    "failed_stocks INTEGER DEFAULT 0,"
                    "avg_score REAL,"
                    "median_score REAL,"
                    "std_score REAL,"
                    "bullish_count INTEGER DEFAULT 0,"
                    "neutral_count INTEGER DEFAULT 0,"
                    "bearish_count INTEGER DEFAULT 0,"
                    "panic_count INTEGER DEFAULT 0,"
                    "euphoria_count INTEGER DEFAULT 0,"
                    "momentum_cross_count INTEGER DEFAULT 0,"
                    "avg_ema3 REAL,"
                    "avg_ema5 REAL,"
                    "distribution_json TEXT,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "PRIMARY KEY (index_code, date))"
        )

        # 任务调度配置（v5, 2026-06-06）：每行一个 APScheduler 任务的可调参数
        cur.execute("CREATE TABLE IF NOT EXISTS scheduler_task_config ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "job_id TEXT UNIQUE NOT NULL,"
                    "display_name TEXT NOT NULL,"
                    "description TEXT,"
                    "trigger_type TEXT NOT NULL CHECK(trigger_type IN ('cron','interval')),"
                    "hour INTEGER,"
                    "minute INTEGER,"
                    "day_of_week TEXT,"
                    "interval_hours INTEGER,"
                    "enabled INTEGER NOT NULL DEFAULT 1,"
                    "next_run_time TIMESTAMP,"
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "updated_by TEXT)"
        )

        # 任务运行历史（v5, 2026-06-07）：记录每个任务的每次触发结果
        cur.execute("CREATE TABLE IF NOT EXISTS scheduler_task_run ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "job_id TEXT NOT NULL,"
                    "started_at TIMESTAMP NOT NULL,"
                    "finished_at TIMESTAMP,"
                    "status TEXT NOT NULL CHECK(status IN ('running','success','failed','skipped')),"
                    "message TEXT,"
                    "duration_ms INTEGER)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_job_started "
                    "ON scheduler_task_run(job_id, started_at DESC)")

        # ── 统一任务追踪（Phase A, 2026-06-10） ──
        cur.execute("CREATE TABLE IF NOT EXISTS task_runs ("
                    "id TEXT PRIMARY KEY,"
                    "kind TEXT NOT NULL,"
                    "title TEXT,"
                    "status TEXT NOT NULL DEFAULT 'pending',"
                    "total INTEGER DEFAULT 0,"
                    "done INTEGER DEFAULT 0,"
                    "current_step TEXT,"
                    "payload_json TEXT,"
                    "result_json TEXT,"
                    "error_message TEXT,"
                    "error_traceback TEXT,"
                    "triggered_by TEXT NOT NULL DEFAULT 'user',"
                    "user_id INTEGER,"
                    "scheduler_job TEXT,"
                    "cancel_requested INTEGER DEFAULT 0,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
                    "started_at TIMESTAMP,"
                    "finished_at TIMESTAMP,"
                    "duration_ms INTEGER)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_kind_status "
                    "ON task_runs(kind, status, created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_status_started "
                    "ON task_runs(status, started_at DESC)")

        cur.execute("CREATE TABLE IF NOT EXISTS task_run_logs ("
                    "id INTEGER PRIMARY KEY,"
                    "task_run_id TEXT NOT NULL,"
                    "level TEXT NOT NULL,"
                    "message TEXT NOT NULL,"
                    "context_json TEXT,"
                    "step_index INTEGER,"
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trl_run_id "
                    "ON task_run_logs(task_run_id, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trl_milestone "
                    "ON task_run_logs(task_run_id, level) WHERE level = 'milestone'")

        cur.execute("""CREATE TABLE IF NOT EXISTS financial_reports_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            report_date TEXT,
            ttm_revenue REAL,
            ttm_net_profit REAL,
            ttm_gross_profit REAL,
            ttm_eps REAL,
            quarterly_data TEXT,
            price REAL,
            total_market_cap REAL,
            float_market_cap REAL,
            total_shares REAL,
            float_shares REAL,
            ttm_pe REAL,
            pe_history TEXT,
            price_history TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # 兼容旧 schema：若缺少新增字段，补列（IF NOT EXISTS 在 SQLite 3.35+ 支持）
        for col, typedef in [
            ("ttm_eps", "REAL"),
            ("total_market_cap", "REAL"),
            ("float_market_cap", "REAL"),
            ("total_shares", "REAL"),
            ("float_shares", "REAL"),
            ("ttm_pe", "REAL"),
            ("pe_history", "TEXT"),
            ("price_history", "TEXT"),
            ("ttm_pe_percentile", "REAL"),
            ("ttm_pe_percentile_basis", "TEXT"),
        ]:
            try:
                cur.execute(f"ALTER TABLE financial_reports_cache ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # 已存在，忽略
        # ── VIX 2.0 机器学习指标（2026-06-29）──
        # 与 v6.1 vix_history 完全独立，便于同屏对比、互不污染。
        cur.execute("""CREATE TABLE IF NOT EXISTS vix2_history (
            date TEXT PRIMARY KEY,
            p_up REAL,                 -- 模型输出的上涨/底部概率
            score REAL,                -- (1-p_up)*100，低分=恐慌=机会
            percentile REAL,           -- 近 252 日滚动百分位
            regime TEXT,               -- 沿用 classify_by_percentile
            model_version TEXT,
            features_json TEXT,        -- 当日因子快照（审计用）
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        cur.execute("""CREATE TABLE IF NOT EXISTS report_parse_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_text_hash TEXT NOT NULL,
            report_text_preview TEXT,
            parsed_result TEXT,
            model_name TEXT,
            company_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rph_hash "
                    "ON report_parse_history(report_text_hash)")



def _create_default_admin(conn):
    if not DEFAULT_ADMIN_USER or not DEFAULT_ADMIN_PASSWORD:
        return

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM py_users")
    if cur.fetchone()[0] > 0:
        return

    register_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)


# ─────────────────────────────────────────────────────────────────
# VIX 历史数据 CRUD（v3, 2026-06-04）
# ─────────────────────────────────────────────────────────────────

def upsert_vix_history(date: str, payload: dict) -> None:
    """写入/覆盖某日 VIX 快照。"""
    cols = (
        "date", "iv_50etf", "iv_300etf", "iv_500etf", "iv_cyb", "iv_kcb",
        "pcr", "pcr_volume", "pcr_oi", "pcr_call_volume", "pcr_put_volume",
        "pcr_source", "vix_source", "vix_zscore",
        "rv_hs300", "rv_zz1000", "rv_blended",
        "north_net", "margin_balance", "margin_source",
        "limit_up_count", "limit_down_count", "limit_source",
        "vix", "fear_greed", "regime", "components_json",
        # v2: 现货位置 + 合成评分（2026-06-04）
        "spot_close", "spot_ma60_dev", "spot_mom_5d", "spot_mom_20d",
        "spot_new_high_ratio", "composite_score", "composite_regime",
        # v5: composite 滚动百分位（2026-06-09）
        "composite_percentile",
        # v7.0: construct-truth 恐惧贪婪（2026-06-29）
        "fear_truth_v7", "fear_greed_v7",
        "comp_drawdown_v7", "comp_breadth_v7", "comp_iv_surge_v7", "comp_iv_level_v7",
        "regime_v7",
    )
    placeholders = ",".join("?" for _ in cols)
    col_list = ",".join(cols)
    values = [date] + [payload.get(c) for c in cols[1:]]
    with get_connection() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO vix_history ({col_list}) VALUES ({placeholders})",
            values,
        )


def get_vix_history_for_zscore(days: int = 252) -> list[float]:
    """取最近 N 天的 vix 值（仅数值列表），用于 Z-Score 计算。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT vix FROM vix_history ORDER BY date DESC LIMIT ?",
            (days,),
        )
        return [r[0] for r in cur.fetchall() if r[0] is not None]


def get_vix_latest() -> dict | None:
    """最近一日的 VIX 快照。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM vix_history ORDER BY date DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_vix_history(days: int = 60) -> list[dict]:
    """最近 N 天 VIX 历史（按日期升序）。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM vix_history ORDER BY date DESC LIMIT ?",
            (days,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]


def get_vix_history_count() -> int:
    """vix_history 表总行数（DB 实际存了多少天 VIX）。"""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM vix_history").fetchone()
        return int(row[0]) if row else 0


def get_vix_history_for_range(start_date: str, end_date: str) -> list[dict]:
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM vix_history WHERE date BETWEEN ? AND ? ORDER BY date ASC",
            (start_date, end_date),
        )
        return [dict(r) for r in cur.fetchall()]


def compute_vix_percentile(current_vix: float, days: int = 250) -> float:
    """计算当前 VIX 在历史 N 天的百分位（0-100），用于判断"当前是历史上多恐慌的位置"。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT vix FROM vix_history ORDER BY date DESC LIMIT ?",
            (days,),
        )
        history = [r[0] for r in cur.fetchall() if r[0] is not None]
    if not history:
        return 50.0
    below = sum(1 for v in history if v <= current_vix)
    return round(below / len(history) * 100, 1)


# ─────────────────────────────────────────────────────────────────
# VIX 2.0（机器学习）历史 CRUD（2026-06-29）— 独立于 vix_history
# ─────────────────────────────────────────────────────────────────

def upsert_vix2_history(date: str, payload: dict) -> None:
    """写入/覆盖某日 VIX 2.0 快照。payload 含 p_up/score/percentile/regime/
    model_version/features_json。"""
    import json as _json
    feats = payload.get("features_json")
    if feats is not None and not isinstance(feats, str):
        feats = _json.dumps(feats, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vix2_history "
            "(date, p_up, score, percentile, regime, model_version, features_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                date, payload.get("p_up"), payload.get("score"),
                payload.get("percentile"), payload.get("regime"),
                payload.get("model_version"), feats,
            ),
        )


def get_vix2_latest() -> dict | None:
    """最近一日 VIX 2.0 快照。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM vix2_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_vix2_history(days: int = 365) -> list[dict]:
    """最近 N 天 VIX 2.0 历史（按日期升序）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vix2_history ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_vix2_history_count() -> int:
    """vix2_history 表总行数。"""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM vix2_history").fetchone()
        return int(row[0]) if row else 0


def get_vix2_scores_asc() -> list[tuple]:
    """全表 (date, score)，按日期升序，用于 point-in-time 百分位重算。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, score FROM vix2_history "
            "WHERE score IS NOT NULL ORDER BY date ASC"
        ).fetchall()
        return [(r[0], float(r[1])) for r in rows]


def update_vix2_percentile(date: str, percentile: float, regime: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE vix2_history SET percentile = ?, regime = ? WHERE date = ?",
            (percentile, regime, date),
        )


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


# ── 统一任务追踪 CRUD (Phase A, 2026-06-10) ──

def insert_task_run(**kwargs) -> None:
    """插入一条 task_runs 记录。kwargs 键名对应列名。"""
    import json as _json
    cols = [
        "id", "kind", "title", "status", "total", "done", "current_step",
        "payload_json", "result_json", "error_message", "error_traceback",
        "triggered_by", "user_id", "scheduler_job", "cancel_requested",
        "created_at", "started_at", "finished_at", "duration_ms",
    ]
    values = {}
    for c in cols:
        v = kwargs.get(c)
        if isinstance(v, (dict, list)):
            v = _json.dumps(v, ensure_ascii=False)
        values[c] = v
    vals = [values.get(c) for c in cols]
    ph = placeholders(len(cols))
    col_list = ",".join(cols)
    with get_connection() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO task_runs ({col_list}) VALUES ({ph})", vals
        )


def update_task_run(task_id: str, **kwargs) -> None:
    """更新 task_runs 的部分字段。"""
    import json as _json
    allowed = {
        "status", "total", "done", "current_step", "result_json",
        "error_message", "error_traceback", "cancel_requested",
        "started_at", "finished_at", "duration_ms",
    }
    updates = {}
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if isinstance(v, (dict, list)):
            v = _json.dumps(v, ensure_ascii=False)
        updates[k] = v
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [task_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE task_runs SET {set_clause} WHERE id = ?", vals
        )


def get_task_run(task_id: str) -> dict | None:
    """获取单个 task_run。"""
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def list_task_runs(
    kind: str | None = None,
    status: str | None = None,
    triggered_by: str | None = None,
    limit: int = 20,
) -> list:
    """列出 task_runs，支持过滤。"""
    clauses = []
    params = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if triggered_by:
        clauses.append("triggered_by = ?")
        params.append(triggered_by)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_connection() as conn:
        cur = conn.execute(
            f"SELECT * FROM task_runs{where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def get_active_task_runs() -> list:
    """返回所有 status='running' 的 task_runs。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM task_runs WHERE status = 'running' ORDER BY started_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def cleanup_orphan_task_runs() -> int:
    """启动时清理孤儿任务：进程崩溃/重启后残留的 status='running' 行。

    这些行的执行线程已随上一次进程退出而消失，但 DB 状态停在 running，
    会让 get_active_task_runs() 永远认为有任务在跑，导致回填/重算端点
    一直返回 409「已有任务在进行中」。启动时统一标记为 failed。
    返回清理的行数。
    """
    from datetime import datetime as _dt
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE task_runs SET status='failed', "
            "error_message='进程中断（启动时清理孤儿任务）', finished_at=? "
            "WHERE status IN ('running', 'pending')",
            (_dt.now().isoformat(),),
        )
        n = cur.rowcount
    if n:
        logger.warning(f"启动清理: 标记 {n} 个孤儿任务为 failed")
    return n



def get_recent_task_runs(limit: int = 20) -> list:
    """返回最近 N 个 task_runs（任意状态）。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM task_runs ORDER BY COALESCE(finished_at, started_at, created_at) DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def mark_task_cancelled(task_id: str) -> bool:
    """将 cancel_requested 置 1，返回是否找到该记录。"""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE task_runs SET cancel_requested = 1 WHERE id = ?", (task_id,)
        )
        return cur.rowcount > 0


def append_task_run_log(
    task_run_id: str,
    level: str,
    message: str,
    context_json: dict | None = None,
    step_index: int | None = None,
) -> int:
    """追加一条 task_run_logs，返回新记录的 id。"""
    import json as _json
    ctx = _json.dumps(context_json, ensure_ascii=False) if context_json else None
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_run_logs (task_run_id, level, message, context_json, step_index) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_run_id, level, message, ctx, step_index),
        )
        return cur.lastrowid


def get_task_run_logs(
    task_run_id: str,
    since_id: int = 0,
    level: str | None = None,
) -> list:
    """增量拉取 task_run_logs。since_id=0 表示从头开始。"""
    if level:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM task_run_logs WHERE task_run_id = ? AND id > ? AND level = ? "
                "ORDER BY id ASC",
                (task_run_id, since_id, level),
            )
            return [dict(r) for r in cur.fetchall()]
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM task_run_logs WHERE task_run_id = ? AND id > ? ORDER BY id ASC",
            (task_run_id, since_id),
        )
        return [dict(r) for r in cur.fetchall()]


def get_latest_milestone(task_run_id: str) -> dict | None:
    """获取最新的 milestone 日志。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM task_run_logs WHERE task_run_id = ? AND level = 'milestone' "
            "ORDER BY id DESC LIMIT 1",
            (task_run_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


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


# ── 舆情帖子过滤规则 CRUD ──

def _init_sentiment_filters(conn):
    """初始化预置过滤规则（幂等）。"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sentiment_filters")
    if cur.fetchone()[0] > 0:
        return
    presets = [
        ("转发", "title_keyword", "纯转发帖子，无实际内容"),
        ("阅读", "title_keyword", "阅读量展示帖，无实质讨论"),
        ("股吧", "title_keyword", "跨板块无关帖子"),
        ("收藏", "title_keyword", "收藏类无意义帖子"),
        ("发表于", "title_keyword", "时间戳类标题，无实质内容"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO sentiment_filters (filter_key, filter_type, description) VALUES (?, ?, ?)",
        presets,
    )


def get_sentiment_filters(filter_type: str = None, enabled_only: bool = True) -> list:
    """获取过滤规则白名单。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if filter_type:
            sql = "SELECT * FROM sentiment_filters WHERE filter_type=? AND enabled=1" if enabled_only else "SELECT * FROM sentiment_filters WHERE filter_type=?"
            params = (filter_type,)
        elif enabled_only:
            sql = "SELECT * FROM sentiment_filters WHERE enabled=1"
            params = ()
        else:
            sql = "SELECT * FROM sentiment_filters"
            params = ()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def add_sentiment_filter(filter_key: str, filter_type: str = "title_keyword",
                         description: str = "") -> dict | None:
    """新增过滤规则。"""
    filter_key = str(filter_key).strip()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO sentiment_filters
                   (filter_key, filter_type, description)
                   VALUES (?, ?, ?)""",
                (filter_key, filter_type, description),
            )
            if cur.lastrowid:
                cur.execute("SELECT * FROM sentiment_filters WHERE id=?", (cur.lastrowid,))
                return dict(cur.fetchone())
    except Exception as e:
        logger.warning(f"新增过滤规则失败: {e}")
    return None


def delete_sentiment_filter(filter_id: int) -> bool:
    """删除过滤规则（物理删除）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sentiment_filters WHERE id=?", (filter_id,))
        return cur.rowcount > 0


# ── 舆情帖子标题审计 CRUD（v1, 2026-06-04） ──

def get_audit_posts(code: str, forum_type: str = "eastmoney",
                    only_mismatch: bool = False, limit: int = 200) -> list:
    """获取某股票的帖子审计状态列表。

    Args:
        code: 6位股票代码
        forum_type: 论坛类型
        only_mismatch: 是否只返回不一致 / 未审计 / 错误的帖子
        limit: 上限
    """
    with get_connection() as conn:
        cur = conn.cursor()
        sql = (
            "SELECT id, title, actual_title, title_match, audit_status, "
            "title_verified_at, audit_note, url, author, post_time "
            "FROM forum_posts WHERE stock_code=? AND forum_type=?"
        )
        params = [code, forum_type]
        if only_mismatch:
            sql += " AND (title_match=0 OR audit_status IN ('mismatch','pending','broken'))"
        sql += " ORDER BY post_time DESC LIMIT ?"
        params.append(limit)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def update_post_audit(post_id: int, actual_title: str | None,
                      title_match: int | None, audit_status: str,
                      audit_note: str | None = None) -> bool:
    """更新单条帖子的审计结果。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if audit_note is not None:
            cur.execute(
                """UPDATE forum_posts
                   SET actual_title=?, title_match=?, title_verified_at=CURRENT_TIMESTAMP,
                       audit_status=?, audit_note=?
                   WHERE id=?""",
                (actual_title, title_match, audit_status, audit_note, post_id),
            )
        else:
            cur.execute(
                """UPDATE forum_posts
                   SET actual_title=?, title_match=?, title_verified_at=CURRENT_TIMESTAMP,
                       audit_status=?
                   WHERE id=?""",
                (actual_title, title_match, audit_status, post_id),
            )
        return cur.rowcount > 0


def accept_actual_title(post_id: int) -> dict | None:
    """接受 actual_title 覆盖 title，返回更新后的帖子。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT actual_title FROM forum_posts WHERE id=?",
            (post_id,),
        )
        row = cur.fetchone()
        if not row or not row["actual_title"]:
            return None
        cur.execute(
            """UPDATE forum_posts
               SET title=actual_title, audit_status='manual_accepted',
                   title_match=1, audit_note=NULL
               WHERE id=?""",
            (post_id,),
        )
        cur.execute(
            "SELECT id, title, actual_title, audit_status, title_match FROM forum_posts WHERE id=?",
            (post_id,),
        )
        return dict(cur.fetchone())


def mark_post_broken(post_id: int, note: str = "") -> bool:
    """标记帖子为垃圾（前端展示时过滤掉）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE forum_posts
               SET audit_status='broken', audit_note=?
               WHERE id=?""",
            (note, post_id),
        )
        return cur.rowcount > 0


def reset_post_audit(post_id: int) -> bool:
    """重置帖子审计状态为 pending。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE forum_posts
               SET actual_title=NULL, title_match=NULL,
                   title_verified_at=NULL, audit_status='pending',
                   audit_note=NULL
               WHERE id=?""",
            (post_id,),
        )
        return cur.rowcount > 0


def get_audit_summary(stock_code: str | None = None) -> dict:
    """全局（或单只股票）审计摘要。"""
    with get_connection() as conn:
        cur = conn.cursor()
        # audited = 已有明确判定（verified/mismatch/manual_accepted/manual_rejected）
        # pending = 还没真正审计 或 被重置后
        if stock_code:
            cur.execute(
                """SELECT
                     COUNT(*) AS total_posts,
                     SUM(CASE WHEN audit_status IN ('verified','mismatch','manual_accepted','manual_rejected') THEN 1 ELSE 0 END) AS audited,
                     SUM(CASE WHEN title_match=1 OR audit_status IN ('verified','manual_accepted') THEN 1 ELSE 0 END) AS matched,
                     SUM(CASE WHEN title_match=0 OR audit_status='mismatch' THEN 1 ELSE 0 END) AS mismatched,
                     SUM(CASE WHEN audit_status='broken' THEN 1 ELSE 0 END) AS broken,
                     SUM(CASE WHEN audit_status='pending' OR audit_status IS NULL THEN 1 ELSE 0 END) AS pending
                   FROM forum_posts WHERE stock_code=?""",
                (stock_code,),
            )
        else:
            cur.execute(
                """SELECT
                     COUNT(*) AS total_posts,
                     SUM(CASE WHEN audit_status IN ('verified','mismatch','manual_accepted','manual_rejected') THEN 1 ELSE 0 END) AS audited,
                     SUM(CASE WHEN title_match=1 OR audit_status IN ('verified','manual_accepted') THEN 1 ELSE 0 END) AS matched,
                     SUM(CASE WHEN title_match=0 OR audit_status='mismatch' THEN 1 ELSE 0 END) AS mismatched,
                     SUM(CASE WHEN audit_status='broken' THEN 1 ELSE 0 END) AS broken,
                     SUM(CASE WHEN audit_status='pending' OR audit_status IS NULL THEN 1 ELSE 0 END) AS pending
                   FROM forum_posts"""
            )
        row = cur.fetchone()
    total = row["total_posts"] or 0
    audited = row["audited"] or 0
    mismatched = row["mismatched"] or 0
    mismatch_rate = round(mismatched / audited * 100, 1) if audited else 0.0
    return {
        "total_posts": total,
        "audited": audited,
        "matched": row["matched"] or 0,
        "mismatched": mismatched,
        "broken": row["broken"] or 0,
        "pending": row["pending"] or 0,
        "mismatch_rate": mismatch_rate,
    }


def get_post_by_id(post_id: int) -> dict | None:
    """按主键取帖子（含审计字段 + 正文内容）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, stock_code, forum_type, title, actual_title, "
            "title_match, audit_status, title_verified_at, audit_note, "
            "url, author, post_time, content FROM forum_posts WHERE id=?",
            (post_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_post_content(post_id: int, content: str) -> bool:
    """更新帖子正文（手动重抓时调用）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE forum_posts SET content=? WHERE id=?",
            (content, post_id),
        )
        return cur.rowcount > 0


# ── 舆情 v3 升级（2026-06-06）：post labels / top picks / indicators ──


def upsert_post_labels(stock_code: str, labels: list[dict],
                       forum_type: str = "eastmoney",
                       model: str = "") -> int:
    """批量写入/覆盖某只股票当日的帖子级 LLM 标签。

    Args:
        labels: [{post_id, label, raw_response?}]，label ∈ {1, 0, -1, 99}

    Returns:
        实际写入条数
    """
    if not labels:
        return 0
    label_date = datetime.now().strftime("%Y-%m-%d")
    rows = [
        (stock_code, int(l["post_id"]), forum_type, label_date,
         int(l["label"]), model, l.get("raw_response"))
        for l in labels if l.get("post_id") is not None
    ]
    if not rows:
        return 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(
            """INSERT OR REPLACE INTO sentiment_post_labels
               (stock_code, post_id, forum_type, date, label, model, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return cur.rowcount


def get_post_labels(stock_code: str, date: str | None = None,
                    days: int = 1) -> list[dict]:
    """获取某只股票最近 N 天的帖子级标签。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if date:
            cur.execute(
                """SELECT * FROM sentiment_post_labels
                   WHERE stock_code=? AND date=?
                   ORDER BY post_id""",
                (stock_code, date),
            )
        else:
            cur.execute(
                """SELECT * FROM sentiment_post_labels
                   WHERE stock_code=?
                   AND date >= date('now', ?)
                   ORDER BY date DESC, post_id""",
                (stock_code, f"-{days} day"),
            )
        return [dict(r) for r in cur.fetchall()]


# ── 热门股池 ──


def upsert_top_picks(snapshot_date: str, picks: list[dict],
                     source: str = "volume_top100") -> int:
    """写入某日 top N 热门股。

    Args:
        picks: [{stock_code, stock_name, rank, amount}]
    """
    if not picks:
        return 0
    rows = [
        (p["stock_code"], p.get("stock_name", ""), int(p["rank"]),
         float(p.get("amount", 0) or 0), source, snapshot_date)
        for p in picks if p.get("stock_code")
    ]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(
            """INSERT OR REPLACE INTO sentiment_top_picks
               (stock_code, stock_name, rank, amount, source, snapshot_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return cur.rowcount


def get_latest_top_picks(snapshot_date: str | None = None,
                         limit: int = 100) -> list[dict]:
    """获取某日（默认最新一天）的 top picks 列表。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if snapshot_date is None:
            cur.execute("SELECT MAX(snapshot_date) FROM sentiment_top_picks")
            row = cur.fetchone()
            snapshot_date = row[0] if row and row[0] else None
        if not snapshot_date:
            return []
        cur.execute(
            """SELECT * FROM sentiment_top_picks
               WHERE snapshot_date=?
               ORDER BY rank LIMIT ?""",
            (snapshot_date, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def mark_top_pick_auto_added(stock_code: str, snapshot_date: str) -> bool:
    """标记某只热门股已被自动加入 sentiment_config。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE sentiment_top_picks
               SET auto_added=1
               WHERE stock_code=? AND snapshot_date=?""",
            (stock_code, snapshot_date),
        )
        return cur.rowcount > 0


# ── 时序因子（EMA / panic / euphoria） ──


def upsert_indicators(stock_code: str, date: str,
                      score: float, ema3: float | None, ema5: float | None,
                      bullish_ma30: float | None, bullish_std30: float | None,
                      bearish_ma30: float | None, bearish_std30: float | None,
                      panic_signal: int, euphoria_signal: int,
                      momentum_cross: int) -> bool:
    """写入/覆盖某只股票当日的时序因子。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO sentiment_indicators
               (stock_code, date, score, ema3, ema5,
                bullish_ma30, bullish_std30, bearish_ma30, bearish_std30,
                panic_signal, euphoria_signal, momentum_cross)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (stock_code, date, score, ema3, ema5,
             bullish_ma30, bullish_std30, bearish_ma30, bearish_std30,
             int(panic_signal), int(euphoria_signal), int(momentum_cross)),
        )
        return cur.rowcount > 0


def get_indicators(stock_code: str, days: int = 30) -> list[dict]:
    """获取某只股票的最近 N 天时序因子。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM sentiment_indicators
               WHERE stock_code=?
               AND date >= date('now', ?)
               ORDER BY date""",
            (stock_code, f"-{days} day"),
        )
        return [dict(r) for r in cur.fetchall()]


def get_sentiment_latest_overview(codes: list[str], forum_type: str = "eastmoney",
                                  post_limit: int = 15) -> dict:
    """批量取多只股票的最新情绪概览（消除 /latest 端点的 N+1 查询）。

    一次查询返回每只股票的：最新一天 sentiment_scores 行、最新一天
    sentiment_indicators 行、最近 post_limit 条帖子。3 条 SQL 替代
    原 per-config 3×N 次。

    Returns:
        {code: {"history": row|None, "indicators": row|None, "posts": [...]}}
    """
    codes = [str(c).strip().zfill(6) for c in codes if c]
    out: dict[str, dict] = {c: {"history": None, "indicators": None, "posts": []}
                            for c in codes}
    if not codes:
        return out
    ph = ",".join("?" for _ in codes)

    with get_connection() as conn:
        cur = conn.cursor()
        # 最新一天 scores（每只取 date 最大的一行）
        cur.execute(
            f"""SELECT s.* FROM sentiment_scores s
                JOIN (SELECT stock_code, MAX(date) AS max_date
                      FROM sentiment_scores
                      WHERE forum_type=? AND stock_code IN ({ph})
                      GROUP BY stock_code) m
                  ON m.stock_code=s.stock_code AND m.max_date=s.date
                WHERE s.forum_type=?""",
            [forum_type, *codes, forum_type],
        )
        for r in cur.fetchall():
            r = dict(r)
            out[r["stock_code"]]["history"] = r

        # 最新一天 indicators
        cur.execute(
            f"""SELECT i.* FROM sentiment_indicators i
                JOIN (SELECT stock_code, MAX(date) AS max_date
                      FROM sentiment_indicators
                      WHERE stock_code IN ({ph})
                      GROUP BY stock_code) m
                  ON m.stock_code=i.stock_code AND m.max_date=i.date""",
            [*codes],
        )
        for r in cur.fetchall():
            r = dict(r)
            out[r["stock_code"]]["indicators"] = r

        # 每只最近 post_limit 条帖子（窗口函数）
        cur.execute(
            f"""SELECT * FROM (
                  SELECT id, stock_code, title, actual_title, title_match,
                         audit_status, title_verified_at, content, author,
                         post_time, url,
                         ROW_NUMBER() OVER (PARTITION BY stock_code
                                            ORDER BY post_time DESC) AS rn
                  FROM forum_posts
                  WHERE forum_type=? AND stock_code IN ({ph})
                    AND (audit_status IS NULL OR audit_status != 'broken')
                ) WHERE rn <= ?""",
            [forum_type, *codes, post_limit],
        )
        for r in cur.fetchall():
            r = dict(r)
            code = r["stock_code"]
            out[code]["posts"].append({
                "post_id": r["id"],
                "title": r["title"],
                "actual_title": r["actual_title"],
                "title_match": r["title_match"],
                "audit_status": r["audit_status"],
                "title_verified_at": r["title_verified_at"],
                "content": r["content"],
                "author": r["author"],
                "post_time": r["post_time"],
                "url": r["url"],
            })

    return out


def get_latest_signals(date: str | None = None) -> list[dict]:
    """获取某日（默认最新一天）所有触发了 panic / euphoria 的股票。

    用于前端「今日极端情绪」看板 + 策略层消费。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        if date is None:
            cur.execute("SELECT MAX(date) FROM sentiment_indicators")
            row = cur.fetchone()
            date = row[0] if row and row[0] else None
        if not date:
            return []
        cur.execute(
            """SELECT i.*, c.stock_name
               FROM sentiment_indicators i
               LEFT JOIN sentiment_config c
                 ON c.stock_code = i.stock_code AND c.forum_type='eastmoney'
               WHERE i.date=?
                 AND (i.panic_signal=1 OR i.euphoria_signal=1
                      OR i.momentum_cross=1)
               ORDER BY i.panic_signal DESC, i.euphoria_signal DESC""",
            (date,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── 知乎监控 CRUD ──

def _extract_url_token(url_or_token: str) -> str:
    """从 URL 或 url_token 字符串中提取 url_token。"""
    s = (url_or_token or "").strip()
    m = re.search(r"zhihu\.com/people/([\w-]+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    return s.lstrip("@")


def get_zhihu_users(enabled_only: bool = False) -> list:
    """获取监控的知乎用户列表。"""
    with get_connection() as conn:
        cur = conn.cursor()
        sql = "SELECT * FROM zhihu_users" + (" WHERE enabled=1" if enabled_only else "")
        sql += " ORDER BY id DESC"
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def get_zhihu_user_by_token(url_token: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM zhihu_users WHERE url_token=?", (url_token,))
        row = cur.fetchone()
        return dict(row) if row else None


def add_zhihu_user(url_or_token: str, display_name: str = "",
                   avatar_url: str = "", headline: str = "",
                   follower_count: int = 0) -> dict | None:
    token = _extract_url_token(url_or_token)
    if not token:
        return None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO zhihu_users
                   (url_token, display_name, avatar_url, headline, follower_count, enabled)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (token, display_name, avatar_url, headline, follower_count),
            )
            cur.execute("SELECT * FROM zhihu_users WHERE url_token=?", (token,))
            return dict(cur.fetchone())
    except Exception as e:
        logger.warning(f"新增知乎用户失败: {e}")
        return None


def update_zhihu_user(user_id: int, **kwargs) -> bool:
    """更新 zhihu_users 字段（白名单）。"""
    allowed = {"display_name", "avatar_url", "headline", "follower_count",
               "enabled", "email_notify", "last_checked_at",
               "last_notified_at", "last_error"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE zhihu_users SET {sets} WHERE id=?", vals)
        return cur.rowcount > 0


def delete_zhihu_user(user_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM zhihu_users WHERE id=?", (user_id,))
        return cur.rowcount > 0


def upsert_zhihu_post(url_token: str, post_id: str, post_type: str,
                      title: str, excerpt: str, content_text: str,
                      url: str, voteup_count: int, comment_count: int,
                      created_at_original: str) -> tuple[bool, int]:
    """插入知乎动态（URL 唯一），返回 (是否新增, id)。

    若已存在且 content_text 为空（之前抓取失败的占位），用新内容回填。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR IGNORE INTO zhihu_posts
               (url_token, post_id, post_type, title, excerpt, content_text,
                url, voteup_count, comment_count, created_at_original)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (url_token, post_id, post_type, title, excerpt, content_text,
             url, voteup_count, comment_count, created_at_original),
        )
        inserted = cur.rowcount > 0
        # 若新数据有正文但旧记录 content_text 为空，回填
        if not inserted and content_text:
            cur.execute(
                """UPDATE zhihu_posts
                   SET title=?, excerpt=?, content_text=?,
                       voteup_count=?, comment_count=?, created_at_original=?
                   WHERE url=? AND (content_text IS NULL OR content_text='')""",
                (title, excerpt, content_text,
                 voteup_count, comment_count, created_at_original, url),
            )
        cur.execute("SELECT id FROM zhihu_posts WHERE url=?", (url,))
        row = cur.fetchone()
        post_pk = row["id"] if row else 0
        return inserted, post_pk


def get_zhihu_posts(url_token: str = None, limit: int = 20) -> list:
    """获取知乎动态（带分析结果）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if url_token:
            cur.execute(
                """SELECT p.*, a.stance, a.stance_assets, a.sectors,
                          a.summary, a.action_suggestion, a.key_points,
                          a.confidence, a.analyzed_at
                   FROM zhihu_posts p
                   LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
                   WHERE p.url_token=?
                   ORDER BY p.created_at_original DESC
                   LIMIT ?""",
                (url_token, limit),
            )
        else:
            cur.execute(
                """SELECT p.*, a.stance, a.stance_assets, a.sectors,
                          a.summary, a.action_suggestion, a.key_points,
                          a.confidence, a.analyzed_at
                   FROM zhihu_posts p
                   LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
                   ORDER BY p.created_at_original DESC
                   LIMIT ?""",
                (limit,),
            )
        rows = [dict(r) for r in cur.fetchall()]
    return rows


def _is_stock_related(stance, stance_assets, sectors) -> bool:
    """判断 LLM 分析结果是否与股票/投资相关。

    大V时间线只保留与投资相关的动态，过滤掉「中性立场 + 未提任何资产或行业」
    的纯生活/职场/科普类内容。规则（任一满足即视为相关）：
      1. stance 为 bullish / bearish / mixed（非中性立场）
      2. stance_assets 非空（提到 A股/港股/美股/黄金/加密等具体资产）
      3. sectors 非空（提到科技/金融/医药等行业）
    """
    if stance in ("bullish", "bearish", "mixed"):
        return True
    if stance_assets and len(stance_assets) > 0:
        return True
    if sectors and len(sectors) > 0:
        return True
    return False


def get_zhihu_timeline_posts(days: int = 7) -> list:
    """获取最近 N 天内所有大V的【已分析且与股票相关】的动态（时间升序，含用户资料）。

    非股票类动态（中性立场 + 无资产/行业提及）会被过滤。
    """
    import json as _json
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.id, p.url_token, p.post_id, p.post_type, p.title,
                      p.excerpt, p.url, p.created_at_original,
                      p.voteup_count, p.comment_count,
                      a.stance, a.stance_assets, a.sectors, a.summary,
                      a.action_suggestion, a.key_points, a.confidence,
                      a.model_name, a.analyzed_at,
                      u.display_name, u.avatar_url
               FROM zhihu_posts p
               JOIN zhihu_analyses a ON a.post_id = p.post_id
               JOIN zhihu_users u ON u.url_token = p.url_token
               WHERE p.created_at_original >= datetime('now', '-' || ? || ' days')
               ORDER BY p.created_at_original ASC""",
            (days,),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            for f in ("stance_assets", "sectors", "key_points"):
                raw = d.get(f)
                try:
                    d[f] = _json.loads(raw) if raw else []
                except (_json.JSONDecodeError, TypeError):
                    d[f] = []
            if not _is_stock_related(d.get("stance"), d.get("stance_assets"), d.get("sectors")):
                continue
            rows.append(d)
    return rows


def get_zhihu_post_by_id(post_id: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.*, a.stance, a.stance_assets, a.sectors,
                      a.summary, a.action_suggestion, a.key_points,
                      a.confidence, a.model_name, a.raw_response, a.analyzed_at
               FROM zhihu_posts p
               LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
               WHERE p.post_id=?""",
            (post_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_zhihu_analysis(post_id: str, url_token: str,
                          stance: str, stance_assets: str,
                          sectors: str, summary: str,
                          action_suggestion: str, key_points: str,
                          confidence: int, raw_response: str,
                          model_name: str) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO zhihu_analyses
               (post_id, url_token, stance, stance_assets, sectors, summary,
                action_suggestion, key_points, confidence, raw_response, model_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_id) DO UPDATE SET
                 stance=excluded.stance,
                 stance_assets=excluded.stance_assets,
                 sectors=excluded.sectors,
                 summary=excluded.summary,
                 action_suggestion=excluded.action_suggestion,
                 key_points=excluded.key_points,
                 confidence=excluded.confidence,
                 raw_response=excluded.raw_response,
                 model_name=excluded.model_name,
                 analyzed_at=CURRENT_TIMESTAMP""",
            (post_id, url_token, stance, stance_assets, sectors,
             summary, action_suggestion, key_points, confidence,
             raw_response, model_name),
        )
        cur.execute("SELECT id FROM zhihu_analyses WHERE post_id=?", (post_id,))
        row = cur.fetchone()
        return row["id"] if row else 0


def get_zhihu_subscriptions(enabled_only: bool = False) -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        sql = "SELECT * FROM zhihu_email_subscriptions"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id DESC"
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def add_zhihu_subscription(email: str, url_tokens: str = "[]") -> dict | None:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO zhihu_email_subscriptions
                   (email, url_tokens, enabled) VALUES (?, ?, 1)""",
                (email, url_tokens),
            )
            cur.execute("SELECT * FROM zhihu_email_subscriptions WHERE email=?", (email,))
            return dict(cur.fetchone())
    except Exception as e:
        logger.warning(f"新增邮件订阅失败: {e}")
        return None


def update_zhihu_subscription(sub_id: int, **kwargs) -> bool:
    allowed = {"url_tokens", "enabled", "verified"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [sub_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE zhihu_email_subscriptions SET {sets} WHERE id=?", vals)
        return cur.rowcount > 0


def delete_zhihu_subscription(sub_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM zhihu_email_subscriptions WHERE id=?", (sub_id,))
        return cur.rowcount > 0


def get_zhihu_smtp_settings() -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM zhihu_smtp_settings WHERE id=1")
        row = cur.fetchone()
        return dict(row) if row else None


def save_zhihu_smtp_settings(host: str, port: int, user: str,
                             password: str, smtp_from: str,
                             use_ssl: int) -> bool:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO zhihu_smtp_settings
                   (id, smtp_host, smtp_port, smtp_user, smtp_password,
                    smtp_from, smtp_use_ssl, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(id) DO UPDATE SET
                     smtp_host=excluded.smtp_host,
                     smtp_port=excluded.smtp_port,
                     smtp_user=excluded.smtp_user,
                     smtp_password=excluded.smtp_password,
                     smtp_from=excluded.smtp_from,
                     smtp_use_ssl=excluded.smtp_use_ssl,
                     updated_at=CURRENT_TIMESTAMP""",
                (host, port, user, password, smtp_from, use_ssl),
            )
        return True
    except Exception as e:
        logger.error(f"保存 SMTP 设置失败: {e}")
        return False


def add_zhihu_email_log(email: str, subject: str, url_token: str,
                        post_ids: str, status: str,
                        error_message: str = "") -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO zhihu_email_log
               (email, subject, url_token, post_ids, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email, subject, url_token or "", post_ids or "[]", status, error_message),
        )
        return cur.lastrowid or 0


def get_zhihu_email_logs(limit: int = 50) -> list:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM zhihu_email_log ORDER BY sent_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def count_unanalyzed_posts(url_token: str = None) -> int:
    """统计尚未分析过的 post 数（用于邮件通知节流判断）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        if url_token:
            cur.execute(
                """SELECT COUNT(*) AS c FROM zhihu_posts p
                   LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
                   WHERE p.url_token=? AND a.id IS NULL""",
                (url_token,),
            )
        else:
            cur.execute(
                """SELECT COUNT(*) AS c FROM zhihu_posts p
                   LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
                   WHERE a.id IS NULL"""
            )
        row = cur.fetchone()
        return row["c"] if row else 0


# ── 全市场舆情观测台（v4, 2026-06-06）──
# 5 张新表的 upsert + 6 个 read 函数
# DDL 走 db_compat.upsert_sql()，未来切 MySQL 时只改 db_compat 一个文件


def upsert_universe_indices(rows: list[dict]) -> int:
    """写入 sentiment_universe_indices。rows: [{code, name, akshare_symbol,
    akshare_method, akshare_filter, enabled, priority, description}]"""
    if not rows:
        return 0
    cols = ["code", "name", "akshare_symbol", "akshare_method", "akshare_filter",
            "enabled", "priority", "description"]
    sql = upsert_sql("sentiment_universe_indices", cols, conflict_cols=["code"])
    values = [tuple(r.get(c) for c in cols) for r in rows]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(sql, values)
        return cur.rowcount


def upsert_universe_constituents(index_code: str, date_str: str,
                                  constituents: list[dict]) -> int:
    """写入 sentiment_universe_constituents。constituents: [{stock_code, stock_name, weight}]"""
    if not constituents:
        return 0
    cols = ["index_code", "stock_code", "stock_name", "weight", "snapshot_date"]
    sql = upsert_sql("sentiment_universe_constituents", cols,
                     conflict_cols=["index_code", "stock_code", "snapshot_date"])
    values = [(index_code, c["stock_code"], c.get("stock_name", ""),
               c.get("weight"), date_str) for c in constituents]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(sql, values)
        return cur.rowcount


def upsert_universe_job(index_code: str, scheduled_date: str,
                        **fields) -> None:
    """更新/插入 sentiment_universe_jobs 单行。fields 可包含 total_stocks /
    completed_stocks / failed_stocks / skipped_stocks / status / started_at /
    completed_at / error_message。

    实现：先读已存在行的所有字段，再 merge fields，最后 UPSERT。
    简化：每次都全字段写（覆盖），fields 缺省则不更新（用 SELECT 拿当前值）。
    """
    cols = ["index_code", "scheduled_date", "total_stocks", "completed_stocks",
            "failed_stocks", "skipped_stocks", "status", "started_at",
            "completed_at", "error_message"]

    with get_connection() as conn:
        cur = conn.cursor()
        # 读已存在
        cur.execute(
            """SELECT total_stocks, completed_stocks, failed_stocks, skipped_stocks,
                      status, started_at, completed_at, error_message
               FROM sentiment_universe_jobs
               WHERE index_code=? AND scheduled_date=?""",
            (index_code, scheduled_date),
        )
        row = cur.fetchone()
        if row is None:
            merged = {c: 0 for c in cols if c not in ("index_code", "scheduled_date")}
            merged["status"] = "pending"
        else:
            merged = dict(row)
        merged.update(fields)
        merged["index_code"] = index_code
        merged["scheduled_date"] = scheduled_date

        values = tuple(merged.get(c) for c in cols)
        sql = upsert_sql("sentiment_universe_jobs", cols,
                         conflict_cols=["index_code", "scheduled_date"])
        cur.execute(sql, values)


def upsert_universe_scores(rows: list[dict]) -> int:
    """写入 sentiment_universe_scores。rows: [{index_code, stock_code,
    forum_type, date, score, sentiment, bullish_n, bearish_n, neutral_n, noise_n,
    panic_signal, euphoria_signal, momentum_cross, ema3, ema5, source}]"""
    if not rows:
        return 0
    cols = ["index_code", "stock_code", "forum_type", "date", "score",
            "sentiment", "bullish_n", "bearish_n", "neutral_n", "noise_n",
            "panic_signal", "euphoria_signal", "momentum_cross", "ema3", "ema5",
            "source"]
    sql = upsert_sql("sentiment_universe_scores", cols,
                     conflict_cols=["index_code", "stock_code", "date"])
    values = [tuple(r.get(c) for c in cols) for r in rows]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(sql, values)
        return cur.rowcount


def upsert_universe_aggregates(index_code: str, date_str: str, agg: dict) -> None:
    """写入 sentiment_universe_aggregates 单行。agg 包含聚合字段。"""
    cols = ["index_code", "date", "total_stocks", "analyzed_stocks",
            "failed_stocks", "avg_score", "median_score", "std_score",
            "bullish_count", "neutral_count", "bearish_count",
            "panic_count", "euphoria_count", "momentum_cross_count",
            "avg_ema3", "avg_ema5", "distribution_json"]
    values = (
        index_code, date_str,
        agg.get("total_stocks", 0), agg.get("analyzed_stocks", 0),
        agg.get("failed_stocks", 0),
        agg.get("avg_score"), agg.get("median_score"), agg.get("std_score"),
        agg.get("bullish_count", 0), agg.get("neutral_count", 0),
        agg.get("bearish_count", 0),
        agg.get("panic_count", 0), agg.get("euphoria_count", 0),
        agg.get("momentum_cross_count", 0),
        agg.get("avg_ema3"), agg.get("avg_ema5"),
        agg.get("distribution_json"),
    )
    sql = upsert_sql("sentiment_universe_aggregates", cols,
                     conflict_cols=["index_code", "date"])
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)


def get_universe_indices(enabled_only: bool = True) -> list[dict]:
    """列出 sentiment_universe_indices 中所有（或仅 enabled）指数。"""
    sql = "SELECT * FROM sentiment_universe_indices"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY priority ASC, id ASC"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def get_universe_constituents_for_date(date_str: str) -> dict[str, list[dict]]:
    """取某日各指数的成分股映射：{index_code: [{stock_code, stock_name, weight}]}

    回退逻辑：若 date_str 当日无 snapshot，用 MAX(snapshot_date) <= date_str 的最近一天。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        # 找最近 snapshot_date
        cur.execute(
            """SELECT MAX(snapshot_date) AS d
               FROM sentiment_universe_constituents
               WHERE snapshot_date <= ?""",
            (date_str,),
        )
        row = cur.fetchone()
        snap = row["d"] if row and row["d"] else date_str
        cur.execute(
            """SELECT index_code, stock_code, stock_name, weight
               FROM sentiment_universe_constituents
               WHERE snapshot_date=?
               ORDER BY index_code, stock_code""",
            (snap,),
        )
        result: dict[str, list[dict]] = {}
        for r in cur.fetchall():
            result.setdefault(r["index_code"], []).append({
                "stock_code": r["stock_code"],
                "stock_name": r["stock_name"] or "",
                "weight": r["weight"],
            })
        return result


def get_universe_jobs(date_str: str | None = None) -> list[dict]:
    """取某日（或默认今天）所有 universe 任务进度。"""
    if date_str is None:
        from datetime import date
        date_str = date.today().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM sentiment_universe_jobs
               WHERE scheduled_date=?
               ORDER BY created_at""",
            (date_str,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_universe_summary(date_str: str) -> list[dict]:
    """取某日 6 指数的聚合汇总 + vs_yesterday_score。

    对每个 enabled 指数：LEFT JOIN sentiment_universe_aggregates（如无数据行仍返回，
    avg_score 留空）。vs_yesterday_score = 今日 avg_score - 昨日 avg_score。
    """
    from datetime import date as date_cls, timedelta
    with get_connection() as conn:
        cur = conn.cursor()
        # 算昨日
        try:
            yesterday = (date_cls.fromisoformat(date_str) - timedelta(days=1)).isoformat()
        except Exception:
            yesterday = date_str

        # 主表：6 指数 LEFT JOIN 当日 + 昨日
        cur.execute(
            """SELECT i.code, i.name, i.priority, i.enabled,
                      t.total_stocks, t.analyzed_stocks, t.failed_stocks,
                      t.avg_score, t.median_score, t.std_score,
                      t.bullish_count, t.neutral_count, t.bearish_count,
                      t.panic_count, t.euphoria_count, t.momentum_cross_count,
                      t.avg_ema3, t.avg_ema5,
                      y.avg_score AS yesterday_score
               FROM sentiment_universe_indices i
               LEFT JOIN sentiment_universe_aggregates t
                 ON t.index_code=i.code AND t.date=?
               LEFT JOIN sentiment_universe_aggregates y
                 ON y.index_code=i.code AND y.date=?
               WHERE i.enabled=1
               ORDER BY i.priority ASC, i.id ASC""",
            (date_str, yesterday),
        )
        out = []
        for r in cur.fetchall():
            d = dict(r)
            today_s = d.get("avg_score")
            yest_s = d.get("yesterday_score")
            if today_s is not None and yest_s is not None:
                d["vs_yesterday_score"] = round(today_s - yest_s, 2)
            else:
                d["vs_yesterday_score"] = None
            out.append(d)
        return out


def get_universe_index_history(index_code: str, days: int = 60) -> list[dict]:
    """取某指数最近 N 天的聚合时序。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT * FROM sentiment_universe_aggregates
               WHERE index_code=?
               AND date >= date('now', ?)
               ORDER BY date""",
            (index_code, f"-{int(days)} days"),
        )
        return [dict(r) for r in cur.fetchall()]


def get_universe_constituent_scores(index_code: str, date_str: str,
                                    limit: int = 500, offset: int = 0) -> list[dict]:
    """取某指数某日成分股的情绪快照（带分页）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT stock_code, score, sentiment, bullish_n, bearish_n,
                      neutral_n, noise_n, panic_signal, euphoria_signal,
                      momentum_cross, ema3, ema5
               FROM sentiment_universe_scores
               WHERE index_code=? AND date=?
               ORDER BY stock_code
               LIMIT ? OFFSET ?""",
            (index_code, date_str, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]


# ── 任务调度配置（v5, 2026-06-06）──

def get_all_scheduler_configs() -> list[dict]:
    """列出所有 scheduler_task_config 行，按 display_name 排序。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        cur.execute(
            "SELECT * FROM scheduler_task_config ORDER BY trigger_type DESC, display_name"
        )
        return [dict(r) for r in cur.fetchall()]


def get_scheduler_config(job_id: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        cur.execute("SELECT * FROM scheduler_task_config WHERE job_id=?", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def seed_scheduler_config_if_absent(row: dict) -> bool:
    """INSERT OR IGNORE；返回 True 表示新增了一行。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cols = ["job_id", "display_name", "description", "trigger_type",
                "hour", "minute", "day_of_week", "interval_hours", "enabled"]
        placeholders = ",".join(["?"] * len(cols))
        values = [row.get(c) for c in cols]
        cur.execute(
            f"INSERT OR IGNORE INTO scheduler_task_config ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            values,
        )
        return cur.rowcount > 0


def update_scheduler_config(job_id: str, updated_by: str | None = None,
                             **fields) -> int:
    """更新 scheduler_task_config 行的可调字段（白名单过滤）。"""
    allowed = {"hour", "minute", "day_of_week", "interval_hours", "enabled"}
    set_parts = []
    values = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            set_parts.append(f"{k}=?")
            values.append(v)
    if not set_parts:
        return 0
    set_parts.append("updated_at=CURRENT_TIMESTAMP")
    if updated_by is not None:
        set_parts.append("updated_by=?")
        values.append(updated_by)
    values.append(job_id)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE scheduler_task_config SET {','.join(set_parts)} WHERE job_id=?",
            values,
        )
        return cur.rowcount


def update_scheduler_next_run(job_id: str, next_run_iso: str | None) -> None:
    """把 scheduler 算出的 next_run_time 同步回 DB（仅作展示用）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE scheduler_task_config SET next_run_time=? WHERE job_id=?",
            (next_run_iso, job_id),
        )


# ── scheduler_task_run（v5, 2026-06-07）：任务运行历史 ──

def record_run_start(job_id: str, started_iso: str) -> int:
    """插入一条 status='running' 的运行记录，返回新行 id。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scheduler_task_run (job_id, started_at, status) VALUES (?, ?, 'running')",
            (job_id, started_iso),
        )
        return cur.lastrowid


def record_run_finish(
    run_id: int, finished_iso: str, status: str, message: str | None,
) -> int:
    """更新运行记录的 finished_at / status / message / duration_ms。

    status ∈ {'success', 'failed', 'skipped'}。duration_ms 自动算。
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE scheduler_task_run "
            "SET finished_at=?, status=?, message=?, "
            "    duration_ms=(CAST((julianday(?) - julianday(started_at)) AS REAL) * 86400000) "
            "WHERE id=?",
            (finished_iso, status, message, finished_iso, run_id),
        )
        return cur.rowcount


def get_recent_runs(job_id: str, limit: int = 20) -> list[dict]:
    """返回 job_id 最近 limit 条运行记录（按 started_at DESC）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, job_id, started_at, finished_at, status, message, duration_ms "
            "FROM scheduler_task_run WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
            (job_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_latest_run(job_id: str) -> dict | None:
    """返回 job_id 最近一条运行记录（无论 status）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, job_id, started_at, finished_at, status, message, duration_ms "
            "FROM scheduler_task_run WHERE job_id=? ORDER BY started_at DESC LIMIT 1",
            (job_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────
# 财报解析 — 财务数据缓存 + 解析历史
# ─────────────────────────────────────────────────────────────────

def upsert_financials_cache(symbol: str, report_date: str | None,
                            ttm_revenue: float | None, ttm_net_profit: float | None,
                            ttm_gross_profit: float | None, ttm_eps: float | None,
                            quarterly_data: str, price: float | None,
                            total_market_cap: float | None, float_market_cap: float | None,
                            total_shares: float | None, float_shares: float | None,
                            ttm_pe: float | None, pe_history: str,
                            price_history: str,
                            ttm_pe_percentile: float | None = None,
                            ttm_pe_percentile_basis: str | None = None) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO financial_reports_cache
               (symbol, report_date, ttm_revenue, ttm_net_profit, ttm_gross_profit,
                ttm_eps, quarterly_data, price,
                total_market_cap, float_market_cap, total_shares, float_shares,
                ttm_pe, pe_history, price_history,
                ttm_pe_percentile, ttm_pe_percentile_basis,
                fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, CURRENT_TIMESTAMP)""",
            (symbol, report_date, ttm_revenue, ttm_net_profit, ttm_gross_profit,
             ttm_eps, quarterly_data, price,
             total_market_cap, float_market_cap, total_shares, float_shares,
             ttm_pe, pe_history, price_history,
             ttm_pe_percentile, ttm_pe_percentile_basis),
        )


def get_financials_cache(symbol: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM financial_reports_cache WHERE symbol=?",
            (symbol,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def insert_report_parse(report_text_hash: str, report_text_preview: str,
                        parsed_result: str, model_name: str,
                        company_count: int) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO report_parse_history
               (report_text_hash, report_text_preview, parsed_result,
                model_name, company_count)
               VALUES (?, ?, ?, ?, ?)""",
            (report_text_hash, report_text_preview, parsed_result,
             model_name, company_count),
        )
        return cur.lastrowid


def get_recent_report_parses(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, report_text_hash, report_text_preview,
                      company_count, model_name, created_at
               FROM report_parse_history
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
