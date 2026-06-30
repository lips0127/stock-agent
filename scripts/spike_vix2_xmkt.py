"""研究性 spike：跨市场长历史因子能否把 VIX2.0 的 embargoed walk-forward
均值 AUC 推过 0.5（即真信号），还是与 core-only 一样塌回 ~0.5。

不落盘、不改生产代码。仅验证「增强因子集」赛道 A1 是否值得集成。

跨市场因子（均为长历史，回溯 >2016，不截断 2504 样本）：
  hsi_ret5         恒指 5 日收益 %（港股与 A 股同日收盘，同日可用）
  hsi_rv20         恒指 20 日已实现波动（年化%）
  us10y            美债 10Y 收益率（滞后 1 交易日：美盘收盘晚于 A 股）
  us10y_chg20      美债 10Y 20 日变化（滞后）
  cn_us_10y_spread 中美 10Y 利差（美债端滞后）
  usdcny_chg20     人民币中间价 20 日动量 %（升值为负=risk-on）

验收口径沿用 scripts/robust_vix2：6 个连续 OOS 区块 + H 天 embargo，
对比 core-only vs core+xmkt 的跨块均值 AUC。

用法: ./venv_new/Scripts/python.exe -m scripts.spike_vix2_xmkt
"""
import warnings
warnings.filterwarnings("ignore")

import math
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.stock_service import _no_proxy
from backend.services.vix2_features import CORE_FEATURES, build_core_features
from backend.services.vix2_labels import build_labeled_dataset

XMKT_FEATURES = ["hsi_ret5", "hsi_rv20", "us10y", "us10y_chg20",
                 "cn_us_10y_spread", "usdcny_chg20"]

CANDIDATES = [
    dict(pt=0.10, sl=0.07, H=60, rv=False, C=0.01),
    dict(pt=0.10, sl=0.05, H=60, rv=False, C=3.0),
    dict(pt=0.07, sl=0.05, H=20, rv=False, C=None),
    dict(pt=0.05, sl=0.05, H=20, rv=True,  C=None),
]
N_BLOCKS = 6


def _annualized_cc_rv(close: pd.Series, window: int = 20) -> pd.Series:
    r = np.log(close / close.shift(1))
    return (r.rolling(window).std() * math.sqrt(252) * 100).round(2)


def build_xmkt_features() -> pd.DataFrame:
    """构建跨市场因子，返回 [date, <XMKT_FEATURES>]，全部 point-in-time。"""
    import akshare as ak
    with _no_proxy():
        hsi = ak.stock_zh_index_daily_tx(symbol="hkHSI")
        bond = ak.bond_zh_us_rate()
        fx = ak.currency_boc_safe()

    # 恒指（同日可用）
    hsi = hsi.copy()
    hsi["date"] = pd.to_datetime(hsi["date"]).dt.strftime("%Y-%m-%d")
    hsi["close"] = pd.to_numeric(hsi["close"], errors="coerce")
    hsi = hsi.sort_values("date").reset_index(drop=True)
    hsi["hsi_ret5"] = (hsi["close"].pct_change(5) * 100).round(2)
    hsi["hsi_rv20"] = _annualized_cc_rv(hsi["close"], 20)
    hsi_f = hsi[["date", "hsi_ret5", "hsi_rv20"]]

    # 中美利差 / 美债（美债端滞后 1 交易日避免前视）
    bond = bond.rename(columns={
        "日期": "date", "中国国债收益率10年": "cn10y", "美国国债收益率10年": "us10y_raw",
    })
    bond["date"] = pd.to_datetime(bond["date"]).dt.strftime("%Y-%m-%d")
    bond = bond.sort_values("date").reset_index(drop=True)
    bond["cn10y"] = pd.to_numeric(bond["cn10y"], errors="coerce")
    bond["us10y_raw"] = pd.to_numeric(bond["us10y_raw"], errors="coerce")
    bond["us10y"] = bond["us10y_raw"].shift(1)             # 滞后
    bond["us10y_chg20"] = (bond["us10y"] - bond["us10y"].shift(20)).round(3)
    bond["cn_us_10y_spread"] = (bond["cn10y"] - bond["us10y"]).round(3)
    bond_f = bond[["date", "us10y", "us10y_chg20", "cn_us_10y_spread"]]

    # 人民币中间价（早盘公布，A 股收盘已知，同日）
    fx = fx.rename(columns={"日期": "date", "美元": "usdcny"})
    fx["date"] = pd.to_datetime(fx["date"]).dt.strftime("%Y-%m-%d")
    fx["usdcny"] = pd.to_numeric(fx["usdcny"], errors="coerce")
    fx = fx.sort_values("date").reset_index(drop=True)
    fx["usdcny_chg20"] = (fx["usdcny"].pct_change(20) * 100).round(3)
    fx_f = fx[["date", "usdcny_chg20"]]

    out = hsi_f.merge(bond_f, on="date", how="outer").merge(fx_f, on="date", how="outer")
    return out.sort_values("date").reset_index(drop=True)


def robust_auc(ds, feats, pt, sl, H, rv, C):
    ds = ds.sort_values("date").reset_index(drop=True)
    X = ds[feats].to_numpy(float)
    y = ds["label"].to_numpy(int)
    n = len(ds)
    block = n // (N_BLOCKS + 1)
    aucs = []
    for b in range(1, N_BLOCKS + 1):
        te_lo = block * b
        te_hi = block * (b + 1) if b < N_BLOCKS else n
        tr_hi = te_lo - H
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
            "std": round(float(np.std(valid)), 3) if valid else None}


def main():
    from backend.core.database import init_db
    init_db()
    print("构建 core 特征…", flush=True)
    core = build_core_features()
    print(f"  core rows={len(core)}", flush=True)
    print("构建跨市场特征…", flush=True)
    xmkt = build_xmkt_features()
    print(f"  xmkt rows={len(xmkt)}", flush=True)

    merged = core.merge(xmkt, on="date", how="left")
    cov = merged[XMKT_FEATURES].notna().all(axis=1).mean()
    print(f"  合并后 xmkt 全非空覆盖率={cov:.3f}\n", flush=True)

    for cfg in CANDIDATES:
        ds_core = build_labeled_dataset(core, pt=cfg["pt"], sl=cfg["sl"],
                                        horizon=cfg["H"], rv_scale=cfg["rv"])
        ds_full = build_labeled_dataset(merged, pt=cfg["pt"], sl=cfg["sl"],
                                        horizon=cfg["H"], rv_scale=cfg["rv"])
        # full 需丢弃 xmkt NaN
        ds_full = ds_full.dropna(subset=XMKT_FEATURES).reset_index(drop=True)
        r_core = robust_auc(ds_core, CORE_FEATURES, **{k: cfg[k] for k in ("pt","sl","H","rv","C")})
        r_full = robust_auc(ds_full, CORE_FEATURES + XMKT_FEATURES,
                            **{k: cfg[k] for k in ("pt","sl","H","rv","C")})
        print(f"pt={cfg['pt']} sl={cfg['sl']} H={cfg['H']} rv={cfg['rv']} C={cfg['C']}")
        print(f"   core      blocks={r_core['blocks']}  mean={r_core['mean']} ± {r_core['std']}")
        print(f"   core+xmkt blocks={r_full['blocks']}  mean={r_full['mean']} ± {r_full['std']}\n",
              flush=True)


if __name__ == "__main__":
    main()
