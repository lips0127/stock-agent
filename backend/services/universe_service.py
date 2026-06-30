"""全市场舆情观测台（v4, 2026-06-06）。

职责：
- 维护 6 个 A 股指数（沪深300/上证50/中证1000/中证2000/创业板/科创50）的定义 + 成分股快照
- 每日全量对 6 指数的并集（约 3700 只去重股票）跑一遍 analyze_sentiment
- 写入每只股票在每个指数下的情绪快照（sentiment_universe_scores）
- 计算指数级聚合（avg_score / 分布 / 极端情绪计数）写入 sentiment_universe_aggregates
- 提供读 API 给前端市场情绪仪表盘（IndexDashboard）

设计约束：
- 复用现有 analyze_sentiment / GubaCircuitBreaker / batch_analyze
- DB schema 走 db_compat，未来切 MySQL 不改本文件
- akshare 失败兜底：csindex 优先 → spot（新浪源）过滤 code 前缀
"""

import json
import logging
import statistics
import threading
import time
from datetime import date as date_cls
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.core.database import (
    get_connection,
    upsert_universe_indices,
    upsert_universe_constituents,
    upsert_universe_job,
    upsert_universe_scores,
    upsert_universe_aggregates,
    get_universe_indices,
    get_universe_constituents_for_date,
    get_universe_jobs,
    get_universe_summary,
    get_universe_index_history,
    get_universe_constituent_scores,
    get_indicators,
    get_post_labels,
)

logger = logging.getLogger(__name__)


# ── universe 实时进度状态（v4, 2026-06-08） ─────────────────────────────
import threading as _threading
_UNIVERSE_BATCH_LOCK = _threading.Lock()
_UNIVERSE_BATCH_STATE: dict = {
    "running": False, "total": 0, "completed": 0, "failed": 0,
    "current": None, "current_name": None,
    "started_at": None, "finished_at": None,
}


def get_universe_batch_status() -> dict:
    """Universe 批量分析当前 in-memory 状态（仅本次会话内有效）。"""
    return dict(_UNIVERSE_BATCH_STATE)


# ── 6 指数 seed 数据 ──
SEED_INDICES: list[dict] = [
    {
        "code": "csi300", "name": "沪深300",
        "akshare_symbol": "000300", "akshare_method": "csindex",
        "akshare_filter": None, "priority": 1,
        "description": "沪深300指数（沪深两市市值最大 300 只）",
    },
    {
        "code": "sse50", "name": "上证50",
        "akshare_symbol": "000016", "akshare_method": "csindex",
        "akshare_filter": None, "priority": 2,
        "description": "上证50指数（上交所市值最大 50 只）",
    },
    {
        "code": "star50", "name": "科创50",
        "akshare_symbol": "000688", "akshare_method": "csindex",
        "akshare_filter": None, "priority": 3,
        "description": "科创50指数（科创板市值最大 50 只）",
    },
    {
        "code": "csi1000", "name": "中证1000",
        "akshare_symbol": "000852", "akshare_method": "csindex",
        "akshare_filter": None, "priority": 4,
        "description": "中证1000指数（中盘代表 1000 只）",
    },
    {
        "code": "chinext", "name": "创业板",
        "akshare_symbol": None, "akshare_method": "spot_filter",
        "akshare_filter": "30", "priority": 5,
        "description": "深交所创业板全部（code 前缀 30/301）",
    },
    {
        "code": "csi2000", "name": "中证2000",
        "akshare_symbol": "932004", "akshare_method": "csindex",
        "akshare_filter": None, "priority": 6,
        "description": "中证2000指数（小盘代表 2000 只）",
    },
]


def seed_indices() -> int:
    """启动时调用：把 6 个指数 seed 到 DB。已存在则更新 name/akshare_*。"""
    return upsert_universe_indices(SEED_INDICES)


def list_indices(enabled_only: bool = True) -> list[dict]:
    """读所有（或仅 enabled）指数。"""
    return get_universe_indices(enabled_only=enabled_only)


# ── 成分股刷新（akshare）──

