"""VIX 2.0 — 模型层：训练 / 时间序列 CV / 落盘 / 加载 / 单日推断。

设计见 docs/vix2-ml-design.md §3。Pipeline:
  StandardScaler → LogisticRegression(penalty='l2', class_weight='balanced',
                                       C=TimeSeriesSplit 网格搜索, ROC-AUC 选优)

落盘两份：
  data/models/vix2_<version>.joblib  — sklearn Pipeline（推断用）
  data/models/vix2_<version>.json    — 元数据 + 可解释权重（前端权重条形图用）
另维护 data/models/vix2_latest.json 指针，记录当前生效 version。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from backend.services.vix2_features import CORE_FEATURES, build_core_features
from backend.services.vix2_labels import build_labeled_dataset

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
_LATEST_PTR = _MODEL_DIR / "vix2_latest.json"
_WALKFORWARD_META_PATH = _MODEL_DIR / "vix2_walkforward_latest.json"

DEFAULT_LABEL_PARAMS = {"pt": 0.05, "sl": 0.05, "horizon": 20, "rv_scale": True}
_OOS_TAIL = 252          # 最近 N 个样本留作纯样本外评估
_RANDOM_SEED = 42


def _ensure_dir() -> None:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────
# 训练
# ─────────────────────────────────────────────────────────────────

def train_model(
    label_params: Optional[dict] = None,
    feature_set: str = "core",
    c_grid: Optional[list] = None,
    n_splits: int = 5,
    cv_gap: int = 5,
    save: bool = True,
    progress=None,
    features: Optional[pd.DataFrame] = None,
) -> dict:
    """训练 VIX 2.0 模型并（可选）落盘。

    progress：可选回调 progress(msg:str) 用于 TaskRunner.milestone。
    features：可传入预构建的 build_core_features 结果复用（扫参时避免重复拉数据）。
    返回元数据 dict（含 weights / cv_auc / oos_auc / 落盘路径）。
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    import joblib

    def _say(msg: str):
        logger.info(msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    label_params = {**DEFAULT_LABEL_PARAMS, **(label_params or {})}
    c_grid = c_grid or [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]
    label_horizon = label_params["horizon"]
    if isinstance(label_horizon, bool) or not isinstance(label_horizon, (int, np.integer)):
        raise ValueError("label horizon 必须是整数")
    label_horizon = int(label_horizon)
    if not 1 <= label_horizon <= 60:
        raise ValueError("label horizon 必须在 1 到 60 个交易日之间")
    if isinstance(cv_gap, bool) or not isinstance(cv_gap, (int, np.integer)):
        raise ValueError("cv_gap 必须是整数")
    requested_cv_gap = int(cv_gap)
    if not 5 <= requested_cv_gap <= 60:
        raise ValueError("cv_gap 必须在 5 到 60 个交易日之间")
    effective_cv_gap = max(requested_cv_gap, label_horizon)

    if features is not None:
        feats = features
    else:
        _say("构建长历史核心因子矩阵…")
        feats = build_core_features()
    if feats is None or feats.empty:
        raise RuntimeError("特征构建失败（数据源为空）")

    _say(f"三隘栏打标签 (pt={label_params['pt']} sl={label_params['sl']} H={label_params['horizon']})…")
    ds = build_labeled_dataset(feats, **{
        "pt": label_params["pt"], "sl": label_params["sl"],
        "horizon": label_params["horizon"], "rv_scale": label_params["rv_scale"],
    })
    if ds is None or len(ds) < 200:
        raise RuntimeError(f"有效样本不足: {0 if ds is None else len(ds)}")

    ds = ds.sort_values("date").reset_index(drop=True)
    X = ds[CORE_FEATURES].to_numpy(dtype=float)
    y = ds["label"].to_numpy(dtype=int)
    dates = ds["date"].tolist()
    n = len(ds)
    oos_tail = min(_OOS_TAIL, max(40, n // 5))
    split = n - oos_tail
    # Labels look forward by ``label_horizon`` observations. Purge the same
    # effective embargo used by CV so no training label can inspect OOS prices.
    train_end = split - effective_cv_gap
    if train_end <= 0:
        raise RuntimeError("有效样本不足以同时保留 OOS 与标签隔离区")
    X_tr, y_tr = X[:train_end], y[:train_end]
    X_oos, y_oos = X[split:], y[split:]
    _say(
        f"样本 {n}（训练 {train_end} / 隔离 {effective_cv_gap} / "
        f"纯样本外 {oos_tail}），正类占比 {y.mean():.3f}"
    )

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            penalty="l2", class_weight="balanced",
            max_iter=2000, random_state=_RANDOM_SEED,
        )),
    ])
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=effective_cv_gap)
    cv_splits = list(tscv.split(X_tr))
    fold_audit = [{
        "fold": fold_number,
        "train_end_index": int(train_idx[-1]),
        "test_start_index": int(test_idx[0]),
        "gap_observations": int(test_idx[0] - train_idx[-1] - 1),
    } for fold_number, (train_idx, test_idx) in enumerate(cv_splits, start=1)]
    _say(
        f"TimeSeriesSplit({n_splits}, requested_gap={requested_cv_gap}, "
        f"effective_gap={effective_cv_gap}) 网格搜索 C={c_grid}（ROC-AUC）…"
    )
    gs = GridSearchCV(
        pipe, {"clf__C": c_grid}, scoring="roc_auc",
        cv=cv_splits, n_jobs=-1, refit=True,
    )
    gs.fit(X_tr, y_tr)
    best = gs.best_estimator_
    cv_auc = float(gs.best_score_)
    best_c = float(gs.best_params_["clf__C"])
    _say(f"最优 C={best_c}，CV ROC-AUC={cv_auc:.4f}")

    # 纯样本外评估
    oos_auc = None
    if len(np.unique(y_oos)) == 2:
        oos_p = best.predict_proba(X_oos)[:, 1]
        oos_auc = float(roc_auc_score(y_oos, oos_p))
        _say(f"纯样本外 ROC-AUC={oos_auc:.4f}（样本 {len(y_oos)}）")
    else:
        _say("纯样本外仅单一类别，跳过 OOS AUC")

    # 用全量数据重训最终模型（含 OOS 段），保留最优 C
    final = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            penalty="l2", C=best_c, class_weight="balanced",
            max_iter=2000, random_state=_RANDOM_SEED,
        )),
    ])
    final.fit(X, y)

    scaler = final.named_steps["scaler"]
    clf = final.named_steps["clf"]
    coefs = clf.coef_[0]
    weights = {f: round(float(w), 4) for f, w in zip(CORE_FEATURES, coefs)}

    version = f"vix2-l2-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "model_version": version,
        "legacy_classifier": True,
        "predictive_claim": False,
        "validation_status": "legacy_no_robust_edge",
        "feature_set": feature_set,
        "features": CORE_FEATURES,
        "trained_at": datetime.now().isoformat(),
        "train_range": [dates[0], dates[-1]],
        "n_samples": n,
        "n_oos": int(oos_tail),
        "n_train_for_oos": int(train_end),
        "label_horizon": label_horizon,
        "requested_cv_gap": requested_cv_gap,
        "cv_gap": effective_cv_gap,
        "cv_folds": fold_audit,
        "oos_boundary": {
            "train_end_index": int(train_end - 1),
            "oos_start_index": int(split),
            "gap_observations": int(split - train_end),
        },
        "pos_rate": round(float(y.mean()), 4),
        "label_params": label_params,
        "best_C": best_c,
        "cv_auc": round(cv_auc, 4),
        "oos_auc": round(oos_auc, 4) if oos_auc is not None else None,
        "weights": weights,
        "intercept": round(float(clf.intercept_[0]), 4),
        "scaler": {
            "mean": [round(float(m), 6) for m in scaler.mean_],
            "scale": [round(float(s), 6) for s in scaler.scale_],
        },
    }

    if save:
        _ensure_dir()
        joblib.dump(final, _MODEL_DIR / f"{version}.joblib")
        (_MODEL_DIR / f"{version}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _LATEST_PTR.write_text(
            json.dumps({"model_version": version}, ensure_ascii=False), encoding="utf-8"
        )
        _say(f"模型已落盘: {version}")

    return meta


