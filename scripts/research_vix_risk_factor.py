"""VIX/恐慌指数作为“风险因子”的严肃 OOS 验证。

收益 alpha 研究未过闸门后，按 VIX 本质改测：它是否能预测未来回撤/波动，
从而用于降仓/风控，而不是直接加仓。

方法：
  - point-in-time 长历史特征（VIX2 core + 跨市场 + 派生状态）
  - 标签：未来20日最大回撤严重度、未来20日实现波动
  - purged/embargoed walk-forward OOS 预测
  - 评价：风险 IC、Top-Bottom 回撤差、风险控制仓位策略

用法:
  ./venv_new/Scripts/python.exe -m scripts.research_vix_risk_factor
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.core.database import init_db
from backend.services.vix2_features import CORE_FEATURES, build_core_features
from scripts.spike_vix2_xmkt import XMKT_FEATURES, build_xmkt_features

HORIZON = 20
EMBARGO = HORIZON
N_BLOCKS = 7
MIN_TRAIN = 700
OUT = Path("data/research/vix_risk_factor_oos.json")

DERIVED_FEATURES = ["qvix_pct_252", "rv_pct_252", "panic_depth", "vol_shock", "trend_repair"]
FEATURE_SETS = {
    "baseline_qvix_risk": ["qvix_pct_252"],
    "core_risk_linear": CORE_FEATURES + DERIVED_FEATURES,
    "core_xmkt_risk_linear": CORE_FEATURES + DERIVED_FEATURES + XMKT_FEATURES,
    "core_xmkt_risk_gbdt": CORE_FEATURES + DERIVED_FEATURES + XMKT_FEATURES,
}


def _add_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    vals = close.to_numpy(float)
    fwd_mdd = np.full(len(df), np.nan)
    fwd_vol = np.full(len(df), np.nan)
    for i in range(len(df) - HORIZON):
        entry = vals[i]
        path = vals[i + 1:i + HORIZON + 1]
        if np.isfinite(entry) and entry > 0 and len(path) == HORIZON:
            min_ret = np.nanmin(path / entry - 1)
            fwd_mdd[i] = max(0.0, -float(min_ret)) * 100
            r = pd.Series(path).pct_change().dropna()
            if len(r) >= 5:
                fwd_vol[i] = float(r.std() * math.sqrt(252) * 100)
    df["target_mdd20"] = fwd_mdd
    df["target_vol20"] = fwd_vol
    df["next_ret"] = close.shift(-1) / close - 1
    return df


def build_dataset() -> pd.DataFrame:
    print("构建 VIX core 特征…", flush=True)
    core = build_core_features()
    print(f"  core rows={len(core)}", flush=True)
    print("构建跨市场特征…", flush=True)
    xmkt = build_xmkt_features()
    print(f"  xmkt rows={len(xmkt)}", flush=True)
    df = core.merge(xmkt, on="date", how="left").sort_values("date").reset_index(drop=True)
    df["qvix_pct_252"] = df["qvix_50"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["rv_pct_252"] = df["rv_hs300"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["panic_depth"] = (-df["drawdown_252"]).clip(lower=0)
    df["vol_shock"] = df["qvix_50_z"].clip(lower=0) * df["panic_depth"]
    df["trend_repair"] = df["mom_20d"] - df["mom_60d"]
    return _add_labels(df)


def _blocks(n: int):
    block = n // (N_BLOCKS + 1)
    for b in range(1, N_BLOCKS + 1):
        te_lo = block * b
        te_hi = block * (b + 1) if b < N_BLOCKS else n
        tr_hi = te_lo - EMBARGO
        if tr_hi >= MIN_TRAIN and te_hi > te_lo:
            yield b, tr_hi, te_lo, te_hi


def _model(name: str):
    if name.endswith("gbdt"):
        return HistGradientBoostingRegressor(max_iter=180, max_depth=3, learning_rate=0.04,
                                             l2_regularization=1.0, random_state=42)
    return Pipeline([("s", StandardScaler()), ("m", Ridge(alpha=10.0, random_state=42))])


def _predict_oos(ds: pd.DataFrame, name: str, feats: list[str], target: str) -> pd.DataFrame:
    rows = ds.dropna(subset=feats + [target, "next_ret"]).reset_index(drop=True)
    pred = np.full(len(rows), np.nan)
    block_id = np.full(len(rows), np.nan)
    for b, tr_hi, te_lo, te_hi in _blocks(len(rows)):
        train = rows.iloc[:tr_hi]
        test = rows.iloc[te_lo:te_hi]
        if name == "baseline_qvix_risk":
            p = test["qvix_pct_252"].to_numpy(float)
        else:
            m = _model(name)
            m.fit(train[feats].to_numpy(float), train[target].to_numpy(float))
            p = m.predict(test[feats].to_numpy(float))
        pred[te_lo:te_hi] = p
        block_id[te_lo:te_hi] = b
    out = rows[["date", "close", "next_ret", "target_mdd20", "target_vol20"]].copy()
    out["risk_pred"] = pred
    out["block"] = block_id
    return out.dropna(subset=["risk_pred"]).reset_index(drop=True)


def _ic(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 20:
        return None, None
    return float(spearmanr(x[mask], y[mask]).correlation), float(pearsonr(x[mask], y[mask])[0])


def _risk_control_stats(oos: pd.DataFrame) -> dict:
    # 高风险预测降仓：最高30%风险=0.2仓，中间=0.6，最低30%=1.0。
    q30 = oos["risk_pred"].quantile(0.30)
    q70 = oos["risk_pred"].quantile(0.70)
    pos = np.where(oos["risk_pred"] >= q70, 0.2, np.where(oos["risk_pred"] <= q30, 1.0, 0.6))
    ret = pd.Series(pos * oos["next_ret"].to_numpy(float), index=pd.to_datetime(oos["date"]))
    bh = pd.Series(oos["next_ret"].to_numpy(float), index=ret.index)
    eq = (1 + ret.fillna(0)).cumprod()
    bh_eq = (1 + bh.fillna(0)).cumprod()
    dd = eq / eq.cummax() - 1
    bh_dd = bh_eq / bh_eq.cummax() - 1
    vol = ret.std() * math.sqrt(252)
    bh_vol = bh.std() * math.sqrt(252)
    return {
        "total_ret": round((float(eq.iloc[-1]) - 1) * 100, 2),
        "buy_hold_ret": round((float(bh_eq.iloc[-1]) - 1) * 100, 2),
        "sharpe": round(float(ret.mean() * 252 / vol), 2) if vol and np.isfinite(vol) else None,
        "buy_hold_sharpe": round(float(bh.mean() * 252 / bh_vol), 2) if bh_vol and np.isfinite(bh_vol) else None,
        "max_dd": round(float(dd.min()) * 100, 2),
        "buy_hold_max_dd": round(float(bh_dd.min()) * 100, 2),
        "avg_position": round(float(np.mean(pos)), 2),
    }


def _summarize(name: str, target: str, oos: pd.DataFrame) -> dict:
    target_col = target
    ri, pi = _ic(oos["risk_pred"].to_numpy(float), oos[target_col].to_numpy(float))
    q = pd.qcut(oos["risk_pred"], 5, labels=False, duplicates="drop")
    oos = oos.copy(); oos["q"] = q
    bucket = oos.groupby("q")[target_col].agg(["count", "mean", "median"]).reset_index()
    low = float(bucket.iloc[0]["mean"])
    high = float(bucket.iloc[-1]["mean"])
    block_ics = []
    for b, g in oos.groupby("block"):
        bri, bpi = _ic(g["risk_pred"].to_numpy(float), g[target_col].to_numpy(float))
        block_ics.append({"block": int(b), "n": int(len(g)), "rank_ic": round(bri, 4), "pearson_ic": round(bpi, 4)})
    return {
        "model": name,
        "target": target,
        "n_oos": int(len(oos)),
        "date_range": [str(oos["date"].iloc[0]), str(oos["date"].iloc[-1])],
        "rank_ic": round(ri, 4),
        "pearson_ic": round(pi, 4),
        "block_positive_frac": round(sum(x["rank_ic"] > 0 for x in block_ics) / len(block_ics), 3),
        "top_bottom_risk_spread": round(high - low, 2),
        "quantiles": [
            {"q": int(r["q"]), "n": int(r["count"]), "avg_target": round(float(r["mean"]), 2), "median_target": round(float(r["median"]), 2)}
            for _, r in bucket.iterrows()
        ],
        "block_ics": block_ics,
        "risk_control_strategy": _risk_control_stats(oos),
    }


def main():
    init_db()
    ds = build_dataset()
    print(f"总样本 rows={len(ds)} range={ds['date'].iloc[0]}..{ds['date'].iloc[-1]}", flush=True)
    results = []
    for target in ("target_mdd20", "target_vol20"):
        print(f"\n######## TARGET {target} ########", flush=True)
        for name, feats in FEATURE_SETS.items():
            print(f"\n=== {name} ({len(feats)} features) ===", flush=True)
            oos = _predict_oos(ds, name, feats, target)
            if oos.empty:
                print("no OOS predictions"); continue
            s = _summarize(name, target, oos)
            results.append(s)
            print(f"OOS {s['date_range'][0]}..{s['date_range'][1]} n={s['n_oos']}")
            print(f"RiskIC={s['rank_ic']} Pearson={s['pearson_ic']} block_pos={s['block_positive_frac']}")
            print(f"Top-Bottom risk spread={s['top_bottom_risk_spread']}")
            print(f"Strategy={s['risk_control_strategy']}")
            print("Block IC:", s["block_ics"])
            print("Quantiles:", s["quantiles"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"horizon": HORIZON, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
