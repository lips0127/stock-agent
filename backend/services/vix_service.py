"""
VIX 恐慌指数 + 恐惧贪婪综合指数 计算服务（v5, 2026-06-09）

v5 重构要点：
  1. 合成 VIX = 5 ETF QVIX 等权平均（50/300/500/创业板/科创）
  2. Sigmoid 中心改为滚动 Z-Score 自适应
  3. PCR 接入 option_daily_stats_sse 真实数据
  4. 北向资金删除（已停止披露）
  5. 现货位置分改为连续 sigmoid（消除 5 档跳变）
  6. 统一输出口径：composite_score + 滚动百分位

设计：
  * 合成 VIX = avg(50ETF_QVIX, 300ETF_QVIX, 500ETF_QVIX, 创业板_QVIX, 科创50_QVIX)
  * 恐惧贪婪综合指数 = 0-100，0=极度恐慌 100=极度贪婪
    构成（权重，v5 修订）：
      - 合成 VIX          35%
      - 已实现波动率变化  15%
      - PCR（Put/Call）   15%
      - 融资融券变化      15%
      - 涨跌停家数比      20%

  阈值（regime 分类，v5 改为滚动百分位）：
    VIX:  基于近 252 日滚动百分位
    FG :  基于近 252 日滚动百分位
    Composite: 基于近 252 日滚动百分位
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.database import (
    upsert_vix_history, get_vix_latest, get_vix_history,
    compute_vix_percentile as db_compute_percentile,
    get_vix_history_for_zscore,
    get_vix_latest_before,
)
from backend.data.vix_sources import (
    fetch_50etf_qvix, fetch_multi_etf_qvix, fetch_index_daily,
    fetch_pcr, fetch_margin_balance, fetch_limit_counts,
    HS300_SYMBOL, ZZ1000_SYMBOL, SH_COMPOSITE_SYMBOL,
    get_spot_signals_for_date,
)
from backend.services.fear_greed_truth import truth_score_as_of

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 已实现波动率（Realized Volatility）算法（保持不变）
# ─────────────────────────────────────────────────────────────────

def garman_klass_rv(df: pd.DataFrame, window: int = 30) -> Optional[float]:
    """Garman-Klass 波动率估计（年化 %）。

    公式：σ² = (1/n) Σ [ 0.5·(ln(H/L))² − (2·ln2 − 1)·(ln(C/O))² ]
    比 close-to-close 更准确，因为用了 OHLC 全信息。

    入参：df 须含 date/open/high/low/close 列
    """
    if df is None or len(df) < window + 1:
        return None
    df = df.sort_values("date").tail(window + 1).reset_index(drop=True)
    log_hl = np.log(df["high"] / df["low"])
    log_co = np.log(df["close"] / df["open"])
    n = len(df)
    var = np.mean(0.5 * log_hl ** 2 - (2 * math.log(2) - 1) * log_co ** 2)
    if var <= 0:
        return None
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)


def close_to_close_rv(df: pd.DataFrame, window: int = 30) -> Optional[float]:
    """简单 close-to-close 波动率（年化 %）作为对照。"""
    if df is None or len(df) < window + 1:
        return None
    df = df.sort_values("date").tail(window + 1).reset_index(drop=True)
    rets = np.log(df["close"] / df["close"].shift(1)).dropna()
    if rets.std() is None or pd.isna(rets.std()):
        return None
    return round(float(rets.std()) * math.sqrt(252) * 100, 2)


def blended_rv(rv_hs300: Optional[float], rv_zz1000: Optional[float]) -> Optional[float]:
    """沪深 300 + 中证 1000 加权 RV（70/30），缺失一侧用另一侧。"""
    if rv_hs300 is not None and rv_zz1000 is not None:
        return round(rv_hs300 * 0.7 + rv_zz1000 * 0.3, 2)
    return rv_hs300 or rv_zz1000


# ─────────────────────────────────────────────────────────────────
# Z-Score 动态中心（v5 新增）
# ─────────────────────────────────────────────────────────────────

def compute_vix_zscore(current_vix: float) -> float:
    """计算当前合成 VIX 在近 252 个交易日的 Z-Score。

    Z = (current - μ_rolling) / σ_rolling

    从 vix_history 表取最近 252 天的合成 VIX 值，
    计算滚动均值和标准差，返回 Z 值。
    数据不足 20 天时返回 0.0（中性）。
    """
    history = get_vix_history_for_zscore(252)
    if len(history) < 20:
        return 0.0
    mu = float(np.mean(history))
    sigma = float(np.std(history))
    if sigma < 0.5:  # 波动率太低，Z 无意义
        return 0.0
    return round((current_vix - mu) / sigma, 3)


# ─────────────────────────────────────────────────────────────────
# 恐惧贪婪综合指数 — 得分映射（v5 修订）
# ─────────────────────────────────────────────────────────────────

def _vix_to_score(vix: float, zscore: Optional[float] = None) -> float:
    """合成 VIX → 0-100 分数（VIX 高 = 恐慌 = 低分）。

    v5 改动：sigmoid 中心用 Z-Score 替代固定值 21。
    Z=0 时 score=50（中性），Z=+2 时 score≈12（恐慌），Z=-2 时 score≈88（贪婪）。
    当 Z-Score 不可用时回退到固定中心 21 的旧公式。
    """
    if vix is None or pd.isna(vix):
        return 50.0
    if zscore is not None and not pd.isna(zscore):
        # Z-Score 自适应：k=2 使得 Z∈[-2.5, +2.5] 覆盖大部分范围
        return float(100 / (1 + math.exp(2.0 * zscore)))
    # 回退：固定中心 21
    return float(100 / (1 + math.exp(0.24 * (vix - 21))))


def _pcr_to_score(pcr_volume: Optional[float], pcr_oi: Optional[float] = None) -> float:
    """PCR → 0-100（PCR 高 = 看空多 = 低分）。

    v5 改动：接入真实数据。使用成交量 PCR 为主，持仓量 PCR 为辅。
    A 股 50ETF 期权 PCR 中位约 0.85，范围约 0.5-1.5。
    """
    pcr = pcr_volume if pcr_volume is not None else pcr_oi
    if pcr is None or pd.isna(pcr):
        return 50.0
    return float(100 / (1 + math.exp(3.0 * (pcr - 0.85))))


def _margin_change_to_score(prev: Optional[float], curr: Optional[float]) -> float:
    """融资融券余额环比变化 → 0-100（增长 = 加杠杆 = 贪婪）。"""
    if prev is None or curr is None or prev <= 0:
        return 50.0
    change_pct = (curr - prev) / prev * 100
    score = 50 + change_pct * 8.33
    return max(5.0, min(95.0, score))


def _limit_ratio_to_score(zt: Optional[int], dt: Optional[int]) -> float:
    """涨跌停家数比 → 0-100。"""
    zt = zt or 0
    dt = dt or 0
    total = zt + dt
    if total == 0:
        return 50.0
    ratio = zt / total * 100
    return float(100 / (1 + math.exp(-0.08 * (ratio - 50))))


def _rv_change_to_score(curr_rv: Optional[float], prev_rv: Optional[float]) -> float:
    """已实现波动率变化 → 0-100（上升 = 恐慌）。"""
    if curr_rv is None:
        return 50.0
    if prev_rv is None or prev_rv <= 0:
        return 50.0
    change = (curr_rv - prev_rv) / prev_rv
    score = 50 - change * 150
    return max(5.0, min(95.0, score))


# ─────────────────────────────────────────────────────────────────
# v6 新增 / v6.1 修订：VIX 动态信号（变化率 + 波动冲击）—— 提升平稳日敏感度
# ─────────────────────────────────────────────────────────────────

def _vix_change_to_score(chg_pct: Optional[float]) -> float:
    """合成 VIX 日变化率（已平滑）→ 0-100（VIX 上升 = 恐慌抬头 = 低分）。

    动机：平稳日 VIX 绝对值几乎不动，但其日间边际变化仍能反映情绪转向。
    v6.1：入参直接传平滑后的变化率%（2-3 日均值，过滤单日噪声）。
    chg=0 → 50；chg=+10% → ~23（恐慌抬头）；chg=-10% → ~77（情绪转暖）。
    """
    if chg_pct is None or pd.isna(chg_pct):
        return 50.0
    return float(100 / (1 + math.exp(0.12 * chg_pct)))


def _vix_swing_to_score(swing_pct: Optional[float]) -> float:
    """跨 ETF 波动冲击强度 → 0-100（振幅越大 = 盘中恐慌 = 低分）。

    v6.1：入参为单 ETF 振幅% 加权后的值（vix_sources 已正确合成，
    不再先拼 high/low 造假）。基准振幅约 6%。
    swing=6% → 50；swing=16% → ~10；swing=0 → ~74。
    """
    if swing_pct is None or pd.isna(swing_pct):
        return 50.0
    return max(5.0, min(95.0, 50 - (swing_pct - 6) * 4))


def compute_fear_greed(components: dict) -> float:
    """综合各分项加权得到 0-100 恐惧贪婪指数。

    v6.1 权重（快信号 20%→15%，回补给 VIX 水平；快信号易受单日噪声）：
      - 合成 VIX（水平，Z-Score） 30%
      - VIX 日变化率（已平滑）     9%
      - VIX 波动冲击强度           6%
      - RV 变化                   12%
      - PCR                       13%
      - 融资融券变化              10%
      - 涨跌停家数比              20%
    某分量数据缺失时，其权重按比例分摊到可用分量（active_weight 归一化）。
    """
    weights = {
        "vix":       0.30,
        "vix_chg":   0.09,
        "vix_swing": 0.06,
        "rv_chg":    0.12,
        "pcr":       0.13,
        "margin":    0.10,
        "limit":     0.20,
    }
    scores = {
        "vix":       components.get("vix_score", 50.0),
        "vix_chg":   components.get("vix_change_score", 50.0),
        "vix_swing": components.get("vix_swing_score", 50.0),
        "rv_chg":    components.get("rv_change_score", 50.0),
        "pcr":       components.get("pcr_score", 50.0),
        "margin":    components.get("margin_change_score", 50.0),
        "limit":     components.get("limit_score", 50.0),
    }
    vix_ok = components.get("vix") is not None and components.get("vix_source") != "none"
    available = {
        "vix":       vix_ok,
        "vix_chg":   vix_ok and components.get("vix_change_pct") is not None,
        "vix_swing": vix_ok and components.get("vix_swing_pct") is not None,
        "rv_chg":    components.get("rv_blended") is not None,
        "pcr":       components.get("pcr_volume") is not None or components.get("pcr_oi") is not None,
        "margin":    components.get("margin_balance") is not None,
        "limit":     components.get("limit_source") == "real",
    }
    active_weight = sum(weights[k] for k, ok in available.items() if ok)
    if active_weight <= 0:
        components["fg_scores"] = scores
        components["fg_available_weights"] = {}
        return 50.0

    normalized_weights = {
        k: round(weights[k] / active_weight, 4)
        for k, ok in available.items()
        if ok
    }
    components["fg_scores"] = {k: round(v, 2) for k, v in scores.items()}
    components["fg_available_weights"] = normalized_weights
    total = sum(scores[k] * normalized_weights[k] for k in normalized_weights)
    return round(total, 1)


# ─────────────────────────────────────────────────────────────────
# v8 大盘/小盘分离轨道：纯 cap 信号 FG（废弃 composite 合成）
# ─────────────────────────────────────────────────────────────────

# 单条轨道的 FG 只用该 cap 能区分的情绪信号：IV 水平(Z) + IV 变化率 +
# IV 跨标的振幅 + RV 变化。PCR/融资/涨跌停是全市场信号，无法区分大小盘，
# 降级为参考展示（仍计算并存库，但不再进 FG）。现货位置分单独展示，不进 FG。
_TRACK_WEIGHTS = {
    "vix":       0.45,
    "vix_chg":   0.15,
    "vix_swing": 0.10,
    "rv_chg":    0.30,
}


def compute_track_fg(track: str, c: dict) -> Optional[float]:
    """单条轨道（large/small）的恐惧贪婪分：纯 cap 信号加权。

    c 为该轨道的分量 dict，需含 vix/vix_score/vix_change_pct/vix_change_score/
    vix_swing_pct/vix_swing_score/rv_blended/rv_change_score/rv_prev。
    缺失分量按比例分摊到可用分量；IV 主体缺失则返回 None（轨道不可用）。
    """
    vix = c.get("vix")
    if vix is None:
        return None
    vix_ok = vix is not None
    scores = {
        "vix":       c.get("vix_score", 50.0),
        "vix_chg":   c.get("vix_change_score", 50.0),
        "vix_swing": c.get("vix_swing_score", 50.0),
        "rv_chg":    c.get("rv_change_score", 50.0),
    }
    available = {
        "vix":       vix_ok,
        "vix_chg":   vix_ok and c.get("vix_change_pct") is not None,
        "vix_swing": vix_ok and c.get("vix_swing_pct") is not None,
        "rv_chg":    c.get("rv") is not None,
    }
    active_weight = sum(_TRACK_WEIGHTS[k] for k, ok in available.items() if ok)
    if active_weight <= 0:
        return None
    norm = {k: _TRACK_WEIGHTS[k] / active_weight for k, ok in available.items() if ok}
    c["fg_scores"] = {k: round(v, 2) for k, v in scores.items()}
    c["fg_available_weights"] = {k: round(v, 4) for k, v in norm.items()}
    return round(sum(scores[k] * norm[k] for k in norm), 1)


def compute_track_zscore(track: str, current_vix: float,
                         date_str: Optional[str] = None) -> Optional[float]:
    """单条轨道 VIX 的滚动 Z-Score，point-in-time。

    date_str 给定（回填）→ 取 date < date_str 的近 252 行该轨道 VIX；
    date_str=None（实时今日）→ 取 DB 最近 252 行。两种口径都不含当日，
    即「当日 VIX 相对自身历史的标准化」。
    """
    from backend.core.database import get_vix_column_before, get_vix_history_for_zscore
    col = "large_vix" if track == "large" else "small_vix"
    if date_str:
        history = get_vix_column_before(date_str, col, 252)
    else:
        # 实时：取近 252 行该列（get_vix_history_for_zscore 只读 vix 列，这里手写）
        from backend.core.database import get_connection
        with get_connection() as conn:
            history = [r[0] for r in conn.execute(
                f"SELECT {col} FROM vix_history "
                f"WHERE {col} IS NOT NULL ORDER BY date DESC LIMIT 252"
            ).fetchall() if r[0] is not None]
    if len(history) < 20:
        return None
    mu = float(np.mean(history))
    sigma = float(np.std(history))
    if sigma < 0.5:
        return None
    return round((current_vix - mu) / sigma, 3)


def _track_change_pct(curr, prev, prev2) -> Optional[float]:
    """2 日平滑 VIX 变化率%（curr/prev/prev2 为该轨道连续三日的合成 VIX）。"""
    raw = (curr - prev) / prev * 100 if (curr and prev and prev > 0) else None
    prv = (prev - prev2) / prev2 * 100 if (prev and prev2 and prev2 > 0) else None
    if raw is not None and prv is not None:
        return round((raw + prv) / 2, 2)
    return round(raw, 2) if raw is not None else None


def _track_percentile(track: str, fg: Optional[float],
                      date_str: Optional[str] = None) -> Optional[float]:
    """单条轨道 FG 的滚动百分位，point-in-time（回填用 date < date_str）。"""
    if fg is None:
        return None
    from backend.core.database import get_vix_column_before, get_connection
    col = "large_fg" if track == "large" else "small_fg"
    if date_str:
        history = get_vix_column_before(date_str, col, 252)
    else:
        with get_connection() as conn:
            history = [r[0] for r in conn.execute(
                f"SELECT {col} FROM vix_history "
                f"WHERE {col} IS NOT NULL ORDER BY date DESC LIMIT 252"
            ).fetchall() if r[0] is not None]
    if len(history) < 5:
        return 50.0
    # 样本 5-19：用累积百分位（样本虽小但仍有方向意义，避免恒 50 抹平早期曲线）
    below = sum(1 for v in history if v <= fg)
    return round(below / len(history) * 100, 1)


# ─────────────────────────────────────────────────────────────────
# 阈值与 regime（v5 改为基于滚动百分位）
# ─────────────────────────────────────────────────────────────────

def classify_by_percentile(pct: Optional[float]) -> str:
    """基于滚动百分位输出 5 档 regime。

    阈值（对称）：
      0-10%   → extreme_fear   （比 90% 的日子都恐慌）
      10-30%  → fear
      30-70%  → neutral
      70-90%  → greed
      90-100% → extreme_greed
    """
    if pct is None or pd.isna(pct):
        return "unknown"
    if pct < 10:
        return "extreme_fear"
    if pct < 30:
        return "fear"
    if pct <= 70:
        return "neutral"
    if pct <= 90:
        return "greed"
    return "extreme_greed"


# 保留旧函数以兼容（标记 deprecated）
def classify_vix_regime(vix: Optional[float]) -> str:
    """[deprecated] 基于绝对值阈值，v5 不再使用。保留仅为兼容。"""
    if vix is None or pd.isna(vix):
        return "unknown"
    if vix < 14:  return "extreme_greed"
    if vix < 18:  return "greed"
    if vix < 24:  return "neutral"
    if vix < 32:  return "fear"
    return "extreme_fear"


def classify_fg_regime(fg: Optional[float]) -> str:
    """[deprecated] 基于绝对值阈值，v5 不再使用。保留仅为兼容。"""
    if fg is None or pd.isna(fg):
        return "unknown"
    if fg < 25:  return "extreme_fear"
    if fg < 45:  return "fear"
    if fg < 55:  return "neutral"
    if fg < 75:  return "greed"
    return "extreme_greed"


# ─────────────────────────────────────────────────────────────────
# 现货位置维度（v5 连续化）
# ─────────────────────────────────────────────────────────────────

def _spot_to_score(spot: Optional[dict]) -> Optional[float]:
    """现货位置 → 0-100 分数（0=极恐/底部, 100=极贪/顶部）。

    v5 改动：用加权 sigmoid 替代 5 档离散 AND 逻辑。
    三个子信号各自 sigmoid 后加权平均，输出连续平滑的 0-100 曲线。

    子信号权重：
      - ma60_dev (偏离 60 日均线)   50%
      - mom_20d  (20 日动量)        30%
      - new_high_ratio (新高比例)   20%
    """
    if not spot:
        return None
    dev = spot.get("spot_ma60_dev")
    mom20 = spot.get("spot_mom_20d")
    hi20 = spot.get("spot_new_high_ratio")
    if dev is None or mom20 is None:
        return None

    # ma60_dev sigmoid：中心 0%，k=0.3
    # dev=-5% → ~18, dev=0% → 50, dev=+5% → 82
    dev_score = 100 / (1 + math.exp(-0.3 * dev))

    # mom_20d sigmoid：中心 0%，k=0.2
    # mom=-5% → ~27, mom=0% → 50, mom=+5% → 73
    mom_score = 100 / (1 + math.exp(-0.2 * mom20))

    # new_high_ratio 线性：0 → 30, 0.5 → 65, 1.0 → 95
    if hi20 is not None and not pd.isna(hi20):
        hi_score = 30 + hi20 * 65
    else:
        hi_score = 50.0

    score = 0.50 * dev_score + 0.30 * mom_score + 0.20 * hi_score
    return round(score, 1)


def compute_composite_score(vix_fg: Optional[float], spot_score: Optional[float]) -> Optional[float]:
    """合成单一信号（VIX 恐惧贪婪 60% + 现货位置 40%）。

    v6.1：FG 占比 50%→60%。FG（期权 IV/PCR）是前瞻性情绪指标；现货均线/动量
    是同步/滞后指标，且与涨跌停、融资有重复计量。给前瞻信号更大话语权，
    避免趋势行情里被现货价格拖成过度乐观/悲观。
    任一维度为 None 时退回到另一维度。
    """
    if vix_fg is None and spot_score is None:
        return None
    if vix_fg is None:
        return round(spot_score, 1)
    if spot_score is None:
        return round(vix_fg, 1)
    return round(0.6 * vix_fg + 0.4 * spot_score, 1)


def classify_composite_regime(score: Optional[float]) -> str:
    """合成评分 → 5 档 regime（与 classify_by_percentile 一致）。"""
    if score is None or pd.isna(score):
        return "unknown"
    if score < 25:  return "extreme_fear"
    if score < 45:  return "fear"
    if score < 55:  return "neutral"
    if score < 75:  return "greed"
    return "extreme_greed"


# ─────────────────────────────────────────────────────────────────
# 主入口：算今日并入库
# ─────────────────────────────────────────────────────────────────

@dataclass
class VixSnapshot:
    date: str
    # v5: synthetic_vix = 多 ETF 等权平均
    vix: Optional[float]
    vix_source: str
    vix_zscore: Optional[float]
    # v5: 各 ETF QVIX 明细
    iv_50etf: Optional[float]
    iv_300etf: Optional[float]
    iv_500etf: Optional[float]
    iv_cyb: Optional[float]
    iv_kcb: Optional[float]
    # v5: PCR 真实数据
    pcr_volume: Optional[float]
    pcr_oi: Optional[float]
    pcr_call_volume: Optional[int]
    pcr_put_volume: Optional[int]
    pcr_source: str
    # 已实现波动率
    rv_hs300: Optional[float]
    rv_zz1000: Optional[float]
    rv_blended: Optional[float]
    # 融资融券
    margin_balance: Optional[float]
    margin_source: str
    # 涨跌停
    limit_up_count: Optional[int]
    limit_down_count: Optional[int]
    limit_source: str
    # 综合得分
    fear_greed: Optional[float]
    composite_score: Optional[float]
    composite_regime: Optional[str]
    composite_percentile: Optional[float]  # v5 新增：composite 滚动百分位
    # v7.0 construct-truth 恐惧贪婪（2026-06-29，与 v6.1 并存）
    fear_truth_v7: Optional[float] = None
    fear_greed_v7: Optional[float] = None
    comp_drawdown_v7: Optional[float] = None
    comp_breadth_v7: Optional[float] = None
    comp_iv_surge_v7: Optional[float] = None
    comp_iv_level_v7: Optional[float] = None
    regime_v7: Optional[str] = None
    # 现货位置
    spot_close: Optional[float] = None
    spot_ma60_dev: Optional[float] = None
    spot_mom_5d: Optional[float] = None
    spot_mom_20d: Optional[float] = None
    spot_new_high_ratio: Optional[float] = None
    # v8 大小盘分离轨道
    large_vix: Optional[float] = None
    large_zscore: Optional[float] = None
    large_fg: Optional[float] = None
    large_percentile: Optional[float] = None
    large_regime: Optional[str] = None
    large_rv: Optional[float] = None
    large_spot_score: Optional[float] = None
    small_vix: Optional[float] = None
    small_zscore: Optional[float] = None
    small_fg: Optional[float] = None
    small_percentile: Optional[float] = None
    small_regime: Optional[str] = None
    small_rv: Optional[float] = None
    small_spot_score: Optional[float] = None
    # 内部状态
    components: dict = None

    def to_db_payload(self) -> dict:
        return {
            "iv_50etf": self.iv_50etf,
            "iv_300etf": self.iv_300etf,
            "iv_500etf": self.iv_500etf,
            "iv_cyb": self.iv_cyb,
            "iv_kcb": self.iv_kcb,
            "pcr_volume": self.pcr_volume,
            "pcr_oi": self.pcr_oi,
            "pcr_call_volume": self.pcr_call_volume,
            "pcr_put_volume": self.pcr_put_volume,
            "pcr_source": self.pcr_source,
            "rv_hs300": self.rv_hs300,
            "rv_zz1000": self.rv_zz1000,
            "rv_blended": self.rv_blended,
            "margin_balance": self.margin_balance,
            "margin_source": self.margin_source,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "limit_source": self.limit_source,
            "vix": self.vix,
            "vix_source": self.vix_source,
            "vix_zscore": self.vix_zscore,
            "fear_greed": self.fear_greed,
            "composite_score": self.composite_score,
            "composite_regime": self.composite_regime,
            "composite_percentile": self.composite_percentile,
            "fear_truth_v7": self.fear_truth_v7,
            "fear_greed_v7": self.fear_greed_v7,
            "comp_drawdown_v7": self.comp_drawdown_v7,
            "comp_breadth_v7": self.comp_breadth_v7,
            "comp_iv_surge_v7": self.comp_iv_surge_v7,
            "comp_iv_level_v7": self.comp_iv_level_v7,
            "regime_v7": self.regime_v7,
            "components_json": json.dumps(self.components, ensure_ascii=False, default=str),
            "spot_close": self.spot_close,
            "spot_ma60_dev": self.spot_ma60_dev,
            "spot_mom_5d": self.spot_mom_5d,
            "spot_mom_20d": self.spot_mom_20d,
            "spot_new_high_ratio": self.spot_new_high_ratio,
            "large_vix": self.large_vix,
            "large_zscore": self.large_zscore,
            "large_fg": self.large_fg,
            "large_percentile": self.large_percentile,
            "large_regime": self.large_regime,
            "large_rv": self.large_rv,
            "large_spot_score": self.large_spot_score,
            "small_vix": self.small_vix,
            "small_zscore": self.small_zscore,
            "small_fg": self.small_fg,
            "small_percentile": self.small_percentile,
            "small_regime": self.small_regime,
            "small_rv": self.small_rv,
            "small_spot_score": self.small_spot_score,
        }


def _compute_composite_percentile(composite: Optional[float], days: int = 252) -> Optional[float]:
    """计算当前 composite 在近 N 天历史 composite 中的百分位。"""
    if composite is None:
        return None
    rows = get_vix_history(days)
    history = [r.get("composite_score") for r in rows if r.get("composite_score") is not None]
    if len(history) < 20:
        return 50.0
    below = sum(1 for v in history if v <= composite)
    return round(below / len(history) * 100, 1)


def recompute_percentiles(window: int = 252) -> dict:
    """全表重算 large/small 轨道与恐慌贪婪指数（fg7）的 percentile + regime（纯 DB，point-in-time）。

    v8：废弃 composite。两条轨道各自基于自身 FG 的 trailing window 百分位。
    2026-08-30：新增恐慌贪婪指数 fg7（fear_greed_v7）的 trailing window 百分位，
    regime 用 classify_by_percentile 划分，供 /vix 页面单一主指标展示。
    口径：每行取「该行及之前 window 个交易日」的历史，不含未来。
    返回 {"updated": N}。
    """
    from backend.core.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, large_fg, small_fg, fear_greed_v7 FROM vix_history "
            "ORDER BY date ASC"
        ).fetchall()
        records = [(r[0], r[1], r[2], r[3]) for r in rows]
        updated = 0
        for i, (d, large_fg, small_fg, fg7) in enumerate(records):
            start = max(0, i + 1 - window)
            hist_large = [v for _, v, _, _ in records[start:i + 1]
                          if v is not None]
            hist_small = [v for _, _, v, _ in records[start:i + 1]
                          if v is not None]
            hist_fg7 = [v for _, _, _, v in records[start:i + 1]
                        if v is not None]

            def _pct(hist, val):
                if val is None or len(hist) < 5:
                    return 50.0
                return round(sum(1 for v in hist if v <= val) / len(hist) * 100, 1)

            large_pct = _pct(hist_large, large_fg)
            small_pct = _pct(hist_small, small_fg)
            conn.execute(
                "UPDATE vix_history SET large_percentile = ?, large_regime = ?, "
                "small_percentile = ?, small_regime = ? WHERE date = ?",
                (large_pct, classify_by_percentile(large_pct),
                 small_pct, classify_by_percentile(small_pct), d),
            )
            if fg7 is not None:
                fg7_pct = _pct(hist_fg7, fg7)
                conn.execute(
                    "UPDATE vix_history SET fg7_percentile = ?, fg7_regime = ? "
                    "WHERE date = ?",
                    (fg7_pct, classify_by_percentile(fg7_pct), d),
                )
            # 兼容旧字段：composite_* 跟随大盘轨道，避免旧前端/仪表盘读到 NULL
            conn.execute(
                "UPDATE vix_history SET composite_percentile = ?, composite_regime = ? "
                "WHERE date = ?",
                (large_pct, classify_by_percentile(large_pct), d),
            )
            updated += 1
        conn.commit()
    logger.info(f"recompute_percentiles: 重算 {updated} 行（large/small 双轨道 + fg7）")
    return {"updated": updated}


def compute_today_snapshot(date_str: Optional[str] = None,
                           require_multi: bool = False,
                           truth_series: Optional[pd.DataFrame] = None,
                           progress=None) -> Optional[VixSnapshot]:
    """计算并返回某日 VIX 快照（v8 大小盘分离版，2026-07-01）。

    v8 重构：
      * 废弃 composite = 0.6·FG + 0.4·spot 合成。改为两条独立轨道：
        - 大盘轨道：50ETF + 300ETF QVIX + 沪深300 RV + 沪深300 现货
        - 小盘轨道：500ETF + 创业板 + 科创50 QVIX + 中证1000 RV + 中证1000 现货
      * 每条轨道各自 VIX / Z-Score / FG(纯 cap 信号) / percentile / regime。
      * PCR / 融资融券 / 涨跌停 是全市场信号，无法区分大小盘，降级为参考展示，
        不再进入 FG。
      * 现货位置分单独展示（large_spot_score / small_spot_score），不再参与 FG。
      * 全程 point-in-time：回填历史日 d 时所有数据源用 as_of=d 截断，
        Z-Score / 百分位用 date < d 的历史（修复 v6.1 的未来因子泄漏）。

    require_multi=True（回填用）：5 ETF 合成失败则返回 None，保留旧值不写降级。
    require_multi=False（实时用）：允许降级到单 50ETF。
    truth_series: 回填时可传入 build_truth_series() 的结果复用。
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    days_lookback = 60
    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
        days_lookback = max(60, (datetime.now() - target_dt).days + 30)
    except Exception:
        pass

    components: dict = {}
    components["_target_date"] = date_str
    components["_version"] = "v8"

    # ── 1) 多 ETF QVIX → 合成 VIX + 大小盘轨道 ──
    if progress:
        progress("拉取多 ETF QVIX 期权隐含波动率")
    multi_qvix = fetch_multi_etf_qvix(days=days_lookback, as_of=date_str)
    if multi_qvix:
        components["iv_50etf"] = multi_qvix.get("50etf")
        components["iv_300etf"] = multi_qvix.get("300etf")
        components["iv_500etf"] = multi_qvix.get("500etf")
        components["iv_cyb"] = multi_qvix.get("cyb")
        components["iv_kcb"] = multi_qvix.get("kcb")
        synthetic_vix = multi_qvix["synthetic"]
        synth_prev = multi_qvix.get("synthetic_prev")
        synth_prev2 = multi_qvix.get("synthetic_prev2")
        swing_pct = multi_qvix.get("swing_pct")
        vix_source = "multi_etf"
        etf_count = multi_qvix["count"]
    else:
        if require_multi:
            logger.info(f"VIX {date_str}: 多 ETF 合成失败，require_multi 跳过（保留旧值）")
            return None
        qvix_df = fetch_50etf_qvix(days=days_lookback)
        if qvix_df is not None and not qvix_df.empty:
            synthetic_vix = float(qvix_df["iv_close"].iloc[-1])
            components["iv_50etf"] = synthetic_vix
            synth_prev = float(qvix_df["iv_close"].iloc[-2]) if len(qvix_df) >= 2 else None
            synth_prev2 = float(qvix_df["iv_close"].iloc[-3]) if len(qvix_df) >= 3 else None
            swing_pct = None
            vix_source = "50etf_only"
            etf_count = 1
        else:
            synthetic_vix = None
            synth_prev = synth_prev2 = swing_pct = None
            vix_source = "none"
            etf_count = 0
    components["vix"] = synthetic_vix
    components["vix_source"] = vix_source
    components["vix_etf_count"] = etf_count

    # ── 2) 大盘 / 小盘轨道构建 ──
    if progress:
        progress("构建大小盘轨道（RV / 现货位置）")

    def _build_track(track: str, vix, vix_prev, vix_prev2, swing,
                     rv_symbol: str, spot_symbol: str) -> dict:
        """构建单条轨道的分量 dict。"""
        c: dict = {"vix": vix}
        if vix is None:
            c["vix_score"] = 50.0
            c["zscore"] = None
        else:
            c["zscore"] = compute_track_zscore(track, vix, date_str)
            c["vix_score"] = _vix_to_score(vix, c["zscore"])
        c["vix_change_pct"] = _track_change_pct(vix, vix_prev, vix_prev2)
        c["vix_change_score"] = _vix_change_to_score(c["vix_change_pct"])
        c["vix_swing_pct"] = swing
        c["vix_swing_score"] = _vix_swing_to_score(swing)

        # RV（as_of 截断，PIT）
        rv_df = fetch_index_daily(rv_symbol, days=90, as_of=date_str)
        rv_now = garman_klass_rv(rv_df, window=30) if rv_df is not None else None
        rv_prev = garman_klass_rv(rv_df, window=60) if rv_df is not None else None
        c["rv"] = rv_now
        c["rv_change_score"] = _rv_change_to_score(rv_now, rv_prev)

        # 现货位置（as_of 截断，PIT；单独展示不进 FG）
        spot = get_spot_signals_for_date(date_str, days=400, symbol=spot_symbol)
        c["spot"] = spot
        c["spot_score"] = _spot_to_score(spot)
        return c

    large_c = _build_track("large",
                           multi_qvix.get("large") if multi_qvix else synthetic_vix,
                           multi_qvix.get("large_prev") if multi_qvix else synth_prev,
                           multi_qvix.get("large_prev2") if multi_qvix else synth_prev2,
                           multi_qvix.get("large_swing") if multi_qvix else swing_pct,
                           HS300_SYMBOL, HS300_SYMBOL)
    small_c = _build_track("small",
                           multi_qvix.get("small") if multi_qvix else None,
                           multi_qvix.get("small_prev") if multi_qvix else None,
                           multi_qvix.get("small_prev2") if multi_qvix else None,
                           multi_qvix.get("small_swing") if multi_qvix else None,
                           ZZ1000_SYMBOL, ZZ1000_SYMBOL)
    components["large"] = large_c
    components["small"] = small_c

    large_fg = compute_track_fg("large", large_c)
    small_fg = compute_track_fg("small", small_c)
    large_c["fg"] = large_fg
    small_c["fg"] = small_fg

    # 百分位（PIT）+ regime
    large_pct = _track_percentile("large", large_fg, date_str)
    small_pct = _track_percentile("small", small_fg, date_str)
    large_c["percentile"] = large_pct
    small_c["percentile"] = small_pct
    large_c["regime"] = classify_by_percentile(large_pct)
    small_c["regime"] = classify_by_percentile(small_pct)

    # ── 3) 全市场参考信号（PCR / 融资融券 / 涨跌停）—— 仅展示，不进 FG ──
    if progress:
        progress("拉取全市场参考信号（PCR / 融资 / 涨跌停）")
    pcr_data = fetch_pcr(date_str)
    if pcr_data:
        components["pcr_volume"] = pcr_data["pcr_volume"]
        components["pcr_oi"] = pcr_data["pcr_oi"]
        components["pcr_call_volume"] = pcr_data["call_volume"]
        components["pcr_put_volume"] = pcr_data["put_volume"]
        components["pcr_source"] = "sse"
    else:
        components["pcr_volume"] = components["pcr_oi"] = None
        components["pcr_source"] = "unavailable"
    components["pcr_score"] = _pcr_to_score(
        components.get("pcr_volume"), components.get("pcr_oi"))

    margin = fetch_margin_balance(as_of=date_str)
    if margin:
        components["margin_balance"] = margin["margin_balance"]
        components["margin_source"] = "real"
    else:
        components["margin_balance"] = None
        components["margin_source"] = "unavailable"
    prev_row = get_vix_latest_before(date_str) if date_str else get_vix_latest()
    prev_margin = prev_row.get("margin_balance") if prev_row else None
    components["margin_change_score"] = _margin_change_to_score(
        prev_margin, components.get("margin_balance"))

    limits = fetch_limit_counts(date_str)
    if limits:
        components["limit_up_count"] = limits["limit_up_count"]
        components["limit_down_count"] = limits["limit_down_count"]
        components["limit_source"] = "real"
    else:
        components["limit_up_count"] = 0
        components["limit_down_count"] = 0
        components["limit_source"] = "unavailable"
    components["limit_score"] = _limit_ratio_to_score(
        components.get("limit_up_count"), components.get("limit_down_count"))

    # ── 4) v7.0 construct-truth 恐惧分（与真相同公式，并存对照）──
    if progress:
        progress("计算 v7 构造真实情绪分")
    try:
        ld_count = components.get("limit_down_count")
        ld_arg = float(ld_count) if (components.get("limit_source") == "real" and ld_count is not None) else None
        truth = truth_score_as_of(date_str, limit_down_count=ld_arg, cached=truth_series)
    except Exception as e:
        logger.warning(f"v7.0 truth 评分失败 {date_str}: {e}")
        truth = None
    if truth is not None:
        components["fear_truth_v7"] = truth.get("fear_truth")
        components["fear_greed_v7"] = truth.get("greed_v7")
        components["comp_drawdown_v7"] = truth.get("comp_drawdown")
        components["comp_breadth_v7"] = truth.get("comp_breadth")
        components["comp_iv_surge_v7"] = truth.get("comp_iv_surge")
        components["comp_iv_level_v7"] = truth.get("comp_iv_level")
        components["regime_v7"] = truth.get("regime")
    else:
        for k in ("fear_truth_v7", "fear_greed_v7", "regime_v7"):
            components[k] = None

    return VixSnapshot(
        date=date_str,
        vix=synthetic_vix,
        vix_source=vix_source,
        vix_zscore=large_c.get("zscore"),
        iv_50etf=components.get("iv_50etf"),
        iv_300etf=components.get("iv_300etf"),
        iv_500etf=components.get("iv_500etf"),
        iv_cyb=components.get("iv_cyb"),
        iv_kcb=components.get("iv_kcb"),
        pcr_volume=components.get("pcr_volume"),
        pcr_oi=components.get("pcr_oi"),
        pcr_call_volume=components.get("pcr_call_volume"),
        pcr_put_volume=components.get("pcr_put_volume"),
        pcr_source=components.get("pcr_source", "unavailable"),
        rv_hs300=large_c.get("rv"),
        rv_zz1000=small_c.get("rv"),
        rv_blended=large_c.get("rv"),
        margin_balance=components.get("margin_balance"),
        margin_source=components.get("margin_source", "unavailable"),
        limit_up_count=components.get("limit_up_count"),
        limit_down_count=components.get("limit_down_count"),
        limit_source=components.get("limit_source", "unavailable"),
        fear_greed=large_fg,
        composite_score=large_fg,
        composite_regime=large_c.get("regime"),
        composite_percentile=large_pct,
        fear_truth_v7=components.get("fear_truth_v7"),
        fear_greed_v7=components.get("fear_greed_v7"),
        comp_drawdown_v7=components.get("comp_drawdown_v7"),
        comp_breadth_v7=components.get("comp_breadth_v7"),
        comp_iv_surge_v7=components.get("comp_iv_surge_v7"),
        comp_iv_level_v7=components.get("comp_iv_level_v7"),
        regime_v7=components.get("regime_v7"),
        spot_close=large_c.get("spot", {}).get("spot_close") if large_c.get("spot") else None,
        spot_ma60_dev=large_c.get("spot", {}).get("spot_ma60_dev") if large_c.get("spot") else None,
        spot_mom_5d=large_c.get("spot", {}).get("spot_mom_5d") if large_c.get("spot") else None,
        spot_mom_20d=large_c.get("spot", {}).get("spot_mom_20d") if large_c.get("spot") else None,
        spot_new_high_ratio=large_c.get("spot", {}).get("spot_new_high_ratio") if large_c.get("spot") else None,
        large_vix=large_c.get("vix"),
        large_zscore=large_c.get("zscore"),
        large_fg=large_fg,
        large_percentile=large_pct,
        large_regime=large_c.get("regime"),
        large_rv=large_c.get("rv"),
        large_spot_score=large_c.get("spot_score"),
        small_vix=small_c.get("vix"),
        small_zscore=small_c.get("zscore"),
        small_fg=small_fg,
        small_percentile=small_pct,
        small_regime=small_c.get("regime"),
        small_rv=small_c.get("rv"),
        small_spot_score=small_c.get("spot_score"),
        components=components,
    )


