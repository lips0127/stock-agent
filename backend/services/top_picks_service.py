"""
热门股自动发现服务（v4, 2026-06-16）。

职责：
- 每日拉取全市场 A 股的成交额排名
- 取 top N（默认 100）写入 sentiment_top_picks
- 可选自动加入 sentiment_config（auto_add=True 时）
- 提供 API：list / refresh / toggle auto-add

数据源：akshare ``stock_zh_a_spot``（新浪源，v3 之前是东财
``stock_zh_a_spot_em``，2026-06-16 切换 — 东财 push2 域对
盘后大流量接口会主动 RST）。
"""

import logging
import time
from datetime import date as date_cls
from backend.core.database import (
    upsert_top_picks, get_latest_top_picks, mark_top_pick_auto_added,
    add_sentiment_config, get_connection,
)
from backend.services.stock_service import _no_proxy
from backend.services.sentiment_service import analyze_sentiment

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 100


def fetch_top_picks(top_n: int = DEFAULT_TOP_N) -> list[dict]:
    """从新浪拉取当日 A 股成交额 top N。

    Returns:
        [{stock_code, stock_name, rank, amount}]

    注：全局 ``install_proxy_bypass()`` 已保证不走系统代理；此处
    ``with _no_proxy():`` 仅作为显式语义标注，便于代码阅读。
    """
    # 新浪源（ak.stock_zh_a_spot）盘后大流量下偶发 502 / ConnectionReset，
    # 加 3 次指数退避重试（与 universe_service 的 spot_filter 路径一致）。
    df = None
    last_err = None
    import akshare as ak
    for attempt in range(3):
        try:
            with _no_proxy():
                df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_err = e
            logger.warning(f"top_picks 拉全市场行情第 {attempt+1} 次失败: {e}, 重试...")
            time.sleep(2 + attempt * 2)
    if df is None or df.empty:
        logger.error(f"拉取全市场行情 3 次均失败: {last_err}", exc_info=False)
        return []

    # ak.stock_zh_a_spot 列名：['代码', '名称', '最新价', '涨跌幅', '涨跌额',
    # '成交量', '成交额', '振幅', '最高', '最低', '今开', '昨收', '量比', '换手率', '时间戳']
    # 兼容不同版本：按列名匹配
    code_col = _pick_col(df, ["代码", "code"])
    name_col = _pick_col(df, ["名称", "name"])
    amount_col = _pick_col(df, ["成交额", "amount"])
    if not (code_col and name_col and amount_col):
        logger.error(f"akshare 行情列名不匹配: {list(df.columns)}")
        return []

    df_sorted = df.sort_values(amount_col, ascending=False).head(top_n)
    out = []
    for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
        # 新浪源 code 列带前缀（bj920000 / sh600000 / sz000001），剥成纯 6 位
        raw_code = str(row[code_col]).strip()
        code = raw_code[2:] if raw_code[:2] in ("sh", "sz", "bj") else raw_code
        code = code.zfill(6)
        if not code.isdigit() or len(code) != 6:
            continue
        out.append({
            "stock_code": code,
            "stock_name": str(row[name_col]).strip(),
            "rank": rank,
            "amount": float(row[amount_col]) if row[amount_col] else 0.0,
        })
    return out


