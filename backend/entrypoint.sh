#!/bin/bash
set -e

echo "[$(date -Iseconds)] Starting Stock Agent Python Backend..."

mkdir -p /data/cache /data/logs

python -c "from backend.core.database import init_db; init_db()"

exec gunicorn --config backend/gunicorn_config.py "backend.api.app:create_app()"