def compute_and_store(date_str: Optional[str] = None,
                      progress=None,
                      task_runner=None) -> Optional[VixSnapshot]:
    """计算 + 写入 DB。返回快照。

    非交易日防护（2026-08-30）：live 路径（date_str=None）落在周末/节假日时，
    自动回退到最近一个交易日——否则会用上一交易日的 QVIX/行情造出一条
    「日期是今天但 PCR/构造分全缺」的垃圾行（2026-06-07、2026-08-30 即此问题）。
    入库后同步重算滚动百分位（含 fg7/large/small/composite）并刷新大小盘
    拆分轨道，保证当日读数立即可用；失败仅告警不阻塞主快照。
    """
    if not date_str:
        probe = datetime.now()
        for _ in range(20):
            if _is_trading_day(probe.strftime("%Y-%m-%d")):
                break
            probe -= timedelta(days=1)
        date_str = probe.strftime("%Y-%m-%d")

    snap = compute_today_snapshot(date_str, progress=progress)
    if snap is None:
        return None
    try:
        upsert_vix_history(snap.date, snap.to_db_payload())
        logger.info(
            f"VIX 快照入库: {snap.date} large(VIX={snap.large_vix} FG={snap.large_fg} "
            f"pct={snap.large_percentile}) small(VIX={snap.small_vix} FG={snap.small_fg} "
            f"pct={snap.small_percentile})"
        )
    except Exception as e:
        logger.error(f"VIX 入库失败: {e}", exc_info=True)

    try:
        if progress:
            progress("重算滚动百分位 + regime")
        recompute_percentiles()
    except Exception as e:
        logger.warning(f"compute_and_store: recompute_percentiles 失败: {e}")

    try:
        if progress:
            progress("更新大小盘拆分轨道")
        from backend.services.fear_greed_tracks import recompute_track_history
        recompute_track_history(task_runner=task_runner)
    except Exception as e:
        logger.warning(f"compute_and_store: 拆分轨道更新失败: {e}")

    return snap


