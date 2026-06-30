"""严格评估：embargoed 扩窗 walk-forward，多个 OOS 区块，验证 sweep 里
H=60 的高 OOS-AUC 是真信号还是重叠标签人为产物。

对每个候选配置：把样本切成 K 个连续 OOS 区块；每块用「该块之前 − embargo(H 天)」
训练，块内评估 AUC。报告各块 AUC + 均值±std。真信号应跨块稳定 >0.5；
人为产物会在多数块塌回 ~0.5 或更低。

用法: python -m scripts.robust_vix2
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.vix2_features import CORE_FEATURES, build_core_features
from backend.services.vix2_labels import build_labeled_dataset

# sweep 里 OOS 最高 / 排序正确的几个候选
CANDIDATES = [
    dict(pt=0.10, sl=0.07, H=60, rv=False, C=0.01),   # sweep oos 第一 (0.65)
    dict(pt=0.10, sl=0.05, H=60, rv=False, C=3.0),    # oos 0.61 order_ok
    dict(pt=0.07, sl=0.05, H=20, rv=False, C=None),   # 中等 H 对照
    dict(pt=0.05, sl=0.05, H=20, rv=True,  C=None),   # 原首版对照
]
N_BLOCKS = 6


def robust_auc(feats, pt, sl, H, rv, C):
    ds = build_labeled_dataset(feats, pt=pt, sl=sl, horizon=H, rv_scale=rv)
    if ds is None:
        return None
    ds = ds.sort_values("date").reset_index(drop=True)
    X = ds[CORE_FEATURES].to_numpy(float)
    y = ds["label"].to_numpy(int)
    n = len(ds)
    block = n // (N_BLOCKS + 1)   # 第一块留作最小训练
    aucs = []
    for b in range(1, N_BLOCKS + 1):
        te_lo = block * b
        te_hi = block * (b + 1) if b < N_BLOCKS else n
        tr_hi = te_lo - H        # embargo = H 天，杜绝标签重叠泄漏
        if tr_hi < 200:
            continue
        Xtr, ytr = X[:tr_hi], y[:tr_hi]
        Xte, yte = X[te_lo:te_hi], y[te_lo:te_hi]
        if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
            aucs.append(None); continue
        c = C if C is not None else 0.1
        pipe = Pipeline([("s", StandardScaler()),
                         ("c", LogisticRegression(penalty="l2", C=c,
                              class_weight="balanced", max_iter=2000, random_state=42))])
        pipe.fit(Xtr, ytr)
        a = roc_auc_score(yte, pipe.predict_proba(Xte)[:, 1])
        aucs.append(round(a, 3))
    valid = [a for a in aucs if a is not None]
    return {"blocks": aucs,
            "mean": round(float(np.mean(valid)), 3) if valid else None,
            "std": round(float(np.std(valid)), 3) if valid else None,
            "n_pos_frac": round(float(y.mean()), 3)}


def main():
    from backend.core.database import init_db
    init_db()
    print("构建特征矩阵（一次）…", flush=True)
    feats = build_core_features()
    print(f"  rows={len(feats)}\n", flush=True)
    for cfg in CANDIDATES:
        r = robust_auc(feats, cfg["pt"], cfg["sl"], cfg["H"], cfg["rv"], cfg["C"])
        print(f"pt={cfg['pt']} sl={cfg['sl']} H={cfg['H']} rv={cfg['rv']} C={cfg['C']}")
        print(f"   blocks={r['blocks']}  mean={r['mean']} ± {r['std']}  pos_frac={r['n_pos_frac']}\n",
              flush=True)


if __name__ == "__main__":
    main()