# ─────────────────────────────────────────────────────────────────
# 加载 / 推断
# ─────────────────────────────────────────────────────────────────

def _resolve_version(version: Optional[str]) -> Optional[str]:
    if version:
        return version
    if _LATEST_PTR.exists():
        try:
            return json.loads(_LATEST_PTR.read_text(encoding="utf-8")).get("model_version")
        except Exception:
            return None
    return None


def load_model(version: Optional[str] = None):
    """加载落盘的 Pipeline，返回 (pipeline, meta)。不存在返回 (None, None)。"""
    import joblib

    version = _resolve_version(version)
    if not version:
        return None, None
    jb = _MODEL_DIR / f"{version}.joblib"
    js = _MODEL_DIR / f"{version}.json"
    if not jb.exists() or not js.exists():
        logger.warning(f"load_model: 模型文件缺失 {version}")
        return None, None
    pipe = joblib.load(jb)
    meta = json.loads(js.read_text(encoding="utf-8"))
    return pipe, meta


def get_model_meta(version: Optional[str] = None) -> Optional[dict]:
    """仅读元数据（不加载 joblib），供 /api/vix2/model 画权重条形图。"""
    version = _resolve_version(version)
    if not version:
        return None
    js = _MODEL_DIR / f"{version}.json"
    if not js.exists():
        return None
    return json.loads(js.read_text(encoding="utf-8"))


