import logging
import json
import sys
from pathlib import Path
from backend.config import LOG_LEVEL, LOG_DIR


class JSONFormatter(logging.Formatter):
    """将日志格式化为 JSON，方便 ELK / Loki 等系统采集。"""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def setup_logging() -> None:
    """初始化全局日志配置。应在应用启动时调用一次。"""
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if root_logger.handlers:
        return

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    root_logger.addHandler(stdout_handler)

    file_handler = logging.FileHandler(
        log_dir / "app.log", encoding="utf-8", delay=True
    )
    file_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    root_logger.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
