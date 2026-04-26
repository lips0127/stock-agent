
import concurrent.futures
import time
import akshare as ak
from backend.services.stock_service import get_stock_metrics, _no_proxy, get_sina_index_spot
from backend.services.scanner_service import get_dividend_index_constituents
from backend.core.database import get_connection
from backend.config import SCAN_MAX_WORKERS
import pandas as pd
from datetime import date
import random
import logging

logger = logging.getLogger(__name__)

INDEX_SYMBOLS = {
    "s_sh000001": "上证指数",
    "s_sz399001": "深证成指",
    "s_sz399006": "创业板指",
    "s_sh000688": "科创50",
    "s_sh000012": "国债指数",
}


def process_single_stock(code):
    """Process a single stock code, translating to English keys for DB."""
    try:
        if not code:
            return None
        time.sleep(random.uniform(0.05, 0.2))
        metrics = get_stock_metrics(code)
        if metrics and metrics.get('最新价', 0) > 0:
            return {
                "code": code,
                "name": metrics['名称'],
                "price": metrics['最新价'],
                "dividend_yield": metrics['股息率']
            }
        return None
    except Exception:
        return None


def get_all_indices():
    """Fetch all major A-share index spot data."""
    results = []
    for symbol, expected_name in INDEX_SYMBOLS.items():
        try:
            data = get_sina_index_spot(symbol)
            if data:
                results.append({
                    "symbol": symbol.replace("s_", ""),
                    "name": data["name"],
                    "value": data["current"],
                    "change_amount": data["change_amount"],
                    "change_pct": data["change_pct"],
                })
        except Exception as e:
            logger.warning(f"Failed to fetch index {symbol}: {e}")
    return results


def full_market_scan(max_workers=None):
    """全市场扫描任务。"""
    logger.info("Starting full market scan...")

    codes = get_dividend_index_constituents()

    workers = max_workers or SCAN_MAX_WORKERS
    stock_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_stock, code): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
                if result:
                    stock_data.append(result)
            except Exception as e:
                logger.error(f"Failed to get metrics for {code}: {e}")

    indices_data = get_all_indices()

    today = date.today().isoformat()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if stock_data:
                cur.executemany(
                    """INSERT INTO stock_daily_metrics
                       (date, code, name, price, dividend_yield)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(date, code) DO UPDATE SET
                           name=excluded.name,
                           price=excluded.price,
                           dividend_yield=excluded.dividend_yield""",
                    [(today, s['code'], s['name'], s['price'], s['dividend_yield'])
                     for s in stock_data],
                )

            if indices_data:
                cur.executemany(
                    """INSERT INTO market_indices
                       (date, symbol, name, value, change_amount, change_pct)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(date, symbol) DO UPDATE SET
                           name=excluded.name,
                           value=excluded.value,
                           change_amount=excluded.change_amount,
                           change_pct=excluded.change_pct""",
                    [(today, i['symbol'], i['name'],
                      i['value'], i['change_amount'], i['change_pct'])
                     for i in indices_data],
                )

        logger.info(f"Market scan complete: {len(stock_data)} stocks, {len(indices_data)} indices")
    except Exception as e:
        logger.error(f"Failed to save scan results: {e}")
        raise

if __name__ == "__main__":
    start_time = time.time()
    full_market_scan(max_workers=30)
    logger.info(f"Total time: {time.time() - start_time:.2f} seconds")
