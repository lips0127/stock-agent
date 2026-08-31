import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import time
from datetime import datetime
import functools
import threading
from backend.tasks.market_scan import scan_dividend_index
from backend.config import (
    SCAN_MAX_WORKERS, SCHEDULER_MAX_RETRIES, SCHEDULER_RETRY_INTERVAL,
    UNIVERSE_CRAWL_MAX_WORKERS, UNIVERSE_CRAWL_STOCK_DELAY_S,
    SENTIMENT_TOP_PICKS_ANALYZE_LIMIT,
)
# 注：v5 之后调度时间由 scheduler_task_config 表控制（env 仅作 seed 时的默认值）。
# 真正的默认值在 backend/services/scheduler_config_service.py:JOB_REGISTRY 里。

logger = logging.getLogger("scheduler")

_task_logs_lock = threading.Lock()
task_logs = []

_scan_lock = threading.Lock()
_scan_running = False

_forum_prefetch_lock = threading.Lock()
_forum_prefetch_running = False

_universe_cons_lock = threading.Lock()
_universe_cons_running = False

_universe_crawl_lock = threading.Lock()
_universe_crawl_running = False

_universe_agg_lock = threading.Lock()
_universe_agg_running = False


def log_message(msg: str) -> None:
    from datetime import datetime
    logger.info(msg)
    entry = {"time": datetime.now().isoformat(), "message": msg}
    with _task_logs_lock:
        task_logs.append(entry)
        if len(task_logs) > 1000:
            task_logs.pop(0)


# ── 运行追踪装饰器（v5, 2026-06-07）：把每次任务触发写进 scheduler_task_run
#                    v6, 2026-06-10）：同时写进 task_runs（TaskRunner 统一任务台） ──

def track_run(job_id: str):
    """装饰一个 scheduler task 函数；记录 start / success / failed / skipped 到 DB。

    - 抛异常 → status='failed'，message=str(e)[:500]
    - 函数返回 'skipped' → status='skipped'（用于 lock 冲突早退场景）
    - 其他返回值（None / 'success'） → status='success'

    同时使用 TaskRunner 把每次执行记入 task_runs（用于前端统一任务中心）。
    """
    from backend.core.database import record_run_start, record_run_finish
    from backend.core.task_runner import TaskRunner

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = datetime.now().isoformat(timespec="seconds")
            run_id = record_run_start(job_id, started)
            with TaskRunner(
                kind=job_id,
                title=func.__name__,
                scheduler_job=job_id,
                triggered_by="scheduler",
            ) as t:
                t.set_current("执行中")
                try:
                    result = func(*args, **kwargs)
                    status = "skipped" if result == "skipped" else "success"
                    finished = datetime.now().isoformat(timespec="seconds")
                    record_run_finish(run_id, finished, status, None)
                    if status == "skipped":
                        t.milestone("skipped (lock 冲突或早退)")
                    else:
                        t.milestone("scheduler tick 完成")
                    t.complete(result={"status": status})
                    return result
                except Exception as e:
                    finished = datetime.now().isoformat(timespec="seconds")
                    record_run_finish(run_id, finished, "failed", str(e)[:500])
                    t.fail(str(e)[:500])
                    raise
        return wrapper
    return decorator


@track_run("daily_update")
def daily_update_task():
    """每日红利指数扫描任务（工作日定时触发）。"""
    global _scan_running
    with _scan_lock:
        if _scan_running:
            log_message("Scan already running, skipping")
            return "skipped"
        _scan_running = True

    try:
        log_message("Starting daily dividend index scan")
        last_err = None
        for attempt in range(1, SCHEDULER_MAX_RETRIES + 1):
            try:
                scan_dividend_index(max_workers=SCAN_MAX_WORKERS)
                log_message("Daily dividend index scan completed successfully")
                return
            except Exception as e:
                last_err = e
                logger.error(f"每日红利指数扫描第 {attempt} 次尝试失败: {e}", exc_info=True)
                log_message(f"Attempt {attempt} failed: {e}")
                if attempt < SCHEDULER_MAX_RETRIES:
                    time.sleep(SCHEDULER_RETRY_INTERVAL)
        logger.error("每日红利指数扫描所有重试均失败")
        log_message("All retry attempts failed")
        if last_err is not None:
            raise last_err
    finally:
        with _scan_lock:
            _scan_running = False


