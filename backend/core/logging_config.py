import logging
import logging.handlers
import os
import sys
from pathlib import Path
from backend.config import LOG_LEVEL, LOG_DIR


class WindowsSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Windows 兼容的 RotatingFileHandler，处理文件锁定错误。"""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # Windows 下旧日志文件可能被其他进程持有，跳过轮转
            pass


class TaskAwareFormatter(logging.Formatter):
    """日志格式化器，自动注入 task_run_id（Phase A, 2026-06-10）。

    格式: 2026-05-10 15:30:45 [线程名] [task=xxxxxxxx] INFO  模块名 - 消息
    """

    def format(self, record: logging.LogRecord) -> str:
        from backend.core.task_runner import current_task_run_id

        run_id = current_task_run_id.get()
        record.task_run_id = run_id[:8] if run_id else "--------"

        logger_name = record.name
        if "." in logger_name:
            logger_name = logger_name.split(".")[-1]

        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        thread_name = record.threadName or "MainThread"
        level = record.levelname.ljust(5)
        msg = record.getMessage()

        result = (
            f"{timestamp} [{thread_name}] [task={record.task_run_id}] "
            f"{level} {logger_name} - {msg}"
        )
        if record.exc_info and record.exc_info[0] is not None:
            result += "\n" + self.formatException(record.exc_info)
        return result


def setup_logging() -> None:
    """初始化全局日志配置。应在应用启动时调用一次。"""
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # 强制移除旧 handler，防止 Debug reloader 导致重复注册
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    fmt = TaskAwareFormatter()

    # stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)
    root_logger.addHandler(stdout_handler)

    # 文件：RotatingFileHandler（10MB × 5 保留）
    file_handler = WindowsSafeRotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(fmt)
    root_logger.addHandler(file_handler)

    # 压制第三方库噪声
    for noisy in (
        "werkzeug", "urllib3", "apscheduler", "akshare",
        "httpx", "httpcore", "matplotlib",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
