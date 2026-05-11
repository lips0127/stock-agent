import logging
import sys
from pathlib import Path
from backend.config import LOG_LEVEL, LOG_DIR


class Log4jFormatter(logging.Formatter):
    """Log4j 风格的日志格式化器。

    格式: 2026-05-10 15:30:45 [线程名] INFO  模块名 - 消息
    """

    def format(self, record: logging.LogRecord) -> str:
        # 简化模块名（取最后一个点后的部分，更像 Log4j 的类名风格）
        logger_name = record.name
        if '.' in logger_name:
            logger_name = logger_name.split('.')[-1]

        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        thread_name = record.threadName or "MainThread"
        level = record.levelname.ljust(5)  # 左对齐，INFO/WARN/ERROR
        msg = record.getMessage()

        result = f"{timestamp} [{thread_name}] {level} {logger_name} - {msg}"
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

    # 应用日志：stdout + 文件
    log4j_fmt = Log4jFormatter()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(log4j_fmt)
    root_logger.addHandler(stdout_handler)

    file_handler = logging.FileHandler(
        log_dir / "app.log", encoding="utf-8", delay=True
    )
    file_handler.setFormatter(log4j_fmt)
    root_logger.addHandler(file_handler)

    # werkzeug: 只显示 WARNING+（隐藏每条 HTTP 请求的噪音行），但显示路由错误
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # urllib3/apscheduler 安静
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