def _fetch_index_constituents_akshare(idx_def: dict) -> list[dict]:
    """根据 akshare_method 调对应接口：
    - csindex: ak.index_stock_cons_weight_csindex(symbol=...)
    - spot_filter: ak.stock_zh_a_spot() 过滤 code 前缀（新浪源，2026-06-16
      替代东财 push2 域的 stock_zh_a_spot_em — 后者 RST 频繁）
    - 失败兜底：spot 过滤

    Returns: [{stock_code, stock_name, weight}]
    Raises: Exception（外层会捕获 + 记日志）
    """
    import akshare as ak
    from backend.services.stock_service import _no_proxy

    method = idx_def.get("akshare_method") or "csindex"
    symbol = idx_def.get("akshare_symbol")
    code_filter = idx_def.get("akshare_filter")  # e.g. "30" for chinext

    if method == "csindex" and symbol:
        try:
            with _no_proxy():
                df = ak.index_stock_cons_weight_csindex(symbol=symbol)
            if df is None or df.empty:
                raise ValueError(f"akshare 返回空 df for {idx_def['code']}")
            # akshare csindex 实际列（GBK）：日期, 指数代码, 指数名称, 指数英文名称,
            #   成分券代码, 成分券名称, 成分券英文名称, 交易所, 交易所英文名称, 权重
            # 必须用「成分券代码」匹配，跳过「指数代码」
            code_col = next((c for c in df.columns if "成分券代码" in c), None)
            if not code_col:
                # fallback: 找「代码」但跳过「指数代码」
                code_col = next((c for c in df.columns if "代码" in c and "指数" not in c), None)
            name_col = next((c for c in df.columns if "成分券名称" in c), None)
            if not name_col:
                name_col = next((c for c in df.columns if "名称" in c and "指数" not in c and "英文" not in c), None)
            weight_col = next((c for c in df.columns if "权重" in c), None)
            if not (code_col and name_col):
                raise ValueError(f"akshare 列名不匹配: {list(df.columns)}")
            out = []
            for _, row in df.iterrows():
                code = str(row[code_col]).strip()
                if not code.isdigit() or len(code) != 6:
                    continue
                out.append({
                    "stock_code": code.zfill(6),
                    "stock_name": str(row[name_col]).strip() if row[name_col] else "",
                    "weight": float(row[weight_col]) if weight_col and row[weight_col] else None,
                })
            return out
        except Exception as e:
            logger.warning(f"csindex 拉 {idx_def['code']} 失败: {e}，尝试 spot 兜底")
            # 兜底到 spot（如果 code_filter 已设）或用 symbol 在全市场搜
            if code_filter:
                idx_def = {**idx_def, "akshare_method": "spot_filter",
                           "akshare_filter": code_filter}
            else:
                # symbol 兜底：只拿 code 前 1 位 (0/3/6 区分交易所)
                idx_def = {**idx_def, "akshare_method": "spot_filter",
                           "akshare_filter": symbol[:1] if symbol else None}

    # spot_filter 路径（chinext / 兜底）
    # spot 接口（新浪源）偶尔 502 / ConnectionReset，加 3 次重试
    df = None
    last_err = None
    for attempt in range(3):
        try:
            with _no_proxy():
                df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_err = e
            logger.warning(f"spot 第 {attempt+1} 次失败: {e}, 重试...")
            time.sleep(2 + attempt * 2)
    if df is None or df.empty:
        raise ValueError(f"spot 3 次都失败: {last_err}")
    code_col = next((c for c in df.columns if c in ("代码", "code")), None)
    name_col = next((c for c in df.columns if c in ("名称", "name")), None)
    if not (code_col and name_col):
        raise ValueError(f"spot 列名不匹配: {list(df.columns)}")
    out = []
    for _, row in df.iterrows():
        # 新浪源 code 列带前缀（bj920000 / sh600000 / sz000001），剥成纯 6 位
        raw_code = str(row[code_col]).strip()
        code = raw_code[2:] if raw_code[:2] in ("sh", "sz", "bj") else raw_code
        if not code.isdigit() or len(code) != 6:
            continue
        if code_filter and not code.startswith(code_filter):
            continue
        out.append({
            "stock_code": code.zfill(6),
            "stock_name": str(row[name_col]).strip() if row[name_col] else "",
            "weight": None,
        })
    return out


