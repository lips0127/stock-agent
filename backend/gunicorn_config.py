import multiprocessing
import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "gevent"
max_requests = 1000
max_requests_jitter = 50
preload_app = True
timeout = 30
graceful_timeout = 10
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