# ─────────────────────────────────────────────────────────────────
# 回填历史
# ─────────────────────────────────────────────────────────────────

def _is_trading_day(date_str: str) -> bool:
    """判断是否交易日：周末 + A 股节假日。"""
    from datetime import datetime as _dt
    d = _dt.strptime(date_str, "%Y-%m-%d")
    if d.weekday() >= 5:  # 周六周日
        return False
    # A 股法定节假日（2025-2026，硬编码；后续可接 tushare 交易日历）
    _HOLIDAYS_2025_2026 = {
        # 2025
        "2025-01-01",                          # 元旦
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-02-03", "2025-02-04",            # 春节
        "2025-04-04", "2025-04-05", "2025-04-06",  # 清明
        "2025-05-01", "2025-05-02", "2025-05-05",  # 劳动节
        "2025-05-31", "2025-06-02",            # 端午
        "2025-10-01", "2025-10-02", "2025-10-03",
        "2025-10-06", "2025-10-07", "2025-10-08",  # 国庆+中秋
        # 2026
        "2026-01-01", "2026-01-02",            # 元旦
        "2026-02-16", "2026-02-17", "2026-02-18",
        "2026-02-19", "2026-02-20", "2026-02-23",  # 春节
        "2026-04-04", "2026-04-05", "2026-04-06",  # 清明
        "2026-05-01", "2026-05-04", "2026-05-05",  # 劳动节
        "2026-06-19", "2026-06-22",            # 端午
        "2026-09-25", "2026-09-28",            # 中秋
        "2026-10-01", "2026-10-02", "2026-10-05",
        "2026-10-06", "2026-10-07", "2026-10-08",  # 国庆
    }
    return date_str not in _HOLIDAYS_2025_2026


