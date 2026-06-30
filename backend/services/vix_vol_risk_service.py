"""VIX 波动率风险预算因子（生产候选）。

输出用于仓位上限/风险预算，不用于买卖方向判断。当前生产候选先采用
稳健性验证最稳定的 QVIX 252日 percentile：越高表示未来 10/20 日实现波动率风险越高。
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.database import get_vix_history
from backend.services.vix2_features import build_core_features

_CACHE_TTL = 1800.0
_CACHE: tuple[float, dict] | None = None


def _risk_level(score: float) -> dict:
    if score >= 80:
        return {
            "level": "very_high",
            "label": "极高波动风险",
            "tone": "danger",
            "suggested_equity_max": 0.3,
            "message": "未来波动率风险处于历史高位，适合作为降低权益仓位或杠杆上限的提示。",
        }
    if score >= 60:
        return {
            "level": "high",
            "label": "偏高波动风险",
            "tone": "warning",
            "suggested_equity_max": 0.6,
            "message": "未来波动率风险偏高，建议控制新增风险暴露并收紧仓位预算。",
        }
    if score <= 20:
        return {
            "level": "very_low",
            "label": "极低波动风险",
            "tone": "success",
            "suggested_equity_max": 1.0,
            "message": "未来波动率风险处于历史低位，但这不代表收益 alpha 或买入信号。",
        }
    if score <= 40:
        return {
            "level": "low",
            "label": "偏低波动风险",
            "tone": "success",
            "suggested_equity_max": 1.0,
            "message": "未来波动率风险偏低，可按原策略仓位预算执行。",
        }
    return {
        "level": "neutral",
        "label": "中性波动风险",
        "tone": "info",
        "suggested_equity_max": 0.8,
        "message": "未来波动率风险处于中性区间，仓位应主要由原策略信号决定。",
    }


def _validation_summary() -> dict:
    return {
        "status": "candidate",
        "not_alpha": True,
        "default_horizon": 20,
        "production_scope": "risk_budget_only",
        "baseline_qvix": {
            "targets": ["上证综指", "沪深300"],
            "horizons_passed": [10, 20],
            "horizon_failed": [60],
            "sh_h20_rank_ic": 0.3369,
            "sh_h20_block_positive_frac": 1.0,
            "sh_h20_top_bottom_vol_spread_pct": 3.69,
            "hs300_h20_rank_ic": 0.3498,
            "hs300_h20_block_positive_frac": 1.0,
            "hs300_h20_top_bottom_vol_spread_pct": 4.05,
        },
        "core_xmkt_linear_research": {
            "status": "research_validated_not_served_live_yet",
            "reason": "需要离线训练/落盘后再作为线上模型；当前 API 先使用更稳定且可解释的 QVIX percentile 基线。",
            "sh_h20_rank_ic": 0.1898,
            "sh_h20_block_positive_frac": 1.0,
            "sh_h20_10bps_sharpe": 0.64,
            "sh_h20_10bps_buy_hold_sharpe": 0.40,
        },
        "caveat": "这是未来波动率风险提示和仓位上限参考，不是买入、卖出或收益预测信号。",
    }


def _latest_score_from_vix_history() -> Optional[dict]:
    rows = get_vix_history(365)
    if len(rows) < 120:
        return None
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    source_col = "vix"
    if source_col not in df.columns:
        return None
    df[source_col] = pd.to_numeric(df[source_col], errors="coerce")
    valid = df.dropna(subset=[source_col]).copy()
    if len(valid) < 120:
        return None
    row = valid.iloc[-1]
    recent = valid.tail(252)
    score = float((recent[source_col] <= row[source_col]).mean() * 100)
    level = _risk_level(score)
    return {
        "date": str(row["date"]),
        "score": round(score, 2),
        "qvix_50": round(float(row[source_col]), 2),
        "qvix_50_z": None if pd.isna(row.get("vix_zscore")) else round(float(row["vix_zscore"]), 3),
        "qvix_percentile_window": int(len(recent)),
        "data_source": "vix_history.vix",
        "risk_level": level,
        "position_rule": _position_rule(),
        "validation": _validation_summary(),
    }


def _position_rule() -> dict:
    return {
        "name": "q60_40_baseline",
        "high_risk_threshold": 60,
        "low_risk_threshold": 40,
        "high_risk_equity_max": 0.6,
        "very_high_risk_equity_max": 0.3,
        "neutral_equity_max": 0.8,
        "low_risk_equity_max": 1.0,
    }


def _latest_score_from_core_features() -> Optional[dict]:
    df = build_core_features()
    if df is None or df.empty:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    df["qvix_pct_252"] = df["qvix_50"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    valid = df.dropna(subset=["qvix_50", "qvix_pct_252"])
    if valid.empty:
        return None
    row = valid.iloc[-1]
    score = float(row["qvix_pct_252"])
    level = _risk_level(score)
    recent = valid.tail(252)
    return {
        "date": str(row["date"]),
        "score": round(score, 2),
        "qvix_50": round(float(row["qvix_50"]), 2),
        "qvix_50_z": None if pd.isna(row.get("qvix_50_z")) else round(float(row["qvix_50_z"]), 3),
        "qvix_percentile_window": int(len(recent)),
        "data_source": "vix2_core_features.qvix_50",
        "risk_level": level,
        "position_rule": _position_rule(),
        "validation": _validation_summary(),
    }


def get_vix_vol_risk_api(force: bool = False) -> dict:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]
    latest = _latest_score_from_vix_history() or _latest_score_from_core_features()
    if latest is None:
        payload = {
            "status": "insufficient_data",
            "message": "缺少足够 QVIX 长历史，暂不能计算波动率风险因子。",
            "validation": _validation_summary(),
        }
    else:
        payload = {
            "status": "ok",
            "factor": "vix_vol_risk_score",
            "orientation": "higher_score_means_higher_future_volatility_risk",
            "latest": latest,
        }
    _CACHE = (now, payload)
    return payload
