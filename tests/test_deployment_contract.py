"""Static and application-factory contracts for the production deployment."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_scheduler_startup_respects_testing_and_enabled_flag(monkeypatch):
    pytest.importorskip("flask_cors")
    import backend.api.app as app_module

    calls = {"scheduler": 0, "cleanup": 0, "stock_cache": 0}

    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(app_module, "init_cors", lambda app: None)
    monkeypatch.setattr(app_module, "install_security_headers", lambda app: app)
    monkeypatch.setattr(app_module, "FRONTEND_DEV_PROXY", False)
    monkeypatch.setattr(
        app_module,
        "init_scheduler",
        lambda: calls.__setitem__("scheduler", calls["scheduler"] + 1),
    )
    monkeypatch.setattr(
        app_module,
        "cleanup_orphan_task_runs",
        lambda: calls.__setitem__("cleanup", calls["cleanup"] + 1),
    )
    monkeypatch.setattr(
        app_module,
        "init_stock_cache",
        lambda: calls.__setitem__("stock_cache", calls["stock_cache"] + 1),
    )

    monkeypatch.setattr(app_module, "SCHEDULER_ENABLED", True)
    app_module.create_app(testing=True)
    assert calls == {"scheduler": 0, "cleanup": 0, "stock_cache": 0}

    monkeypatch.setattr(app_module, "SCHEDULER_ENABLED", False)
    app_module.create_app()
    assert calls == {"scheduler": 0, "cleanup": 1, "stock_cache": 1}

    monkeypatch.setattr(app_module, "SCHEDULER_ENABLED", True)
    app_module.create_app()
    assert calls == {"scheduler": 1, "cleanup": 2, "stock_cache": 2}


def test_compose_is_single_container_and_requires_production_secrets():
    compose = yaml.safe_load(_read("docker-compose.yml"))
    services = compose["services"]

    # 前后端一体：只有 app 一个服务，不再有独立 nginx 容器
    assert set(services.keys()) == {"app"}
    app = services["app"]
    assert app["build"] == {"context": ".", "dockerfile": "backend/Dockerfile"}
    assert app["ports"] == ["${APP_PORT:-80}:5000"]
    assert app["volumes"] == ["app-data:/data"]

    environment = app["environment"]
    assert environment["CACHE_DIR"] == "/data/cache"
    assert environment["FRONTEND_DEV_PROXY"] == "false"
    assert environment["SCHEDULER_ENABLED"] == "${SCHEDULER_ENABLED:-true}"
    assert environment["GUNICORN_WORKERS"] == "${GUNICORN_WORKERS:-1}"
    for name in (
        "JWT_SECRET",
        "DEFAULT_ADMIN_USER",
        "DEFAULT_ADMIN_PASSWORD",
        "CORS_ORIGINS",
    ):
        assert environment[name].startswith(f"${{{name}:?")


def test_backend_dockerfile_builds_frontend_and_backend_into_one_image():
    dockerfile = _read("backend/Dockerfile")

    # 前端阶段：干净 npm ci + 构建，产物拷入运行时镜像由 Flask 静态服务
    assert "FROM node:22-alpine AS frontend-builder" in dockerfile
    assert "COPY frontend/package.json frontend/package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "COPY --from=frontend-builder --chown=appuser:appuser /web/dist /app/frontend/dist" in dockerfile

    # Python 阶段：可复现的安全布局
    assert dockerfile.count("FROM python:3.11-slim-bookworm") == 2
    assert "COPY backend/requirements-production.txt requirements-production.txt" in dockerfile
    assert "COPY --chown=appuser:appuser backend /app/backend" in dockerfile
    assert "libffi8" in dockerfile
    assert "libffi7" not in dockerfile
    assert "USER appuser" in dockerfile
    assert "sed -i 's/\\r$//' /app/backend/entrypoint.sh" in dockerfile
    assert "chmod +x /app/backend/entrypoint.sh" in dockerfile
    assert "CMD /usr/local/bin/python -c" in dockerfile
    assert 'ENTRYPOINT ["/app/backend/entrypoint.sh"]' in dockerfile
    assert "COPY . " not in dockerfile


def test_backend_build_context_excludes_runtime_and_sensitive_content():
    patterns = {
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    required_exclusions = {
        ".env",
        ".env.*",
        "**/.env",
        "**/.env.*",
        ".github",
        "data",
        "data/models",
        "data/research",
        "docs",
        "frontend/node_modules",
        "frontend/dist",
        "frontend/legacy",
        "logs",
        "tests",
        "venv",
        "venv_new",
        "**/*.db",
        "market_dividends_cache.json",
    }
    assert required_exclusions <= patterns
    # 前端源码必须进入构建上下文（镜像内编译产物），不得整目录排除
    assert "frontend" not in patterns
    assert "backend" not in patterns
    assert "backend/requirements-production.txt" not in patterns


def test_no_legacy_split_frontend_image_or_nginx_deploy_artifacts():
    # 单容器后，双容器遗留物不得回流
    assert not (ROOT / "frontend" / "Dockerfile").exists()
    assert not (ROOT / "deploy" / "nginx.conf").exists()
    assert not (ROOT / "deploy" / "stock-python-api.service").exists()
    compose = _read("docker-compose.yml")
    assert "nginx" not in compose
    assert "/usr/share/nginx/html" not in compose


def test_entrypoint_fails_fast_before_touching_runtime_state():
    entrypoint = _read("backend/entrypoint.sh")

    validation_end = entrypoint.index("echo \"[$(date -Iseconds)] Starting")
    mkdir_start = entrypoint.index("mkdir -p /data/cache")
    assert validation_end < mkdir_start
    assert 'WORKERS="${GUNICORN_WORKERS:-1}"' in entrypoint
    assert 'SCHEDULER_VALUE="${SCHEDULER_ENABLED:-true}"' in entrypoint
    assert '"$SCHEDULER_ACTIVE" == "true" && "$WORKERS" != "1"' in entrypoint
    assert "${#JWT_SECRET} < 32" in entrypoint
    assert 'ADMIN_USER_LOWER="${DEFAULT_ADMIN_USER,,}"' in entrypoint
    assert "${#DEFAULT_ADMIN_PASSWORD} < 12" in entrypoint
    assert '"$CORS_ORIGINS" == *"*"*' in entrypoint
    # 深度安全审计在启动前执行
    assert "/usr/local/bin/python -m backend.security_check" in entrypoint
    assert 'echo "$JWT_SECRET"' not in entrypoint
    assert 'echo "${JWT_SECRET' not in entrypoint
    # 禁用 max_requests：worker 循环重启会杀掉跑到一半的定时任务
    assert "--max-requests" not in entrypoint


def test_environment_template_is_intentionally_non_production():
    template = _read(".env.example")

    assert "JWT_SECRET=CHANGE_ME_" in template
    assert "DEFAULT_ADMIN_USER=CHANGE_ME_" in template
    assert "DEFAULT_ADMIN_PASSWORD=CHANGE_ME_" in template
    assert "CORS_ORIGINS=https://CHANGE_ME.example.com" in template
    assert "SCHEDULER_ENABLED=true" in template
    assert "GUNICORN_WORKERS=1" in template
    assert "FRONTEND_DEV_PROXY=false" in template
    assert "secrets.token_urlsafe(48)" in template


def test_production_env_template_documents_tencent_deploy_contract():
    template = _read(".env.production.example")

    assert "JWT_SECRET=CHANGE_ME_" in template
    assert "secrets.token_urlsafe(48)" in template
    assert "APP_PORT=80" in template
    assert "ENABLE_HSTS=false" in template


def test_gunicorn_defaults_to_one_worker():
    source = _read("backend/gunicorn_config.py")
    assert 'os.environ.get("GUNICORN_WORKERS", "1")' in source
    assert "PostgreSQL" not in source


def test_gunicorn_access_logs_exclude_sensitive_request_data():
    entrypoint = _read("backend/entrypoint.sh")
    config = _read("backend/gunicorn_config.py")
    safe_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s" %(D)s'

    assert f"--access-logformat '{safe_format}'" in entrypoint
    assert f"access_log_format = '{safe_format}'" in config

    for source in (entrypoint.lower(), config.lower()):
        for forbidden_atom in (
            "%(r)s",
            "%(q)s",
            "%(f)s",
            "{authorization}i",
            "{cookie}i",
            "{cookie}o",
            "{referer}i",
        ):
            assert forbidden_atom not in source