def backfill_vix_history(
    days: int = 30,
    skip_existing: bool = False,
    task_runner=None,
) -> dict:
    """回填过去 N 个交易日的 VIX 快照。

    串行执行（避免触发限流），每个交易日一次 akshare 抓取。
    入库跳过已存在日期（除非 skip_existing=False）。
    若传入 task_runner (TaskRunner)，则写入 task_runs 表；否则为兼容旧调用方
    返回 dict。
    """
    from backend.core.database import get_connection
    with get_connection() as conn:
        existing = {r[0] for r in conn.execute("SELECT date FROM vix_history").fetchall()}

    today = datetime.now()
    candidates: list[str] = []
    for i in range(0, days * 2):
        d = today - timedelta(days=i)
        candidates.append(d.strftime("%Y-%m-%d"))
    candidates = [d for d in candidates if _is_trading_day(d)]
    candidates = candidates[:days]
    candidates.reverse()

    skipped = 0
    failed = 0
    done = 0
    last_error = None

    if task_runner is not None:
        task_runner.set_total(len(candidates))
        task_runner.milestone(f"开始回填 {len(candidates)} 个交易日 VIX 快照")

    # v7.0 truth 序列只建一次（全历史，trailing 窗口 point-in-time），逐日复用
    truth_series = None
    try:
        from backend.services.fear_greed_truth import build_truth_series
        truth_series = build_truth_series()
    except Exception as e:
        logger.warning(f"回填: truth 序列构建失败，v7.0 将缺失: {e}")

    for idx, d in enumerate(candidates):
        if task_runner is not None:
            task_runner.check_cancelled()
            task_runner.set_current(f"回填 {d}")

        if skip_existing and d in existing:
            skipped += 1
            if task_runner is not None:
                task_runner.progress(idx + 1)
            continue
        try:
            snap = compute_today_snapshot(d, require_multi=True, truth_series=truth_series)
            if snap is None:
                failed += 1
                last_error = f"{d}: 多 ETF 合成失败（跳过，保留旧值）"
                if task_runner is not None:
                    task_runner.warn(f"VIX 回填 {d}: 多 ETF 合成失败，跳过")
            else:
                upsert_vix_history(snap.date, snap.to_db_payload())
                done += 1
                logger.info(f"VIX 回填入库: {snap.date} VIX={snap.vix} FG={snap.fear_greed}")
        except Exception as e:
            failed += 1
            last_error = f"{d}: {type(e).__name__}: {e}"
            logger.warning(f"VIX 回填 {d} 失败: {e}")
            if task_runner is not None:
                task_runner.warn(f"VIX 回填 {d} 失败: {e}")

        if task_runner is not None:
            task_runner.progress(idx + 1)

    result = {"total": len(candidates), "done": done, "skipped": skipped,
              "failed": failed, "last_error": last_error}

    # 全部 v6 数据就位后，统一按 point-in-time 口径重算百分位 + regime
    # （回填 oldest→newest，早期行算百分位时历史不完整，必须收尾统一修正）
    if done > 0:
        try:
            if task_runner is not None:
                task_runner.milestone("重算 composite 百分位 + regime")
            pct_result = recompute_percentiles()
            result["percentiles_updated"] = pct_result.get("updated", 0)
        except Exception as e:
            logger.warning(f"recompute_percentiles 失败: {e}")
            result["percentiles_error"] = str(e)
        try:
            from backend.services.fear_greed_tracks import recompute_track_history
            track_result = recompute_track_history(task_runner=task_runner)
            result["track_rows"] = track_result.get("rows", 0)
        except Exception as e:
            logger.warning(f"拆分轨道更新失败: {e}")
            result["tracks_error"] = str(e)

    if task_runner is not None:
        task_runner.milestone(
            f"VIX 回填完成: 成功 {done}, 跳过 {skipped}, 失败 {failed}"
        )
        task_runner.complete(result=result)

    return result