def predict_score(feature_row: dict, pipe=None, meta=None) -> Optional[dict]:
    """对单日因子向量推断，返回 {p_up, score, model_version}。

    feature_row：latest_feature_row 的输出（含 date + CORE_FEATURES）。
    score = (1 − p_up) × 100，与 v6.1 口径一致（低分=恐慌=机会）。
    """
    if pipe is None or meta is None:
        pipe, meta = load_model()
    if pipe is None:
        return None
    try:
        x = np.array([[feature_row[f] for f in CORE_FEATURES]], dtype=float)
    except (KeyError, TypeError):
        logger.warning("predict_score: feature_row 缺少核心因子")
        return None
    if not np.all(np.isfinite(x)):
        return None
    p_up = float(pipe.predict_proba(x)[0, 1])
    return {
        "p_up": round(p_up, 4),
        "score": round((1 - p_up) * 100, 2),
        "model_version": meta.get("model_version"),
    }


# ─────────────────────────────────────────────────────────────────
# Track B：construct-truth 重定向（回归逼近真实情绪，2026-06-29）
# ─────────────────────────────────────────────────────────────────

_TRUTH_VERSION_PREFIX = "vix2-truth"
_TRUTH_LATEST_PTR = _MODEL_DIR / "vix2_truth_latest.json"