@track_run("daily_sentiment")
def daily_sentiment_task():
    """每日舆情分析任务（收盘后执行）。"""
    from backend.services.sentiment_service import batch_analyze
    log_message("开始每日舆情分析...")
    try:
        results = batch_analyze()
        log_message(f"每日舆情分析完成: {len(results)} 只股票")
    except Exception as e:
        logger.error(f"每日舆情分析失败: {e}", exc_info=True)
        log_message(f"每日舆情分析失败: {e}")
        raise


@track_run("daily_vix")
def daily_vix_task():
    """每日 VIX 恐慌指数 + 恐惧贪婪综合指数计算（收盘后 16:30）。"""
    _vix_lock_local = getattr(daily_vix_task, "_lock", None)
    if _vix_lock_local is None:
        _vix_lock_local = threading.Lock()
        daily_vix_task._lock = _vix_lock_local
    with _vix_lock_local:
        from backend.services.vix_service import compute_and_store
        log_message("开始每日 VIX 计算...")
        vix_err = None
        try:
            snap = compute_and_store()
            if snap:
                log_message(
                    f"VIX 计算完成: date={snap.date} "
                    f"恐慌贪婪指数={snap.fear_greed_v7} "
                    f"大盘(VIX={snap.large_vix} FG={snap.large_fg} {snap.large_regime}) "
                    f"小盘(VIX={snap.small_vix} FG={snap.small_fg} {snap.small_regime})"
                )
            else:
                log_message("VIX 计算返回 None（数据源全部不可用）")
        except Exception as e:
            vix_err = e
            logger.error(f"VIX 计算失败: {e}", exc_info=True)
            log_message(f"VIX 计算失败: {e}")

        # VIX 2.0（机器学习）推断：接在 v6.1 之后；模型未训练则静默跳过。
        try:
            from backend.services.vix2_service import (
                compute_and_store_vix2, recompute_vix2_percentiles,
            )
            v2 = compute_and_store_vix2()
            if v2:
                recompute_vix2_percentiles()
                log_message(f"VIX2.0 推断完成: date={v2['date']} score={v2['score']}")
            else:
                log_message("VIX2.0 跳过（模型未训练或因子缺失）")
        except Exception as e:
            logger.error(f"VIX2.0 推断失败: {e}", exc_info=True)
            log_message(f"VIX2.0 推断失败: {e}")

        if vix_err is not None:
            raise vix_err


@track_run("daily_tenbag_scan")
def daily_tenbag_scan_task():
    """每日盘后跑十倍股/财报异动扫描（默认 17:00）。

    长任务（候选 top50 × EM 财报 ~2-3 分钟/只 ≈ 2h），函数级锁防自重叠。
    track_run 提供任务生命周期记录；run_scan 内部按需可读 contextvar 取
    task_run_id（本调度路径不传 task_runner，故无逐只进度，只有起止）。
    """
    _lock = getattr(daily_tenbag_scan_task, "_lock", None)
    if _lock is None:
        _lock = threading.Lock()
        daily_tenbag_scan_task._lock = _lock
    with _lock:
        from backend.services.tenbag_scan_service import run_scan
        log_message("开始每日十倍股扫描...")
        try:
            result = run_scan()
            log_message(
                f"十倍股扫描完成: scanned={result.get('scanned')} "
                f"failed={result.get('failed')} tiers={result.get('tiers')}"
            )
        except Exception as e:
            logger.error(f"每日十倍股扫描失败: {e}", exc_info=True)
            log_message(f"每日十倍股扫描失败: {e}")
            raise


