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
)
from backend.data.vix_sources import (
    fetch_50etf_qvix, fetch_multi_etf_qvix, fetch_index_daily,
    fetch_pcr, fetch_margin_balance, fetch_limit_counts,
    HS300_SYMBOL, ZZ1000_SYMBOL, SH_COMPOSITE_SYMBOL,
    get_spot_signals_for_date,
)

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
    # 现货位置
    spot_close: Optional[float] = None
    spot_ma60_dev: Optional[float] = None
    spot_mom_5d: Optional[float] = None
    spot_mom_20d: Optional[float] = None
    spot_new_high_ratio: Optional[float] = None
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
            "components_json": json.dumps(self.components, ensure_ascii=False, default=str),
            "spot_close": self.spot_close,
            "spot_ma60_dev": self.spot_ma60_dev,
            "spot_mom_5d": self.spot_mom_5d,
            "spot_mom_20d": self.spot_mom_20d,
            "spot_new_high_ratio": self.spot_new_high_ratio,
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
    """全表重算 composite_percentile + composite_regime（纯 DB，不拉外部数据）。

    回填是 oldest→newest，早期行算百分位时历史里仍混着尚未覆盖的旧数据，
    且 v6 后 composite 分布整体下移，必须在全部数据就位后统一按
    「该行自身日期往前 window 个交易日」的 point-in-time 口径重算一遍。

    返回 {"updated": N}。
    """
    from backend.core.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, composite_score FROM vix_history "
            "WHERE composite_score IS NOT NULL ORDER BY date ASC"
        ).fetchall()
        scores = [(r[0], float(r[1])) for r in rows]
        updated = 0
        for i, (d, score) in enumerate(scores):
            # 取该行及之前 window 个交易日的 composite 历史（point-in-time）
            start = max(0, i + 1 - window)
            hist = [s for _, s in scores[start:i + 1]]
            if len(hist) < 20:
                pct = 50.0
            else:
                below = sum(1 for v in hist if v <= score)
                pct = round(below / len(hist) * 100, 1)
            regime = classify_by_percentile(pct)
            conn.execute(
                "UPDATE vix_history SET composite_percentile = ?, composite_regime = ? "
                "WHERE date = ?",
                (pct, regime, d),
            )
            updated += 1
        conn.commit()
    logger.info(f"recompute_percentiles: 重算 {updated} 行")
    return {"updated": updated}


