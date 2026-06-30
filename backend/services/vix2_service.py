"""VIX 2.0 — 推断 / 回填 / 百分位重算的编排层。

把 features → model → vix2_history 串起来，并复用 v6.1 的
classify_by_percentile 做 regime 分级（口径一致：低分=恐慌=机会）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.core.database import (
    upsert_vix2_history, get_vix2_latest, get_vix2_history,
    get_vix2_scores_asc, update_vix2_percentile,
)
from backend.services.vix2_features import (
    CORE_FEATURES, build_core_features, latest_feature_row,
)
from backend.services.vix2_model import (
    load_model, predict_score, get_model_meta,
    load_truth_model, predict_truth_score,
)
from backend.services.vix_service import classify_by_percentile

logger = logging.getLogger(__name__)


def compute_and_store_vix2(date_str: Optional[str] = None,
                           cached_features: Optional[pd.DataFrame] = None,
                           pipe=None, meta=None) -> Optional[dict]:
    """计算某日 VIX 2.0 分数并写库（不含百分位，回填后统一重算）。

    返回写入的快照 dict；模型未训练 / 因子缺失时返回 None。
    """
    if pipe is None or meta is None:
        pipe, meta = load_model()
    if pipe is None:
        logger.warning("compute_and_store_vix2: 模型未训练，跳过")
        return None

    frow = latest_feature_row(as_of=date_str, cached=cached_features)
    if frow is None:
        logger.info(f"VIX2 {date_str}: 因子缺失，跳过")
        return None

    pred = predict_score(frow, pipe=pipe, meta=meta)
    if pred is None:
        return None

    feats = {k: frow[k] for k in CORE_FEATURES}
    payload = {
        "p_up": pred["p_up"],
        "score": pred["score"],
        "model_version": pred["model_version"],
        "features_json": json.dumps(feats, ensure_ascii=False),
    }
    upsert_vix2_history(frow["date"], payload)
    return {"date": frow["date"], **payload}


def recompute_vix2_percentiles(window: int = 252) -> dict:
    """全表重算 percentile + regime（point-in-time，纯 DB）。返回 {"updated": N}。"""
    scores = get_vix2_scores_asc()
    updated = 0
    for i, (d, score) in enumerate(scores):
        start = max(0, i + 1 - window)
        hist = [s for _, s in scores[start:i + 1]]
        if len(hist) < 20:
            pct = 50.0
        else:
            below = sum(1 for v in hist if v <= score)
            pct = round(below / len(hist) * 100, 1)
        update_vix2_percentile(d, pct, classify_by_percentile(pct))
        updated += 1
    logger.info(f"recompute_vix2_percentiles: 重算 {updated} 行")
    return {"updated": updated}


def backfill_vix2(days: int = 365, skip_existing: bool = False, task_runner=None) -> dict:
    """用当前模型回填历史 score。

    一次性构建全历史因子矩阵，逐日推断写库，最后统一重算百分位。
    task_runner：可选 TaskRunner，用于进度/取消。
    """
    def _ms(msg):
        logger.info(msg)
        if task_runner:
            task_runner.milestone(msg)

    pipe, meta = load_model()
    if pipe is None:
        raise RuntimeError("模型未训练，无法回填（先 POST /api/vix2/train）")

    _ms("构建长历史核心因子矩阵…")
    feats = build_core_features()
    if feats is None or feats.empty:
        raise RuntimeError("特征构建失败")

    # 仅保留核心因子齐全的行
    valid = feats.dropna(subset=CORE_FEATURES).sort_values("date").reset_index(drop=True)
    if days and days > 0:
        valid = valid.tail(days).reset_index(drop=True)
    total = len(valid)
    if task_runner:
        task_runner.set_total(total)
    _ms(f"开始回填 {total} 个交易日…")

    existing = set()
    if skip_existing:
        existing = {r["date"] for r in get_vix2_history(days=100000)}

    import numpy as np
    X = valid[CORE_FEATURES].to_numpy(dtype=float)
    p_up_all = pipe.predict_proba(X)[:, 1]
    written = 0
    for i, row in valid.iterrows():
        if task_runner:
            task_runner.check_cancelled()
        d = row["date"]
        if skip_existing and d in existing:
            continue
        p_up = float(p_up_all[i])
        feats_row = {k: float(row[k]) for k in CORE_FEATURES}
        upsert_vix2_history(d, {
            "p_up": round(p_up, 4),
            "score": round((1 - p_up) * 100, 2),
            "model_version": meta.get("model_version"),
            "features_json": json.dumps(feats_row, ensure_ascii=False),
        })
        written += 1
        if task_runner:
            task_runner.progress(i + 1)

    _ms("重算滚动百分位…")
    rc = recompute_vix2_percentiles()
    result = {"written": written, "total": total, **rc}
    if task_runner:
        task_runner.complete(result=result)
    _ms(f"回填完成: 写入 {written}/{total}，百分位重算 {rc['updated']} 行")
    return result


# ─────────────────────────────────────────────────────────────────
# API 视图辅助
# ─────────────────────────────────────────────────────────────────

def get_vix2_latest_api() -> dict:
    latest = get_vix2_latest()
    meta = get_model_meta()
    # 重定向版（construct-truth 情绪因子）单日推断；与 v6.1/v7.0 对照
    truth_pred = None
    tpipe, tmeta = load_truth_model()
    if tpipe is not None:
        # latest_feature_row 严格要求所有因子非空；非交易日/数据未更新时回退到最近完整日
        frow = latest_feature_row()
        if frow is None:
            feats_df = build_core_features()
            if feats_df is not None and not feats_df.empty:
                from backend.services.vix2_features import CORE_FEATURES
                valid = feats_df.dropna(subset=CORE_FEATURES)
                if not valid.empty:
                    last = valid.iloc[-1]
                    frow = {"date": last["date"], **{f: float(last[f]) for f in CORE_FEATURES}}
        if frow is not None:
            truth_pred = predict_truth_score(frow, pipe=tpipe, meta=tmeta)
    return {
        "latest": latest,
        "model_version": (meta or {}).get("model_version"),
        "model_trained": meta is not None,
        "truth_model_trained": tpipe is not None,
        "truth_prediction": truth_pred,
    }


def get_vix2_history_api(days: int = 365) -> list[dict]:
    return get_vix2_history(days=days)
