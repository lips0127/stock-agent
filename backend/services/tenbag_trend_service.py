"""模块二 股价趋势分析器（纯量化，零额外依赖）。

输入 financial_service._fetch_tencent_kline 返回的日 K 列表
[{date, open, close, high, low, volume}, ...]，输出趋势信号 dict + regime。

口径：仅作趋势确认/观察池输入，不输出买卖信号。
"""

from __future__ import annotations

from collections import defaultdict

# regime 枚举
STAGE2_BREAKOUT = "stage2_breakout"
ADVANCING = "advancing"
CONSOLIDATION = "consolidation"
DOWNTREND = "downtrend"


def compute_trend_signals(daily_bars: list[dict],
                          benchmark_bars: list[dict] | None = None) -> dict:
    """计算趋势信号。

    Args:
        daily_bars: 日 K 列表，按日期升序。
        benchmark_bars: 可选大盘日 K（同结构），用于相对强度 RS。

    Returns:
        {monthly_bars, ma12_monthly, ma24_monthly, drawdown_from_high,
         new_high_ratio, volume_ratio, relative_strength, regime}
        数据不足时 regime=None，各数值字段尽量给 None。
    """
    result = {
        "monthly_bars": [],
        "ma12_monthly": None,
        "ma24_monthly": None,
        "ma60_daily": None,
        "ma120_daily": None,
        "drawdown_from_high": None,
        "new_high_ratio": None,
        "volume_ratio": None,
        "relative_strength": None,
        "regime": None,
    }
    if not daily_bars:
        return result

    closes = [b["close"] for b in daily_bars]
    last_close = closes[-1]

    # 1) 月线重采样：按 YYYY-MM 取每月最后一根的 close，volume 求和
    monthly = _resample_monthly(daily_bars)
    result["monthly_bars"] = monthly

    # 2) 月线 MA12 / MA24（信息项，数据不足为 None）
    month_closes = [m["close"] for m in monthly]
    result["ma12_monthly"] = _sma(month_closes, 12)
    result["ma24_monthly"] = _sma(month_closes, 24)

    # 2b) 日线 MA60 / MA120（regime 主锚点，3~6 个月趋势，短历史也可用）
    result["ma60_daily"] = _sma(closes, 60)
    result["ma120_daily"] = _sma(closes, 120)

    # 3) 距 52 周（约 252 交易日）高点回撤 %
    window = closes[-252:] if len(closes) >= 252 else closes
    high = max(window)
    result["drawdown_from_high"] = round((last_close - high) / high * 100, 2) if high else None

    # 4) 月度创新高占比：近 12 月中，月 close 创 12 月新高的月数占比
    result["new_high_ratio"] = _new_high_ratio(month_closes, window_months=12)

    # 5) 月度放量：末根成交量 / 近 20 日均量
    vols = [b["volume"] for b in daily_bars]
    if len(vols) >= 21 and sum(vols[-21:-1]) > 0:
        avg20 = sum(vols[-21:-1]) / 20.0
        result["volume_ratio"] = round(vols[-1] / avg20, 2) if avg20 > 0 else None

    # 6) 相对大盘强度 RS：近 60 日股票收益 - 大盘收益（%）
    if benchmark_bars and len(benchmark_bars) >= 2:
        result["relative_strength"] = round(
            _period_ret(closes, 60) - _period_ret(
                [b["close"] for b in benchmark_bars], 60), 2)

    # 7) regime 判定
    result["regime"] = _classify_regime(result, last_close, month_closes)
    return result


def _resample_monthly(daily_bars: list[dict]) -> list[dict]:
    """日 K -> 月 K：每月取最后一交易日的 close，volume 求和。按月升序。"""
    by_month: dict[str, dict] = {}
    for b in daily_bars:
        ym = b["date"][:7]  # YYYY-MM
        slot = by_month.setdefault(ym, {"month": ym, "close": b["close"],
                                        "volume": 0.0, "high": b["high"],
                                        "low": b["low"]})
        slot["close"] = b["close"]  # 升序遍历，最后保留即月末
        slot["volume"] += b["volume"]
        slot["high"] = max(slot["high"], b["high"])
        slot["low"] = min(slot["low"], b["low"])
    return [by_month[k] for k in sorted(by_month.keys())]


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return round(sum(values[-period:]) / period, 3)


def _new_high_ratio(month_closes: list[float], window_months: int = 12) -> float | None:
    if len(month_closes) < 2:
        return None
    w = window_months
    if len(month_closes) <= w:
        # 数据不足 window，用全部可用历史做基准
        lookback = month_closes
        target = month_closes
    else:
        lookback = month_closes[-w:]
        target = month_closes[-(w - 1):]  # 排除首月（无前序可比）
    if not target or len(lookback) < 2:
        return None
    count = 0
    total = 0
    # 对每个月，判断其 close 是否等于到此月为止的 window 内最大值
    start_idx = max(0, len(month_closes) - w)
    for i in range(start_idx, len(month_closes)):
        prev_window = month_closes[max(0, i - w):i]
        if not prev_window:
            continue
        total += 1
        if month_closes[i] >= max(prev_window):
            count += 1
    return round(count / total, 3) if total else None


def _period_ret(values: list[float], period: int) -> float:
    if len(values) < 2:
        return 0.0
    n = min(period, len(values) - 1)
    base = values[-n - 1]
    if not base:
        return 0.0
    return (values[-1] - base) / base * 100


def _classify_regime(sig: dict, last_close: float,
                     month_closes: list[float]) -> str | None:
    if not month_closes or len(month_closes) < 2:
        return None
    drawdown = sig.get("drawdown_from_high")
    new_high = sig.get("new_high_ratio")

    # 主锚点：日线 MA60（3 个月趋势，短历史也可用）；回退到月线 MA12
    trend_ma = sig.get("ma60_daily") or sig.get("ma12_monthly")
    if trend_ma is None:
        return None

    # Stage 2 突破：站上趋势 MA + 距高点回撤浅 + 新高比例高
    if last_close > trend_ma:
        dd_ok = drawdown is not None and drawdown > -15.0
        nh_ok = new_high is not None and new_high >= 0.3
        if dd_ok and nh_ok:
            return STAGE2_BREAKOUT
        return ADVANCING

    # 下跌：跌破趋势 MA
    if last_close < trend_ma:
        return DOWNTREND

    return CONSOLIDATION
