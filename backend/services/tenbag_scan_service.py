"""十倍股/财报异动扫描编排服务。

编排模块二趋势分析器 + 财报异动信号 + 分层器，对候选池（热门股 top N）
逐只跑完整管线，结果写入 tenbag_trend_signals / tenbag_anomaly_signals /
tenbag_pools。TaskRunner 包裹（进度/milestone/取消）。

候选池默认热门股 top 50（EM 财报接口单只 2-3 分钟，全市场不可行）。
口径：输出是观察池/基本面雷达，不是买卖信号。
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from backend.services.financial_service import _fetch_tencent_kline
from backend.services.tenbag_trend_service import compute_trend_signals
from backend.services.tenbag_anomaly_service import (
    fetch_financials_em, derive_anomaly_signals,
)
from backend.services.tenbag_pool_service import classify_pool
from backend.core.database import (
    get_latest_top_picks, upsert_tenbag_trend, upsert_tenbag_anomaly,
    upsert_tenbag_pool,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 50
KLINE_DAYS = 400  # 约 1.5 年日 K，够月线 MA + 52 周回撤


def run_scan(task_runner=None, top_n: int = DEFAULT_TOP_N,
             snapshot_date: str | None = None) -> dict:
    """扫描编排：候选池 → 逐只 trend+anomaly+pool → 写 DB。

    Args:
        task_runner: 可选 TaskRunner 上下文（已在 with 块内）。用于进度/取消。
        top_n: 候选池规模（热门股 top N）。
        snapshot_date: 分层快照日期（YYYY-MM-DD），默认今天。

    Returns:
        {snapshot_date, scanned, failed, tiers: {1,2,3,exclude}}
    """
    snapshot_date = snapshot_date or date_cls.today().isoformat()
    candidates = get_latest_top_picks(limit=top_n)

    if task_runner:
        task_runner.set_total(len(candidates))
        task_runner.milestone(f"十倍股扫描启动: 候选 {len(candidates)} 只")

    scanned = 0
    failed = 0
    tier_counts = {"1": 0, "2": 0, "3": 0, "exclude": 0}

    for i, c in enumerate(candidates):
        if task_runner:
            task_runner.check_cancelled()
        code = c.get("stock_code")
        if not code:
            continue
        name = c.get("stock_name")
        try:
            tier = _scan_single(code, name, snapshot_date)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            scanned += 1
        except Exception as e:
            failed += 1
            logger.warning(f"扫描失败 {code}: {e}")
            if task_runner:
                task_runner.warn(f"{code} 扫描失败: {e}")
        if task_runner:
            task_runner.progress(i + 1)

    result = {
        "snapshot_date": snapshot_date,
        "scanned": scanned,
        "failed": failed,
        "tiers": tier_counts,
    }
    if task_runner:
        task_runner.complete(result=result)
    logger.info(f"十倍股扫描完成: {result}")
    return result


def _scan_single(symbol: str, name: str | None, snapshot_date: str) -> str:
    """单只股票完整管线：趋势 → 异动 → 分层 → 落库。返回 tier。"""
    symbol = str(symbol).zfill(6)

    # 1) 趋势信号
    bars = _fetch_tencent_kline(symbol, KLINE_DAYS)
    trend = compute_trend_signals(bars)
    upsert_tenbag_trend(symbol, snapshot_date, trend, trend.get("regime"))

    # 2) 财报异动信号
    fin = fetch_financials_em(symbol, periods=4)
    if name and not fin.get("name"):
        fin["name"] = name
    anom = derive_anomaly_signals(fin)
    report_date = _latest_report_date(fin.get("periods") or [])
    upsert_tenbag_anomaly(
        symbol, report_date, anom["signals"], anom["score"],
        anom["core_changes"], anom["risks"],
    )

    # 3) 分层
    pool = classify_pool(trend, anom)
    upsert_tenbag_pool(snapshot_date, symbol, pool["tier"], pool["reasons"])
    return pool["tier"]


def _latest_report_date(periods: list[dict]) -> str | None:
    """取最近一期报告日期（兼容升降序输入）。"""
    dates = [p.get("report_date") for p in periods if p.get("report_date")]
    if not dates:
        return None
    return max(dates, key=str)