@track_run("daily_top_picks")
def daily_top_picks_task():
    """每日 16:05 拉取全市场成交额 top 100，写入 sentiment_top_picks。"""
    _top_picks_lock_local = getattr(daily_top_picks_task, "_lock", None)
    if _top_picks_lock_local is None:
        _top_picks_lock_local = threading.Lock()
        daily_top_picks_task._lock = _top_picks_lock_local
    with _top_picks_lock_local:
        from backend.services.top_picks_service import refresh_top_picks, analyze_top_picks
        log_message("开始每日 top_picks 刷新...")
        try:
            result = refresh_top_picks(top_n=100, auto_add=False)
            log_message(
                f"top_picks 刷新完成: date={result['snapshot_date']} "
                f"count={result['count']} auto_added={result['auto_added']}"
            )
            if result["count"]:
                analyzed = analyze_top_picks(limit=SENTIMENT_TOP_PICKS_ANALYZE_LIMIT)
                log_message(
                    f"top_picks 情绪分析完成: total={analyzed['total']} "
                    f"ok={analyzed['ok']} failed={analyzed['failed']}"
                )
        except Exception as e:
            logger.error(f"top_picks 刷新失败: {e}", exc_info=True)
            log_message(f"top_picks 刷新失败: {e}")
            raise


@track_run("daily_indicators_recompute")
def daily_indicators_recompute_task():
    """每日 16:35 重算所有监控股的 indicators（v3, 2026-06-06）。

    设计理由：16:00 跑完舆情，16:05 拉 top_picks，16:30 跑 VIX。
    16:35 重算 indicators 让所有股票都有今日的 EMA/panic/euphoria。
    """
    _ind_lock_local = getattr(daily_indicators_recompute_task, "_lock", None)
    if _ind_lock_local is None:
        _ind_lock_local = threading.Lock()
        daily_indicators_recompute_task._lock = _ind_lock_local
    with _ind_lock_local:
        from backend.services.sentiment_indicators_service import recompute_all_for_today
        log_message("开始每日 indicators 重算...")
        try:
            result = recompute_all_for_today()
            log_message(
                f"indicators 重算完成: total={result['total']} "
                f"ok={result['ok']} skip={result['skip']}"
            )
        except Exception as e:
            logger.error(f"indicators 重算失败: {e}", exc_info=True)
            log_message(f"indicators 重算失败: {e}")
            raise


@track_run("forum_prefetch")
def forum_prefetch_task():
    """定期预拉股吧帖子（不调 LLM，单纯抓列表 + 写入 DB）。

    v1 2026-06-04：网络韧性调优。
    - 复用 GubaCircuitBreaker：guba 不可达时熔断保护，10s 内短路
    - 不抓正文、不审计（节省 80% 网络）
    - 单只股票失败不影响其他股票
    """
    global _forum_prefetch_running
    with _forum_prefetch_lock:
        if _forum_prefetch_running:
            log_message("Forum prefetch already running, skipping")
            return "skipped"
        _forum_prefetch_running = True
    try:
        from backend.services.forum_service import fetch_forum_posts, _GUBA_CIRCUIT
        from backend.core.database import get_sentiment_configs
        from backend.services.forum_service import CircuitOpenError

        configs = get_sentiment_configs()
        if not configs:
            log_message("论坛预拉: 无启用监控的股票")
            return

        log_message(f"论坛预拉开始: {len(configs)} 只股票, "
                    f"circuit={_GUBA_CIRCUIT.state['state']}")

        ok, fail, skipped, circuit_skip = 0, 0, 0, 0

        for cfg in configs:
            # 熔断检测：guba 不可达时直接跳过本轮
            if _GUBA_CIRCUIT.state["state"] == "open":
                circuit_skip = len(configs) - ok - fail - skipped
                log_message(f"论坛预拉: guba 熔断中，跳过 {circuit_skip} 只股票")
                break

            try:
                # prefetch 只拿列表 + 缓存，不抓正文、不审计
                posts, _ = fetch_forum_posts(
                    cfg["stock_code"], cfg["forum_type"],
                    days=3, fetch_content=False, audit=False,
                )
                if posts:
                    ok += 1
                else:
                    skipped += 1
            except CircuitOpenError as e:
                logger.warning(f"预拉 {cfg['stock_code']} 触发熔断: {e}")
                circuit_skip = 1
                break
            except Exception as e:
                logger.error(f"预拉 {cfg['stock_code']} 失败: {e}", exc_info=True)
                fail += 1

        log_message(
            f"论坛预拉完成: ok={ok} fail={fail} skipped={skipped} "
            f"circuit_skip={circuit_skip}"
        )
    finally:
        with _forum_prefetch_lock:
            _forum_prefetch_running = False


