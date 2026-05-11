# ── 构建阶段 ──
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-production.txt requirements.txt

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── 运行阶段 ──
FROM python:3.11-slim

LABEL maintainer="stock-agent"
LABEL description="A 股股息监测系统 Python 后端"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi7 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1001 appuser && useradd -u 1001 -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local

COPY . ./

RUN mkdir -p /data/cache /data/logs /data && chown -R appuser:appuser /data /app

RUN chmod +x entrypoint.sh && chown appuser:appuser entrypoint.sh

USER appuser

ENV PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=5000 \
    APP_DEBUG=false \
    CACHE_DIR=/data/cache \
    LOG_DIR=/data/logs \
    LOG_LEVEL=INFO \
    GUNICORN_WORKERS=2

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
