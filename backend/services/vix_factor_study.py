"""VIX 因子事件研究（只读）：把恐慌/贪婪状态转成可验证的交易因子候选。

不修改 vix_history，不参与每日 VIX 计算链。用于回答：
  - 哪些 VIX/综合位置状态之后的 5/10/20/60 日收益更好？
  - 极度恐慌是否真的具备反转价值？
  - 贪婪区是否适合降仓？
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.database import get_vix_history
from backend.data.vix_sources import SH_COMPOSITE_SYMBOL, fetch_index_daily_tx

_HORIZONS = (5, 10, 20, 60)
_MIN_RULE_N = 30
_CACHE_TTL = 1800.0
_CACHE: dict[int, tuple[float, dict]] = {}


@dataclass(frozen=True)
class Bucket:
    key: str
    label: str
    lo: float
    hi: float


_BUCKETS = (
    Bucket("extreme_fear", "极度恐慌", 0, 10),
    Bucket("fear", "恐慌", 10, 30),
    Bucket("neutral", "中性", 30, 70),
    Bucket("greed", "贪婪", 70, 90),
    Bucket("extreme_greed", "极度贪婪", 90, 100.000001),
)


def _safe_float(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _bucket_key(percentile: float) -> Optional[str]:
    if percentile is None or pd.isna(percentile):
        return None
    for b in _BUCKETS:
        if b.lo <= percentile < b.hi:
            return b.key
    return None


def _future_max_drawdown(closes: np.ndarray, start: int, horizon: int) -> Optional[float]:
    entry = closes[start]
    if not np.isfinite(entry) or entry <= 0:
        return None
    end = min(start + horizon, len(closes) - 1)
    if end <= start:
        return None
    path = closes[start + 1:end + 1]
    if len(path) == 0:
        return None
    trough = float(np.nanmin(path))
    if not np.isfinite(trough):
        return None
    return (trough / entry - 1) * 100


def _metric_summary(df: pd.DataFrame, horizon: int) -> dict:
    ret_col = f"fwd_ret_{horizon}d"
    dd_col = f"fwd_mdd_{horizon}d"
    vals = df[ret_col].dropna().astype(float)
    dds = df[dd_col].dropna().astype(float)
    n = int(len(vals))
    if n == 0:
        return {
            "n": 0, "avg_ret": None, "median_ret": None, "win_rate": None,
            "avg_mdd": None, "worst_mdd": None, "ret_mdd_ratio": None,
        }
    avg_ret = float(vals.mean())
    avg_mdd = float(dds.mean()) if len(dds) else None
    denom = abs(avg_mdd) if avg_mdd is not None and abs(avg_mdd) > 1e-9 else None
    return {
        "n": n,
        "avg_ret": round(avg_ret, 2),
        "median_ret": round(float(vals.median()), 2),
        "win_rate": round(float((vals > 0).mean()) * 100, 1),
        "avg_mdd": round(avg_mdd, 2) if avg_mdd is not None else None,
        "worst_mdd": round(float(dds.min()), 2) if len(dds) else None,
        "ret_mdd_ratio": round(avg_ret / denom, 2) if denom else None,
    }


def _rule_pass(summary_20: dict, summary_60: dict, direction: str = "long") -> tuple[bool, list[str]]:
    reasons = []
    n = int(summary_20.get("n") or 0)
    if n < _MIN_RULE_N:
        reasons.append(f"样本不足 {n}/{_MIN_RULE_N}")
    if direction == "long":
        if (summary_20.get("avg_ret") or -999) <= 0:
            reasons.append("20日均值收益不为正")
        if (summary_60.get("avg_ret") or -999) <= 0:
            reasons.append("60日均值收益不为正")
        if (summary_20.get("win_rate") or 0) <= 55:
            reasons.append("20日胜率未超过55%")
        if (summary_20.get("ret_mdd_ratio") or 0) <= 0.8:
            reasons.append("收益/回撤比未超过0.8")
    else:
        if (summary_20.get("avg_ret") or 999) >= 0:
            reasons.append("20日后并未体现风险收益为负")
        if (summary_20.get("win_rate") or 100) >= 45:
            reasons.append("下跌概率不足")
    return len(reasons) == 0, reasons


def _evaluate_rules(df: pd.DataFrame) -> list[dict]:
    rules = [
        {
            "key": "panic_reversal",
            "name": "极度恐慌反转候选",
            "intent": "分批加仓候选",
            "direction": "long",
            "mask": (df["bucket"] == "extreme_fear") & (df["spot_mom_5d"].fillna(0) >= -3),
            "logic": "综合百分位≤10，且5日动量未继续大幅恶化",
        },
        {
            "key": "fear_accumulate",
            "name": "恐慌区左侧布局候选",
            "intent": "小仓位试探候选",
            "direction": "long",
            "mask": (df["bucket"] == "fear") & (df["spot_mom_20d"].fillna(-999) > -8),
            "logic": "综合百分位10-30，且20日动量没有极端破坏",
        },
        {
            "key": "greed_reduce",
            "name": "贪婪区降仓候选",
            "intent": "止盈/降风险候选",
            "direction": "short_risk",
            "mask": df["bucket"].isin(["greed", "extreme_greed"]) & (df["spot_ma60_dev"].fillna(0) > 0),
            "logic": "综合百分位≥70，且价格高于60日均线",
        },
    ]
    out = []
    for r in rules:
        sub = df[r["mask"]].copy()
        horizons = {str(h): _metric_summary(sub, h) for h in _HORIZONS}
        passed, reasons = _rule_pass(horizons["20"], horizons["60"], r["direction"])
        out.append({
            "key": r["key"],
            "name": r["name"],
            "intent": r["intent"],
            "logic": r["logic"],
            "passed": passed,
            "verdict": "可进入回测" if passed else "仅观察，未达交易因子门槛",
            "failed_reasons": reasons,
            "metrics": horizons,
        })
    return out


def _build_dataset(days: int) -> pd.DataFrame:
    vix_rows = get_vix_history(days)
    if not vix_rows:
        return pd.DataFrame()
    vix = pd.DataFrame(vix_rows)
    vix["date"] = pd.to_datetime(vix["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    keep = [
        "date", "composite_percentile", "composite_score", "fear_greed",
        "vix", "vix_zscore", "spot_ma60_dev", "spot_mom_5d", "spot_mom_20d",
        "spot_new_high_ratio",
    ]
    for c in keep:
        if c not in vix.columns:
            vix[c] = np.nan
    vix = vix[keep].dropna(subset=["date"]).sort_values("date")

    px = fetch_index_daily_tx(SH_COMPOSITE_SYMBOL, days=days + 120)
    if px is None or px.empty:
        return pd.DataFrame()
    px = px[["date", "close"]].copy().sort_values("date").reset_index(drop=True)
    px["close"] = pd.to_numeric(px["close"], errors="coerce")

    df = vix.merge(px, on="date", how="inner").sort_values("date").reset_index(drop=True)
    closes = df["close"].to_numpy(float)
    for h in _HORIZONS:
        fwd = np.full(len(df), np.nan)
        mdd = np.full(len(df), np.nan)
        for i in range(len(df)):
            j = i + h
            if j < len(df) and np.isfinite(closes[i]) and closes[i] > 0 and np.isfinite(closes[j]):
                fwd[i] = (closes[j] / closes[i] - 1) * 100
                dd = _future_max_drawdown(closes, i, h)
                if dd is not None:
                    mdd[i] = dd
        df[f"fwd_ret_{h}d"] = fwd
        df[f"fwd_mdd_{h}d"] = mdd

    df["bucket"] = df["composite_percentile"].apply(_bucket_key)
    return df.dropna(subset=["bucket"]).reset_index(drop=True)


def _run_vix_factor_study_uncached(days: int = 365) -> dict:
    """返回 VIX 因子事件研究结果。days 为最近 N 个交易样本。"""
    days = max(120, min(int(days or 365), 1200))
    df = _build_dataset(days)
    if df.empty:
        return {
            "days": days,
            "n": 0,
            "status": "no_data",
            "message": "VIX 或指数历史数据不足，无法进行事件研究。",
            "buckets": [],
            "rules": [],
            "current": None,
        }

    bucket_rows = []
    for b in _BUCKETS:
        sub = df[df["bucket"] == b.key]
        bucket_rows.append({
            "key": b.key,
            "label": b.label,
            "range": f"{int(b.lo)}-{int(min(b.hi, 100))}%",
            "metrics": {str(h): _metric_summary(sub, h) for h in _HORIZONS},
        })

    rules = _evaluate_rules(df)
    current_row = df.iloc[-1]
    current_bucket = next((b for b in _BUCKETS if b.key == current_row["bucket"]), None)
    best_long = None
    candidates = [r for r in rules if r["intent"].startswith(("分批", "小仓位"))]
    if candidates:
        best_long = max(candidates, key=lambda r: r["metrics"]["20"].get("avg_ret") or -999)

    return {
        "days": days,
        "n": int(len(df)),
        "status": "ok",
        "horizons": list(_HORIZONS),
        "current": {
            "date": current_row["date"],
            "bucket": current_row["bucket"],
            "bucket_label": current_bucket.label if current_bucket else current_row["bucket"],
            "composite_percentile": _safe_float(current_row.get("composite_percentile")),
            "composite_score": _safe_float(current_row.get("composite_score")),
            "fear_greed": _safe_float(current_row.get("fear_greed")),
        },
        "summary": {
            "best_long_rule": best_long["name"] if best_long else None,
            "best_long_20d_avg": best_long["metrics"]["20"].get("avg_ret") if best_long else None,
            "production_ready_rules": [r["name"] for r in rules if r["passed"]],
        },
        "buckets": bucket_rows,
        "rules": rules,
    }


def run_vix_factor_study(days: int = 365) -> dict:
    """带短 TTL 缓存的只读事件研究入口，避免页面刷新反复拉指数全量历史。"""
    days = max(120, min(int(days or 365), 1200))
    now = time.time()
    cached = _CACHE.get(days)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    result = _run_vix_factor_study_uncached(days)
    _CACHE[days] = (now, result)
    return result