def train_truth_model(
    alpha_grid: Optional[list] = None,
    n_splits: int = 5,
    cv_gap: int = 5,
    save: bool = True,
    progress=None,
    features: Optional[pd.DataFrame] = None,
) -> dict:
    """训练重定向 VIX2：回归逼近 construct-truth 恐惧分（0-100，越大越恐）。

    目标从“未来涨跌方向”改为“真实情绪状态”，避免 v6.1 锚定 IV 水平的坑。
    Pipeline: StandardScaler → Ridge（TimeSeriesSplit 网格 alpha，R2 选优）。
    score = clip(predict, 0, 100)，与 v7.0 fear_truth 同口径便于对照。
    """
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score, mean_absolute_error
    from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    import joblib
    from backend.services.vix2_truth_labels import build_truth_labeled_dataset

    def _say(msg: str):
        logger.info(msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    alpha_grid = alpha_grid or [0.1, 1.0, 3.0, 10.0, 30.0, 100.0]
    _say("构建 construct-truth 重定向标签（fear_truth 回归目标）…")
    ds = build_truth_labeled_dataset(features=features)
    if ds is None or len(ds) < 200:
        raise RuntimeError(f"重定向样本不足: {0 if ds is None else len(ds)}")

    ds = ds.sort_values("date").reset_index(drop=True)
    X = ds[CORE_FEATURES].to_numpy(dtype=float)
    y = ds["fear_truth"].to_numpy(dtype=float)
    dates = ds["date"].tolist()
    n = len(ds)
    oos_tail = min(_OOS_TAIL, max(40, n // 5))
    split = n - oos_tail
    X_tr, y_tr = X[:split], y[:split]
    X_oos, y_oos = X[split:], y[split:]
    _say(f"样本 {n}（训练 {split} / 纯样本外 {oos_tail}），fear_truth 均值 {y.mean():.1f}")

    pipe = Pipeline([("scaler", StandardScaler()), ("reg", Ridge(random_state=_RANDOM_SEED))])
    if cv_gap < 5:
        raise ValueError("cv_gap 必须至少为 5 个交易日")
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=cv_gap)
    _say(f"TimeSeriesSplit({n_splits}, gap={cv_gap}) 网格搜索 alpha={alpha_grid}（R2）…")
    gs = GridSearchCV(pipe, {"reg__alpha": alpha_grid}, scoring="r2",
                      cv=tscv, n_jobs=-1, refit=True)
    gs.fit(X_tr, y_tr)
    best = gs.best_estimator_
    cv_r2 = float(gs.best_score_)
    best_alpha = float(gs.best_params_["reg__alpha"])
    _say(f"最优 alpha={best_alpha}，CV R2={cv_r2:.4f}")

    oos_pred = np.clip(best.predict(X_oos), 0, 100)
    oos_r2 = float(r2_score(y_oos, oos_pred))
    oos_mae = float(mean_absolute_error(y_oos, oos_pred))
    baseline_oos = y[split - 1:n - 1]
    baseline_oos_mae = float(mean_absolute_error(y_oos, baseline_oos))
    oos_rank_ic = float(pd.Series(y_oos).rank().corr(pd.Series(oos_pred).rank()))
    _say(f"纯样本外 R2={oos_r2:.4f} MAE={oos_mae:.2f} RankIC={oos_rank_ic:.4f}")

    # 用全量重训最终模型
    final = Pipeline([("scaler", StandardScaler()),
                      ("reg", Ridge(alpha=best_alpha, random_state=_RANDOM_SEED))])
    final.fit(X, y)
    scaler = final.named_steps["scaler"]
    reg = final.named_steps["reg"]
    coefs = reg.coef_
    weights = {f: round(float(w), 4) for f, w in zip(CORE_FEATURES, coefs)}

    version = f"{_TRUTH_VERSION_PREFIX}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "model_version": version,
        "target": "fear_truth_regression",
        "target_definition": "同日构造恐惧状态分（0-100），不是未来收益标签",
        "target_horizon": "same_day",
        "target_components": ["price_drawdown", "iv_surge", "iv_level_gate"],
        "breadth_available": False,
        "predictive_claim": False,
        "features": CORE_FEATURES,
        "trained_at": datetime.now().isoformat(),
        "train_range": [dates[0], dates[-1]],
        "n_samples": n,
        "n_oos": int(oos_tail),
        "cv_gap": int(cv_gap),
        "y_mean": round(float(y.mean()), 2),
        "best_alpha": best_alpha,
        "cv_r2": round(cv_r2, 4),
        "oos_r2": round(oos_r2, 4),
        "oos_mae": round(oos_mae, 2),
        "baseline_lag1_oos_mae": round(baseline_oos_mae, 2),
        "validation_status": (
            "state_fit_outperformed_baseline"
            if oos_mae < baseline_oos_mae else "no_robust_edge"
        ),
        "oos_rank_ic": round(oos_rank_ic, 4),
        "weights": weights,
        "intercept": round(float(reg.intercept_), 4),
        "scaler": {
            "mean": [round(float(m), 6) for m in scaler.mean_],
            "scale": [round(float(s), 6) for s in scaler.scale_],
        },
    }
    if save:
        _ensure_dir()
        joblib.dump(final, _MODEL_DIR / f"{version}.joblib")
        (_MODEL_DIR / f"{version}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _TRUTH_LATEST_PTR.write_text(
            json.dumps({"model_version": version}, ensure_ascii=False), encoding="utf-8")
        _say(f"重定向模型已落盘: {version}")
    return meta


def load_truth_model(version: Optional[str] = None):
    """加载重定向回归模型，返回 (pipeline, meta)。不存在返回 (None, None)。"""
    import joblib
    if not version and _TRUTH_LATEST_PTR.exists():
        try:
            version = json.loads(_TRUTH_LATEST_PTR.read_text(encoding="utf-8")).get("model_version")
        except Exception:
            return None, None
    if not version:
        return None, None
    jb = _MODEL_DIR / f"{version}.joblib"
    js = _MODEL_DIR / f"{version}.json"
    if not jb.exists() or not js.exists():
        return None, None
    return joblib.load(jb), json.loads(js.read_text(encoding="utf-8"))


def predict_truth_score(feature_row: dict, pipe=None, meta=None) -> Optional[dict]:
    """单日推断重定向恐惧分。score=clip(predict,0,100)，与 v7.0 fear_truth 同口径。"""
    if pipe is None or meta is None:
        pipe, meta = load_truth_model()
    if pipe is None:
        return None
    try:
        x = np.array([[feature_row[f] for f in CORE_FEATURES]], dtype=float)
    except (KeyError, TypeError):
        return None
    if not np.all(np.isfinite(x)):
        return None
    pred = float(pipe.predict(x)[0])
    score = round(max(0.0, min(100.0, pred)), 2)
    return {"fear_truth_vix2": score, "model_version": meta.get("model_version")}


# ─────────────────────────────────────────────────────────────────
# Track B+: walk-forward OOS 训练器（2026-07-01）
# ─────────────────────────────────────────────────────────────────

def train_truth_at_cutoff(ds: pd.DataFrame, cutoff_idx: int,
                          alpha_grid: Optional[list] = None,
                          n_splits: int = 5, cv_gap: int = 5,
                          min_train_samples: int = 200) -> Optional[dict]:
    """用 ds 前 cutoff_idx 行训练 Ridge 同日状态拟合模型。

    用于 walk-forward 回填：在推断日期 d 时，只用 d 之前的数据训练，保证历史曲线
    是按时间顺序的实验状态估计（非 in-sample 回放）。构造标签是 trailing 派生，
    cutoff 即「最后见到的训练日」= ds.iloc[cutoff_idx-1].date。

    返回 {"pipe": pipeline, "train_cutoff": str, "alpha": float} 或 None（样本不足）。
    """
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if min_train_samples < 40:
        raise ValueError("min_train_samples 必须至少为 40")
    if cv_gap < 5:
        raise ValueError("cv_gap 必须至少为 5 个交易日")
    if not 2 <= n_splits <= 10:
        raise ValueError("n_splits 必须在 2 到 10 之间")
    if cutoff_idx < min_train_samples:
        return None
    if cutoff_idx > len(ds):
        raise ValueError("cutoff_idx 超出数据集范围")
    alpha_grid = alpha_grid or [0.1, 1.0, 3.0, 10.0, 30.0, 100.0]
    sub = ds.iloc[:cutoff_idx].sort_values("date").reset_index(drop=True)
    X = sub[CORE_FEATURES].to_numpy(dtype=float)
    y = sub["fear_truth"].to_numpy(dtype=float)
    if len(sub) < min_train_samples or len(np.unique(y)) < 2:
        return None

    pipe = Pipeline([("scaler", StandardScaler()), ("reg", Ridge(random_state=_RANDOM_SEED))])
    n_cv = min(n_splits, max(2, len(sub) // 60))
    tscv = TimeSeriesSplit(n_splits=n_cv, gap=cv_gap)
    fold_audit = []
    for train_idx, test_idx in tscv.split(X):
        fold_audit.append({
            "train_end": str(sub.iloc[int(train_idx[-1])]["date"]),
            "test_start": str(sub.iloc[int(test_idx[0])]["date"]),
            "gap_observations": int(test_idx[0] - train_idx[-1] - 1),
        })
    gs = GridSearchCV(pipe, {"reg__alpha": alpha_grid},
                      scoring="neg_mean_absolute_error",
                      cv=tscv, n_jobs=1, refit=True)
    gs.fit(X, y)
    best = gs.best_estimator_
    return {
        "pipe": best,
        "train_cutoff": str(sub.iloc[-1]["date"]),
        "alpha": float(gs.best_params_["reg__alpha"]),
        "n_train": int(len(sub)),
        "cv_gap": int(cv_gap),
        "cv_folds": fold_audit,
    }


def save_walkforward_meta(meta: dict) -> None:
    """持久化最近一次时间顺序状态估计的审计摘要。"""
    _ensure_dir()
    tmp = _WALKFORWARD_META_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_WALKFORWARD_META_PATH)


def get_walkforward_meta() -> Optional[dict]:
    """读取最近一次时间顺序状态估计审计摘要。"""
    if not _WALKFORWARD_META_PATH.exists():
        return None
    try:
        return json.loads(_WALKFORWARD_META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        logger.warning("VIX2 walk-forward 审计摘要不可读", exc_info=True)
        return None