def compute_today_snapshot(date_str: Optional[str] = None,
                           require_multi: bool = False) -> Optional[VixSnapshot]:
    """计算并返回某日 VIX 快照（v6.1）。

    require_multi=True（回填用）：若 5 ETF 合成失败（只能拿到单 50ETF 或全缺），
    返回 None，让调用方跳过写库、保留旧值，避免降级值污染历史曲线。
    require_multi=False（实时用）：允许降级到单 50ETF，保证当日总有值可展示。
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
    components["_version"] = "v6.1"

    # ── 1) 多 ETF QVIX → 合成 VIX（v6.1 代表性加权 + 宽基/成长拆分）──
    multi_qvix = fetch_multi_etf_qvix(days=days_lookback, as_of=date_str)
    synth_prev = None
    synth_prev2 = None
    swing_pct = None
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
        components["vix_broad"] = multi_qvix.get("broad")
        components["vix_growth"] = multi_qvix.get("growth")
        components["vix_growth_premium"] = multi_qvix.get("growth_premium")
        vix_source = "multi_etf"
        etf_count = multi_qvix["count"]
    else:
        # 5 ETF 合成失败。回填模式下宁可跳过也不写降级值（避免污染历史曲线）。
        if require_multi:
            logger.info(f"VIX {date_str}: 多 ETF 合成失败，require_multi 跳过（保留旧值）")
            return None
        # 实时模式：回退到单 50ETF QVIX，保证当日有值
        qvix_df = fetch_50etf_qvix(days=days_lookback)
        if qvix_df is not None and not qvix_df.empty:
            synthetic_vix = float(qvix_df["iv_close"].iloc[-1])
            components["iv_50etf"] = synthetic_vix
            if len(qvix_df) >= 2:
                synth_prev = float(qvix_df["iv_close"].iloc[-2])
            vix_source = "50etf_only"
            etf_count = 1
        else:
            synthetic_vix = None
            vix_source = "none"
            etf_count = 0
    components["vix"] = synthetic_vix
    components["vix_source"] = vix_source
    components["vix_etf_count"] = etf_count

    # ── 2) Z-Score ──
    if synthetic_vix is not None:
        zscore = compute_vix_zscore(synthetic_vix)
    else:
        zscore = None
    components["vix_zscore"] = zscore

    # ── 3) VIX → 0-100 分（水平 + 平滑变化率 + 波动冲击）──
    vix_score = _vix_to_score(synthetic_vix, zscore)
    components["vix_score"] = vix_score

    # v6.1: VIX 日变化率（2 日平滑：当日环比与上一日环比取均值，过滤单日噪声）
    # 全部从 QVIX 序列内派生，回填顺序无关（不依赖 DB 中可能未就位的行）。
    raw_change_pct = None
    if synthetic_vix is not None and synth_prev is not None and synth_prev > 0:
        raw_change_pct = (synthetic_vix - synth_prev) / synth_prev * 100
    prev_change = None
    if synth_prev is not None and synth_prev2 is not None and synth_prev2 > 0:
        prev_change = (synth_prev - synth_prev2) / synth_prev2 * 100
    if raw_change_pct is not None and prev_change is not None:
        vix_change_pct = round((raw_change_pct + prev_change) / 2, 2)
    elif raw_change_pct is not None:
        vix_change_pct = round(raw_change_pct, 2)
    else:
        vix_change_pct = None
    components["vix_change_pct_raw"] = round(raw_change_pct, 2) if raw_change_pct is not None else None
    components["vix_change_pct"] = vix_change_pct
    components["vix_change_score"] = _vix_change_to_score(vix_change_pct)

    # v6.1: 跨 ETF 波动冲击强度（vix_sources 已做单 ETF 标准化后加权）
    components["vix_swing_pct"] = swing_pct
    components["vix_swing_score"] = _vix_swing_to_score(swing_pct)

    # ── 4) 已实现波动率 ──
    hs300_df = fetch_index_daily(HS300_SYMBOL, days=90)
    zz1000_df = fetch_index_daily(ZZ1000_SYMBOL, days=90)
    rv_hs300 = garman_klass_rv(hs300_df, window=30) if hs300_df is not None else None
    rv_zz1000 = garman_klass_rv(zz1000_df, window=30) if zz1000_df is not None else None
    rv_blended = blended_rv(rv_hs300, rv_zz1000)
    rv_hs300_prev = garman_klass_rv(hs300_df, window=60) if hs300_df is not None else None
    rv_change_score = _rv_change_to_score(rv_blended, rv_hs300_prev)
    components["rv_change_score"] = rv_change_score
    components["rv_hs300"] = rv_hs300
    components["rv_zz1000"] = rv_zz1000
    components["rv_blended"] = rv_blended

    # ── 5) PCR（v5 真实数据） ──
    pcr_data = fetch_pcr(date_str)
    if pcr_data:
        components["pcr_volume"] = pcr_data["pcr_volume"]
        components["pcr_oi"] = pcr_data["pcr_oi"]
        components["pcr_call_volume"] = pcr_data["call_volume"]
        components["pcr_put_volume"] = pcr_data["put_volume"]
        components["pcr_call_oi"] = pcr_data["call_oi"]
        components["pcr_put_oi"] = pcr_data["put_oi"]
        components["pcr_source"] = "sse"
    else:
        components["pcr_volume"] = None
        components["pcr_oi"] = None
        components["pcr_source"] = "unavailable"
    pcr_score = _pcr_to_score(
        components.get("pcr_volume"),
        components.get("pcr_oi"),
    )
    components["pcr_score"] = pcr_score

    # ── 6) 融资融券 ──
    margin = fetch_margin_balance()
    if margin:
        components["margin_balance"] = margin["margin_balance"]
        components["margin_source"] = "real"
    else:
        components["margin_balance"] = None
        components["margin_source"] = "unavailable"
    prev = get_vix_latest()
    prev_margin = prev.get("margin_balance") if prev else None
    components["margin_change_score"] = _margin_change_to_score(
        prev_margin, components.get("margin_balance")
    )

    # ── 7) 涨跌停 ──
    limits = fetch_limit_counts(date_str)
    if limits:
        components["limit_up_count"] = limits["limit_up_count"]
        components["limit_down_count"] = limits["limit_down_count"]
        components["limit_source"] = "real"
    else:
        components["limit_up_count"] = 0
        components["limit_down_count"] = 0
        components["limit_source"] = "unavailable"
    limit_score = _limit_ratio_to_score(
        components.get("limit_up_count"),
        components.get("limit_down_count"),
    )
    components["limit_score"] = limit_score

    # ── 8) 恐惧贪婪综合指数 ──
    fg = compute_fear_greed(components)

    # ── 9) 现货位置信号 ──
    spot = get_spot_signals_for_date(date_str, days=400)
    if spot:
        components["spot"] = spot
        components["spot_source"] = "real"
    else:
        components["spot"] = None
        components["spot_source"] = "unavailable"
    spot_score = _spot_to_score(spot)
    components["spot_score"] = spot_score

    # ── 10) 合成 + 百分位 + regime ──
    composite = compute_composite_score(fg, spot_score)
    components["composite_score"] = composite

    # composite 滚动百分位（基于 vix_history 中的 composite_score 历史）
    composite_pct = _compute_composite_percentile(composite)
    components["composite_percentile"] = composite_pct

    # regime 基于百分位
    composite_regime = classify_by_percentile(composite_pct)

    return VixSnapshot(
        date=date_str,
        vix=synthetic_vix,
        vix_source=vix_source,
        vix_zscore=zscore,
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
        rv_hs300=rv_hs300,
        rv_zz1000=rv_zz1000,
        rv_blended=rv_blended,
        margin_balance=components.get("margin_balance"),
        margin_source=components.get("margin_source", "unavailable"),
        limit_up_count=components.get("limit_up_count"),
        limit_down_count=components.get("limit_down_count"),
        limit_source=components.get("limit_source", "unavailable"),
        fear_greed=fg,
        composite_score=composite,
        composite_regime=composite_regime,
        composite_percentile=composite_pct,
        spot_close=spot.get("spot_close") if spot else None,
        spot_ma60_dev=spot.get("spot_ma60_dev") if spot else None,
        spot_mom_5d=spot.get("spot_mom_5d") if spot else None,
        spot_mom_20d=spot.get("spot_mom_20d") if spot else None,
        spot_new_high_ratio=spot.get("spot_new_high_ratio") if spot else None,
        components=components,
    )


def compute_and_store(date_str: Optional[str] = None) -> Optional[VixSnapshot]:
    """计算 + 写入 DB。返回快照。"""
    snap = compute_today_snapshot(date_str)
    if snap is None:
        return None
    try:
        upsert_vix_history(snap.date, snap.to_db_payload())
        logger.info(
            f"VIX 快照入库: {snap.date} VIX={snap.vix} FG={snap.fear_greed} "
            f"composite={snap.composite_score} regime={snap.composite_regime}"
        )
    except Exception as e:
        logger.error(f"VIX 入库失败: {e}", exc_info=True)
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
            snap = compute_today_snapshot(d, require_multi=True)
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


def get_latest_api() -> dict:
    return snapshot_to_api(get_vix_latest() or {})


def get_history_api(days: int = 60) -> list[dict]:
    rows = get_vix_history(days)
    return [snapshot_to_api(r) for r in rows]
