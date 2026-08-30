"""QVIX 当前值相对过去窗口的位置（实验性只读统计）。

分数仅表示当前 QVIX 在 trailing window 内的经验分位，不预测未来波动，
也不提供仓位、杠杆、买卖或风险预算动作建议。
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
            "label": "当前 QVIX 历史分位极高",
            "tone": "danger",
            "message": "当前 QVIX 高于过去窗口中的大多数观测值。",
        }
    if score >= 60:
        return {
            "level": "high",
            "label": "当前 QVIX 历史分位偏高",
            "tone": "warning",
            "message": "当前 QVIX 位于过去窗口的较高分位。",
        }
    if score <= 20:
        return {
            "level": "very_low",
            "label": "当前 QVIX 历史分位极低",
            "tone": "success",
            "message": "当前 QVIX 低于过去窗口中的大多数观测值。",
        }
    if score <= 40:
        return {
            "level": "low",
            "label": "当前 QVIX 历史分位偏低",
            "tone": "success",
            "message": "当前 QVIX 位于过去窗口的较低分位。",
        }
    return {
        "level": "neutral",
        "label": "当前 QVIX 历史分位居中",
        "tone": "info",
        "message": "当前 QVIX 位于过去窗口的中部分位。",
    }


def _validation_summary() -> dict:
    return {
        "status": "experimental",
        "evidence_status": "legacy_evidence_not_independently_revalidated",
        "not_a_forecast": True,
        "not_position_advice": True,
        "caveat": "该分位只描述当前值相对过去窗口的位置，不预测未来波动，也不构成仓位或买卖建议。",
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
        "validation": _validation_summary(),
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
            "factor": "qvix_trailing_percentile",
            "orientation": "current_value_relative_to_trailing_window",
            "message": "缺少足够 QVIX 历史，暂不能计算当前值的 trailing percentile。",
            "validation": _validation_summary(),
        }
    else:
        payload = {
            "status": "ok",
            "factor": "qvix_trailing_percentile",
            "orientation": "higher_score_means_higher_current_qvix_relative_to_trailing_window",
            "not_a_forecast": True,
            "not_position_advice": True,
            "latest": latest,
        }
    _CACHE = (now, payload)
    return payload