def refresh_constituents(index_code: str | None = None,
                         date_str: str | None = None) -> dict:
    """从 akshare 拉指定（或全部 enabled）指数的成分股，写入 sentiment_universe_constituents。

    Returns: {"refreshed": [{"code","count"}], "skipped": [...], "errors": [...]}
    """
    if date_str is None:
        date_str = date_cls.today().isoformat()

    indices = get_universe_indices(enabled_only=True)
    if index_code:
        indices = [i for i in indices if i["code"] == index_code]
        if not indices:
            return {"refreshed": [], "skipped": [], "errors": [f"未知指数: {index_code}"]}

    refreshed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for idx in indices:
        try:
            t0 = time.time()
            cons = _fetch_index_constituents_akshare(idx)
            n = upsert_universe_constituents(idx["code"], date_str, cons)
            elapsed = time.time() - t0
            refreshed.append({"code": idx["code"], "name": idx["name"], "count": n,
                              "elapsed_s": round(elapsed, 1)})
            logger.info(f"成分股刷新 {idx['code']}: {n} 只 ({elapsed:.1f}s)")
        except Exception as e:
            logger.error(f"成分股刷新 {idx['code']} 失败: {e}", exc_info=True)
            errors.append({"code": idx["code"], "error": str(e)})
            skipped.append({"code": idx["code"], "reason": str(e)})

    return {"date": date_str, "refreshed": refreshed, "skipped": skipped, "errors": errors}


# ── 取某日 universe ──

