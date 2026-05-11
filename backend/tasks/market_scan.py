
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
    """处理单只股票，将 get_stock_metrics 的中文 key 转换为英文 key 写入 DB。"""
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
                "dividend_yield": metrics['股息率'],
                "dividend_per_share": metrics['每股分红'],
            }
        return None
    except Exception as e:
        logger.warning(f"处理股票 {code} 失败: {e}", exc_info=True)
        return None


def get_all_indices():
    """获取全部大盘指数实时行情。"""
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
            logger.warning(f"获取指数 {symbol} 失败: {e}", exc_info=True)
    return results


def get_all_a_share_codes() -> list:
    """获取全部 A 股股票代码（按兼容性排序尝试多个数据源）。"""
    try:
        with _no_proxy():
            df = ak.stock_zh_a_spot()
        codes = df['代码'].astype(str).str.zfill(6).tolist()
        logger.info(f"通过 stock_zh_a_spot 获取 A 股代码总数: {len(codes)}")
        return codes
    except Exception as e:
        logger.warning(f"stock_zh_a_spot 失败: {e}", exc_info=True)

    try:
        with _no_proxy():
            df = ak.stock_info_a_code_name()
        codes = df['A股代码'].astype(str).str.zfill(6).tolist()
        logger.info(f"通过 stock_info_a_code_name 获取 A 股代码总数: {len(codes)}")
        return codes
    except Exception as e:
        logger.warning(f"stock_info_a_code_name 失败: {e}", exc_info=True)

    try:
        with _no_proxy():
            df = ak.stock_zh_a_spot_em()
        codes = df['代码'].astype(str).str.zfill(6).tolist()
        logger.info(f"通过 stock_zh_a_spot_em 获取 A 股代码总数: {len(codes)}")
        return codes
    except Exception as e:
        logger.error(f"获取 A 股代码列表失败（所有数据源均失败）: {e}", exc_info=True)
        return []


def scan_dividend_index(max_workers=None, task_id=None):
    """扫描中证红利指数成分股（约100只），同时更新大盘指数。"""
    from backend.core.database import update_scan_task

    logger.info("开始红利指数扫描...")

    codes = get_dividend_index_constituents()
    if not codes:
        logger.error("无法获取红利指数成分股，扫描终止")
        if task_id:
            update_scan_task(task_id, status='failed', error_message="无法获取红利指数成分股")
        return

    total = len(codes)
    if task_id:
        update_scan_task(task_id, total=total, done=0)

    workers = max_workers or SCAN_MAX_WORKERS
    done = 0
    stock_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_stock, code): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            done += 1
            try:
                result = future.result()
                if result:
                    stock_data.append(result)
            except Exception as e:
                logger.error(f"处理股票 {code} 失败: {e}", exc_info=True)

            if task_id and done % max(10, total // 20) == 0:
                update_scan_task(task_id, done=done)

    indices_data = get_all_indices()
    today = date.today().isoformat()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if stock_data:
                cur.executemany(
                    """INSERT INTO stock_daily_metrics
                       (date, code, name, price, dividend_yield, dividend_per_share, scan_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(date, code) DO UPDATE SET
                           name=excluded.name,
                           price=excluded.price,
                           dividend_yield=excluded.dividend_yield,
                           dividend_per_share=excluded.dividend_per_share,
                           scan_type=excluded.scan_type""",
                    [(today, s['code'], s['name'], s['price'], s['dividend_yield'],
                      s.get('dividend_per_share', 0), 'index')
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

        logger.info(f"红利指数扫描完成: {len(stock_data)} 只股票, {len(indices_data)} 条指数")
        if task_id:
            update_scan_task(task_id, status='success', done=total, result_count=len(stock_data))
    except Exception as e:
        logger.error(f"保存红利指数扫描结果失败: {e}", exc_info=True)
        if task_id:
            update_scan_task(task_id, status='failed', error_message=str(e))
        raise


def scan_all_a_shares(max_workers=None, task_id=None):
    """全市场扫描（全部 A 股约5800+只），逐批写入DB以支持实时进度查询。"""
    from backend.core.database import update_scan_task

    logger.info("开始全市场扫描（全部 A 股）...")

    codes = get_all_a_share_codes()
    if not codes:
        logger.error("无法获取 A 股代码列表，扫描终止")
        if task_id:
            update_scan_task(task_id, status='failed', error_message="无法获取 A 股代码列表")
        raise ValueError("无法获取 A 股代码列表")

    total = len(codes)
    if task_id:
        update_scan_task(task_id, total=total, done=0)

    workers = max_workers or SCAN_MAX_WORKERS
    done = 0
    result_count = 0
    batch = []
    batch_size = 20
    _insert_sql = """INSERT INTO stock_daily_metrics
                       (date, code, name, price, dividend_yield, dividend_per_share, scan_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(date, code) DO UPDATE SET
                           name=excluded.name,
                           price=excluded.price,
                           dividend_yield=excluded.dividend_yield,
                           dividend_per_share=excluded.dividend_per_share,
                           scan_type=excluded.scan_type"""
    today = date.today().isoformat()

    def _flush_batch(rows):
        if not rows:
            return
        with get_connection() as conn:
            conn.cursor().executemany(_insert_sql, rows)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_stock, code): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            done += 1
            try:
                result = future.result()
                if result:
                    result_count += 1
                    batch.append((
                        today, result['code'], result['name'],
                        result['price'], result['dividend_yield'],
                        result.get('dividend_per_share', 0), 'full'
                    ))
                    if len(batch) >= batch_size:
                        _flush_batch(batch)
                        batch = []
            except Exception as e:
                logger.error(f"处理股票 {code} 失败: {e}", exc_info=True)

            if task_id and done % max(10, total // 20) == 0:
                update_scan_task(task_id, done=done, result_count=result_count)

    _flush_batch(batch)

    indices_data = get_all_indices()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
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

        logger.info(f"全市场扫描完成: {result_count} 只股票, {len(indices_data)} 条指数")
        if task_id:
            update_scan_task(task_id, status='success', done=total, result_count=result_count)
    except Exception as e:
        logger.error(f"保存全市场扫描指数数据失败: {e}", exc_info=True)
        if task_id:
            update_scan_task(task_id, status='failed', error_message=str(e))
        raise


if __name__ == "__main__":
    start_time = time.time()
    scan_dividend_index(max_workers=30)
    logger.info(f"总耗时: {time.time() - start_time:.2f} 秒")
