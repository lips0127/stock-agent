#!/bin/bash
set -euo pipefail

fail() {
    echo "Configuration error: $1" >&2
    exit 64
}

require_value() {
    local name="$1"
    local value="${!name:-}"
    [[ -n "$value" ]] || fail "$name must be set"
}

# Production containers never fall back to the development credentials from
# backend/config.py. Validate before creating directories or initializing DB.
require_value JWT_SECRET
require_value DEFAULT_ADMIN_USER
require_value DEFAULT_ADMIN_PASSWORD
require_value CORS_ORIGINS

JWT_SECRET_LOWER="${JWT_SECRET,,}"
if (( ${#JWT_SECRET} < 32 )) || [[ "$JWT_SECRET_LOWER" == *"replace"* ]] \
    || [[ "$JWT_SECRET_LOWER" == *"change-me"* ]] \
    || [[ "$JWT_SECRET_LOWER" == *"change_me"* ]] \
    || [[ "$JWT_SECRET_LOWER" == *"changeme"* ]] \
    || [[ "$JWT_SECRET_LOWER" == *"placeholder"* ]]; then
    fail "JWT_SECRET must be at least 32 characters and must not be an example value"
fi

ADMIN_USER_LOWER="${DEFAULT_ADMIN_USER,,}"
if [[ "$ADMIN_USER_LOWER" == "admin" ]] \
    || [[ "$ADMIN_USER_LOWER" == *"change_me"* ]] \
    || [[ "$ADMIN_USER_LOWER" == *"placeholder"* ]]; then
    fail "DEFAULT_ADMIN_USER must not be admin or an example value"
fi

ADMIN_PASSWORD_LOWER="${DEFAULT_ADMIN_PASSWORD,,}"
if (( ${#DEFAULT_ADMIN_PASSWORD} < 12 )) \
    || [[ "$ADMIN_PASSWORD_LOWER" == "admin123" ]] \
    || [[ "$ADMIN_PASSWORD_LOWER" == *"change_me"* ]] \
    || [[ "$ADMIN_PASSWORD_LOWER" == *"placeholder"* ]]; then
    fail "DEFAULT_ADMIN_PASSWORD must be at least 12 characters and must not be an example value"
fi

if [[ "$CORS_ORIGINS" == *"*"* ]]; then
    fail "CORS_ORIGINS must list explicit trusted origins and must not contain a wildcard"
fi

WORKERS="${GUNICORN_WORKERS:-1}"
[[ "$WORKERS" =~ ^[1-9][0-9]*$ ]] || fail "GUNICORN_WORKERS must be a positive integer"

SCHEDULER_VALUE="${SCHEDULER_ENABLED:-true}"
case "${SCHEDULER_VALUE,,}" in
    1|true|yes) SCHEDULER_ACTIVE=true ;;
    0|false|no) SCHEDULER_ACTIVE=false ;;
    *) fail "SCHEDULER_ENABLED must be one of true/false, 1/0, or yes/no" ;;
esac

if [[ "$SCHEDULER_ACTIVE" == "true" && "$WORKERS" != "1" ]]; then
    fail "GUNICORN_WORKERS must be 1 while the in-process scheduler is enabled"
fi

# 深度安全审计（与上方校验同源；输出 PASS/FAIL 报告，绝不回显密钥值）
/usr/local/bin/python -m backend.security_check || exit 64

echo "[$(date -Iseconds)] Starting Stock Agent Python Backend..."

# 确保数据目录存在
mkdir -p /data/cache /data/logs /data

# 初始化数据库（CACHE_DIR=/data/cache 时为 /data/cache/stocks.db）
/usr/local/bin/python -c "from backend.core.database import init_db; init_db()"

# 启动 Gunicorn
# 不用 max_requests：worker 循环重启会杀掉跑到一半的定时扫描/回填任务
exec /usr/local/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "$WORKERS" \
    --worker-class gevent \
    --timeout 30 \
    --graceful-timeout 10 \
    --access-logfile - \
    --access-logformat '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s" %(D)s' \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}" \
    --chdir /app \
    "backend.api.app:create_app()"
