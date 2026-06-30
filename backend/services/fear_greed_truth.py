"""Construct-truth 恐惧分（市场真实情绪锚）。

v6.1 恐惧贪婪在 2025-04-07（关税千股跌停，上证 3096）与 2026-03-23（上证 3813）
上失效：两者 fg≈16，3-23 甚至略更恐，但 4-07 价格深得多、应最恐慌。根因是 v6.1
锚定 IV *水平*（3-23 IV=51 > 4-07 IV=42），而真实恐慌信号是价格回撤深度 + 跌停
广度 + IV *飙升幅度*。2025-08 单边上涨却进恐慌区同理：上涨趋势里的 IV 上升是行情
波动放大，不是恐慌。

本模块定义一个“市场真实情绪”的可计算锚，显式去耦 IV 水平，作为 v7.0 手工版与
VIX2 ML 版重定向的共用真相定义。口径：fear_truth ∈ [0,100]，越大越恐慌。

构造（point-in-time，全部 trailing 窗口，无未来泄漏）：
  - 价格回撤锚（主导）：close 距 trailing 60 日高点回撤深度。越深越恐。
  - 趋势/体制门控：均线之上 + 正动量 → 抑制 IV 类分量（消灭上涨假恐慌）。
  - IV 飙升（变化率，非水平）：QVIX 5 日变化率。突发飙升 → 恐慌。
  - 广度崩塌：跌停家数。缺失时显式降权并标记，不静默中性。
  - IV 水平仅作次级、体制门控后贡献（仅下跌体制给话语权）。
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

from backend.services.stock_service import _no_proxy
from backend.data.vix_sources import (
    fetch_index_daily_tx, SH_COMPOSITE_SYMBOL, ak_index_option_50etf_qvix,
)

logger = logging.getLogger(__name__)

_DD_WINDOW = 60          # 回撤锚窗口
_Z_WINDOW = 252          # IV 水平分位窗口
_IV_SURGE_WIN = 5        # IV 飙升回看天数
_MA_WINDOW = 60
_MOM_WIN = 20
_LONG_DAYS = 4200

# 分量映射阈值（经验值，可用锚点校准）
_DD_FULL_FEAR_PCT = 12.0   # 距 60 日高点回撤 12% → 恐惧分满
_IV_SURGE_FULL = 30.0      # QVIX 5 日涨 30% → IV 飙升分满
_BREADTH_FULL = 500        # 跌停 500 家 → 广度分满

# 合成权重（广度缺失时其权重按比例分摊给回撤锚）
_W = {
    "drawdown": 0.40,
    "breadth":  0.30,
    "iv_surge": 0.20,
    "iv_level": 0.10,
}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _fetch_qvix_full() -> Optional[pd.DataFrame]:
    try:
        with _no_proxy():
            df = ak_index_option_50etf_qvix()
    except Exception as e:
        logger.warning(f"fear_greed_truth: QVIX 拉取失败: {e}")
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["qvix_50"] = pd.to_numeric(df["close"], errors="coerce")
    return df[["date", "qvix_50"]].dropna().sort_values("date").reset_index(drop=True)


def build_truth_series(limit_down: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """构建长历史 construct-truth 恐惧分序列。

    limit_down: 可选 [date, limit_down_count]；缺失日期广度分量降权。
    返回 [date, close, fear_truth, comp_drawdown, comp_breadth, comp_iv_surge,
          comp_iv_level, breadth_available, regime]。
    """
    sh = fetch_index_daily_tx(SH_COMPOSITE_SYMBOL, days=_LONG_DAYS)
    if sh is None or sh.empty:
        logger.warning("fear_greed_truth: 上证综指日线为空")
        return None
    df = sh.sort_values("date").reset_index(drop=True)[["date", "close"]].copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    roll_max = df["close"].rolling(_DD_WINDOW).max()
    df["drawdown_60"] = (df["close"] - roll_max) / roll_max * 100.0  # ≤0

    ma = df["close"].rolling(_MA_WINDOW).mean()
    df["ma60_dev"] = (df["close"] - ma) / ma * 100.0
    df["mom_20d"] = df["close"].pct_change(_MOM_WIN) * 100.0
    # 体制：均线之上且正动量 → 上涨体制（抑制 IV 类恐惧）
    df["uptrend"] = (df["ma60_dev"] > 0) & (df["mom_20d"] > 0)

    qvix = _fetch_qvix_full()
    if qvix is None:
        logger.warning("fear_greed_truth: QVIX 为空，IV 类分量缺失")
        df["qvix_50"] = np.nan
        df["qvix_chg5"] = np.nan
        df["qvix_pct_252"] = np.nan
    else:
        qvix = qvix.copy()
        qvix["qvix_chg5"] = qvix["qvix_50"].pct_change(_IV_SURGE_WIN) * 100.0
        qvix["qvix_pct_252"] = qvix["qvix_50"].rolling(_Z_WINDOW).rank(pct=True) * 100.0
        df = df.merge(qvix[["date", "qvix_50", "qvix_chg5", "qvix_pct_252"]], on="date", how="left")

    if limit_down is not None:
        df = df.merge(limit_down[["date", "limit_down_count"]], on="date", how="left")
    else:
        df["limit_down_count"] = np.nan

    rows = []
    for _, r in df.iterrows():
        rows.append(_score_row(r))
    out = pd.DataFrame(rows)
    out.insert(0, "date", df["date"].values)
    out.insert(1, "close", df["close"].values)
    return out


def _score_row(r: pd.Series) -> dict:
    dd = r.get("drawdown_60")
    uptrend = bool(r.get("uptrend")) if pd.notna(r.get("uptrend")) else False
    iv_surge = r.get("qvix_chg5")
    iv_pct = r.get("qvix_pct_252")
    ld = r.get("limit_down_count")

    comp_drawdown = _clip01(-float(dd) / _DD_FULL_FEAR_PCT) * 100.0 if pd.notna(dd) else None

    breadth_available = pd.notna(ld) and float(ld) >= 0
    comp_breadth = _clip01(float(ld) / _BREADTH_FULL) * 100.0 if breadth_available else None

    # IV 飙升：上涨体制里打 0.3 折（上涨中 IV 漂升不是恐慌）
    if pd.notna(iv_surge):
        comp_iv_surge = _clip01(float(iv_surge) / _IV_SURGE_FULL) * 100.0
        comp_iv_surge = comp_iv_surge * (0.3 if uptrend else 1.0)
    else:
        comp_iv_surge = None

    # IV 水平：仅下跌体制贡献（上涨体制 → 0）
    if pd.notna(iv_pct) and not uptrend:
        comp_iv_level = float(iv_pct)
    elif pd.notna(iv_pct) and uptrend:
        comp_iv_level = 0.0
    else:
        comp_iv_level = None

    # 加权合成，缺失分量权重按比例分摊到可用分量
    comps = {
        "drawdown": comp_drawdown,
        "breadth": comp_breadth,
        "iv_surge": comp_iv_surge,
        "iv_level": comp_iv_level,
    }
    active = {k: v for k, v in comps.items() if v is not None}
    total_w = sum(_W[k] for k in active)
    if total_w <= 0 or not active:
        fear = 50.0
    else:
        fear = sum(active[k] * _W[k] for k in active) / total_w

    regime = "uptrend" if uptrend else "downtrend"
    return {
        "fear_truth": round(fear, 2),
        "comp_drawdown": None if comp_drawdown is None else round(comp_drawdown, 2),
        "comp_breadth": None if comp_breadth is None else round(comp_breadth, 2),
        "comp_iv_surge": None if comp_iv_surge is None else round(comp_iv_surge, 2),
        "comp_iv_level": None if comp_iv_level is None else round(comp_iv_level, 2),
        "breadth_available": bool(breadth_available),
        "regime": regime,
    }


def latest_truth() -> Optional[dict]:
    """取最新交易日的 construct-truth 恐惧分（盘后推断用）。"""
    df = build_truth_series()
    if df is None or df.empty:
        return None
    row = df.dropna(subset=["fear_truth"]).iloc[-1]
    return {k: (None if pd.isna(row.get(k)) else row.get(k)) for k in row.index}


def truth_score_as_of(date_str: str, limit_down_count: Optional[float] = None,
                      cached: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """取指定日期的 construct-truth 恐惧分（v7.0 live 用，与真相同公式）。

    limit_down_count: 该日真实跌停家数（live 由 fetch_limit_counts 提供）；
                      None 则广度分量降权。
    cached: 可传入 build_truth_series 的结果复用，避免重复拉数据。
    返回 {date, fear_truth, greed_v7, comp_*, regime, breadth_available} 或 None。
    """
    if cached is not None:
        df = cached
    else:
        ld = None
        if limit_down_count is not None:
            ld = pd.DataFrame([{"date": date_str, "limit_down_count": limit_down_count}])
        df = build_truth_series(limit_down=ld)
    if df is None or df.empty:
        return None
    row = df[df["date"] == date_str]
    if row.empty:
        return None
    r = row.iloc[0]
    fear = r.get("fear_truth")
    if pd.isna(fear):
        return None
    out = {"date": date_str, "fear_truth": float(fear), "greed_v7": greed_from_fear(float(fear))}
    for k in ("comp_drawdown", "comp_breadth", "comp_iv_surge", "comp_iv_level",
              "breadth_available", "regime", "close"):
        v = r.get(k)
        out[k] = None if pd.isna(v) else (bool(v) if k == "breadth_available" else v)
    return out


def greed_from_fear(fear: Optional[float]) -> Optional[float]:
    """与 v6.1 fg 同口径（0=极恐,100=极贪）便于对比。"""
    if fear is None or pd.isna(fear):
        return None
    return round(100.0 - float(fear), 2)