def get_universe_for_date(date_str: str | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """取某日所有 enabled 指数的成分股并集 + 各股票所属的 index_code 列表。

    Returns:
        (stocks, index_map)
        - stocks: [{stock_code, stock_name, index_codes: ['csi300','sse50']}]
        - index_map: {index_code: [stock_code, ...]}
    """
    if date_str is None:
        date_str = date_cls.today().isoformat()

    by_index = get_universe_constituents_for_date(date_str)
    if not by_index:
        return [], {}

    # 反向：stock_code → [(index_code, name, weight)]
    rev: dict[str, dict] = {}
    for idx_code, members in by_index.items():
        for m in members:
            slot = rev.setdefault(m["stock_code"], {
                "stock_code": m["stock_code"],
                "stock_name": m["stock_name"],
                "index_codes": [],
                "_names": [],
            })
            slot["index_codes"].append(idx_code)
            if m["stock_name"] and not slot["stock_name"]:
                slot["stock_name"] = m["stock_name"]

    stocks = list(rev.values())
    # 去重 name（同名股票可能是不同指数里的不同名）
    for s in stocks:
        s.pop("_names", None)
    return stocks, by_index


# ── 主爬取（核心）──

def _prewarm_guba() -> bool:
    """预热 guba session（触发 _GUBA_SESSION warmup + 注入 bootstrap cookies）。"""
    try:
        from backend.services.forum_service import (
            fetch_forum_posts, _GUBA_CIRCUIT, _warmup_guba_session,
        )
        # 调一次轻量接口触发 warmup
        _warmup_guba_session()
        return _GUBA_CIRCUIT.state["state"] == "closed"
    except Exception as e:
        logger.warning(f"guba 预热失败: {e}")
        return False


def run_universe_crawl(date_str: str | None = None,
                       max_workers: int = 8,
                       stock_delay_s: float = 0.5,
                       index_code: str | None = None,
                       task_runner=None) -> dict:
    """对当日 universe 全量（或指定单指数）调 analyze_sentiment，聚合后写入 sentiment_universe_scores。

    流程：
    1. 预热 guba
    2. 取今日 universe（去重 + 拿各股票所属的 index_codes）；如果 index_code 给定，只取该指数
    3. ThreadPoolExecutor(max_workers=N) 调 analyze_sentiment
    4. 每完成 1 只：写 sentiment_universe_scores（按 (index_code, stock_code, date) 一行/指数）
    5. 更新 sentiment_universe_jobs 状态

    Returns: {"date": "...", "total": N, "ok": M, "failed": F, "duration_s": S, "errors": [...]}
    """
    from backend.services.sentiment_service import analyze_sentiment

    if date_str is None:
        date_str = date_cls.today().isoformat()

    t_start = time.time()
    _prewarm_guba()

    # 取 universe
    stocks, by_index = get_universe_for_date(date_str)
    if not stocks:
        return {"date": date_str, "total": 0, "ok": 0, "failed": 0,
                "duration_s": 0, "errors": ["无 universe 快照，请先 refresh_constituents"]}

    # 单指数过滤（手动 /api/sentiment/universe/run/<index_code>）
    if index_code:
        if index_code not in by_index:
            return {"date": date_str, "total": 0, "ok": 0, "failed": 0,
                    "duration_s": 0, "errors": [f"指数 {index_code} 无 universe 快照"]}
        target_codes = {m["stock_code"] for m in by_index[index_code]}
        stocks = [s for s in stocks if s["stock_code"] in target_codes]
        by_index = {index_code: by_index[index_code]}

    codes = [s["stock_code"] for s in stocks]
    code_to_name: dict[str, str] = {s["stock_code"]: (s.get("stock_name") or "") for s in stocks}
    logger.info(f"universe crawl 启动: date={date_str} total={len(codes)} "
                f"workers={max_workers} index={index_code or 'all'}")

    # 初始化 in-memory 实时进度（v4 2026-06-08）
    global _UNIVERSE_BATCH_STATE
    _UNIVERSE_BATCH_STATE = {
        "running": True, "total": len(codes), "completed": 0, "failed": 0,
        "current": None, "current_name": None,
        "started_at": time.time(), "finished_at": None,
    }
    if task_runner:
        task_runner.set_total(len(codes))
        task_runner.milestone(
            f"universe crawl 启动: date={date_str} total={len(codes)} workers={max_workers}"
        )

    # 对每个指数创建 job row（status=running）
    for idx_code in by_index.keys():
        upsert_universe_job(idx_code, date_str,
                            total_stocks=len(by_index[idx_code]),
                            status="running",
                            started_at=_now_ts(),
                            error_message=None)

    # 收集结果：code → analyze_sentiment result dict
    results: dict[str, dict | None] = {}
    errors: list[dict] = []

    def _analyze_one(code: str):
        try:
            r = analyze_sentiment(code)
            return r
        except Exception as e:
            logger.error(f"universe analyze {code} 异常: {e}", exc_info=True)
            return {"_error": True, "_reason": "internal", "_message": str(e)}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 平滑 QPS：在 submit 之间 sleep
        futures = {}
        for i, code in enumerate(codes):
            if i > 0 and stock_delay_s > 0:
                time.sleep(stock_delay_s)
            futures[executor.submit(_analyze_one, code)] = code
            _UNIVERSE_BATCH_STATE["current"] = code
            _UNIVERSE_BATCH_STATE["current_name"] = code_to_name.get(code, "")

        # 维护每只股票所属指数 → 该指数的完成进度
        # code → set(index_codes) 反查
        code_to_indices: dict[str, list[str]] = {s["stock_code"]: s["index_codes"] for s in stocks}
        per_idx_done: dict[str, int] = {idx: 0 for idx in by_index.keys()}
        per_idx_failed: dict[str, int] = {idx: 0 for idx in by_index.keys()}

        def _flush_jobs_to_db():
            for idx, n_done in per_idx_done.items():
                n_fail = per_idx_failed[idx]
                upsert_universe_job(idx, date_str,
                                    completed_stocks=n_done,
                                    failed_stocks=n_fail,
                                    status="running",
                                    error_message=None)

        last_log = [time.time()]
        last_flush = [time.time()]
        done = 0
        n_fail_total = 0
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"_error": True, "_message": str(e)}
            results[code] = r
            done += 1
            is_fail = bool(r and r.get("_error")) or not r
            if is_fail:
                n_fail_total += 1
            for idx in code_to_indices.get(code, []):
                if is_fail:
                    per_idx_failed[idx] += 1
                else:
                    per_idx_done[idx] += 1
            # in-memory 进度
            _UNIVERSE_BATCH_STATE["completed"] = done - n_fail_total
            _UNIVERSE_BATCH_STATE["failed"] = n_fail_total
            # 当前正在分析：挑一个还在 inflight 的
            in_flight_codes = [c for c, f in futures.items() if not f.done()]
            next_code = in_flight_codes[0] if in_flight_codes else None
            _UNIVERSE_BATCH_STATE["current"] = next_code
            _UNIVERSE_BATCH_STATE["current_name"] = code_to_name.get(next_code, "") if next_code else ""
            # 进度日志：每 10s 打一次
            if time.time() - last_log[0] > 10:
                logger.info(f"universe crawl 进度: {done}/{len(codes)}")
                last_log[0] = time.time()
            # 进度落库：每 5s 或每 25 只，刷一次（避免太频繁）
            if time.time() - last_flush[0] > 5 or done % 25 == 0:
                _flush_jobs_to_db()
                last_flush[0] = time.time()
            if task_runner:
                task_runner.progress(done)
        # 收尾落一次
        _flush_jobs_to_db()

    # 写 sentiment_universe_scores：每只股票按其所属指数拆成 N 行
    score_rows: list[dict] = []
    ok = 0
    failed = 0
    for stock in stocks:
        code = stock["stock_code"]
        r = results.get(code)
        if not r or r.get("_error"):
            failed += 1
            errors.append({"code": code, "reason": (r or {}).get("_reason", "unknown"),
                           "message": (r or {}).get("_message", "")})
            continue
        ok += 1
        signals = r.get("signals") or {}
        # 注意键名与 sentiment_service.analyze_sentiment 写入的 signals_json 对齐：
        # panic / euphoria / momentum_cross（不是 panic_2sigma/euphoria_2sigma）
        panic = 1 if signals.get("panic") else 0
        euph = 1 if signals.get("euphoria") else 0
        mom = 1 if signals.get("momentum_cross") else 0
        for idx_code in stock["index_codes"]:
            score_rows.append({
                "index_code": idx_code,
                "stock_code": code,
                "forum_type": "eastmoney",
                "date": date_str,
                "score": r.get("score"),
                "sentiment": r.get("sentiment"),
                "bullish_n": r.get("bullish", 0),
                "bearish_n": r.get("bearish", 0),
                "neutral_n": r.get("neutral", 0),
                "noise_n": r.get("noise", 0),
                "panic_signal": panic,
                "euphoria_signal": euph,
                "momentum_cross": mom,
                "ema3": (signals.get("ema3") if signals else None),
                "ema5": (signals.get("ema5") if signals else None),
                "source": "universe_crawl",
            })

    n_written = upsert_universe_scores(score_rows)

    # 更新各指数 job 状态
    duration = time.time() - t_start
    for idx_code, members in by_index.items():
        idx_failed = sum(1 for s in stocks
                         if s["stock_code"] in {m["stock_code"] for m in members}
                         and (results.get(s["stock_code"]) is None
                              or results.get(s["stock_code"], {}).get("_error")))
        idx_completed = sum(1 for m in members
                            if results.get(m["stock_code"])
                            and not results.get(m["stock_code"], {}).get("_error"))
        idx_failed = max(0, len(members) - idx_completed)
        status = "completed" if idx_failed == 0 else ("partial" if idx_completed > 0 else "failed")
        upsert_universe_job(idx_code, date_str,
                            completed_stocks=idx_completed,
                            failed_stocks=idx_failed,
                            status=status,
                            completed_at=_now_ts(),
                            error_message=json.dumps({"total_errors": idx_failed},
                                                     ensure_ascii=False)
                                          if idx_failed else None)

    logger.info(f"universe crawl 完成: date={date_str} ok={ok} failed={failed} "
                f"rows={n_written} duration={duration:.1f}s")
    _UNIVERSE_BATCH_STATE["running"] = False
    _UNIVERSE_BATCH_STATE["finished_at"] = time.time()
    _UNIVERSE_BATCH_STATE["current"] = None
    _UNIVERSE_BATCH_STATE["current_name"] = None
    if task_runner:
        task_runner.milestone(
            f"universe crawl 完成: ok={ok} failed={failed} rows={n_written} duration={duration:.1f}s"
        )
        task_runner.complete(result={
            "date": date_str,
            "total": len(codes),
            "ok": ok,
            "failed": failed,
            "rows_written": n_written,
            "duration_s": round(duration, 1),
        })

    return {
        "date": date_str,
        "total": len(codes),
        "ok": ok,
        "failed": failed,
        "rows_written": n_written,
        "duration_s": round(duration, 1),
        "errors": errors[:20],  # 截前 20 条
    }


