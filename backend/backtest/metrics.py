"""
绩效指标计算 — 从回测交易记录计算各项量化指标。

指标：
  - 总收益率、年化收益率
  - 夏普比率
  - 最大回撤（含回撤区间）
  - 胜率、盈亏比
  - 年化波动率
"""

from __future__ import annotations
import math
from typing import Any


def calculate_metrics(
    daily_values: list[float],
    trades: list[dict],
    initial_capital: float,
    trading_days: int,
    risk_free_rate: float = 0.03,
) -> dict[str, Any]:
    """计算全套绩效指标。

    Args:
        daily_values: 每日组合总值序列
        trades: 交易明细列表 [{"pnl": float, ...}, ...]
        initial_capital: 初始资金
        trading_days: 交易天数
        risk_free_rate: 无风险利率（默认 3%）

    Returns:
        指标字典
    """
    if not daily_values:
        return _empty_report(initial_capital)

    final_value = daily_values[-1]
    total_return = (final_value - initial_capital) / initial_capital

    # 每日收益率序列
    daily_returns = []
    for i in range(1, len(daily_values)):
        if daily_values[i - 1] > 0:
            daily_returns.append(daily_values[i] / daily_values[i - 1] - 1)

    # 年化收益率
    annual_return = (1 + total_return) ** (252 / max(trading_days, 1)) - 1

    # 年化波动率
    if daily_returns:
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
        annual_volatility = math.sqrt(variance) * math.sqrt(252)
    else:
        annual_volatility = 0.0

    # 夏普比率
    if annual_volatility > 0:
        sharpe = (annual_return - risk_free_rate) / annual_volatility
    else:
        sharpe = 0.0

    # 最大回撤
    max_dd, dd_start, dd_end = _calc_max_drawdown(daily_values)

    # 卡玛比率
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0.0

    # 交易统计
    trade_stats = _calc_trade_stats(trades)

    return {
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "max_drawdown": max_dd,
        "max_drawdown_pct": abs(max_dd),
        "dd_start": dd_start,
        "dd_end": dd_end,
        "trading_days": trading_days,
        **trade_stats,
    }


def _calc_max_drawdown(values: list[float]) -> tuple[float, str, str]:
    """计算最大回撤。

    Returns:
        (max_dd_ratio, peak_date_str, trough_date_str)
    """
    peak = values[0]
    max_dd = 0.0
    dd_start_idx = 0
    dd_end_idx = 0
    peak_idx = 0

    for i, v in enumerate(values):
        if v > peak:
            peak = v
            peak_idx = i
        dd = (v - peak) / peak if peak != 0 else 0
        if dd < max_dd:
            max_dd = dd
            dd_start_idx = peak_idx
            dd_end_idx = i

    return max_dd, str(dd_start_idx), str(dd_end_idx)


def _calc_trade_stats(trades: list[dict]) -> dict:
    """计算交易维度的统计指标。"""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
        }

    winning = [t for t in trades if t.get("pnl", 0) > 0]
    losing = [t for t in trades if t.get("pnl", 0) < 0]

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    win_rate = len(winning) / len(trades) if trades else 0
    avg_win = sum(t.get("pnl", 0) for t in winning) / len(winning) if winning else 0
    avg_loss = sum(t.get("pnl", 0) for t in losing) / len(losing) if losing else 0

    total_gains = sum(t.get("pnl", 0) for t in winning)
    total_losses = abs(sum(t.get("pnl", 0) for t in losing))
    profit_factor = total_gains / total_losses if total_losses != 0 else float("inf")

    return {
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
    }


def _empty_report(initial_capital: float) -> dict:
    return {
        "initial_capital": initial_capital,
        "final_value": initial_capital,
        "total_return": 0.0,
        "annual_return": 0.0,
        "annual_volatility": 0.0,
        "sharpe_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "dd_start": "",
        "dd_end": "",
        "trading_days": 0,
        "total_trades": 0,
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "total_pnl": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
    }