# ─────────────────────────────────────────────────────────────────
# 给前端用的反序列化
# ─────────────────────────────────────────────────────────────────

def snapshot_to_api(snap_dict: dict) -> dict:
    """DB 行 → API JSON（v5 结构）。"""
    if not snap_dict:
        return {}
    components = {}
    if snap_dict.get("components_json"):
        try:
            components = json.loads(snap_dict["components_json"])
        except Exception:
            pass

    def _is_real(source) -> bool:
        if source is None:
            return False
        return str(source) in ("real", "iv", "hist", "min", "summary",
                                "rv_fallback", "multi_etf", "50etf_only", "sse")

    quality_signals = {
        "vix":     _is_real(components.get("vix_source", "")),
        "rv_chg":  snap_dict.get("rv_hs300") is not None,
        "pcr":     _is_real(components.get("pcr_source", "")),
        "margin":  _is_real(components.get("margin_source", "")),
        "limit":   _is_real(components.get("limit_source", "")),
        "spot":    _is_real(components.get("spot_source", "")),
    }
    real_count = sum(1 for v in quality_signals.values() if v)

    return {
        "date":                snap_dict.get("date"),
        # v5: 合成 VIX
        "vix":                 snap_dict.get("vix"),
        "vix_source":          components.get("vix_source", "unknown"),
        "vix_zscore":          snap_dict.get("vix_zscore"),
        "vix_etf_count":       components.get("vix_etf_count", 0),
        # v6: VIX 动态信号
        "vix_change_pct":      components.get("vix_change_pct"),
        "vix_swing_pct":       components.get("vix_swing_pct"),
        # v6.1: 宽基/成长拆分
        "vix_broad":           components.get("vix_broad"),
        "vix_growth":          components.get("vix_growth"),
        "vix_growth_premium":  components.get("vix_growth_premium"),
        # v5: 各 ETF IV 明细
        "iv_50etf":            snap_dict.get("iv_50etf"),
        "iv_300etf":           snap_dict.get("iv_300etf"),
        "iv_500etf":           snap_dict.get("iv_500etf"),
        "iv_cyb":              snap_dict.get("iv_cyb"),
        "iv_kcb":              snap_dict.get("iv_kcb"),
        # v5: PCR
        "pcr_volume":          snap_dict.get("pcr_volume"),
        "pcr_oi":              snap_dict.get("pcr_oi"),
        "pcr_call_volume":     snap_dict.get("pcr_call_volume"),
        "pcr_put_volume":      snap_dict.get("pcr_put_volume"),
        "pcr_source":          components.get("pcr_source", "unknown"),
        # RV
        "rv_hs300":            snap_dict.get("rv_hs300"),
        "rv_zz1000":           snap_dict.get("rv_zz1000"),
        "rv_blended":          snap_dict.get("rv_blended"),
        # 融资融券
        "margin_balance":      snap_dict.get("margin_balance"),
        "margin_source":       components.get("margin_source", "unknown"),
        # 涨跌停
        "limit_up_count":      snap_dict.get("limit_up_count"),
        "limit_down_count":    snap_dict.get("limit_down_count"),
        "limit_source":        components.get("limit_source", "unknown"),
        # 综合得分（v5 统一输出）
        "fear_greed":          snap_dict.get("fear_greed"),
        "composite_score":     snap_dict.get("composite_score"),
        "composite_regime":    snap_dict.get("composite_regime"),
        "composite_percentile": snap_dict.get("composite_percentile"),
        # v5: regime = composite_regime（统一标签）
        "regime":              snap_dict.get("composite_regime"),
        "vix_only_regime":     snap_dict.get("regime"),  # 保留兼容
        # v7.0: construct-truth 恐惧贪婪（与 v6.1 并存，同屏对比）
        "fear_truth_v7":       snap_dict.get("fear_truth_v7"),
        "fear_greed_v7":       snap_dict.get("fear_greed_v7"),
        "regime_v7":           snap_dict.get("regime_v7"),
        # 恐慌贪婪指数（/vix 页面单一主指标）：滚动百分位与 regime 由
        # recompute_percentiles 落库；缺失时前端必须显示降级而非伪装正常
        "fg7_percentile":      snap_dict.get("fg7_percentile"),
        "fg7_regime":          snap_dict.get("fg7_regime"),
        "v7_components": {
            "drawdown":  snap_dict.get("comp_drawdown_v7"),
            "breadth":   snap_dict.get("comp_breadth_v7"),
            "iv_surge":  snap_dict.get("comp_iv_surge_v7"),
            "iv_level":  snap_dict.get("comp_iv_level_v7"),
        },
        # 百分位（基于 composite，不再基于 vix）
        "percentile":          snap_dict.get("composite_percentile"),
        # 现货位置
        "spot": {
            "close":          snap_dict.get("spot_close"),
            "ma60_dev":       snap_dict.get("spot_ma60_dev"),
            "mom_5d":         snap_dict.get("spot_mom_5d"),
            "mom_20d":        snap_dict.get("spot_mom_20d"),
            "new_high_ratio": snap_dict.get("spot_new_high_ratio"),
            "source":         components.get("spot_source", "unknown"),
        },
        # v8 大小盘分离轨道（前端主曲线）
        "tracks": {
            "large": {
                "vix":        snap_dict.get("large_vix"),
                "zscore":     snap_dict.get("large_zscore"),
                "fg":         snap_dict.get("large_fg"),
                "percentile": snap_dict.get("large_percentile"),
                "regime":     snap_dict.get("large_regime"),
                "rv":         snap_dict.get("large_rv"),
                "spot_score": snap_dict.get("large_spot_score"),
                "iv": {
                    "50etf": snap_dict.get("iv_50etf"),
                    "300etf": snap_dict.get("iv_300etf"),
                },
            },
            "small": {
                "vix":        snap_dict.get("small_vix"),
                "zscore":     snap_dict.get("small_zscore"),
                "fg":         snap_dict.get("small_fg"),
                "percentile": snap_dict.get("small_percentile"),
                "regime":     snap_dict.get("small_regime"),
                "rv":         snap_dict.get("small_rv"),
                "spot_score": snap_dict.get("small_spot_score"),
                "iv": {
                    "500etf": snap_dict.get("iv_500etf"),
                    "cyb":    snap_dict.get("iv_cyb"),
                    "kcb":    snap_dict.get("iv_kcb"),
                },
            },
            "small_large_premium": (
                round(snap_dict.get("small_vix") - snap_dict.get("large_vix"), 2)
                if snap_dict.get("small_vix") is not None
                and snap_dict.get("large_vix") is not None else None
            ),
        },
        # composite 明细
        "composite": {
            "score":     snap_dict.get("composite_score"),
            "regime":    snap_dict.get("composite_regime"),
            "percentile": snap_dict.get("composite_percentile"),
            "vix_fg":    snap_dict.get("fear_greed"),
            "spot_score": components.get("spot_score"),
        },
        # 数据质量（v5：5 分量 + 现货 = 6 总）
        "data_quality": {
            "total":   6,
            "real":    real_count,
            "missing": 6 - real_count,
            "signals": quality_signals,
        },
        "components": components,
    }