# ── 指数级聚合 ──

def _compute_distribution(scores: list[float]) -> dict:
    """10 桶直方图: {"0-10": N, "10-20": N, ..., "90-100": N}"""
    bins = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50),
            (50, 60), (60, 70), (70, 80), (80, 90), (90, 100.1)]
    out = {f"{lo}-{int(hi) if hi < 100 else 100}": 0 for lo, hi in bins}
    for s in scores:
        if s is None:
            continue
        for lo, hi in bins:
            if lo <= s < hi:
                key = f"{lo}-{int(hi) if hi < 100 else 100}"
                out[key] += 1
                break
    return out


def compute_universe_aggregates(date_str: str | None = None) -> dict:
    """对当日每个 index_code：从 sentiment_universe_scores 计算统计量，写入 aggregates。

    Returns: {"date": "...", "indices": [{"code", "avg_score", "analyzed", "failed"}]}
    """
    if date_str is None:
        date_str = date_cls.today().isoformat()

    indices = get_universe_indices(enabled_only=True)
    _, by_index = get_universe_for_date(date_str)

    out: list[dict] = []
    for idx in indices:
        idx_code = idx["code"]
        members = by_index.get(idx_code, [])
        if not members:
            out.append({"code": idx_code, "name": idx["name"], "analyzed": 0, "failed": 0,
                        "reason": "no constituents"})
            continue
        # 读所有 stock 当日分数
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT score, sentiment, panic_signal, euphoria_signal,
                          momentum_cross, ema3, ema5
                   FROM sentiment_universe_scores
                   WHERE index_code=? AND date=?""",
                (idx_code, date_str),
            )
            rows = [dict(r) for r in cur.fetchall()]
        scores = [r["score"] for r in rows if r["score"] is not None]
        if not scores:
            out.append({"code": idx_code, "name": idx["name"], "analyzed": 0,
                        "total": len(members), "reason": "no scores"})
            upsert_universe_aggregates(idx_code, date_str, {
                "total_stocks": len(members),
                "analyzed_stocks": 0,
                "failed_stocks": len(members),
            })
            continue

        avg = round(statistics.mean(scores), 2)
        med = round(statistics.median(scores), 2)
        std = round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0
        bullish = sum(1 for s in scores if s >= 60)
        neutral = sum(1 for s in scores if 40 < s < 60)
        bearish = sum(1 for s in scores if s <= 40)
        panic = sum(1 for r in rows if r["panic_signal"])
        euph = sum(1 for r in rows if r["euphoria_signal"])
        mom = sum(1 for r in rows if r["momentum_cross"])
        ema3_vals = [r["ema3"] for r in rows if r["ema3"] is not None]
        ema5_vals = [r["ema5"] for r in rows if r["ema5"] is not None]
        avg_ema3 = round(statistics.mean(ema3_vals), 2) if ema3_vals else None
        avg_ema5 = round(statistics.mean(ema5_vals), 2) if ema5_vals else None
        dist = _compute_distribution(scores)

        agg = {
            "total_stocks": len(members),
            "analyzed_stocks": len(scores),
            "failed_stocks": len(members) - len(scores),
            "avg_score": avg,
            "median_score": med,
            "std_score": std,
            "bullish_count": bullish,
            "neutral_count": neutral,
            "bearish_count": bearish,
            "panic_count": panic,
            "euphoria_count": euph,
            "momentum_cross_count": mom,
            "avg_ema3": avg_ema3,
            "avg_ema5": avg_ema5,
            "distribution_json": json.dumps(dist, ensure_ascii=False),
        }
        upsert_universe_aggregates(idx_code, date_str, agg)
        out.append({
            "code": idx_code, "name": idx["name"],
            "analyzed": len(scores), "failed": len(members) - len(scores),
            "avg_score": avg, "panic_count": panic, "euphoria_count": euph,
        })

    return {"date": date_str, "indices": out}


# ── 读 API（前端用，直接转发 database 的 read）──

def get_summary(date_str: str | None = None) -> list[dict]:
    if date_str is None:
        date_str = date_cls.today().isoformat()
    return get_universe_summary(date_str)


def get_history(index_code: str, days: int = 60) -> list[dict]:
    return get_universe_index_history(index_code, days=days)


def get_constituents(index_code: str, date_str: str | None = None,
                     limit: int = 500, offset: int = 0) -> list[dict]:
    if date_str is None:
        date_str = date_cls.today().isoformat()
    return get_universe_constituent_scores(index_code, date_str, limit=limit, offset=offset)


def get_jobs(date_str: str | None = None) -> list[dict]:
    return get_universe_jobs(date_str)


# ── 工具 ──

def _now_ts() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# ── 模块加载时自动 seed（幂等）──
try:
    n = seed_indices()
    logger.info(f"universe seed_indices: 写入/更新 {n} 个指数")
except Exception as e:
    logger.warning(f"universe seed_indices 失败（忽略）: {e}")
