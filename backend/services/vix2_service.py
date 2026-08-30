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
    upsert_vix2_truth, get_vix2_truth_scores_asc, update_vix2_truth_percentile,
)
from backend.services.vix2_features import (
    CORE_FEATURES, build_core_features, latest_feature_row,
)
from backend.services.vix2_model import (
    load_model, predict_score, get_model_meta,
    load_truth_model, predict_truth_score, train_truth_at_cutoff,
    get_walkforward_meta, save_walkforward_meta,
)
from backend.services.vix_service import classify_by_percentile

logger = logging.getLogger(__name__)


def classify_fear_percentile(percentile: float) -> str:
    """按恐惧分百分位解释状态：百分位越高，恐惧越强。"""
    if percentile >= 90:
        return "极度恐慌"
    if percentile >= 70:
        return "恐慌"
    if percentile >= 30:
        return "中性"
    if percentile >= 10:
        return "平静"
    return "极度平静"


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


def recompute_vix2_truth_percentiles(window: int = 252) -> dict:
    """全表重算 truth_percentile（point-in-time，纯 DB）。返回 {"updated": N}。"""
    scores = get_vix2_truth_scores_asc()
    updated = 0
    for i, (d, score) in enumerate(scores):
        start = max(0, i + 1 - window)
        hist = [s for _, s in scores[start:i + 1]]
        if len(hist) < 5:
            pct = 50.0
        else:
            below = sum(1 for v in hist if v <= score)
            pct = round(below / len(hist) * 100, 1)
        update_vix2_truth_percentile(d, pct, classify_fear_percentile(pct))
        updated += 1
    logger.info(f"recompute_vix2_truth_percentiles: 重算 {updated} 行")
    return {"updated": updated}


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