def _tracks_to_api(by_track: dict) -> dict:
    """vix_track_history 行 → 拆分轨道 API 结构（缺失轨道 available=False）。"""
    from backend.services.fear_greed_tracks import TRACKS

    def _blank(meta) -> dict:
        return {
            "name": meta["name"], "available": False,
            "greed": None, "percentile": None, "regime": "unknown",
            "has_iv": bool(meta.get("qvix")),
            "iv_label": meta.get("iv_label"),
            "components": {"drawdown": None, "breadth": None,
                           "iv_surge": None, "iv_level": None},
        }

    out = {}
    for key, meta in TRACKS.items():
        row = by_track.get(key)
        if not row:
            out[key] = _blank(meta)
            continue
        out[key] = {
            "name": meta["name"],
            "available": row.get("greed") is not None,
            "greed": row.get("greed"),
            "percentile": row.get("percentile"),
            "regime": row.get("regime") or "unknown",
            "uptrend": bool(row.get("uptrend")),
            "has_iv": bool(meta.get("qvix")),
            "iv_label": meta.get("iv_label"),
            "components": {
                "drawdown": row.get("drawdown"),
                "breadth": row.get("breadth"),
                "iv_surge": row.get("iv_surge"),
                "iv_level": row.get("iv_level"),
            },
        }
    return out


def _attach_size_tracks(api_rows: list[dict]) -> list[dict]:
    """给 API 快照行挂上 size_tracks（批量查 vix_track_history，避免 N+1）。"""
    from backend.core.database import get_vix_tracks_by_dates

    dates = [r.get("date") for r in api_rows if r.get("date")]
    if not dates:
        return api_rows
    try:
        track_rows = get_vix_tracks_by_dates(dates)
    except Exception as e:
        logger.warning(f"读取拆分轨道失败: {e}")
        track_rows = {}
    for r in api_rows:
        r["size_tracks"] = _tracks_to_api(track_rows.get(r.get("date"), {}))
    return api_rows


def get_latest_api() -> dict:
    api = snapshot_to_api(get_vix_latest() or {})
    if api:
        _attach_size_tracks([api])
    return api


def get_history_api(days: int = 60) -> list[dict]:
    rows = get_vix_history(days)
    api_rows = [snapshot_to_api(r) for r in rows]
    _attach_size_tracks(api_rows)
    return api_rows
