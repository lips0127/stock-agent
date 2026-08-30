"""大小盘拆分轨道（2026-08-30）：把 v7 构造真实情绪分作用到五条单指数轨道。

同一构造、同一权重（fear_greed_truth.score_components）：
  - drawdown 主导：该指数自身距 trailing 60 日高点的回撤深度
  - breadth：全市场跌停家数（共享分量，可得时）
  - iv_surge / iv_level：该指数对应场内期权 QVIX 的 5 日变化率 / 252 日分位
  五条轨道的 IV 锚与价格一一对应，无跨品种代替：
    sh50  上证50  = 上证50 指数 + 50ETF 期权
    hs300 沪深300 = 沪深300 指数 + 300ETF 期权
    zz500 中证500 = 中证500 指数 + 500ETF 期权
    cyb   创业板  = 创业板指 + 创业板ETF 期权
    kcb   科创50  = 科创50 指数 + 科创50ETF 期权

数据源：优先新浪 stock_zh_index_daily（单请求全历史），失败回退腾讯
stock_zh_index_daily_tx。全部 trailing 窗口，无未来泄漏。

percentile：每条轨道各自 trailing 252 交易日滚动百分位（point-in-time，
含当日自身的 self-inclusive 口径，与 recompute_percentiles 一致），
regime 用 classify_by_percentile 五档。本模块是观察口径，不是预测模型。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backend.core.database import get_connection, upsert_vix_tracks
from backend.data.vix_sources import (
    _cached_raw, fetch_index_daily_tx, fetch_limit_counts,
    ak_index_option_50etf_qvix, ak_index_option_300etf_qvix,
    ak_index_option_500etf_qvix, ak_index_option_cyb_qvix,
    ak_index_option_kcb_qvix,
)
from backend.services.fear_greed_truth import (
    _IV_SURGE_WIN, _LONG_DAYS, _Z_WINDOW, add_truth_features, score_components,
)

logger = logging.getLogger(__name__)

# track key -> 展示名 / 指数符号（sina 与 tx 两种）/ 对应期权 QVIX key。
# 2026-08-30 用户确认：不搞跨品种代替——五条轨道的 IV 锚与价格一一对应，
# 创业板、科创50 直接作为独立轨道（各自指数 + 各自 ETF 期权 IV）。
TRACKS: dict[str, dict] = {
    "sh50":  {"name": "上证50",   "tx_symbol": "sh000016", "sina_symbol": "sh000016",
              "qvix": "50etf", "iv_label": "IV 锚：50ETF 期权"},
    "hs300": {"name": "沪深300",  "tx_symbol": "sh000300", "sina_symbol": "sh000300",
              "qvix": "300etf", "iv_label": "IV 锚：300ETF 期权"},
    "zz500": {"name": "中证500",  "tx_symbol": "sh000905", "sina_symbol": "sh000905",
              "qvix": "500etf", "iv_label": "IV 锚：500ETF 期权"},
    "cyb":   {"name": "创业板",   "tx_symbol": "sz399006", "sina_symbol": "sz399006",
              "qvix": "cyb", "iv_label": "IV 锚：创业板ETF 期权"},
    "kcb":   {"name": "科创50",   "tx_symbol": "sh000688", "sina_symbol": "sh000688",
              "qvix": "kcb", "iv_label": "IV 锚：科创50ETF 期权"},
}

_QVIX_FETCHERS = {
    "50etf":  ak_index_option_50etf_qvix,
    "300etf": ak_index_option_300etf_qvix,
    "500etf": ak_index_option_500etf_qvix,
    "cyb":    ak_index_option_cyb_qvix,
    "kcb":    ak_index_option_kcb_qvix,
}

# 广度分量的逐日补抓上限：只对目标日期里最近 N 个缺失日尝试东财涨跌停池，
# 更早的历史与总体 v7 口径一致地缺广度（页面如实显示「缺」）。
_LIMIT_FETCH_BACKTRACK = 90


def _fetch_index_frame(track_key: str) -> Optional[pd.DataFrame]:
    """单指数日线 [date, close]（全历史），新浪优先、腾讯兜底。

    2026-08-30 实测：东财 index_zh_a_hist 在本机网络不可达；新浪
    stock_zh_index_daily 对 000016/000300/000905/399006/000688 全历史可用；
    腾讯分页抓取极慢作最后兜底。
    新浪返回的绝对价格带固定倍数，构造只用比率（回撤/均线偏离/动量），无影响。
    返回已排序去重的 DataFrame；全部源失败返回 None（该轨道本轮跳过）。
    """
    meta = TRACKS[track_key]
    df = None
    try:
        import akshare as ak
        raw = _cached_raw(
            f"sina_idx:{meta['sina_symbol']}",
            lambda: ak.stock_zh_index_daily(symbol=meta["sina_symbol"]),
        )
        if raw is not None and not raw.empty and "close" in raw.columns:
            df = raw[["date", "close"]].copy()
    except Exception as e:
        logger.warning(f"tracks {track_key}: 新浪日线失败: {e}")
    if df is None or df.empty:
        df = fetch_index_daily_tx(meta["tx_symbol"], days=_LONG_DAYS)
        if df is not None and not df.empty:
            df = df[["date", "close"]].copy()
    if df is None or df.empty:
        logger.warning(f"tracks {track_key}: 指数日线所有源均不可用")
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna().drop_duplicates("date").reset_index(drop=True)


def _fetch_qvix_series(qvix_key: str) -> Optional[pd.DataFrame]:
    """单个 ETF QVIX → [date, iv, chg5, pct252]（trailing，无未来泄漏）。"""
    fn = _QVIX_FETCHERS.get(qvix_key)
    if fn is None:
        return None
    raw = _cached_raw(f"qvix:{qvix_key}", fn)
    if raw is None or raw.empty or "close" not in raw.columns:
        return None
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["iv"] = pd.to_numeric(df["close"], errors="coerce")
    df = df[["date", "iv"]].dropna().drop_duplicates("date").sort_values("date")
    return _add_qvix_derived(df).reset_index(drop=True)


def _add_qvix_derived(df: pd.DataFrame) -> pd.DataFrame:
    """在 [date, iv] 序列上追加 chg5（5 日变化率）与 pct252（252 日分位）。"""
    df = df.copy()
    df["chg5"] = df["iv"].pct_change(_IV_SURGE_WIN) * 100.0
    df["pct252"] = df["iv"].rolling(_Z_WINDOW).rank(pct=True) * 100.0
    return df


def _target_dates() -> list[str]:
    """目标日期集 = vix_history 已有日期（均为交易日，非交易日行由重算路径清理）。"""
    with get_connection() as conn:
        return [r[0] for r in conn.execute(
            "SELECT date FROM vix_history ORDER BY date ASC"
        ).fetchall()]


def _limit_down_map(target_dates: list[str]) -> dict[str, int]:
    """跌停家数映射：优先 vix_history 中 limit_source='real' 的行，
    最近 _LIMIT_FETCH_BACKTRACK 个缺失日逐日补抓东财涨跌停池；失败则缺省。"""
    limit_map: dict[str, int] = {}
    with get_connection() as conn:
        for r in conn.execute(
            "SELECT date, limit_down_count FROM vix_history "
            "WHERE limit_source = 'real' AND limit_down_count IS NOT NULL"
        ).fetchall():
            limit_map[r[0]] = int(r[1])

    missing = [d for d in target_dates if d not in limit_map]
    for d in missing[-_LIMIT_FETCH_BACKTRACK:]:
        try:
            counts = fetch_limit_counts(d)
        except Exception as e:
            logger.debug(f"tracks 广度补抓 {d} 失败: {e}")
            continue
        if counts and counts.get("limit_down_count") is not None:
            limit_map[d] = int(counts["limit_down_count"])
    return limit_map


def _compute_track_rows(target_dates: list[str], limit_map: dict[str, int],
                        frames: dict[str, pd.DataFrame],
                        qvix_series: dict[str, pd.DataFrame]) -> list[dict]:
    """逐日 × 逐轨道套用 v7 评分核心，输出待入库行（不含 percentile）。

    qvix_series 以 "|".join(qvix_keys) 为键（多只 IV 已等权合成）。
    """
    rows: list[dict] = []
    for d in target_dates:
        ld = limit_map.get(d)
        for track_key, meta in TRACKS.items():
            frame = frames.get(track_key)
            if frame is None:
                continue
            idx_rows = frame.index[frame["date"] == d]
            if len(idx_rows) == 0:
                continue  # 指数序列缺该日（数据源滞后），保留旧值
            r = frame.loc[idx_rows[0]]
            iv = qvix_series.get(meta["qvix"])
            chg5 = pct252 = None
            if iv is not None:
                iv_rows = iv.index[iv["date"] == d]
                if len(iv_rows) > 0:
                    ir = iv.loc[iv_rows[0]]
                    chg5 = None if pd.isna(ir["chg5"]) else float(ir["chg5"])
                    pct252 = None if pd.isna(ir["pct252"]) else float(ir["pct252"])
            out = score_components(
                r["drawdown_60"], r["uptrend"],
                iv_surge_chg5=chg5, iv_level_pct=pct252, limit_down_count=ld,
            )
            fear = out["fear_truth"]
            rows.append({
                "date": d,
                "track": track_key,
                "fear": fear,
                "greed": round(100.0 - fear, 2),
                "drawdown": out["comp_drawdown"],
                "breadth": out["comp_breadth"],
                "iv_surge": out["comp_iv_surge"],
                "iv_level": out["comp_iv_level"],
                "uptrend": 1 if out["regime"] == "uptrend" else 0,
                "breadth_available": 1 if out["breadth_available"] else 0,
            })
    return rows


def _recompute_track_percentiles(window: int = 252) -> int:
    """全表重算各轨道 greed 的 trailing 252 日滚动百分位 + regime（point-in-time）。"""
    from backend.services.vix_service import classify_by_percentile

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, track, greed, fear, drawdown, breadth, iv_surge, iv_level, "
            "uptrend, breadth_available FROM vix_track_history ORDER BY track, date"
        ).fetchall()
        by_track: dict[str, list] = {}
        for r in rows:
            by_track.setdefault(r["track"], []).append(dict(r))

        updates = []
        for track, trows in by_track.items():
            hist: list[float] = []
            for tr in trows:
                greed = tr.get("greed")
                if greed is not None:
                    hist.append(float(greed))
                window_hist = hist[-window:]
                if greed is None:
                    pct = None
                elif len(window_hist) < 5:
                    pct = 50.0
                else:
                    pct = round(
                        sum(1 for v in window_hist if v <= greed) / len(window_hist) * 100, 1
                    )
                updates.append((
                    pct, classify_by_percentile(pct), tr["date"], track,
                ))
        conn.executemany(
            "UPDATE vix_track_history SET percentile = ?, regime = ? WHERE date = ? AND track = ?",
            updates,
        )
    return len(updates)


def recompute_track_history(task_runner=None) -> dict:
    """重建全部拆分轨道行并重算百分位。

    逐日打分是纯内存计算（日期 × 5 轨道），耗时在外部序列抓取（进程内缓存
    TTL 30 分钟覆盖整轮）。幂等：INSERT OR REPLACE，可重复执行。
    返回 {"dates": N, "rows": M, "percentiles": K, "tracks": [...]}。
    """
    target_dates = _target_dates()
    if not target_dates:
        return {"dates": 0, "rows": 0, "percentiles": 0, "tracks": list(TRACKS)}

    if task_runner is not None:
        task_runner.milestone(f"拆分轨道: 构建指数序列（{len(TRACKS)} 条轨道）")

    frames: dict[str, pd.DataFrame] = {}
    for track_key in TRACKS:
        f = _fetch_index_frame(track_key)
        if f is not None:
            frames[track_key] = add_truth_features(f)

    # 每条轨道各自的 IV 锚（键 = qvix key）
    qvix_series: dict[str, pd.DataFrame] = {}
    for meta in TRACKS.values():
        key = meta.get("qvix")
        if key and key not in qvix_series:
            s = _fetch_qvix_series(key)
            if s is not None:
                qvix_series[key] = s

    if task_runner is not None:
        task_runner.milestone("拆分轨道: 广度分量（vix_history + 近期补抓）")
    limit_map = _limit_down_map(target_dates)

    if task_runner is not None:
        task_runner.set_total(len(target_dates))
        task_runner.milestone(f"拆分轨道: 逐日打分（{len(target_dates)} 日）")
    rows = _compute_track_rows(target_dates, limit_map, frames, qvix_series)

    if task_runner is not None:
        task_runner.milestone(f"拆分轨道: 入库 {len(rows)} 行并重算百分位")
    upsert_vix_tracks(rows)
    pct_count = _recompute_track_percentiles()

    logger.info(
        f"recompute_track_history: {len(target_dates)} 日 × {len(TRACKS)} 轨道, "
        f"{len(rows)} 行, 百分位 {pct_count} 条"
    )
    return {
        "dates": len(target_dates), "rows": len(rows),
        "percentiles": pct_count, "tracks": list(TRACKS),
    }
