#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/stock-agent"
VENV_DIR="$PROJECT_DIR/venv"

echo "=== Stock Agent Python Backend Deployment ==="

id -u appuser &>/dev/null || useradd -r -m -d "$PROJECT_DIR" -s /sbin/nologin appuser

if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"
chown -R appuser:appuser "$PROJECT_DIR/data" "$PROJECT_DIR/logs"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found at $PROJECT_DIR/.env"
    echo "Copy .env.example to .env and fill in production values."
    exit 1
fi

sudo -u appuser "$VENV_DIR/bin/python" -c "from backend.core.database import init_db; init_db()"

cp "$PROJECT_DIR/deploy/stock-python-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable stock-python-api
systemctl start stock-python-api

echo "=== Deployment complete ==="
echo "Status: systemctl status stock-python-api"
echo "Logs:   journalctl -u stock-python-api -f"