# ── 全市场舆情观测台（v4, 2026-06-06）──

@track_run("universe_constituents_weekly")
def weekly_universe_constituents_task():
    """每周日 17:00 拉所有 enabled 指数的成分股。

    指数再平衡是季度级别，无需日更；周日拉一次足够。
    """
    global _universe_cons_running
    with _universe_cons_lock:
        if _universe_cons_running:
            log_message("Universe constituents refresh already running, skipping")
            return "skipped"
        _universe_cons_running = True
    try:
        from backend.services.universe_service import refresh_constituents
        log_message("Universe 成分股刷新开始（周更）")
        result = refresh_constituents()
        log_message(f"Universe 成分股刷新完成: {result}")
    except Exception as e:
        logger.exception(f"Weekly universe constituents 失败: {e}")
        log_message(f"Weekly universe constituents 失败: {e}")
        raise
    finally:
        with _universe_cons_lock:
            _universe_cons_running = False


@track_run("universe_crawl_daily")
def daily_universe_crawl_task():
    """工作日 18:00 全市场爬取（先 prefetch 再 analyze）。

    - 依赖 16:35 indicators_recompute 跑完，给 90min buffer
    - 复用 forum_prefetch 的 GubaCircuitBreaker 保护
    - 复用 batch_analyze 的 max_workers=8 + 0.5s sleep 平滑 QPS
    """
    global _universe_crawl_running
    with _universe_crawl_lock:
        if _universe_crawl_running:
            log_message("Universe crawl already running, skipping")
            return "skipped"
        _universe_crawl_running = True
    try:
        from backend.services.universe_service import run_universe_crawl
        log_message(f"Universe crawl 启动: workers={UNIVERSE_CRAWL_MAX_WORKERS} "
                    f"delay={UNIVERSE_CRAWL_STOCK_DELAY_S}s")
        result = run_universe_crawl(
            max_workers=UNIVERSE_CRAWL_MAX_WORKERS,
            stock_delay_s=UNIVERSE_CRAWL_STOCK_DELAY_S,
        )
        log_message(f"Universe crawl 完成: {result}")
    except Exception as e:
        logger.exception(f"Daily universe crawl 失败: {e}")
        log_message(f"Daily universe crawl 失败: {e}")
        raise
    finally:
        with _universe_crawl_lock:
            _universe_crawl_running = False


@track_run("universe_aggregate_daily")
def daily_universe_aggregate_task():
    """工作日 19:30 计算指数级聚合（crawl 完 1.5h 后）。"""
    global _universe_agg_running
    with _universe_agg_lock:
        if _universe_agg_running:
            log_message("Universe aggregate already running, skipping")
            return "skipped"
        _universe_agg_running = True
    try:
        from backend.services.universe_service import compute_universe_aggregates
        log_message("Universe 聚合启动")
        result = compute_universe_aggregates()
        log_message(f"Universe 聚合完成: {result}")
    except Exception as e:
        logger.exception(f"Daily universe aggregate 失败: {e}")
        log_message(f"Daily universe aggregate 失败: {e}")
        raise
    finally:
        with _universe_agg_lock:
            _universe_agg_running = False


# ── 模块级单例（v5, 2026-06-06）：API 路由通过 get_scheduler() 拿引用 ──
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """返回当前进程内的 BackgroundScheduler 单例；未初始化时抛错。"""
    if _scheduler is None:
        raise RuntimeError("scheduler 未初始化；请确认 app.py 已调用 init_scheduler()")
    return _scheduler


def set_scheduler_for_test(s: BackgroundScheduler | None) -> None:
    """测试场景用：注入 mock scheduler；仅供 unit test 使用。"""
    global _scheduler
    _scheduler = s


