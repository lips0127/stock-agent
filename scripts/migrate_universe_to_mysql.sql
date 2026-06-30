-- ──────────────────────────────────────────────────────────────────
-- 全市场舆情观测台（v4, 2026-06-06）— MySQL 8.0+ DDL
-- ──────────────────────────────────────────────────────────────────
-- 用法：
--   1. 先创建数据库（如果还没有）：
--        CREATE DATABASE stock_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   2. 切到该库：
--        USE stock_agent;
--   3. 导入本文件：
--        mysql -u root -p stock_agent < scripts/migrate_universe_to_mysql.sql
--   4. 导入数据：
--        python scripts/migrate_universe_data.py \
--          --from sqlite:///path/to/stocks.db \
--          --to mysql+pymysql://root:pwd@localhost:3306/stock_agent
--
-- 设计要点：
--   * 主键从 INTEGER AUTOINCREMENT 改为 BIGINT AUTO_INCREMENT（MySQL 习惯）
--   * 字符串 TEXT 改为 VARCHAR(N)；UNIQUE/PK 列保留 NOT NULL
--   * INTEGER 默认值用 INT DEFAULT ...；布尔 0/1 保持不变（不强制 ENUM）
--   * TIMESTAMP DEFAULT CURRENT_TIMESTAMP 直接照搬
--   * 索引 1:1 复制
-- ──────────────────────────────────────────────────────────────────

-- 1. sentiment_universe_indices（指数定义，~10 行）
CREATE TABLE IF NOT EXISTS sentiment_universe_indices (
  id BIGINT NOT NULL AUTO_INCREMENT,
  code VARCHAR(32) NOT NULL,
  name VARCHAR(64) NOT NULL,
  akshare_symbol VARCHAR(32),
  akshare_method VARCHAR(32) NOT NULL DEFAULT 'csindex',
  akshare_filter VARCHAR(32),
  enabled INT NOT NULL DEFAULT 1,
  priority INT NOT NULL DEFAULT 100,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sui_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. sentiment_universe_constituents（每日成分股快照）
CREATE TABLE IF NOT EXISTS sentiment_universe_constituents (
  index_code VARCHAR(32) NOT NULL,
  stock_code VARCHAR(16) NOT NULL,
  stock_name VARCHAR(64),
  weight DOUBLE,
  snapshot_date VARCHAR(10) NOT NULL,
  PRIMARY KEY (index_code, stock_code, snapshot_date),
  KEY idx_unc_code_date (stock_code, snapshot_date),
  KEY idx_unc_index_date (index_code, snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. sentiment_universe_jobs（每日任务进度，6 行/天）
CREATE TABLE IF NOT EXISTS sentiment_universe_jobs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  index_code VARCHAR(32) NOT NULL,
  scheduled_date VARCHAR(10) NOT NULL,
  total_stocks INT NOT NULL DEFAULT 0,
  completed_stocks INT NOT NULL DEFAULT 0,
  failed_stocks INT NOT NULL DEFAULT 0,
  skipped_stocks INT NOT NULL DEFAULT 0,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  started_at TIMESTAMP NULL,
  completed_at TIMESTAMP NULL,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_suj_index_date (index_code, scheduled_date),
  KEY idx_uj_date (scheduled_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. sentiment_universe_scores（每只股票在每个指数下的情绪快照）
CREATE TABLE IF NOT EXISTS sentiment_universe_scores (
  id BIGINT NOT NULL AUTO_INCREMENT,
  index_code VARCHAR(32) NOT NULL,
  stock_code VARCHAR(16) NOT NULL,
  forum_type VARCHAR(32) NOT NULL DEFAULT 'eastmoney',
  date VARCHAR(10) NOT NULL,
  score DOUBLE,
  sentiment VARCHAR(16),
  bullish_n INT DEFAULT 0,
  bearish_n INT DEFAULT 0,
  neutral_n INT DEFAULT 0,
  noise_n INT DEFAULT 0,
  panic_signal INT DEFAULT 0,
  euphoria_signal INT DEFAULT 0,
  momentum_cross INT DEFAULT 0,
  ema3 DOUBLE,
  ema5 DOUBLE,
  source VARCHAR(32) NOT NULL DEFAULT 'universe_crawl',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_uus_index_code_date (index_code, stock_code, date),
  KEY idx_uus_code_date (stock_code, date),
  KEY idx_uus_index_date (index_code, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. sentiment_universe_aggregates（每日指数级聚合，看板主表）
CREATE TABLE IF NOT EXISTS sentiment_universe_aggregates (
  index_code VARCHAR(32) NOT NULL,
  date VARCHAR(10) NOT NULL,
  total_stocks INT NOT NULL,
  analyzed_stocks INT NOT NULL DEFAULT 0,
  failed_stocks INT DEFAULT 0,
  avg_score DOUBLE,
  median_score DOUBLE,
  std_score DOUBLE,
  bullish_count INT DEFAULT 0,
  neutral_count INT DEFAULT 0,
  bearish_count INT DEFAULT 0,
  panic_count INT DEFAULT 0,
  euphoria_count INT DEFAULT 0,
  momentum_cross_count INT DEFAULT 0,
  avg_ema3 DOUBLE,
  avg_ema5 DOUBLE,
  distribution_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (index_code, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ──────────────────────────────────────────────────────────────────
-- 验证：导入后应该有 5 张表 + 8 个索引
--   SHOW TABLES;
--   SELECT * FROM sentiment_universe_indices;  -- 应该看到 6 行
-- ──────────────────────────────────────────────────────────────────
