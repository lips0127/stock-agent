"""仅回填 vix_history 的 v7.0 construct-truth 列（不重算 v6.1）。

v7.0 只需上证综指 + QVIX 长历史 + 已有跌停家数，因此建一次 truth 序列后逐日
UPDATE，避免逐日重拉 v6.1 全部分量。

用法:
  ./venv_new/Scripts/python.exe -m scripts.backfill_vix_v7
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from backend.services.fear_greed_truth import build_truth_series, truth_score_as_of
from backend.core.database import init_db


def main() -> None:
    init_db()  # 确保 v7.0 列迁移已执行
    print("构建 truth 序列（一次）…")
    series = build_truth_series()
    if series is None:
        print("truth 序列为空，退出")
        return

    con = sqlite3.connect("stocks.db")
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT date, limit_down_count, limit_source FROM vix_history ORDER BY date").fetchall()
    print(f"待回填 {len(rows)} 行")

    done = 0
    for r in rows:
        d = r["date"]
        ld = r["limit_down_count"]
        ld_arg = float(ld) if (r["limit_source"] == "real" and ld is not None) else None
        t = truth_score_as_of(d, limit_down_count=ld_arg, cached=series)
        if t is None:
            continue
        con.execute(
            "UPDATE vix_history SET fear_truth_v7=?, fear_greed_v7=?, "
            "comp_drawdown_v7=?, comp_breadth_v7=?, comp_iv_surge_v7=?, "
            "comp_iv_level_v7=?, regime_v7=? WHERE date=?",
            (t.get("fear_truth"), t.get("greed_v7"), t.get("comp_drawdown"),
             t.get("comp_breadth"), t.get("comp_iv_surge"), t.get("comp_iv_level"),
             t.get("regime"), d),
        )
        done += 1
    con.commit()
    con.close()
    print(f"v7.0 回填完成：{done}/{len(rows)}")


if __name__ == "__main__":
    main()