def _pick_col(df, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def refresh_top_picks(top_n: int = DEFAULT_TOP_N,
                      auto_add: bool = False,
                      source: str = "volume_top100") -> dict:
    """刷新 top picks 池。

    Args:
        top_n: 取前 N
        auto_add: 是否把新出现的股票自动加入 sentiment_config
        source: 来源标识（volume_top100 / volume_top50 / ...）

    Returns:
        {"snapshot_date": "2026-06-06", "count": 100, "auto_added": 5}
    """
    picks = fetch_top_picks(top_n)
    if not picks:
        return {"snapshot_date": date_cls.today().isoformat(),
                "count": 0, "auto_added": 0}

    snapshot_date = date_cls.today().isoformat()
    n_written = upsert_top_picks(snapshot_date, picks, source=source)
    logger.info(f"top_picks 写入: date={snapshot_date} n={n_written} top_n={top_n}")

    auto_added = 0
    if auto_add:
        # 找出本批新出现的（DB 里之前没在 sentiment_config 的）→ 自动加入
        from backend.core.database import get_sentiment_configs
        existing = {c["stock_code"] for c in get_sentiment_configs()}
        for p in picks:
            if p["stock_code"] not in existing:
                r = add_sentiment_config(
                    p["stock_code"], "eastmoney", p["stock_name"]
                )
                if r:
                    mark_top_pick_auto_added(p["stock_code"], snapshot_date)
                    auto_added += 1
                    existing.add(p["stock_code"])  # 避免同批重复 add
        logger.info(f"top_picks auto_add 新增 {auto_added} 只")

    return {
        "snapshot_date": snapshot_date,
        "count": len(picks),
        "auto_added": auto_added,
    }


def list_top_picks(snapshot_date: str | None = None) -> list[dict]:
    """获取某日（默认最新）top picks 列表 + 是否已在 sentiment_config 中。"""
    picks = get_latest_top_picks(snapshot_date)
    if not picks:
        return []
    # 标注 is_monitored
    from backend.core.database import get_sentiment_configs
    monitored = {c["stock_code"] for c in get_sentiment_configs()}
    for p in picks:
        p["is_monitored"] = p["stock_code"] in monitored
        p.pop("auto_added", None)  # 前端不需要这个内部字段
    _attach_latest_sentiment(picks)
    return picks


def _attach_latest_sentiment(picks: list[dict]) -> None:
    """给 top picks 补最新情绪分，便于前端判断热点股是否已纳入因子。"""
    codes = [p["stock_code"] for p in picks if p.get("stock_code")]
    if not codes:
        return
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT s.*
        FROM sentiment_scores s
        JOIN (
            SELECT stock_code, MAX(date) AS max_date
            FROM sentiment_scores
            WHERE forum_type='eastmoney' AND stock_code IN ({placeholders})
            GROUP BY stock_code
        ) latest
          ON latest.stock_code=s.stock_code AND latest.max_date=s.date
        WHERE s.forum_type='eastmoney'
    """
    with get_connection() as conn:
        rows = conn.execute(sql, codes).fetchall()
    by_code = {r["stock_code"]: dict(r) for r in rows}
    for p in picks:
        row = by_code.get(p.get("stock_code"))
        p["sentiment_date"] = row.get("date") if row else None
        p["sentiment"] = row.get("sentiment") if row else None
        p["score"] = row.get("score") if row else None
        p["post_count"] = row.get("post_count") if row else None
        p["summary"] = row.get("summary") if row else None


def analyze_top_picks(limit: int = 20, task_runner=None) -> dict:
    """分析当前最新热门股 top N，结果写入 sentiment_scores / indicators。

    v2 2026-06-29：改并发（ThreadPoolExecutor, max_workers=5，与 batch_analyze
    一致），并支持 task_runner 协作式取消。串行 20 只 × ~25s 的耗时不可接受。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    picks = get_latest_top_picks(limit=max(1, min(int(limit), 100)))
    if not picks:
        return {"total": 0, "ok": 0, "failed": 0, "reason": "no_top_picks"}

    if task_runner:
        task_runner.set_total(len(picks))
        task_runner.milestone(f"开始分析热门股 top {len(picks)}")

    ok = 0
    failed = 0
    done = 0

    def _analyze_one(pick):
        code = pick["stock_code"]
        try:
            result = analyze_sentiment(code, "eastmoney")
            if result and not result.get("_error"):
                return code, True
            logger.warning("热门股分析失败: %s %s", code, result)
            return code, False
        except Exception as e:
            logger.error(f"热门股分析异常: {code}: {e}", exc_info=True)
            return code, False

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_analyze_one, p): p for p in picks}
        for future in as_completed(futures):
            if task_runner:
                task_runner.check_cancelled()
            _, success = future.result()
            if success:
                ok += 1
            else:
                failed += 1
            done += 1
            if task_runner:
                task_runner.progress(done)

    result = {"total": len(picks), "ok": ok, "failed": failed}
    return result