# 任务函数名 → 函数对象的映射（init_scheduler 用）
_TASK_FUNCS = {
    "daily_update_task": daily_update_task,
    "daily_sentiment_task": daily_sentiment_task,
    "daily_vix_task": daily_vix_task,
    "daily_tenbag_scan_task": daily_tenbag_scan_task,
    "daily_top_picks_task": daily_top_picks_task,
    "daily_indicators_recompute_task": daily_indicators_recompute_task,
    "forum_prefetch_task": forum_prefetch_task,
    "weekly_universe_constituents_task": weekly_universe_constituents_task,
    "daily_universe_crawl_task": daily_universe_crawl_task,
    "daily_universe_aggregate_task": daily_universe_aggregate_task,
}


def init_scheduler():
    """按 DB 配置启动 10 个任务（v5, 2026-06-06 改造）。

    启动顺序：
    1. seed_from_env() 把 env-var 默认值写入 scheduler_task_config（已存在跳过）
    2. 读所有 10 行，按 func_name 拿函数对象，build_trigger() 构 trigger
    3. 逐个 add_job；enabled=0 的立即 pause
    4. start()
    """
    global _scheduler
    _scheduler = BackgroundScheduler()
    from backend.services.scheduler_config_service import (
        seed_from_env, build_trigger, JOB_REGISTRY_BY_ID,
    )
    from backend.core.database import get_all_scheduler_configs

    seed_from_env()  # 幂等 INSERT OR IGNORE；首次启动写入 env 默认值

    rows = get_all_scheduler_configs()
    n_added = 0
    for row in rows:
        job_id = row["job_id"]
        reg = JOB_REGISTRY_BY_ID.get(job_id)
        if not reg:
            logger.warning(f"未知 job_id: {job_id}, 跳过")
            continue
        func = _TASK_FUNCS.get(reg["func_name"])
        if not func:
            logger.warning(f"未知 func_name: {reg['func_name']}, 跳过 {job_id}")
            continue
        trigger = build_trigger(row)
        # forum_prefetch 启动后立刻跑一次（guba 列表页不依赖 cookie，可 warm 缓存）。
        # 注意：APScheduler 3.x 中 add_job(next_run_time=None) 的语义是「以暂停态添加」，
        # 不是「按 trigger 计算」——省略该参数才是启用状态。2026-08-31 曾因此导致
        # 全部 cron 任务出生即暂停、永不触发（回归：tests/test_scheduler_init.py）。
        if job_id == "forum_prefetch":
            _scheduler.add_job(func, trigger, id=job_id, next_run_time=datetime.now())
        else:
            _scheduler.add_job(func, trigger, id=job_id)
        n_added += 1
    _scheduler.start()

    # 禁用任务必须在 start() 之后 pause：对 start() 前的 pending 任务调用
    # pause() 不会生效，start() 会按 trigger 重算 next_run_time 把暂停态覆盖掉。
    for row in rows:
        if not row["enabled"]:
            job = _scheduler.get_job(row["job_id"])
            if job:
                job.pause()
                logger.info(f"scheduler {row['job_id']}: 启动时即 disabled, paused")

    # 同步 next_run_time 到 DB（仅用于首屏展示）
    from backend.core.database import update_scheduler_next_run
    for row in rows:
        job = _scheduler.get_job(row["job_id"])
        if job:
            nrt = job.next_run_time.isoformat() if job.next_run_time else None
            update_scheduler_next_run(row["job_id"], nrt)

    # 简化的启动日志（从 DB 行的字段生成）
    cron_lines = [f"{r['job_id']}={r['hour']:02d}:{r['minute']:02d} {r['day_of_week']}"
                  for r in rows if r["trigger_type"] == "cron"]
    interval_lines = [f"{r['job_id']}={r['interval_hours']}h"
                      for r in rows if r["trigger_type"] == "interval"]
    log_message(
        f"Scheduler initialized ({n_added} jobs from DB). "
        f"Cron: {'; '.join(cron_lines[:3])}... "
        f"Interval: {', '.join(interval_lines) or 'none'}"
    )
    return _scheduler


def manual_trigger():
    thread = threading.Thread(target=daily_update_task)
    thread.start()
    return "Task triggered in background."
