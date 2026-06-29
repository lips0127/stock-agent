
import concurrent.futures
import time
import akshare as ak
from backend.services.stock_service import get_stock_metrics, _no_proxy, get_sina_index_spot, is_risk_stock
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


def process_single_stock(code, task_runner=None):
    """处理单只股票，将 get_stock_metrics 的中文 key 转换为英文 key 写入 DB。

    返回 None 即视为"该股处理失败/数据无效"，不抛异常（避免中断整批扫描）。
    失败原因会通过 task_runner.warn() 写入任务日志，让前端可见。
    """
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
        # 静默吞错的根因点：metrics=None 或 最新价=0 时显式打 warn（v2 2026-06-11）
        if metrics is None:
            reason = "数据源全部失败"
        else:
            reason = f"最新价无效 ({metrics.get('最新价')})"
        if task_runner is not None:
            task_runner.warn(f"股票 {code} 处理失败: {reason}")
        else:
            logger.warning(f"股票 {code} 处理失败: {reason}")
        return None
    except Exception as e:
        if task_runner is not None:
            task_runner.warn(f"股票 {code} 异常: {e}")
        else:
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
        # 新浪源 code 列带前缀（bj920000 / sh600000 / sz000001），剥成纯 6 位
        raw = df['代码'].astype(str)
        codes_series = raw.str[2:].where(raw.str[:2].isin(['sh', 'sz', 'bj']), raw).str.zfill(6)
        # 按名称剔除 ST/*ST/退市股（股息率异常 + 退市风险），见 is_risk_stock
        if '名称' in df.columns:
            keep = ~df['名称'].astype(str).map(is_risk_stock)
            excluded = int((~keep).sum())
            codes = codes_series[keep].tolist()
            logger.info(f"通过 stock_zh_a_spot 获取 A 股代码 {len(codes)} 只（已剔除 {excluded} 只 ST/退市）")
        else:
            codes = codes_series.tolist()
            logger.info(f"通过 stock_zh_a_spot 获取 A 股代码总数: {len(codes)}（无名称列，未剔除 ST/退市）")
        return codes
    except Exception as e:
        logger.warning(f"stock_zh_a_spot 失败: {e}", exc_info=True)

    try:
        with _no_proxy():
            df = ak.stock_info_a_code_name()
        name_col = next((c for c in ('名称', 'A股简称') if c in df.columns), None)
        codes_series = df['A股代码'].astype(str).str.zfill(6)
        if name_col:
            keep = ~df[name_col].astype(str).map(is_risk_stock)
            excluded = int((~keep).sum())
            codes = codes_series[keep].tolist()
            logger.info(f"通过 stock_info_a_code_name 获取 A 股代码 {len(codes)} 只（已剔除 {excluded} 只 ST/退市）")
        else:
            codes = codes_series.tolist()
            logger.info(f"通过 stock_info_a_code_name 获取 A 股代码总数: {len(codes)}（无名称列，未剔除 ST/退市）")
        return codes
    except Exception as e:
        logger.warning(f"stock_info_a_code_name 失败: {e}", exc_info=True)

    logger.error("获取 A 股代码列表失败（所有数据源均失败）")
    return []


