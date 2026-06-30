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
    X_tr, y_tr = X[:split], y[:split]
    X_oos, y_oos = X[split:], y[split:]
    _say(f"样本 {n}（训练 {split} / 纯样本外 {oos_tail}），正类占比 {y.mean():.3f}")

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            penalty="l2", class_weight="balanced",
            max_iter=2000, random_state=_RANDOM_SEED,
        )),
    ])
    tscv = TimeSeriesSplit(n_splits=n_splits)
    _say(f"TimeSeriesSplit({n_splits}) 网格搜索 C={c_grid}（ROC-AUC）…")
    gs = GridSearchCV(
        pipe, {"clf__C": c_grid}, scoring="roc_auc",
        cv=tscv, n_jobs=-1, refit=True,
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
        "feature_set": feature_set,
        "features": CORE_FEATURES,
        "trained_at": datetime.now().isoformat(),
        "train_range": [dates[0], dates[-1]],
        "n_samples": n,
        "n_oos": int(oos_tail),
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
    tscv = TimeSeriesSplit(n_splits=n_splits)
    _say(f"TimeSeriesSplit({n_splits}) 网格搜索 alpha={alpha_grid}（R2）…")
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
        "features": CORE_FEATURES,
        "trained_at": datetime.now().isoformat(),
        "train_range": [dates[0], dates[-1]],
        "n_samples": n,
        "n_oos": int(oos_tail),
        "y_mean": round(float(y.mean()), 2),
        "best_alpha": best_alpha,
        "cv_r2": round(cv_r2, 4),
        "oos_r2": round(oos_r2, 4),
        "oos_mae": round(oos_mae, 2),
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