def backfill_vix2_walkforward(days: int = 0, block_size: int = 60,
                              skip_existing: bool = False, task_runner=None,
                              cv_gap: int = 5, min_train_samples: int = 200,
                              n_splits: int = 5) -> dict:
    """按时间顺序回填 VIX2 同日构造分状态估计。

    `days` 只限制输出窗口；训练始终保留输出日前的全部可用历史。每个块的模型只
    使用块首日之前的样本，交叉验证保留至少五个交易日的 gap。这里拟合的是同日
    构造状态，不是未来收益或交易信号。
    """
    from backend.services.vix2_truth_labels import build_truth_labeled_dataset
    import numpy as np

    def _ms(msg):
        logger.info(msg)
        if task_runner:
            task_runner.milestone(msg)

    if days < 0:
        raise ValueError("days 不能小于 0")
    if not 1 <= block_size <= 252:
        raise ValueError("block_size 必须在 1 到 252 之间")
    if cv_gap < 5 or cv_gap > 60:
        raise ValueError("cv_gap 必须在 5 到 60 个交易日之间")
    if min_train_samples < 40:
        raise ValueError("min_train_samples 必须至少为 40")
    if not 2 <= n_splits <= 10:
        raise ValueError("n_splits 必须在 2 到 10 之间")

    _ms("构建核心因子 + 同日构造状态标签数据集…")
    ds = build_truth_labeled_dataset()
    if ds is None or len(ds) <= min_train_samples:
        raise RuntimeError(f"walk-forward 样本不足: {0 if ds is None else len(ds)}")
    ds = ds.sort_values("date").reset_index(drop=True)
    n = len(ds)
    output_start = max(min_train_samples, n - days) if days else min_train_samples
    output_total = n - output_start
    if task_runner:
        task_runner.set_total(output_total)

    existing = set()
    if skip_existing:
        existing = {d for d, _ in get_vix2_truth_scores_asc()}

    version_tag = f"vix2-wf-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}"
    written = 0
    skipped = 0
    model_errors = []
    baseline_errors = []
    block_audit = []
    block_wins = 0
    i = output_start
    while i < n:
        cutoff = i
        block_end = min(i + block_size, n)
        trained = train_truth_at_cutoff(
            ds, cutoff, n_splits=n_splits, cv_gap=cv_gap,
            min_train_samples=min_train_samples,
        )
        if trained is None:
            i = block_end
            continue
        pipe = trained["pipe"]
        train_cutoff = trained["train_cutoff"]
        block_df = ds.iloc[i:block_end]
        first_prediction_date = str(block_df.iloc[0]["date"])
        if not train_cutoff < first_prediction_date:
            raise RuntimeError(
                f"时间边界审计失败: train_cutoff={train_cutoff}, "
                f"prediction_date={first_prediction_date}"
            )
        X_block = block_df[CORE_FEATURES].to_numpy(dtype=float)
        preds = np.clip(pipe.predict(X_block), 0, 100)
        actual = block_df["fear_truth"].to_numpy(dtype=float)
        baseline = ds.iloc[i - 1:block_end - 1]["fear_truth"].to_numpy(dtype=float)
        block_model_errors = np.abs(preds - actual)
        block_baseline_errors = np.abs(baseline - actual)
        model_errors.extend(block_model_errors.tolist())
        baseline_errors.extend(block_baseline_errors.tolist())
        if float(block_model_errors.mean()) < float(block_baseline_errors.mean()):
            block_wins += 1
        block_audit.append({
            "prediction_start": first_prediction_date,
            "prediction_end": str(block_df.iloc[-1]["date"]),
            "train_cutoff": train_cutoff,
            "n_train": trained["n_train"],
            "cv_gap": trained["cv_gap"],
            "cv_folds": trained["cv_folds"],
        })
        for j, (_, row) in enumerate(block_df.iterrows()):
            d = row["date"]
            if d in existing:
                skipped += 1
                continue
            upsert_vix2_truth(d, round(float(preds[j]), 2), version_tag, train_cutoff)
            written += 1
        if task_runner:
            task_runner.check_cancelled()
            task_runner.set_current(f"walk-forward {block_df.iloc[0]['date']}~{block_df.iloc[-1]['date']}")
            task_runner.progress(block_end - output_start)
        i = block_end

    if not model_errors:
        raise RuntimeError("没有生成可验证的时间顺序状态估计")
    model_mae = float(np.mean(model_errors))
    baseline_mae = float(np.mean(baseline_errors))
    block_win_rate = block_wins / len(block_audit)
    stable_baseline_improvement = (
        len(block_audit) >= 3
        and model_mae <= baseline_mae * 0.98
        and block_win_rate >= 0.60
    )
    validation_status = (
        "state_fit_outperformed_baseline"
        if stable_baseline_improvement else "no_robust_edge"
    )

    _ms("重算构造分拟合的滚动百分位…")
    rc = recompute_vix2_truth_percentiles()
    result = {
        "run_version": version_tag,
        "written": written,
        "skipped": skipped,
        "dataset_samples": n,
        "output_samples": output_total,
        "requested_days": days,
        "output_start_date": str(ds.iloc[output_start]["date"]),
        "output_end_date": str(ds.iloc[-1]["date"]),
        "min_train_samples": min_train_samples,
        "block_size": block_size,
        "cv_gap": cv_gap,
        "model_oos_mae": round(model_mae, 4),
        "baseline_lag1_oos_mae": round(baseline_mae, 4),
        "block_baseline_win_rate": round(block_win_rate, 4),
        "validation_status": validation_status,
        "target_definition": "同日构造恐惧状态分（0-100），不是未来收益标签",
        "target_horizon": "same_day",
        "target_components": ["price_drawdown", "iv_surge", "iv_level_gate"],
        "breadth_available": False,
        "breadth_component_used": False,
        "predictive_claim": False,
        "baseline_definition": "前一交易日构造分（lag-1 persistence）",
        "block_audit": block_audit,
        **rc,
    }
    save_walkforward_meta(result)
    if task_runner:
        task_runner.complete(result=result)
    _ms(
        f"时间顺序状态估计完成: 写入 {written}/{output_total}，跳过 {skipped}，"
        f"模型 MAE={model_mae:.3f}，lag-1 MAE={baseline_mae:.3f}，"
        f"验证状态={validation_status}"
    )
    return result


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
        "truth_prediction_mode": "full_sample_same_day_state_fit",
        "truth_prediction_warning": "实验性同日状态拟合，不是未来收益预测或交易信号",
        "walkforward_validation": get_walkforward_meta(),
    }


def get_vix2_history_api(days: int = 365) -> list[dict]:
    return get_vix2_history(days=days)
