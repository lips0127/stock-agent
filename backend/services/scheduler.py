import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import time
from datetime import datetime
import threading
from backend.tasks.market_scan import full_market_scan
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
    global _scan_running
    with _scan_lock:
        if _scan_running:
            log_message("Scan already running, skipping")
            return
        _scan_running = True

    try:
        log_message("Starting daily update task")
        for attempt in range(1, SCHEDULER_MAX_RETRIES + 1):
            try:
                full_market_scan(max_workers=SCAN_MAX_WORKERS)
                log_message("Daily update completed successfully")
                return
            except Exception as e:
                log_message(f"Attempt {attempt} failed: {e}")
                if attempt < SCHEDULER_MAX_RETRIES:
                    time.sleep(SCHEDULER_RETRY_INTERVAL)
        log_message("All retry attempts failed")
    finally:
        with _scan_lock:
            _scan_running = False


def init_scheduler():
    scheduler = BackgroundScheduler()
    trigger = CronTrigger(day_of_week='mon-fri', hour=SCHEDULER_HOUR, minute=SCHEDULER_MINUTE)
    scheduler.add_job(daily_update_task, trigger, id='daily_update')
    scheduler.start()
    log_message(f"Scheduler initialized. Next run at {SCHEDULER_HOUR:02d}:{SCHEDULER_MINUTE:02d} Mon-Fri.")
    return scheduler


def manual_trigger():
    thread = threading.Thread(target=daily_update_task)
    thread.start()
    return "Task triggered in background."
