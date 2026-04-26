#!/bin/bash
set -e

echo "[$(date -Iseconds)] Starting Stock Agent Python Backend..."

# 确保数据目录存在
mkdir -p /data/cache /data/logs /data

# 初始化数据库（SQLite 文件放在 /data 下）
python -c "from backend.core.database import init_db; init_db()"

# 启动 Gunicorn
WORKERS="${GUNICORN_WORKERS:-2}"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "$WORKERS" \
    --worker-class gevent \
    --timeout 30 \
    --graceful-timeout 10 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile - \
    --access-logformat '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s' \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}" \
    --chdir /app \
    "backend.api.app:create_app()"
