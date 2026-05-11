import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import time
from datetime import datetime
import threading
from backend.tasks.market_scan import scan_dividend_index
from backend.config import SCAN_MAX_WORKERS, SCHEDULER_MAX_RETRIES, SCHEDULER_RETRY_INTERVAL, SCHEDULER_HOUR, SCHEDULER_MINUTE

logger = logging.getLogger("scheduler")

_task_logs_lock = threading.Lock()
task_logs = []

_scan_lock = threading.Lock()
_scan_running = False


def log_message(msg: str) -> None:
    from datetime import datetime
    logger.info(msg)
    entry = {"time": datetime.now().isoformat(), "message": msg}
    with _task_logs_lock:
        task_logs.append(entry)
        if len(task_logs) > 1000:
            task_logs.pop(0)


def daily_update_task():
    """每日红利指数扫描任务（工作日定时触发）。"""
    global _scan_running
    with _scan_lock:
        if _scan_running:
            log_message("Scan already running, skipping")
            return
        _scan_running = True

    try:
        log_message("Starting daily dividend index scan")
        for attempt in range(1, SCHEDULER_MAX_RETRIES + 1):
            try:
                scan_dividend_index(max_workers=SCAN_MAX_WORKERS)
                log_message("Daily dividend index scan completed successfully")
                return
            except Exception as e:
                logger.error(f"每日红利指数扫描第 {attempt} 次尝试失败: {e}", exc_info=True)
                log_message(f"Attempt {attempt} failed: {e}")
                if attempt < SCHEDULER_MAX_RETRIES:
                    time.sleep(SCHEDULER_RETRY_INTERVAL)
        logger.error("每日红利指数扫描所有重试均失败")
        log_message("All retry attempts failed")
    finally:
        with _scan_lock:
            _scan_running = False


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


def init_scheduler():
    scheduler = BackgroundScheduler()
    trigger = CronTrigger(day_of_week='mon-fri', hour=SCHEDULER_HOUR, minute=SCHEDULER_MINUTE)
    scheduler.add_job(daily_update_task, trigger, id='daily_update')
    # 收盘后1小时执行舆情分析 (默认16:00)
    sentiment_hour = SCHEDULER_HOUR + 1 if SCHEDULER_HOUR < 23 else 16
    sentiment_trigger = CronTrigger(day_of_week='mon-fri', hour=sentiment_hour, minute=0)
    scheduler.add_job(daily_sentiment_task, sentiment_trigger, id='daily_sentiment')
    scheduler.start()
    log_message(f"Scheduler initialized. Scan at {SCHEDULER_HOUR:02d}:{SCHEDULER_MINUTE:02d}, "
                f"Sentiment at {sentiment_hour:02d}:00 Mon-Fri.")
    return scheduler


def manual_trigger():
    thread = threading.Thread(target=daily_update_task)
    thread.start()
    return "Task triggered in background."
