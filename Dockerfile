# ── 构建阶段 ──
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── 运行阶段 ──
FROM python:3.11-slim

LABEL maintainer="stock-agent"
LABEL description="A股股息监测系统 Python 后端"

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local

COPY backend/ backend/

RUN mkdir -p /data/cache /data/logs && chown -R appuser:appuser /data /app

USER appuser

ENV APP_HOST=0.0.0.0 \
    APP_PORT=5000 \
    APP_DEBUG=false \
    DB_PATH=/data/stocks.db \
    CACHE_DIR=/data/cache \
    LOG_DIR=/data/logs \
    LOG_LEVEL=INFO \
    GUNICORN_WORKERS=2

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

CMD ["gunicorn", "--config", "backend/gunicorn_config.py", "backend.api.app:create_app()"]
