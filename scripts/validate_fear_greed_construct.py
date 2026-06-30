"""恐惧贪婪构造效度校验（v7.0 + VIX2 重定向共用底座）。

用 construct-truth 恐惧分（价格回撤锚 + 体制门控 + IV 飙升 + 广度崩塌）作为
“市场真实情绪”锚，量化 v6.1 手工版与 VIX2 ML 版的构造效度 gap。

事件锚点（真实情绪已知）：
  - 2025-04-07 上证 3096，关税千股跌停 → 应最恐慌
  - 2026-03-23 上证 3813 → 价格高得多，不应比 4-07 更恐
  - 2025-08 中下旬高位上涨 → 不应进恐慌区

用法:
  ./venv_new/Scripts/python.exe -m scripts.validate_fear_greed_construct
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backend.services.fear_greed_truth import build_truth_series

ANCHORS = ["2025-04-07", "2025-04-08", "2026-03-20", "2026-03-23", "2026-03-24",
           "2025-08-08", "2025-08-15", "2025-08-22", "2025-08-25", "2025-08-29"]

# 锚点日的已知跌停广度（人工事件标注，仅用于构造效度校验，不进 live 计算）。
# akshare 跌停池只能取近 30 天，历史日拿不到；4-07 为关税日千股跌停（~2900 家），
# 3-23 为急跌但非千股跌停，8 月高位段基本无跌停。
ANCHOR_BREADTH_KNOWN = {
    "2025-04-07": 2900,
    "2025-04-08": 1500,
    "2026-03-20": 60,
    "2026-03-23": 180,
    "2026-03-24": 120,
    "2025-08-08": 5,
    "2025-08-15": 3,
    "2025-08-22": 2,
    "2025-08-25": 2,
    "2025-08-29": 3,
}

OUT = Path("data/research/fear_greed_construct.json")


def _fetch_limit_down(dates: list[str]) -> pd.DataFrame:
    """锚点日跌停广度：优先 akshare 实时（仅近 30 天可得），否则用已知事件标注。"""
    import akshare as ak
    rows = []
    for d in dates:
        ld = None
        try:
            df = ak.stock_zt_pool_dtgc_em(date=d.replace("-", ""))
            if df is not None and not df.empty:
                ld = len(df)
        except Exception:
            pass
        if ld is None and d in ANCHOR_BREADTH_KNOWN:
            ld = ANCHOR_BREADTH_KNOWN[d]
        rows.append({"date": d, "limit_down_count": ld if ld is not None else np.nan})
    return pd.DataFrame(rows)


def _load_v61_fg() -> pd.DataFrame:
    con = sqlite3.connect("stocks.db")
    df = pd.read_sql("SELECT date, fear_greed, composite_score FROM vix_history", con)
    con.close()
    df["v61_fear"] = 100.0 - df["fear_greed"]
    return df


def _load_vix2() -> pd.DataFrame | None:
    try:
        con = sqlite3.connect("stocks.db")
        df = pd.read_sql("SELECT date, score FROM vix2_history", con)
        con.close()
        return df.rename(columns={"score": "vix2_score"})
    except Exception:
        return None


def _spearman(a: pd.Series, b: pd.Series) -> float:
    mask = a.notna() & b.notna()
    if mask.sum() < 10:
        return float("nan")
    return float(a[mask].rank().corr(b[mask].rank()))


def main() -> None:
    print("构建 construct-truth 恐惧分序列（含锚点日真实跌停广度）…")
    ld = _fetch_limit_down(ANCHORS)
    truth = build_truth_series(limit_down=ld)
    if truth is None:
        print("truth 序列为空，退出")
        return

    v61 = _load_v61_fg()
    vix2 = _load_vix2()

    merged = truth.merge(v61[["date", "fear_greed", "v61_fear"]], on="date", how="left")
    if vix2 is not None:
        merged = merged.merge(vix2, on="date", how="left")

    # —— 锚点表 ——
    print("\n=== 事件锚点（fear 越大越恐慌；v61_fear=100-fg）===")
    cols = ["date", "close", "fear_truth", "comp_drawdown", "comp_breadth",
            "comp_iv_surge", "comp_iv_level", "regime", "v61_fear"]
    if vix2 is not None:
        cols.append("vix2_score")
    anchor_tbl = merged[merged["date"].isin(ANCHORS)][cols].sort_values("date")
    print(anchor_tbl.to_string(index=False))

    print("\n关键反例检验：")
    a = merged.set_index("date")
    f407 = a.loc["2025-04-07", "fear_truth"] if "2025-04-07" in a.index else np.nan
    f323 = a.loc["2026-03-23", "fear_truth"] if "2026-03-23" in a.index else np.nan
    v407 = a.loc["2025-04-07", "v61_fear"] if "2025-04-07" in a.index else np.nan
    v323 = a.loc["2026-03-23", "v61_fear"] if "2026-03-23" in a.index else np.nan
    print(f"  4-07 vs 3-23 truth fear: {f407} vs {f323}  → 4-07 应更恐: {f407 > f323}")
    print(f"  4-07 vs 3-23 v6.1  fear: {v407} vs {v323}  → v6.1 判 3-23 更恐: {v323 > v407}")
    aug = a.loc[[d for d in ["2025-08-15", "2025-08-22", "2025-08-25"] if d in a.index]]
    if not aug.empty:
        print(f"  8月高位段 truth fear: {aug['fear_truth'].round(1).tolist()} (应低，不进恐区)")
        print(f"  8月高位段 v6.1  fear: {aug['v61_fear'].round(1).tolist()}")

    # —— 整体 rank 相关 ——
    print("\n=== 整体构造效度（rank 相关，越高越贴近真实情绪）===")
    print(f"  truth vs v6.1 fear  spearman: {_spearman(merged['fear_truth'], merged['v61_fear']):.4f}")
    if vix2 is not None:
        print(f"  truth vs vix2 score spearman: {_spearman(merged['fear_truth'], merged['vix2_score']):.4f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "anchors": anchor_tbl.to_dict(orient="records"),
        "case_407_gt_323_truth": bool(f407 > f323),
        "v61_judges_323_more_fearful": bool(v323 > v407),
        "spearman_truth_v61": _spearman(merged["fear_truth"], merged["v61_fear"]),
        "spearman_truth_vix2": _spearman(merged["fear_truth"], merged["vix2_score"]) if vix2 is not None else None,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {OUT}")


if __name__ == "__main__":
    main()
