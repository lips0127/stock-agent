# -*- coding: utf-8 -*-
"""手动刷新：先红利指数成分扫描，再全市场扫描（与 /api/full_refresh 同一函数）。

用于 2026-08-30 股息率口径修复后清洗 stock_daily_metrics 中的污染数据。
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import backend.core.proxy_bypass  # noqa: F401  # 在导入 akshare 相关模块前生效
from backend.tasks.market_scan import scan_dividend_index, scan_all_a_shares

start = time.time()

scan_dividend_index(max_workers=30)
scan_all_a_shares(max_workers=30)

print(f"全部扫描完成，总耗时 {time.time() - start:.0f} 秒")
