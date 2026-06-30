"""严肃 VIX/恐慌因子研究：从长历史特征训练可交易择时 alpha。

这不是描述性事件研究，而是：
  1) 构造 point-in-time 长历史特征；
  2) 标签为未来 20 日风险调整收益；
  3) purged/embargoed walk-forward 生成样本外预测序列；
  4) 用 IC、分层收益差、年度稳定性和简单仓位策略检验是否可交易。

结论闸门见 docs/SPEC.md §11F.10。

用法:
  ./venv_new/Scripts/python.exe -m scripts.research_vix_alpha
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
OUT = Path("data/research/vix_alpha_oos.json")


def _add_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    ret1 = close.pct_change()
    rv20 = ret1.rolling(20).std() * math.sqrt(252)
    fwd_ret = close.shift(-HORIZON) / close - 1
    # 未来路径最大回撤（相对 entry），用于策略风险评估
    fwd_mdd = np.full(len(df), np.nan)
    vals = close.to_numpy(float)
    for i in range(len(df) - HORIZON):
        entry = vals[i]
        path = vals[i + 1:i + HORIZON + 1]
        if np.isfinite(entry) and entry > 0 and len(path):
            fwd_mdd[i] = np.nanmin(path / entry - 1)
    df["fwd_ret_20d"] = fwd_ret * 100
    df["fwd_mdd_20d"] = fwd_mdd * 100
    df["target_risk_adj_20d"] = fwd_ret / rv20.clip(lower=0.03)
    # 真实可交易日收益：t 日信号，t+1 持仓；这里只用于 OOS 策略曲线
    df["next_ret"] = close.shift(-1) / close - 1
    return df


def build_dataset() -> pd.DataFrame:
    print("构建 VIX core 特征…", flush=True)
    core = build_core_features()
    print(f"  core rows={len(core)}", flush=True)
    print("构建跨市场特征…", flush=True)
    xmkt = build_xmkt_features()
    print(f"  xmkt rows={len(xmkt)}", flush=True)
    df = core.merge(xmkt, on="date", how="left")

    # 派生状态特征：用滚动 percentile/zscore 替代静态阈值，保持 point-in-time。
    df = df.sort_values("date").reset_index(drop=True)
    df["qvix_pct_252"] = df["qvix_50"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["rv_pct_252"] = df["rv_hs300"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["panic_depth"] = (-df["drawdown_252"]).clip(lower=0)
    df["vol_shock"] = df["qvix_50_z"].clip(lower=0) * df["panic_depth"]
    df["trend_repair"] = df["mom_20d"] - df["mom_60d"]

    df = _add_labels(df)
    return df


DERIVED_FEATURES = ["qvix_pct_252", "rv_pct_252", "panic_depth", "vol_shock", "trend_repair"]
FEATURE_SETS = {
    "baseline_inverse_qvix": ["qvix_pct_252"],
    "core_linear": CORE_FEATURES + DERIVED_FEATURES,
    "core_xmkt_linear": CORE_FEATURES + DERIVED_FEATURES + XMKT_FEATURES,
    "core_xmkt_gbdt": CORE_FEATURES + DERIVED_FEATURES + XMKT_FEATURES,
}


def _blocks(n: int):
    block = n // (N_BLOCKS + 1)
    for b in range(1, N_BLOCKS + 1):
        te_lo = block * b
        te_hi = block * (b + 1) if b < N_BLOCKS else n
        tr_hi = te_lo - EMBARGO
        if tr_hi >= MIN_TRAIN and te_hi > te_lo:
            yield b, tr_hi, te_lo, te_hi


def _make_model(name: str):
    if name == "core_xmkt_gbdt":
        return HistGradientBoostingRegressor(
            max_iter=180, max_depth=3, learning_rate=0.04,
            l2_regularization=1.0, random_state=42,
        )
    return Pipeline([
        ("s", StandardScaler()),
        ("m", Ridge(alpha=10.0, random_state=42)),
    ])


def _predict_oos(ds: pd.DataFrame, model_name: str, feats: list[str]) -> pd.DataFrame:
    rows = ds.dropna(subset=feats + ["target_risk_adj_20d", "fwd_ret_20d", "next_ret"]).reset_index(drop=True)
    pred_raw = np.full(len(rows), np.nan)
    pred = np.full(len(rows), np.nan)
    orient = np.full(len(rows), np.nan)
    block_id = np.full(len(rows), np.nan)
    for b, tr_hi, te_lo, te_hi in _blocks(len(rows)):
        train = rows.iloc[:tr_hi]
        test = rows.iloc[te_lo:te_hi]
        if model_name == "baseline_inverse_qvix":
            train_pred = -train["qvix_pct_252"].to_numpy(float)
            test_pred = -test["qvix_pct_252"].to_numpy(float)
        else:
            model = _make_model(model_name)
            model.fit(train[feats].to_numpy(float), train["target_risk_adj_20d"].to_numpy(float))
            train_pred = model.predict(train[feats].to_numpy(float))
            test_pred = model.predict(test[feats].to_numpy(float))
        train_ic = spearmanr(train_pred, train["fwd_ret_20d"].to_numpy(float)).correlation
        direction = -1.0 if np.isfinite(train_ic) and train_ic < 0 else 1.0
        pred_raw[te_lo:te_hi] = test_pred
        pred[te_lo:te_hi] = direction * test_pred
        orient[te_lo:te_hi] = direction
        block_id[te_lo:te_hi] = b
    out = rows[["date", "close", "fwd_ret_20d", "fwd_mdd_20d", "next_ret", "target_risk_adj_20d"]].copy()
    out["pred_raw"] = pred_raw
    out["pred"] = pred
    out["orientation"] = orient
    out["block"] = block_id
    return out.dropna(subset=["pred"]).reset_index(drop=True)


def _ic(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 20:
        return None
    return float(spearmanr(x[mask], y[mask]).correlation), float(pearsonr(x[mask], y[mask])[0])


def _strategy_stats(oos: pd.DataFrame) -> dict:
    # 只用 OOS pred 排名生成日度仓位：高分=1.0，中=0.5，低=0.0；避免做空。
    q30 = oos["pred"].quantile(0.30)
    q70 = oos["pred"].quantile(0.70)
    pos = np.where(oos["pred"] >= q70, 1.0, np.where(oos["pred"] <= q30, 0.0, 0.5))
    ret = pd.Series(pos * oos["next_ret"].to_numpy(float), index=pd.to_datetime(oos["date"]))
    bh = pd.Series(oos["next_ret"].to_numpy(float), index=ret.index)
    eq = (1 + ret.fillna(0)).cumprod()
    bh_eq = (1 + bh.fillna(0)).cumprod()
    dd = eq / eq.cummax() - 1
    bh_dd = bh_eq / bh_eq.cummax() - 1
    ann = 252
    vol = ret.std() * math.sqrt(ann)
    bh_vol = bh.std() * math.sqrt(ann)
    return {
        "total_ret": round((float(eq.iloc[-1]) - 1) * 100, 2),
        "buy_hold_ret": round((float(bh_eq.iloc[-1]) - 1) * 100, 2),
        "ann_ret": round((eq.iloc[-1] ** (ann / max(len(eq), 1)) - 1) * 100, 2),
        "sharpe": round(float(ret.mean() * ann / vol), 2) if vol and np.isfinite(vol) else None,
        "buy_hold_sharpe": round(float(bh.mean() * ann / bh_vol), 2) if bh_vol and np.isfinite(bh_vol) else None,
        "max_dd": round(float(dd.min()) * 100, 2),
        "buy_hold_max_dd": round(float(bh_dd.min()) * 100, 2),
        "avg_position": round(float(np.mean(pos)), 2),
    }


def _summarize(model_name: str, oos: pd.DataFrame) -> dict:
    rank_ic, pearson_ic = _ic(oos["pred"].to_numpy(float), oos["fwd_ret_20d"].to_numpy(float))
    q = pd.qcut(oos["pred"], 5, labels=False, duplicates="drop")
    oos = oos.copy(); oos["q"] = q
    bucket = oos.groupby("q")["fwd_ret_20d"].agg(["count", "mean", "median"]).reset_index()
    low = bucket.iloc[0]["mean"] if len(bucket) else np.nan
    high = bucket.iloc[-1]["mean"] if len(bucket) else np.nan
    years = []
    oos["year"] = pd.to_datetime(oos["date"]).dt.year
    for y, g in oos.groupby("year"):
        if len(g) < 40:
            continue
        ri, pi = _ic(g["pred"].to_numpy(float), g["fwd_ret_20d"].to_numpy(float))
        years.append({"year": int(y), "n": int(len(g)), "rank_ic": round(ri, 4), "pearson_ic": round(pi, 4)})
    block_ics = []
    for b, g in oos.groupby("block"):
        ri, pi = _ic(g["pred"].to_numpy(float), g["fwd_ret_20d"].to_numpy(float))
        if ri is not None:
            block_ics.append({"block": int(b), "n": int(len(g)), "rank_ic": round(ri, 4), "pearson_ic": round(pi, 4)})
    strat = _strategy_stats(oos)
    return {
        "model": model_name,
        "n_oos": int(len(oos)),
        "date_range": [str(oos["date"].iloc[0]), str(oos["date"].iloc[-1])],
        "rank_ic": round(rank_ic, 4),
        "pearson_ic": round(pearson_ic, 4),
        "block_positive_frac": round(sum(x["rank_ic"] > 0 for x in block_ics) / len(block_ics), 3) if block_ics else None,
        "orientation_by_block": [
            {"block": int(b), "orientation": float(g["orientation"].iloc[0])}
            for b, g in oos.groupby("block")
        ],
        "top_bottom_spread_20d": round(float(high - low), 2) if np.isfinite(high) and np.isfinite(low) else None,
        "quantiles": [
            {"q": int(r["q"]), "n": int(r["count"]), "avg_ret_20d": round(float(r["mean"]), 2), "median_ret_20d": round(float(r["median"]), 2)}
            for _, r in bucket.iterrows()
        ],
        "block_ics": block_ics,
        "year_ics": years,
        "strategy": strat,
    }


def main():
    init_db()
    ds = build_dataset()
    results = []
    print(f"总样本 rows={len(ds)} range={ds['date'].iloc[0]}..{ds['date'].iloc[-1]}", flush=True)
    for name, feats in FEATURE_SETS.items():
        print(f"\n=== {name} ({len(feats)} features) ===", flush=True)
        oos = _predict_oos(ds, name, feats)
        if oos.empty:
            print("no OOS predictions", flush=True)
            continue
        s = _summarize(name, oos)
        results.append(s)
        print(f"OOS {s['date_range'][0]}..{s['date_range'][1]} n={s['n_oos']}")
        print(f"RankIC={s['rank_ic']} PearsonIC={s['pearson_ic']} block_pos={s['block_positive_frac']}")
        print(f"Top-Bottom 20d spread={s['top_bottom_spread_20d']}%")
        print(f"Strategy={s['strategy']}")
        print("Orientation:", s["orientation_by_block"])
        print("Block IC:", s["block_ics"])
        print("Quantiles:", s["quantiles"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"horizon": HORIZON, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT}", flush=True)


if __name__ == "__main__":
    main()
