# ⚠️ 此文件仅用于本地开发（直接 gunicorn --config 引用）
# ⚠️ Docker 环境请使用 entrypoint.sh 中的命令行参数

import multiprocessing
import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))
worker_class = "gevent"
max_requests = 1000
max_requests_jitter = 50
preload_app = False  # 必须为 False：fork 前 PostgreSQL 连接不可共享
timeout = 30
graceful_timeout = 10
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
