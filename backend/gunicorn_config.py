# ⚠️ 此文件仅用于本地开发（直接 gunicorn --config 引用）。
# Docker 环境使用 entrypoint.sh；进程内 APScheduler 启用时只允许一个 worker。

import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
worker_class = "gevent"
# max_requests 的 worker 循环重启会把跑到一半的定时扫描/回填任务直接杀掉
# （重启后又触发孤儿清理把这些任务标 failed），对本产品是纯负收益，禁用。
max_requests = 0
preload_app = False  # 保持应用工厂在 worker 进程中初始化。
timeout = 30

# 本地路径的调度单实例防线（Docker 由 entrypoint.sh 强制）：
# 每个 worker 都会执行 init_scheduler()，多 worker = 同一任务重复调度。
try:
    from backend.config import SCHEDULER_ENABLED

    if workers > 1 and SCHEDULER_ENABLED:
        raise RuntimeError(
            f"GUNICORN_WORKERS={workers} 且 SCHEDULER_ENABLED=true 会导致 "
            "APScheduler 多实例重复调度。要么保持单 worker，要么设置 "
            "SCHEDULER_ENABLED=false。"
        )
except ImportError:
    pass
graceful_timeout = 10
accesslog = "-"
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s" %(D)s'
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
