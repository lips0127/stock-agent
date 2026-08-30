# ── 阶段 1：前端构建（单容器部署：产物由 Flask 直接服务） ──
FROM node:22-alpine AS frontend-builder

WORKDIR /web

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── 阶段 2：Python 依赖构建 ──
FROM python:3.11-slim-bookworm AS python-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-production.txt requirements-production.txt

RUN pip install --no-cache-dir --prefix=/install -r requirements-production.txt

# ── 阶段 3：运行时（API + 前端静态产物同容器） ──
FROM python:3.11-slim-bookworm

LABEL maintainer="stock-agent"
LABEL description="A 股研究与风险辅助看板（前后端一体单容器）"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1001 appuser && useradd -u 1001 -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY --from=python-builder /install /usr/local

COPY --chown=appuser:appuser backend /app/backend

# 前端产物：create_app() 的静态回退直接从该目录服务 SPA
COPY --from=frontend-builder --chown=appuser:appuser /web/dist /app/frontend/dist

RUN mkdir -p /data/cache /data/logs /data && chown -R appuser:appuser /data /app

RUN sed -i 's/\r$//' /app/backend/entrypoint.sh \
    && chmod +x /app/backend/entrypoint.sh

USER appuser

ENV PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=5000 \
    APP_DEBUG=false \
    CACHE_DIR=/data/cache \
    LOG_DIR=/data/logs \
    LOG_LEVEL=INFO \
    FRONTEND_DEV_PROXY=false \
    SCHEDULER_ENABLED=true \
    GUNICORN_WORKERS=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD /usr/local/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

ENTRYPOINT ["/app/backend/entrypoint.sh"]