def scan_dividend_index(max_workers=None, task_id=None, task_runner=None):
    """扫描中证红利指数成分股（约100只），同时更新大盘指数。

    进度同时写入旧 scan_tasks 表（task_id 给出时）和新 task_runs 表（task_runner 给出时）。
    失败统计：fail_count 累加，扫描完成时随 result_json 写入 task_runs（前端可读）。
    """
    from backend.core.database import update_scan_task

    logger.info("开始红利指数扫描...")

    codes = get_dividend_index_constituents()
    if not codes:
        logger.error("无法获取红利指数成分股，扫描终止")
        if task_id:
            update_scan_task(task_id, status='failed', error_message="无法获取红利指数成分股")
        if task_runner:
            task_runner.fail("无法获取红利指数成分股")
        return

    total = len(codes)
    if task_id:
        update_scan_task(task_id, total=total, done=0)
    if task_runner:
        task_runner.set_total(total)
        task_runner.milestone(f"开始扫描 {total} 只红利指数成分股")

    workers = max_workers or SCAN_MAX_WORKERS
    done = 0
    fail_count = 0
    stock_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_stock, code, task_runner): code for code in codes}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            done += 1
            try:
                result = future.result()
                if result:
                    stock_data.append(result)
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                if task_runner:
                    task_runner.warn(f"股票 {code} 异常: {e}")
                else:
                    logger.error(f"处理股票 {code} 失败: {e}", exc_info=True)

            if task_id and done % max(10, total // 20) == 0:
                update_scan_task(task_id, done=done)
            if task_runner:
                task_runner.progress(done)
                task_runner.set_current(f"扫描 {code} (成功 {len(stock_data)} 失败 {fail_count})")

    indices_data = get_all_indices()
    today = date.today().isoformat()
    success_count = len(stock_data)
    result_payload = {
        "stocks": success_count, "indices": len(indices_data),
        "total": total, "fail_count": fail_count,
    }
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

        # 完成日志：成功/失败 0 区分级别（v2 2026-06-11）
        log_msg = (f"红利指数扫描完成: {success_count}/{total} 只成功, "
                   f"{fail_count} 只失败, {len(indices_data)} 条指数")
        if success_count == 0 and total > 0:
            logger.error(log_msg)
            if task_runner:
                task_runner.error(f"扫描全部失败 (0/{total}): 检查数据源连通性")
        else:
            logger.info(log_msg)
        if task_id:
            update_scan_task(task_id, status='success', done=total, result_count=success_count)
        if task_runner:
            task_runner.complete(result=result_payload)
    except Exception as e:
        logger.error(f"保存红利指数扫描结果失败: {e}", exc_info=True)
        if task_id:
            update_scan_task(task_id, status='failed', error_message=str(e))
        if task_runner:
            task_runner.fail(str(e))
        raise


def scan_all_a_shares(max_workers=None, task_id=None, task_runner=None):
    """全市场扫描（全部 A 股约5800+只），逐批写入DB以支持实时进度查询。

    进度同时写入旧 scan_tasks 表（task_id 给出时）和新 task_runs 表（task_runner 给出时）。
    失败统计：fail_count 累加，扫描完成时随 result_json 写入 task_runs（前端可读）。
    """
    from backend.core.database import update_scan_task

    logger.info("开始全市场扫描（全部 A 股）...")

    codes = get_all_a_share_codes()
    if not codes:
        logger.error("无法获取 A 股代码列表，扫描终止")
        if task_id:
            update_scan_task(task_id, status='failed', error_message="无法获取 A 股代码列表")
        if task_runner:
            task_runner.fail("无法获取 A 股代码列表")
        raise ValueError("无法获取 A 股代码列表")

    total = len(codes)
    if task_id:
        update_scan_task(task_id, total=total, done=0)
    if task_runner:
        task_runner.set_total(total)
        task_runner.milestone(f"开始扫描 {total} 只 A 股")

    workers = max_workers or SCAN_MAX_WORKERS
    done = 0
    result_count = 0
    fail_count = 0
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
        futures = {executor.submit(process_single_stock, code, task_runner): code for code in codes}
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
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                if task_runner:
                    task_runner.warn(f"股票 {code} 异常: {e}")
                else:
                    logger.error(f"处理股票 {code} 失败: {e}", exc_info=True)

            if task_id and done % max(10, total // 20) == 0:
                update_scan_task(task_id, done=done, result_count=result_count)
            if task_runner:
                task_runner.progress(done)
                task_runner.set_current(
                    f"扫描 {code} (成功 {result_count} 失败 {fail_count})")

    _flush_batch(batch)

    indices_data = get_all_indices()
    result_payload = {
        "stocks": result_count, "indices": len(indices_data),
        "total": total, "fail_count": fail_count,
    }
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

        # 完成日志：成功/失败 0 区分级别（v2 2026-06-11）
        log_msg = (f"全市场扫描完成: {result_count}/{total} 只成功, "
                   f"{fail_count} 只失败, {len(indices_data)} 条指数")
        if result_count == 0 and total > 0:
            logger.error(log_msg)
            if task_runner:
                task_runner.error(f"扫描全部失败 (0/{total}): 检查数据源连通性")
        elif fail_count > total // 2:
            logger.warning(log_msg)
            if task_runner:
                task_runner.warn(f"扫描失败率过高 ({fail_count}/{total}): 数据源可能不稳定")
        else:
            logger.info(log_msg)
        if task_id:
            update_scan_task(task_id, status='success', done=total, result_count=result_count)
        if task_runner:
            task_runner.complete(result=result_payload)
    except Exception as e:
        logger.error(f"保存全市场扫描指数数据失败: {e}", exc_info=True)
        if task_id:
            update_scan_task(task_id, status='failed', error_message=str(e))
        if task_runner:
            task_runner.fail(str(e))
        raise


if __name__ == "__main__":
    start_time = time.time()
    scan_dividend_index(max_workers=30)
    logger.info(f"总耗时: {time.time() - start_time:.2f} 秒")
