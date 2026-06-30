"""一次性 barrier 参数扫描（不落盘），评估能否把 OOS-AUC 推过 0.55
并修正两大底排序（4-07 应比 3-23 更恐慌 / score 更低）。

用法: python -m scripts.sweep_vix2
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.vix2_features import CORE_FEATURES, build_core_features
from backend.services.vix2_labels import build_labeled_dataset

C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]
BOTTOMS = ("2025-04-07", "2026-03-23")


def eval_cfg(feats, pt, sl, H, rv_scale):
    ds = build_labeled_dataset(feats, pt=pt, sl=sl, horizon=H, rv_scale=rv_scale)
    if ds is None or len(ds) < 300:
        return None
    ds = ds.sort_values("date").reset_index(drop=True)
    X = ds[CORE_FEATURES].to_numpy(float)
    y = ds["label"].to_numpy(int)
    if len(np.unique(y)) < 2:
        return None
    n = len(ds)
    oos = min(252, max(40, n // 5))
    split = n - oos
    Xtr, ytr, Xo, yo = X[:split], y[:split], X[split:], y[split:]
    pipe = Pipeline([("s", StandardScaler()),
                     ("c", LogisticRegression(penalty="l2", class_weight="balanced",
                                              max_iter=2000, random_state=42))])
    gs = GridSearchCV(pipe, {"c__C": C_GRID}, scoring="roc_auc",
                      cv=TimeSeriesSplit(5), n_jobs=-1)
    gs.fit(Xtr, ytr)
    cv = gs.best_score_
    oa = None
    if len(np.unique(yo)) == 2:
        oa = roc_auc_score(yo, gs.best_estimator_.predict_proba(Xo)[:, 1])
    # 两大底排序：用全量重训取这两天的 score
    final = Pipeline([("s", StandardScaler()),
                      ("c", LogisticRegression(penalty="l2", C=gs.best_params_["c__C"],
                                               class_weight="balanced", max_iter=2000,
                                               random_state=42))])
    final.fit(X, y)
    scores = {}
    for d in BOTTOMS:
        r = ds[ds["date"] == d]
        if not r.empty:
            p = final.predict_proba(r[CORE_FEATURES].to_numpy(float))[0, 1]
            scores[d] = round((1 - p) * 100, 1)
    # 期望 4-07 score < 3-23 score（4-07 更恐慌）
    ok = (BOTTOMS[0] in scores and BOTTOMS[1] in scores
          and scores[BOTTOMS[0]] < scores[BOTTOMS[1]])
    return {"pt": pt, "sl": sl, "H": H, "rv": rv_scale, "n": n,
            "C": gs.best_params_["c__C"], "cv": round(cv, 4),
            "oos": round(oa, 4) if oa else None,
            "s_0407": scores.get(BOTTOMS[0]), "s_0323": scores.get(BOTTOMS[1]),
            "order_ok": ok}


def main():
    from backend.core.database import init_db
    init_db()
    print("构建特征矩阵（一次）…", flush=True)
    feats = build_core_features()
    print(f"  rows={len(feats)}", flush=True)

    configs = []
    for H in (10, 20, 40, 60):
        for pt, sl in ((0.05, 0.05), (0.07, 0.05), (0.10, 0.05),
                       (0.10, 0.07), (0.15, 0.10)):
            for rv in (True, False):
                configs.append((pt, sl, H, rv))

    rows = []
    for i, (pt, sl, H, rv) in enumerate(configs):
        r = eval_cfg(feats, pt, sl, H, rv)
        if r:
            rows.append(r)
            print(f"[{i+1}/{len(configs)}] pt={pt} sl={sl} H={H} rv={rv} "
                  f"-> cv={r['cv']} oos={r['oos']} "
                  f"4-07={r['s_0407']} 3-23={r['s_0323']} order_ok={r['order_ok']}",
                  flush=True)

    print("\n=== Top by OOS-AUC ===")
    rows.sort(key=lambda x: (x["oos"] or 0), reverse=True)
    for r in rows[:8]:
        print(r)
    print("\n=== Configs with correct bottom ordering (4-07 < 3-23) ===")
    for r in [x for x in rows if x["order_ok"]][:8]:
        print(r)


if __name__ == "__main__":
    main()
