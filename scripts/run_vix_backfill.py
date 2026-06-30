"""一次性 VIX v6.1 全量回填脚本（带逐日进度日志，便于监控）。

用法：python -m scripts.run_vix_backfill [days]
日志写入 scripts/vix_backfill_progress.log（每日一行，立即 flush）。
"""
import sys
import time
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

from backend.core.database import get_connection, upsert_vix_history
from backend.services.vix_service import (
    compute_today_snapshot, _is_trading_day, recompute_percentiles,
)

LOG_PATH = "scripts/vix_backfill_progress.log"


def log(msg: str):
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
    print(line, flush=True)


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 356
    today = datetime.now()
    candidates = []
    for i in range(0, days * 2):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if _is_trading_day(d):
            candidates.append(d)
    candidates = candidates[:days]
    candidates.reverse()  # oldest -> newest

    open(LOG_PATH, "w", encoding="utf-8").close()  # 清空
    log(f"开始回填 {len(candidates)} 个交易日 ({candidates[0]} ~ {candidates[-1]})")
    t0 = time.time()
    done = failed = 0
    for idx, d in enumerate(candidates):
        try:
            snap = compute_today_snapshot(d, require_multi=True)
            if snap is None:
                failed += 1
                log(f"[{idx+1}/{len(candidates)}] {d} SKIP: 多ETF合成失败，保留旧值")
                continue
            upsert_vix_history(snap.date, snap.to_db_payload())
            done += 1
            if (idx + 1) % 10 == 0 or idx == 0:
                log(f"[{idx+1}/{len(candidates)}] {d} vix={snap.vix} "
                    f"comp={snap.composite_score} ({time.time()-t0:.0f}s)")
        except Exception as e:
            failed += 1
            log(f"[{idx+1}/{len(candidates)}] {d} ERROR: {type(e).__name__}: {e}")

    log(f"回填完成: done={done} failed={failed} elapsed={time.time()-t0:.0f}s")
    log("开始重算百分位...")
    res = recompute_percentiles()
    log(f"百分位重算完成: {res}")
    log("ALL DONE")


if __name__ == "__main__":
    main()
