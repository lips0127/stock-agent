"""VIX 波动率风险因子的稳健性验证。

在首轮研究确认 VIX 更像风险/波动率因子后，本脚本只验证：
  - 是否能稳定预测未来 realized volatility；
  - 降仓规则在不同标的、周期、阈值、成本下是否仍改善风险收益；
  - 是否足够进入 vix_vol_risk_score 生产候选。

用法:
  ./venv_new/Scripts/python.exe -m scripts.research_vix_vol_risk_robustness
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
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.core.database import init_db
from backend.data.vix_sources import HS300_SYMBOL, fetch_index_daily_tx
from backend.services.vix2_features import CORE_FEATURES, build_core_features
from scripts.spike_vix2_xmkt import XMKT_FEATURES, build_xmkt_features

HORIZONS = [10, 20, 60]
N_BLOCKS = 7
MIN_TRAIN = 700
OUT = Path("data/research/vix_vol_risk_robustness.json")

DERIVED_FEATURES = ["qvix_pct_252", "rv_pct_252", "panic_depth", "vol_shock", "trend_repair"]
FEATURE_SETS = {
    "baseline_qvix": ["qvix_pct_252"],
    "core_xmkt_linear": CORE_FEATURES + DERIVED_FEATURES + XMKT_FEATURES,
}
TARGETS = {
    "sh": "上证综指",
    "hs300": "沪深300",
}
THRESHOLDS = [
    {"name": "q60_40", "low_q": 0.40, "high_q": 0.60, "high_pos": 0.3, "mid_pos": 0.6, "low_pos": 1.0},
    {"name": "q70_30", "low_q": 0.30, "high_q": 0.70, "high_pos": 0.2, "mid_pos": 0.6, "low_pos": 1.0},
    {"name": "q80_20", "low_q": 0.20, "high_q": 0.80, "high_pos": 0.0, "mid_pos": 0.6, "low_pos": 1.0},
]
COST_BPS = [0, 5, 10]


def _annualized_vol(path: np.ndarray) -> float:
    r = pd.Series(path).pct_change().dropna()
    if len(r) < 5:
        return np.nan
    return float(r.std() * math.sqrt(252) * 100)


def _add_benchmark_labels(df: pd.DataFrame, close_col: str, horizon: int) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df[close_col].astype(float)
    vals = close.to_numpy(float)
    fwd_vol = np.full(len(df), np.nan)
    for i in range(len(df) - horizon):
        entry = vals[i]
        path = vals[i + 1:i + horizon + 1]
        if np.isfinite(entry) and entry > 0 and len(path) == horizon:
            fwd_vol[i] = _annualized_vol(path)
    df["target_vol"] = fwd_vol
    df["next_ret"] = close.shift(-1) / close - 1
    return df


def build_dataset(target: str, horizon: int) -> pd.DataFrame:
    core = build_core_features()
    if core is None or core.empty:
        raise RuntimeError("core features empty")
    xmkt = build_xmkt_features()
    df = core.merge(xmkt, on="date", how="left").sort_values("date").reset_index(drop=True)
    df = df.rename(columns={"close": "close_sh"})
    if target == "hs300":
        hs = fetch_index_daily_tx(HS300_SYMBOL, days=4200)
        if hs is None or hs.empty:
            raise RuntimeError("HS300 daily data empty")
        hs = hs[["date", "close"]].rename(columns={"close": "close_hs300"})
        df = df.merge(hs, on="date", how="left")
        close_col = "close_hs300"
    else:
        close_col = "close_sh"
    df["qvix_pct_252"] = df["qvix_50"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["rv_pct_252"] = df["rv_hs300"].rolling(252).rank(pct=True).reset_index(drop=True) * 100
    df["panic_depth"] = (-df["drawdown_252"]).clip(lower=0)
    df["vol_shock"] = df["qvix_50_z"].clip(lower=0) * df["panic_depth"]
    df["trend_repair"] = df["mom_20d"] - df["mom_60d"]
    return _add_benchmark_labels(df, close_col, horizon)


def _blocks(n: int, horizon: int):
    block = n // (N_BLOCKS + 1)
    for b in range(1, N_BLOCKS + 1):
        te_lo = block * b
        te_hi = block * (b + 1) if b < N_BLOCKS else n
        tr_hi = te_lo - horizon
        if tr_hi >= MIN_TRAIN and te_hi > te_lo:
            yield b, tr_hi, te_lo, te_hi


def _model():
    return Pipeline([("s", StandardScaler()), ("m", Ridge(alpha=10.0, random_state=42))])


def _predict_oos(ds: pd.DataFrame, model_name: str, feats: list[str], horizon: int) -> pd.DataFrame:
    rows = ds.dropna(subset=feats + ["target_vol", "next_ret"]).reset_index(drop=True)
    pred = np.full(len(rows), np.nan)
    block_id = np.full(len(rows), np.nan)
    for b, tr_hi, te_lo, te_hi in _blocks(len(rows), horizon):
        train = rows.iloc[:tr_hi]
        test = rows.iloc[te_lo:te_hi]
        if model_name == "baseline_qvix":
            p = test["qvix_pct_252"].to_numpy(float)
        else:
            m = _model()
            m.fit(train[feats].to_numpy(float), train["target_vol"].to_numpy(float))
            p = m.predict(test[feats].to_numpy(float))
        pred[te_lo:te_hi] = p
        block_id[te_lo:te_hi] = b
    out = rows[["date", "target_vol", "next_ret"]].copy()
    out["risk_pred"] = pred
    out["block"] = block_id
    return out.dropna(subset=["risk_pred"]).reset_index(drop=True)


def _ic(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 20:
        return None, None
    return float(spearmanr(x[mask], y[mask]).correlation), float(pearsonr(x[mask], y[mask])[0])


def _position(oos: pd.DataFrame, rule: dict) -> np.ndarray:
    lo = oos["risk_pred"].quantile(rule["low_q"])
    hi = oos["risk_pred"].quantile(rule["high_q"])
    return np.where(
        oos["risk_pred"] >= hi,
        rule["high_pos"],
        np.where(oos["risk_pred"] <= lo, rule["low_pos"], rule["mid_pos"]),
    ).astype(float)


def _curve_stats(oos: pd.DataFrame, rule: dict, cost_bps: int) -> dict:
    pos = _position(oos, rule)
    turnover = np.abs(np.diff(np.r_[0.0, pos]))
    cost = turnover * cost_bps / 10000.0
    raw_ret = pos * oos["next_ret"].to_numpy(float)
    ret = pd.Series(raw_ret - cost, index=pd.to_datetime(oos["date"]))
    bh = pd.Series(oos["next_ret"].to_numpy(float), index=ret.index)
    eq = (1 + ret.fillna(0)).cumprod()
    bh_eq = (1 + bh.fillna(0)).cumprod()
    dd = eq / eq.cummax() - 1
    bh_dd = bh_eq / bh_eq.cummax() - 1
    years = max(len(eq) / 252, 1e-9)
    vol = ret.std() * math.sqrt(252)
    bh_vol = bh.std() * math.sqrt(252)
    return {
        "rule": rule["name"],
        "cost_bps": cost_bps,
        "total_ret": round((float(eq.iloc[-1]) - 1) * 100, 2),
        "buy_hold_ret": round((float(bh_eq.iloc[-1]) - 1) * 100, 2),
        "sharpe": round(float(ret.mean() * 252 / vol), 2) if vol and np.isfinite(vol) else None,
        "buy_hold_sharpe": round(float(bh.mean() * 252 / bh_vol), 2) if bh_vol and np.isfinite(bh_vol) else None,
        "max_dd": round(float(dd.min()) * 100, 2),
        "buy_hold_max_dd": round(float(bh_dd.min()) * 100, 2),
        "avg_position": round(float(np.mean(pos)), 2),
        "annual_turnover": round(float(turnover.sum() / years), 2),
    }


def _summarize(oos: pd.DataFrame, target: str, horizon: int, model_name: str) -> dict:
    ri, pi = _ic(oos["risk_pred"].to_numpy(float), oos["target_vol"].to_numpy(float))
    q = pd.qcut(oos["risk_pred"], 5, labels=False, duplicates="drop")
    with_q = oos.copy(); with_q["q"] = q
    bucket = with_q.groupby("q")["target_vol"].agg(["count", "mean", "median"]).reset_index()
    low = float(bucket.iloc[0]["mean"])
    high = float(bucket.iloc[-1]["mean"])
    block_ics = []
    for b, g in oos.groupby("block"):
        bri, bpi = _ic(g["risk_pred"].to_numpy(float), g["target_vol"].to_numpy(float))
        block_ics.append({"block": int(b), "n": int(len(g)), "rank_ic": round(bri, 4), "pearson_ic": round(bpi, 4)})
    strategies = []
    for rule in THRESHOLDS:
        for cost_bps in COST_BPS:
            strategies.append(_curve_stats(oos, rule, cost_bps))
    best = max(strategies, key=lambda x: (x["sharpe"] if x["sharpe"] is not None else -999, -abs(x["max_dd"])))
    return {
        "target": target,
        "target_name": TARGETS[target],
        "horizon": horizon,
        "model": model_name,
        "n_oos": int(len(oos)),
        "date_range": [str(oos["date"].iloc[0]), str(oos["date"].iloc[-1])],
        "rank_ic": round(ri, 4),
        "pearson_ic": round(pi, 4),
        "block_positive_frac": round(sum(x["rank_ic"] > 0 for x in block_ics) / len(block_ics), 3),
        "top_bottom_vol_spread": round(high - low, 2),
        "quantiles": [
            {"q": int(r["q"]), "n": int(r["count"]), "avg_vol": round(float(r["mean"]), 2), "median_vol": round(float(r["median"]), 2)}
            for _, r in bucket.iterrows()
        ],
        "block_ics": block_ics,
        "strategies": strategies,
        "best_strategy": best,
    }


def main():
    init_db()
    results = []
    for target in TARGETS:
        for horizon in HORIZONS:
            print(f"\n######## target={target} horizon={horizon} ########", flush=True)
            ds = build_dataset(target, horizon)
            print(f"rows={len(ds)} range={ds['date'].iloc[0]}..{ds['date'].iloc[-1]}", flush=True)
            for model_name, feats in FEATURE_SETS.items():
                print(f"\n=== {model_name} ({len(feats)} features) ===", flush=True)
                oos = _predict_oos(ds, model_name, feats, horizon)
                if oos.empty:
                    print("no OOS predictions", flush=True)
                    continue
                s = _summarize(oos, target, horizon, model_name)
                results.append(s)
                print(f"OOS {s['date_range'][0]}..{s['date_range'][1]} n={s['n_oos']}")
                print(f"RiskIC={s['rank_ic']} Pearson={s['pearson_ic']} block_pos={s['block_positive_frac']}")
                print(f"Top-Bottom vol spread={s['top_bottom_vol_spread']}")
                print(f"Best strategy={s['best_strategy']}")
                print("Block IC:", s["block_ics"])
                print("Quantiles:", s["quantiles"], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"horizons": HORIZONS, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT}", flush=True)


if __name__ == "__main__":
    main()
