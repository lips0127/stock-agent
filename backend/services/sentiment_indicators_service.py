"""
时序因子服务（v3, 2026-06-06）。

职责：
- 拉取某只股票近 N 日 sentiment_scores
- 计算 EMA3/5、panic/euphoria 2σ 信号
- 写入 sentiment_indicators 表
- 提供「今日极端情绪」查询接口（供前端看板 + 策略层消费）

注：单只股票的指标计算已内联在 analyze_sentiment 里；
本服务用于：
  1. 全市场回填（一次性给所有监控股算今日 indicators）
  2. 历史回补（手动给某只股票重算最近 N 天）
  3. 跨股票查询（今日哪些股触发 panic / euphoria）
"""

import logging
from datetime import date as date_cls, datetime
from backend.core.database import (
    get_connection,
    get_sentiment_configs,
    get_indicators,
    upsert_indicators,
)
from backend.services.sentiment_service import (
    _load_history_for_indicators,
    _compute_indicators,
    _aggregate_labels,
)

logger = logging.getLogger(__name__)


def compute_indicators_for_stock(code: str, forum_type: str = "eastmoney",
                                 days: int = 30) -> int:
    """为某只股票重新计算今日 indicators。

    通常在 analyze_sentiment 之后调用，幂等（upsert）。

    Returns:
        写入条数（0 或 1）
    """
    today = date_cls.today().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT score, bullish_n, bearish_n, neutral_n, noise_n
               FROM sentiment_scores
               WHERE stock_code=? AND forum_type=? AND date=?""",
            (code, forum_type, today),
        )
        row = cur.fetchone()
    if not row:
        logger.debug(f"无今日 score，跳过 indicators: {code}")
        return 0

    # 还原 agg 格式
    agg = {
        "score": row["score"],
        "bullish": row["bullish_n"],
        "bearish": row["bearish_n"],
        "neutral": row["neutral_n"],
        "noise": row["noise_n"],
        "sentiment": "",  # 不需要
    }

    # 加载历史（不含今日）
    history = _load_history_for_indicators(code, forum_type, days)
    # 过滤掉今日
    history["scores"] = [s for s, d in zip(history["scores"], _dates(code, forum_type, days))
                         if d != today]
    # 简化：直接复用 _compute_indicators（它会把今日 append 上去）
    indicators = _compute_indicators(
        code, agg,
        history_scores=history["scores"],
        history_bullish=history["bullish_n"],
        history_bearish=history["bearish_n"],
    )

    ok = upsert_indicators(
        code, today, agg["score"],
        indicators["ema3"], indicators["ema5"],
        indicators["bullish_ma30"], indicators["bullish_std30"],
        indicators["bearish_ma30"], indicators["bearish_std30"],
        indicators["panic_signal"], indicators["euphoria_signal"],
        indicators["momentum_cross"],
    )
    return 1 if ok else 0


def _dates(code: str, forum_type: str, days: int) -> list[str]:
    """辅助：返回某只股票近 N 日的 date 列表（与 _load_history_for_indicators 顺序一致）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date FROM sentiment_scores
               WHERE stock_code=? AND forum_type=?
               AND date >= date('now', ?)
               ORDER BY date ASC""",
            (code, forum_type, f"-{days} day"),
        )
        return [r["date"] for r in cur.fetchall()]


def recompute_all_for_today(forum_type: str = "eastmoney") -> dict:
    """对所有启用的监控股票，重新算今日 indicators。

    用途：scheduler 在 16:30 跑完舆情批量后调用一次，
    避免某些股票当天 analyze_sentiment 因熔断没跑成功、但 DB 有昨日缓存时漏算。

    Returns:
        {"total": N, "ok": M, "skip": K}
    """
    configs = get_sentiment_configs()
    if not configs:
        return {"total": 0, "ok": 0, "skip": 0}
    ok, skip = 0, 0
    for cfg in configs:
        try:
            n = compute_indicators_for_stock(
                cfg["stock_code"], cfg["forum_type"]
            )
            if n > 0:
                ok += 1
            else:
                skip += 1
        except Exception as e:
            logger.error(f"compute_indicators 失败 ({cfg['stock_code']}): {e}",
                         exc_info=True)
            skip += 1
    logger.info(f"indicators 全市场重算: total={len(configs)} ok={ok} skip={skip}")
    return {"total": len(configs), "ok": ok, "skip": skip}


def get_extreme_signals(target_date: str | None = None) -> list[dict]:
    """获取某日（默认今天）所有触发 panic / euphoria / 动量交叉的股票。

    返回每条记录含 stock_code / score / signals / stock_name（LEFT JOIN config）。
    """
    from backend.core.database import get_latest_signals
    return get_latest_signals(target_date)


def get_stock_indicator_series(code: str, days: int = 30) -> list[dict]:
    """获取某只股票近 N 日 indicators 序列（前端绘图用）。"""
    return get_indicators(code, days)
