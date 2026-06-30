"""VIX 2.0 — construct-truth 情绪标签（重定向，2026-06-29）。

VIX2 原三隘栏标签是“未来涨跌方向”（收益 alpha 目标），已证明失败，且把 v6.1
锚定 IV 水平的坑在 ML 里重踩。重定向：训练目标改为回归逼近 construct-truth
恐惧分（fear_truth ∈ [0,100]，越大越恐），VIX2 分数即“学习到的真实情绪状态估计”。

标签来源：backend.services.fear_greed_truth.build_truth_series 的 fear_truth 列，
按 date 与 core features 对齐。fear_truth 用价格回撤+广度+IV飙升+IV水平门控构造，
显式去耦 IV 水平，避免 v6.1 的系统性偏差。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backend.services.fear_greed_truth import build_truth_series

logger = logging.getLogger(__name__)


def build_truth_labeled_dataset(features: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """给特征矩阵附加 construct-truth 回归标签。

    入参 features：build_core_features 的输出（含 date, close, CORE_FEATURES）。
    追加列 'fear_truth'（回归目标，0-100）。丢弃 fear_truth 或任一核心因子缺失的行。
    """
    from backend.services.vix2_features import CORE_FEATURES, build_core_features

    feats = features if features is not None else build_core_features()
    if feats is None or feats.empty:
        return None

    truth = build_truth_series()
    if truth is None or truth.empty:
        logger.warning("truth 数据集为空，无法构建重定向标签")
        return None

    df = feats.sort_values("date").reset_index(drop=True).merge(
        truth[["date", "fear_truth"]], on="date", how="left"
    )
    df = df.dropna(subset=["fear_truth"] + CORE_FEATURES).reset_index(drop=True)
    if df.empty:
        return None
    df["fear_truth"] = df["fear_truth"].astype(float)
    return df
