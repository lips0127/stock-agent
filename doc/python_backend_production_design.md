# Python 后端商业级部署设计书 & 操作手册

> **文档版本**: v1.0
> **日期**: 2026-04-22
> **目标读者**: 具备基础 Python/Shell 能力的初级工程师
> **目标**: 将现有开发态 Python 后端改造为可安全、稳定、可观测地运行于生产环境的商业级服务

---

## 目录

- [第一部分：现状诊断](#第一部分现状诊断)
- [第二部分：架构设计](#第二部分架构设计)
- [第三部分：分步实施指南](#第三部分分步实施指南)
  - [Phase 0 — 紧急修复（阻断性 Bug）](#phase-0--紧急修复阻断性-bug)
  - [Phase 1 — 配置外部化](#phase-1--配置外部化)
  - [Phase 2 — 日志与可观测性](#phase-2--日志与可观测性)
  - [Phase 3 — 安全加固](#phase-3--安全加固)
  - [Phase 4 — 数据库改造](#phase-4--数据库改造)
  - [Phase 5 — WSGI 服务器与容器化](#phase-5--wsgi-服务器与容器化)
  - [Phase 6 — 健康检查与运维接口](#phase-6--健康检查与运维接口)
  - [Phase 7 — 进程管理与服务编排](#phase-7--进程管理与服务编排)
- [第四部分：文件变更清单](#第四部分文件变更清单)
- [第五部分：验证检查清单](#第五部分验证检查清单)
- [附录 A：完整文件内容参考](#附录-a完整文件内容参考)
- [附录 B：常见问题与排障](#附录-b常见问题与排障)

---

# 第一部分：现状诊断

## 1.1 阻断性问题（不修复则无法启动）

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| **B1** | `backend/api/app.py` 第1-13行混入了 Java 代码，Python 解析器无法解析 | `app.py:1-13` | `python -m backend.api.app` 启动报 `SyntaxError`，服务完全无法启动 |
| **B2** | `backend/__init__.py` 包含 Java 代码 | `__init__.py` | 任何 `from backend import ...` 都会触发 `SyntaxError`，整个包不可导入 |

> **结论**: 当前代码在标准 Python 环境下 **无法启动**，是首要修复项。

## 1.2 安全问题

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| S1 | SQL 注入：`limit` 参数直接拼入 SQL | 高 | `app.py:65` |
| S2 | 无 CORS 配置，跨域请求被浏览器拦截 | 中 | `app.py` 全局 |
| S3 | 无认证中间件，除 `/api/login` 外所有接口裸奔 | 高 | `app.py` |
| S4 | 硬编码默认密码 `admin/admin123` | 高 | `database.py:108-109` |
| S5 | Sina API 使用 HTTP 而非 HTTPS | 中 | `stock_service.py` |
| S6 | `task_logs` 列表无线程锁，并发写入可能丢失数据 | 低 | `scheduler.py` |

## 1.3 可靠性问题

| # | 问题 | 位置 |
|---|------|------|
| R1 | SQLite 在多线程场景下无写锁保护 | `market_scan.py` |
| R2 | 缓存文件无过期机制，可能返回陈旧数据 | `scanner_service.py` |
| R3 | 缓存文件使用相对路径，依赖 CWD | `scanner_service.py:10` |
| R4 | 定时任务与手动触发并发执行时无互斥保护 | `scheduler.py` |
| R5 | 数据库连接未使用 context manager，异常时可能泄漏 | `app.py` 各路由 |
| R6 | `market_indices` 表从无数据写入，`/api/indices` 永远返回空 | `market_scan.py` |

## 1.4 可运维性问题

| # | 问题 | 位置 |
|---|------|------|
| O1 | 所有配置项硬编码，无配置文件/环境变量 | 全局 |
| O2 | 使用 `print()` 而非结构化日志 | 全局 |
| O3 | `task_logs` 内存列表重启即丢失 | `scheduler.py` |
| O4 | 无健康检查端点 | `app.py` |
| O5 | `requirements.txt` 未锁定版本号 | `requirements.txt` |
| O6 | Docker 配置引用不存在的文件 (`app_v2.py`, `api_server.py`) | `Dockerfile`, `docker-compose.yml` |
| O7 | 使用 Flask 开发服务器，不适合生产 | `app.py:87` |

---

# 第二部分：架构设计

## 2.1 目标架构

```
                    ┌─────────────────────────────────────────────────┐
                    │              Nginx (反向代理)                      │
                    │   :80/:443 → SSL终止 + 静态资源 + 负载均衡         │
                    └────────────────────┬────────────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────────────┐
                    │         Gunicorn (WSGI 服务器)                    │
                    │   4 workers × gevent 协程                         │
                    │   preload + max-requests 防内存泄漏                │
                    └────────────────────┬────────────────────────────┘
                                         │
          ┌──────────────────────────────▼──────────────────────────────┐
          │                   Flask Application                          │
          │  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────┐ │
          │  │ 路由层    │ │ 中间件层  │ │ 服务层     │ │ 任务层       │ │
          │  │ (Blueprint)│ │(CORS,JWT │ │(stock_svc │ │(scheduler +  │ │
          │  │           │ │ ,日志,限流│ │ ,scanner) │ │ market_scan) │ │
          │  └──────────┘ └──────────┘ └───────────┘ └──────────────┘ │
          └──────────────────────────────┬──────────────────────────────┘
                                           │
          ┌──────────────────────────────▼──────────────────────────────┐
          │              配置层 (config.py + .env)                        │
          │   所有硬编码值 → 环境变量 / .env 文件                          │
          └──────────────────────────────────────────────────────────────┘
                                           │
          ┌──────────────────────────────▼──────────────────────────────┐
          │              数据层                                           │
          │   SQLite (短期) → MySQL/PostgreSQL (中期)                     │
          │   日志 → 文件 + stdout (结构化JSON)                            │
          └──────────────────────────────────────────────────────────────┘
```

## 2.2 设计原则

1. **渐进式改造**：每个 Phase 独立可验证，不跳步
2. **零停机优先**：改动应向后兼容，新字段有默认值
3. **配置外部化**：所有环境差异通过 `.env` 或环境变量表达
4. **结构化可观测**：日志统一为 JSON 格式，输出到 stdout + 文件
5. **最小攻击面**：CORS 白名单、JWT 保护、SQL 参数化、输入校验

## 2.3 目录结构（改造后）

```
backend/
├── __init__.py              # 空（删除 Java 代码）
├── config.py                # 新增：统一配置管理
├── api/
│   ├── __init__.py
│   ├── app.py               # Flask 应用工厂（改造）
│   ├── middleware.py         # 新增：CORS / JWT / 限流 / 请求日志
│   └── routes/
│       ├── __init__.py
│       ├── auth.py           # 新增：登录路由
│       ├── market.py         # 新增：行情路由
│       ├── stock.py          # 新增：个股路由
│       └── ops.py            # 新增：健康检查 / 日志 / 刷新
├── core/
│   ├── __init__.py
│   ├── database.py           # 改造：连接池 + context manager
│   └── logging_config.py     # 新增：统一日志配置
├── services/
│   ├── __init__.py
│   ├── stock_service.py      # 微调：读取配置
│   ├── scanner_service.py    # 改造：缓存过期 + 路径安全
│   └── scheduler.py          # 改造：互斥锁 + 文件日志
├── tasks/
│   ├── __init__.py
│   └── market_scan.py        # 微调：读取配置
├── dashboard/
│   ├── __init__.py
│   └── app.py
├── tests/
│   ├── __init__.py
│   ├── test_config.py        # 新增
│   ├── test_api.py           # 新增
│   └── test_imports.py
├── gunicorn_config.py        # 新增：Gunicorn 配置
└── entrypoint.sh             # 新增：Docker 入口脚本
```

---

# 第三部分：分步实施指南

## Phase 0 — 紧急修复（阻断性 Bug）

> **目标**: 让应用能正常启动
> **预计时间**: 10 分钟
> **验证方式**: `python -m backend.api.app` 能启动且不报错

### 0.1 修复 `backend/__init__.py`

**文件**: `backend/__init__.py`

**当前内容**: 包含 Java 代码

**操作**: 清空该文件，只保留一个空文件（Python 包标记）

```python
# backend/__init__.py
# 此文件为 Python 包标记，必须为空
```

> ⚠️ **注意**: 文件可以为完全空白，也可以只有一行注释。**绝不能有任何 Java 或非 Python 代码**。

### 0.2 修复 `backend/api/app.py`

**文件**: `backend/api/app.py`

**当前内容**: 第1-13行是 Java 代码，第14行起才是 Python

**操作**: 删除第1-13行的 Java 代码，保留第14行及之后的 Python 代码。修复后文件开头应为：

```python
from flask import Flask, jsonify, request
from backend.services.stock_service import get_stock_metrics
from backend.core.database import DB_FILE, authenticate_user
from backend.services.scanner_service import get_high_dividend_stocks_by_concept
import sqlite3
from datetime import date
from backend.services.scheduler import init_scheduler, manual_trigger, task_logs
# ... 后续代码不变
```

### 0.3 验证

```bash
# 在项目根目录执行
python -c "import backend; print('OK')"
python -c "from backend.api.app import app; print('Flask app loaded')"
python -m backend.api.app
# 应看到 Flask 开发服务器在 0.0.0.0:5000 启动
# Ctrl+C 退出
```

---

## Phase 1 — 配置外部化

> **目标**: 所有硬编码值集中到一个配置模块，支持 `.env` 文件和环境变量覆盖
> **预计时间**: 30 分钟
> **依赖**: Phase 0 完成

### 1.1 添加 `python-dotenv` 依赖

**文件**: `requirements.txt`

在文件末尾添加（同时为所有包加上版本锁定）：

```
flask==3.0.3
streamlit==1.36.0
akshare==1.14.0
requests==2.32.3
pandas==2.2.2
passlib==1.7.4
apscheduler==3.10.4
openpyxl==3.1.5
python-dotenv==1.0.1
flask-cors==4.0.1
gunicorn==22.0.0
gevent==24.2.1
pyjwt==2.8.0
```

> ⚠️ **关于版本号**: 以上版本基于 2024 年中期的稳定版本。如果 `pip install` 时报版本不存在，请去掉版本号安装，然后执行 `pip freeze > requirements.lock.txt` 生成精确锁定文件。实际部署时使用 `requirements.lock.txt`。

### 1.2 创建 `backend/config.py`

**文件**: `backend/config.py`（新建）

**完整内容**：

```python
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _env(key: str, default: str = "", cast: type = str) -> object:
    """从环境变量读取配置值，支持类型转换。"""
    val = os.environ.get(key, default)
    if cast is bool:
        return val.lower() in ("1", "true", "yes")
    return cast(val)


# ── 服务器 ──
HOST = _env("APP_HOST", "0.0.0.0")
PORT = _env("APP_PORT", "5000", int)
DEBUG = _env("APP_DEBUG", "false", bool)

# ── 数据库 ──
DB_PATH = _env("DB_PATH", str(_PROJECT_ROOT / "stocks.db"))

# ── JWT ──
JWT_SECRET = _env("JWT_SECRET", "change-me-in-production-256bit")
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = _env("JWT_EXPIRATION_HOURS", "2", int)

# ── 调度器 ──
SCHEDULER_HOUR = _env("SCHEDULER_HOUR", "15", int)
SCHEDULER_MINUTE = _env("SCHEDULER_MINUTE", "30", int)
SCHEDULER_MAX_RETRIES = _env("SCHEDULER_MAX_RETRIES", "3", int)
SCHEDULER_RETRY_INTERVAL = _env("SCHEDULER_RETRY_INTERVAL", "60", int)
SCAN_MAX_WORKERS = _env("SCAN_MAX_WORKERS", "20", int)

# ── 缓存 ──
CACHE_DIR = _env("CACHE_DIR", str(_PROJECT_ROOT))
CACHE_EXPIRE_HOURS = _env("CACHE_EXPIRE_HOURS", "6", int)

# ── CORS ──
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:10086,http://localhost:8501")

# ── Sina API ──
SINA_HQ_URL = _env("SINA_HQ_URL", "http://hq.sinajs.cn/list=")
SINA_REFERER = _env("SINA_REFERER", "http://finance.sina.com.cn")
SINA_TIMEOUT = _env("SINA_TIMEOUT", "10", int)
SINA_INDEX_TIMEOUT = _env("SINA_INDEX_TIMEOUT", "5", int)

# ── 股息计算 ──
DIVIDEND_LOOKBACK_MONTHS = _env("DIVIDEND_LOOKBACK_MONTHS", "18", int)

# ── 限流 ──
RATE_LIMIT_PER_MINUTE = _env("RATE_LIMIT_PER_MINUTE", "30", int)

# ── 日志 ──
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_DIR = _env("LOG_DIR", str(_PROJECT_ROOT / "logs"))

# ── 默认管理员（仅首次初始化） ──
DEFAULT_ADMIN_USER = _env("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = _env("DEFAULT_ADMIN_PASSWORD", "")
```

> **关键说明**:
> - `DEFAULT_ADMIN_PASSWORD` 默认为空字符串，意味着**不会自动创建默认管理员**，除非环境变量显式设置
> - `DB_PATH` 默认值通过 `Path` 计算，不再依赖相对路径 `../../stocks.db`
> - `CORS_ORIGINS` 是逗号分隔的字符串，后续中间件会 split 为列表

### 1.3 创建 `.env.example`

**文件**: `.env.example`（新建，在项目根目录）

```env
# ── 服务器 ──
APP_HOST=0.0.0.0
APP_PORT=5000
APP_DEBUG=false

# ── 数据库 ──
# DB_PATH=/data/stocks.db

# ── JWT（生产环境必须更改！）──
JWT_SECRET=change-me-in-production-256bit
JWT_EXPIRATION_HOURS=2

# ── 调度器 ──
SCHEDULER_HOUR=15
SCHEDULER_MINUTE=30
SCAN_MAX_WORKERS=20

# ── 缓存 ──
# CACHE_DIR=/data/cache
CACHE_EXPIRE_HOURS=6

# ── CORS ──
CORS_ORIGINS=http://localhost:10086,http://localhost:8501

# ── 日志 ──
LOG_LEVEL=INFO
# LOG_DIR=/data/logs

# ── 默认管理员（仅在首次初始化时使用，生产环境请勿设置）──
# DEFAULT_ADMIN_USER=admin
# DEFAULT_ADMIN_PASSWORD=admin123
```

> ⚠️ `.env` 文件**绝不能**提交到 Git。确保 `.gitignore` 包含 `.env`。

### 1.4 创建 `.env`（本地开发用）

**文件**: `.env`（新建，在项目根目录）

```env
APP_DEBUG=true
DEFAULT_ADMIN_USER=admin
DEFAULT_ADMIN_PASSWORD=admin123
LOG_LEVEL=DEBUG
```

### 1.5 更新 `.gitignore`

**文件**: `.gitignore`（新增或追加）

```
.env
*.db
__pycache__/
*.pyc
logs/
venv/
venv_new/
dist/
build/
*.egg-info/
market_dividends_cache.json
```

### 1.6 验证

```bash
python -c "from backend.config import HOST, PORT, JWT_SECRET; print(f'HOST={HOST}, PORT={PORT}, JWT={JWT_SECRET[:8]}...')"
# 应输出: HOST=0.0.0.0, PORT=5000, JWT=change-m...
```

---

## Phase 2 — 日志与可观测性

> **目标**: 统一日志格式为 JSON，输出到 stdout + 文件，替代所有 `print()`
> **预计时间**: 25 分钟

### 2.1 创建 `backend/core/logging_config.py`

**文件**: `backend/core/logging_config.py`（新建）

```python
import logging
import json
import sys
from pathlib import Path
from backend.config import LOG_LEVEL, LOG_DIR


class JSONFormatter(logging.Formatter):
    """将日志格式化为 JSON，方便 ELK / Loki 等系统采集。"""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def setup_logging() -> None:
    """初始化全局日志配置。应在应用启动时调用一次。"""
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # 避免重复添加 handler（Flask reload 时可能多次调用）
    if root_logger.handlers:
        return

    # stdout handler（容器环境采集 stdout）
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    root_logger.addHandler(stdout_handler)

    # 文件 handler
    file_handler = logging.FileHandler(
        log_dir / "app.log", encoding="utf-8", delay=True
    )
    file_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    root_logger.addHandler(file_handler)

    # 降低第三方库日志级别
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
```

### 2.2 替换各文件中的 `print()`

以下是需要替换的位置汇总，每处 `print(...)` 替换为对应的 `logger.info/warning/error(...)`：

**`backend/services/stock_service.py`**：
- 在文件顶部添加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- 将所有 `print(f"Error ...")` → `logger.error(...)`
- 将所有 `print(f"...")` → `logger.info(...)`

**`backend/services/scanner_service.py`**：
- 顶部添加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- `print(f"Using cached ...")` → `logger.info(...)`
- `print(f"Fetching ...")` → `logger.info(...)`

**`backend/services/scheduler.py`**：
- `log_message()` 函数改为使用 logger：
  ```python
  import logging
  logger = logging.getLogger("scheduler")

  def log_message(msg: str) -> None:
      logger.info(msg)
      task_logs.append({"time": datetime.now().isoformat(), "message": msg})
      if len(task_logs) > 1000:
          task_logs.pop(0)
  ```
  保留 `task_logs` 列表用于 API 返回，但不再用 `print()`。

**`backend/tasks/market_scan.py`**：
- 顶部添加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- `print(f"Scanned {count} ...")` → `logger.info(...)`

**`backend/core/database.py`**：
- 顶部添加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- `print("Created default user ...")` → `logger.info(...)`
- `print("Column already exists ...")` → `logger.debug(...)`

### 2.3 在 Flask 应用启动时初始化日志

在 `backend/api/app.py` 中，创建 Flask app 之后立即调用：

```python
from backend.core.logging_config import setup_logging
setup_logging()
```

### 2.4 验证

```bash
# 启动应用后访问任意 API，检查 logs/app.log 是否有 JSON 格式日志
python -m backend.api.app &
sleep 2
curl http://localhost:5000/api/indices
cat logs/app.log | head -5
# 应看到 JSON 格式日志行
kill %1
```

---

## Phase 3 — 安全加固

> **目标**: 修复 SQL 注入、添加 CORS、添加 JWT 认证中间件
> **预计时间**: 45 分钟

### 3.1 创建 `backend/api/middleware.py`

**文件**: `backend/api/middleware.py`（新建）

```python
import time
import functools
import jwt
from flask import request, jsonify, g
from flask_cors import CORS
from backend.config import (
    CORS_ORIGINS,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    RATE_LIMIT_PER_MINUTE,
)

# ── CORS ──

def init_cors(app):
    """初始化 CORS 配置。"""
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    CORS(app, origins=origins, methods=["GET", "POST", "OPTIONS"])


# ── JWT 认证 ──

def generate_token(username: str) -> str:
    """为已认证用户生成 JWT token。"""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRATION_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict | None:
    """验证 JWT token，返回 payload 或 None。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f):
    """装饰器：要求请求携带有效 JWT token。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 401
        token = auth_header[7:]
        payload = verify_token(token)
        if payload is None:
            return jsonify({"error": "Token expired or invalid"}), 401
        g.current_user = payload["sub"]
        return f(*args, **kwargs)
    return decorated


# ── 简易限流（基于内存，单进程有效） ──

_request_times: dict[str, list[float]] = {}


def rate_limit(f):
    """装饰器：每个 IP 每分钟限制请求数。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        now = time.time()
        times = _request_times.setdefault(ip, [])
        # 清理超过60秒的记录
        times[:] = [t for t in times if now - t < 60]
        if len(times) >= RATE_LIMIT_PER_MINUTE:
            return jsonify({"error": "Rate limit exceeded"}), 429
        times.append(now)
        return f(*args, **kwargs)
    return decorated
```

### 3.2 改造 `backend/api/app.py`

> ⚠️ 这是改动最大的文件。请按以下步骤**逐步修改**，不要一次性重写。

#### 3.2.1 修复 SQL 注入（`/api/top_stocks`）

**当前代码**（第 64-65 行）：
```python
limit = request.args.get('limit', 20)
top_stocks = conn.execute(f"SELECT * FROM stock_daily_metrics WHERE date = ? ORDER BY dividend_yield DESC LIMIT {limit}", (latest_date,)).fetchall()
```

**修改为**：
```python
limit = request.args.get('limit', 20, type=int)
if limit < 1 or limit > 100:
    limit = 20
top_stocks = conn.execute(
    "SELECT * FROM stock_daily_metrics WHERE date = ? ORDER BY dividend_yield DESC LIMIT ?",
    (latest_date, limit),
).fetchall()
```

> **解释**：`LIMIT` 也用参数化查询，并且增加范围校验（1-100），防止恶意输入。

#### 3.2.2 添加 CORS 和中间件初始化

在 `app = Flask(__name__)` 之后添加：

```python
from backend.api.middleware import init_cors, login_required, rate_limit, generate_token
from backend.core.logging_config import setup_logging

setup_logging()
init_cors(app)
```

#### 3.2.3 改造 `/api/login` 返回 JWT

**当前代码**：
```python
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if authenticate_user(username, password):
        return jsonify({"success": True, "message": "Login successful"}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401
```

**修改为**：
```python
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '')
    password = data.get('password', '')
    if authenticate_user(username, password):
        token = generate_token(username)
        return jsonify({"success": True, "token": token}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401
```

#### 3.2.4 给受保护路由添加 `@login_required`

为以下路由添加装饰器（注意 `@login_required` 放在 `@app.route` 之下）：

```python
@app.route('/api/indices', methods=['GET'])
@login_required
def get_indices():
    ...

@app.route('/api/top_stocks', methods=['GET'])
@login_required
@rate_limit
def get_top_stocks():
    ...

@app.route('/api/stock/<symbol>', methods=['GET'])
@login_required
def get_stock(symbol):
    ...

@app.route('/api/refresh', methods=['POST'])
@login_required
def refresh_data():
    ...

@app.route('/api/logs', methods=['GET'])
@login_required
def get_logs():
    ...
```

> ⚠️ **注意**: `/api/login` 和 `/health`（后续添加）**不加** `@login_required`。

#### 3.2.5 添加全局错误处理器

在 `app.py` 末尾（`if __name__` 之前）添加：

```python
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    import logging
    logging.getLogger(__name__).error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "Internal server error"}), 500
```

#### 3.2.6 数据库连接使用 context manager

将 `get_db_connection()` 改为：

```python
from contextlib import contextmanager

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

所有路由中的数据库用法改为：

```python
# 旧写法
conn = get_db_connection()
# ... 操作 ...
conn.close()

# 新写法
with get_db_connection() as conn:
    # ... 操作 ...
```

> ⚠️ **逐个路由修改**，不要遗漏。每个路由都要从 `conn = ... / conn.close()` 改为 `with ... as conn:`。

#### 3.2.7 修改 `DB_FILE` 来源

**当前**：`from backend.core.database import DB_FILE`

**修改为**：`from backend.config import DB_PATH as DB_FILE`

> 这样数据库路径由配置文件控制，不再依赖 `database.py` 中的相对路径计算。

### 3.3 更新 `backend/core/database.py` 的 `DB_FILE`

**当前代码**（第 7 行左右）：
```python
DB_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'stocks.db')
```

**修改为**：
```python
from backend.config import DB_PATH as DB_FILE
```

### 3.4 验证

```bash
# 启动服务
python -m backend.api.app &
sleep 2

# 1. 无 token 访问应返回 401
curl -s http://localhost:5000/api/indices | python -m json.tool
# 期望: {"error": "Missing or invalid token"}

# 2. 登录获取 token
TOKEN=$(curl -s -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
echo "Token: $TOKEN"

# 3. 用 token 访问
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/indices | python -m json.tool
# 期望: [] (空列表，因为 market_indices 表无数据) 或 数据列表

# 4. SQL 注入测试
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:5000/api/top_stocks?limit=999;DROP%20TABLE%20users"
# 期望: 正常返回（limit 被截断为20），不会执行注入

kill %1
```

---

## Phase 4 — 数据库改造

> **目标**: 使用配置化路径、添加初始化钩子、修复缺失数据写入
> **预计时间**: 30 分钟

### 4.1 改造 `backend/core/database.py`

**完整替换文件内容**：

```python
import sqlite3
import logging
from backend.config import DB_PATH as DB_FILE, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
from passlib.hash import pbkdf2_sha256

logger = logging.getLogger(__name__)


def get_connection():
    """获取原始数据库连接（服务层使用）。"""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """初始化数据库表结构和默认数据。应在应用启动时调用。"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stock_daily_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                price REAL,
                dividend_yield REAL,
                dividend_per_share REAL,
                update_time TEXT,
                UNIQUE(date, code)
            );

            CREATE TABLE IF NOT EXISTS market_indices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                value REAL,
                change_amount REAL,
                change_pct REAL,
                UNIQUE(date, symbol)
            );
        """)
        conn.commit()

        # 迁移：添加缺失列
        _ensure_column(conn, "stock_daily_metrics", "dividend_per_share", "REAL")
        _ensure_column(conn, "stock_daily_metrics", "update_time", "TEXT")

        # 创建默认管理员（仅在环境变量显式设置了密码时）
        if DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
            register_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)

        logger.info("Database initialized successfully")
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, col_type: str) -> None:
    """安全添加列（如已存在则跳过）。"""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
        logger.info(f"Added column {column} to {table}")
    except sqlite3.OperationalError:
        pass  # 列已存在


def register_user(username: str, password: str) -> bool:
    """注册新用户，成功返回 True，用户已存在返回 False。"""
    password_hash = pbkdf2_sha256.hash(password)
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
        logger.info(f"User '{username}' created")
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate_user(username: str, password: str) -> bool:
    """验证用户名和密码。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False
        return pbkdf2_sha256.verify(password, row[0])
    finally:
        conn.close()
```

### 4.2 在 Flask 应用启动时调用 `init_db()`

在 `backend/api/app.py` 中，`app = Flask(__name__)` 之后添加：

```python
from backend.core.database import init_db
init_db()
```

> **顺序**：`setup_logging()` → `init_db()` → `init_cors(app)` → `init_scheduler()`

### 4.3 修复 `market_indices` 数据写入

**文件**: `backend/tasks/market_scan.py`

在 `full_market_scan()` 函数中，**在写入 `stock_daily_metrics` 之后**，添加写入 `market_indices` 的逻辑：

```python
# 在 full_market_scan() 函数末尾，commit 之后添加：
from backend.services.stock_service import get_sina_index_spot

INDEX_SYMBOLS = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000016": "上证50",
    "000300": "沪深300",
}

today = date.today().isoformat()
for symbol, name in INDEX_SYMBOLS.items():
    try:
        data = get_sina_index_spot(symbol)
        if data:
            conn.execute(
                "INSERT OR REPLACE INTO market_indices (date, symbol, name, value, change_amount, change_pct) VALUES (?, ?, ?, ?, ?, ?)",
                (today, symbol, name, data.get("value", 0), data.get("change_amount", 0), data.get("change_pct", 0)),
            )
    except Exception as e:
        logger.warning(f"Failed to fetch index {symbol}: {e}")
conn.commit()
```

### 4.4 验证

```bash
# 确保 stocks.db 不存在（测试全新初始化）
rm -f stocks.db

# 启动（如果 .env 中设置了 DEFAULT_ADMIN_PASSWORD，会自动创建管理员）
python -c "from backend.core.database import init_db; init_db()"

# 验证表结构
python -c "
import sqlite3
conn = sqlite3.connect('stocks.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('Tables:', [t[0] for t in tables])
conn.close()
"
# 期望: Tables: ['users', 'stock_daily_metrics', 'market_indices']
```

---

## Phase 5 — WSGI 服务器与容器化

> **目标**: 用 Gunicorn 替代 Flask 开发服务器，重建 Docker 配置
> **预计时间**: 40 分钟

### 5.1 创建 `backend/gunicorn_config.py`

**文件**: `backend/gunicorn_config.py`（新建）

```python
import multiprocessing

# 监听地址
bind = "0.0.0.0:5000"

# Worker 数量：通常为 (2 × CPU核心数) + 1，但本项目有调度器，不宜太多 worker
workers = int(os.environ.get("GUNICORN_WORKERS", "2")) if "os" in dir() else 2

# 使用 gevent 协程（适合 I/O 密集型，如 HTTP 请求外部 API）
worker_class = "gevent"

# 每个 worker 处理的最大请求数（之后重启 worker，防内存泄漏）
max_requests = 1000
max_requests_jitter = 50

# 预加载应用（减少内存占用）
preload_app = True

# 请求超时（秒）—— 单只股票查询可能需要10秒
timeout = 30

# 优雅重启超时
graceful_timeout = 10

# 访问日志格式
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 错误日志
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower() if "os" in dir() else "info"
```

> ⚠️ 上面的 `os` 引用有问题。修正为：

```python
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
```

### 5.2 创建 Flask 应用工厂函数

**文件**: `backend/api/app.py` 改造

当前 `app.py` 在模块级别创建 app 并调用 `app.run()`。需要改为应用工厂模式，使 Gunicorn 可以导入：

```python
# backend/api/app.py

from flask import Flask, jsonify, request
from contextlib import contextmanager
import sqlite3
import logging
from datetime import date

from backend.config import DB_PATH as DB_FILE
from backend.core.database import init_db, authenticate_user
from backend.core.logging_config import setup_logging
from backend.services.stock_service import get_stock_metrics
from backend.services.scanner_service import get_high_dividend_stocks_by_concept
from backend.services.scheduler import init_scheduler, manual_trigger, task_logs
from backend.api.middleware import init_cors, login_required, rate_limit, generate_token

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Flask 应用工厂。"""
    app = Flask(__name__)

    # 初始化顺序：日志 → 数据库 → CORS → 调度器
    setup_logging()
    init_db()
    init_cors(app)
    init_scheduler()

    # ── 数据库连接 ──
    @contextmanager
    def get_db_connection():
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ── 路由 ──
    @app.route('/api/login', methods=['POST'])
    def login():
        data = request.json or {}
        username = data.get('username', '')
        password = data.get('password', '')
        if authenticate_user(username, password):
            token = generate_token(username)
            return jsonify({"success": True, "token": token}), 200
        return jsonify({"success": False, "message": "Invalid credentials"}), 401

    @app.route('/api/indices', methods=['GET'])
    @login_required
    def get_indices():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM market_indices")
            row = cursor.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            indices = conn.execute(
                "SELECT * FROM market_indices WHERE date = ?", (latest_date,)
            ).fetchall()
        return jsonify([dict(ix) for ix in indices])

    @app.route('/api/top_stocks', methods=['GET'])
    @login_required
    @rate_limit
    def get_top_stocks():
        limit = request.args.get('limit', 20, type=int)
        if limit < 1 or limit > 100:
            limit = 20
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM stock_daily_metrics")
            row = cursor.fetchone()
            latest_date = row[0] if row and row[0] else date.today().isoformat()
            top_stocks = conn.execute(
                "SELECT * FROM stock_daily_metrics WHERE date = ? ORDER BY dividend_yield DESC LIMIT ?",
                (latest_date, limit),
            ).fetchall()
        return jsonify([dict(s) for s in top_stocks])

    @app.route('/api/stock/<symbol>', methods=['GET'])
    @login_required
    def get_stock(symbol):
        try:
            data = get_stock_metrics(symbol)
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error fetching stock {symbol}: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 400

    @app.route('/api/refresh', methods=['POST'])
    @login_required
    def refresh_data():
        msg = manual_trigger()
        return jsonify({"message": msg}), 200

    @app.route('/api/logs', methods=['GET'])
    @login_required
    def get_logs():
        return jsonify(task_logs)

    # ── 错误处理 ──
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

    return app


# Gunicorn 入口：gunicorn "backend.api.app:create_app()"
# 开发入口：
if __name__ == '__main__':
    from backend.config import HOST, PORT, DEBUG
    app = create_app()
    app.run(host=HOST, port=PORT, debug=DEBUG)
```

> **重要**：`get_db_connection()` 被定义为 `create_app()` 内部的局部函数。如果其他模块需要数据库连接，请使用 `backend.core.database.get_connection()`。

### 5.3 重建 Dockerfile

**文件**: `Dockerfile`（完全重写）

```dockerfile
# ── 构建阶段 ──
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── 运行阶段 ──
FROM python:3.11-slim

LABEL maintainer="stock-agent"
LABEL description="A股股息监测系统 Python 后端"

# 安全：使用非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 从构建阶段复制已安装的包
COPY --from=builder /install /usr/local

# 复制应用代码
COPY backend/ backend/

# 创建数据和日志目录
RUN mkdir -p /data/cache /data/logs && chown -R appuser:appuser /data /app

# 切换到非 root 用户
USER appuser

# 环境变量默认值
ENV APP_HOST=0.0.0.0 \
    APP_PORT=5000 \
    APP_DEBUG=false \
    DB_PATH=/data/stocks.db \
    CACHE_DIR=/data/cache \
    LOG_DIR=/data/logs \
    LOG_LEVEL=INFO \
    GUNICORN_WORKERS=2

EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Gunicorn 启动
CMD ["gunicorn", "--config", "backend/gunicorn_config.py", "backend.api.app:create_app()"]
```

> **设计要点**:
> - 多阶段构建减小镜像体积
> - 使用非 root 用户运行
> - 数据目录 `/data/` 独立于应用代码
> - 内置 `HEALTHCHECK`
> - 使用 Gunicorn 而非 Flask dev server

### 5.4 重建 docker-compose.yml

**文件**: `docker-compose.yml`（完全重写）

```yaml
version: "3.8"

services:
  python-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-python-api
    restart: unless-stopped
    ports:
      - "${APP_PORT:-5000}:5000"
    environment:
      - DB_PATH=/data/stocks.db
      - CACHE_DIR=/data/cache
      - LOG_DIR=/data/logs
      - JWT_SECRET=${JWT_SECRET:-change-me-in-production-256bit}
      - DEFAULT_ADMIN_USER=${DEFAULT_ADMIN_USER:-}
      - DEFAULT_ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD:-}
      - CORS_ORIGINS=${CORS_ORIGINS:-http://localhost:10086}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - app-data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

volumes:
  app-data:
    driver: local
```

### 5.5 创建 `backend/entrypoint.sh`

**文件**: `backend/entrypoint.sh`（新建）

```bash
#!/bin/bash
set -e

echo "[$(date -Iseconds)] Starting Stock Agent Python Backend..."

# 确保数据目录存在
mkdir -p /data/cache /data/logs

# 初始化数据库（如果不存在）
python -c "from backend.core.database import init_db; init_db()"

# 启动 Gunicorn
exec gunicorn --config backend/gunicorn_config.py "backend.api.app:create_app()"
```

> 如果使用 `entrypoint.sh`，Dockerfile 的 CMD 改为：
> ```dockerfile
> CMD ["bash", "backend/entrypoint.sh"]
> ```

### 5.6 验证

```bash
# 本地验证 Gunicorn
pip install gunicorn gevent
gunicorn --config backend/gunicorn_config.py "backend.api.app:create_app()"
# 另一个终端：
curl http://localhost:5000/health  # 后续 Phase 添加
# Ctrl+C 退出

# Docker 验证
docker build -t stock-python-api .
docker run -d --name test-api \
  -e JWT_SECRET=test-secret-123 \
  -e DEFAULT_ADMIN_USER=admin \
  -e DEFAULT_ADMIN_PASSWORD=admin123 \
  -p 5000:5000 \
  stock-python-api

# 等待启动
sleep 5
docker logs test-api
curl http://localhost:5000/api/login \
  -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 清理
docker stop test-api && docker rm test-api
```

---

## Phase 6 — 健康检查与运维接口

> **目标**: 添加 `/health` 端点、改进缓存过期、修复并发问题
> **预计时间**: 20 分钟

### 6.1 添加 `/health` 端点

**文件**: `backend/api/app.py`，在 `create_app()` 中添加：

```python
@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点，无需认证。"""
    db_ok = False
    try:
        with get_db_connection() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass
    status = "healthy" if db_ok else "unhealthy"
    code = 200 if db_ok else 503
    return jsonify({"status": status, "database": db_ok}), code
```

### 6.2 改造缓存过期机制

**文件**: `backend/services/scanner_service.py`

**当前问题**: 缓存文件永不过期

**修改方案**: 在缓存 JSON 中添加 `timestamp` 字段，读取时检查是否过期

```python
import json
import time
import logging
from pathlib import Path
from backend.config import CACHE_DIR, CACHE_EXPIRE_HOURS
from backend.services.stock_service import get_stock_metrics

logger = logging.getLogger(__name__)

CACHE_FILE = Path(CACHE_DIR) / "market_dividends_cache.json"


def _is_cache_valid(cache_data: dict) -> bool:
    """检查缓存是否在有效期内。"""
    ts = cache_data.get("timestamp", 0)
    return (time.time() - ts) < (CACHE_EXPIRE_HOURS * 3600)


def _read_cache() -> dict | None:
    """读取缓存，过期则返回 None。"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if _is_cache_valid(data):
                logger.info("Using cached high-dividend data")
                return data
            else:
                logger.info("Cache expired, will refresh")
                return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cache read failed: {e}")
    return None


def _write_cache(data: list) -> None:
    """写入缓存并附加时间戳。"""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False)
    except OSError as e:
        logger.warning(f"Cache write failed: {e}")


def get_high_dividend_stocks_by_concept(limit: int = 20) -> list:
    """获取高股息股票列表，带缓存。"""
    # 尝试读缓存
    cached = _read_cache()
    if cached is not None:
        return cached.get("data", [])[:limit]

    # 实际获取数据
    import akshare as ak
    import time as _time

    stocks = []
    try:
        df = ak.index_stock_cons(symbol="000922")
    except Exception:
        try:
            df = ak.index_stock_cons(symbol="000015")
        except Exception as e:
            logger.error(f"Failed to fetch index constituents: {e}")
            return []

    for i, row in df.iterrows():
        code = str(row["品种代码"]).zfill(6)
        try:
            metrics = get_stock_metrics(code)
            if metrics and metrics.get("股息率"):
                stocks.append(metrics)
        except Exception as e:
            logger.warning(f"Failed to get metrics for {code}: {e}")
            continue
        if i > 0 and i % 5 == 0:
            _time.sleep(1)

    stocks.sort(key=lambda x: x.get("股息率", 0), reverse=True)
    result = stocks[:limit]

    _write_cache(result)
    return result
```

### 6.3 修复调度器并发问题

**文件**: `backend/services/scheduler.py`

添加互斥锁，防止定时任务和手动触发同时执行：

```python
import threading

_scan_lock = threading.Lock()
_scan_running = False


def daily_update_task():
    global _scan_running
    if _scan_running:
        log_message("Scan already running, skipping")
        return

    with _scan_lock:
        _scan_running = True
        try:
            log_message("Starting daily update task")
            # ... 原有重试逻辑 ...
            from backend.tasks.market_scan import full_market_scan
            from backend.config import SCAN_MAX_WORKERS, SCHEDULER_MAX_RETRIES, SCHEDULER_RETRY_INTERVAL

            for attempt in range(1, SCHEDULER_MAX_RETRIES + 1):
                try:
                    full_market_scan(max_workers=SCAN_MAX_WORKERS)
                    log_message("Daily update completed successfully")
                    return
                except Exception as e:
                    log_message(f"Attempt {attempt} failed: {e}")
                    if attempt < SCHEDULER_MAX_RETRIES:
                        import time
                        time.sleep(SCHEDULER_RETRY_INTERVAL)
            log_message("All retry attempts failed")
        finally:
            _scan_running = False
```

### 6.4 添加 `task_logs` 线程安全

**文件**: `backend/services/scheduler.py`

```python
import threading

_task_logs_lock = threading.Lock()
task_logs = []


def log_message(msg: str) -> None:
    import logging
    from datetime import datetime
    logger = logging.getLogger("scheduler")
    logger.info(msg)
    entry = {"time": datetime.now().isoformat(), "message": msg}
    with _task_logs_lock:
        task_logs.append(entry)
        if len(task_logs) > 1000:
            task_logs.pop(0)
```

### 6.5 验证

```bash
# 健康检查
curl http://localhost:5000/health
# 期望: {"status":"healthy","database":true}

# 缓存过期验证
python -c "
import time, json
from pathlib import Path
# 写一个过期的缓存
cache = Path('market_dividends_cache.json')
cache.write_text(json.dumps({'timestamp': time.time() - 99999, 'data': []}))
from backend.services.scanner_service import _read_cache
print('Cache valid:', _read_cache() is not None)
# 期望: Cache valid: False
"
```

---

## Phase 7 — 进程管理与服务编排

> **目标**: 支持 systemd 管理和 docker-compose 完整编排
> **预计时间**: 20 分钟

### 7.1 创建 systemd 服务文件（Linux 部署）

**文件**: `deploy/stock-python-api.service`（新建）

```ini
[Unit]
Description=Stock Agent Python API
After=network.target

[Service]
Type=notify
User=appuser
Group=appuser
WorkingDirectory=/opt/stock-agent
EnvironmentFile=/opt/stock-agent/.env
ExecStart=/opt/stock-agent/venv/bin/gunicorn \
    --config backend/gunicorn_config.py \
    "backend.api.app:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5

# 安全加固
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/stock-agent/data /opt/stock-agent/logs

[Install]
WantedBy=multi-user.target
```

### 7.2 创建部署脚本

**文件**: `deploy/deploy.sh`（新建）

```bash
#!/bin/bash
set -euo pipefail

PROJECT_DIR="/opt/stock-agent"
VENV_DIR="$PROJECT_DIR/venv"

echo "=== Stock Agent Python Backend Deployment ==="

# 1. 创建用户（如果不存在）
id -u appuser &>/dev/null || useradd -r -m -d "$PROJECT_DIR" -s /sbin/nologin appuser

# 2. 创建虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR"
fi

# 3. 安装依赖
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 4. 创建数据和日志目录
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"
chown -R appuser:appuser "$PROJECT_DIR/data" "$PROJECT_DIR/logs"

# 5. 检查 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found at $PROJECT_DIR/.env"
    echo "Copy .env.example to .env and fill in production values."
    exit 1
fi

# 6. 初始化数据库
sudo -u appuser "$VENV_DIR/bin/python" -c "from backend.core.database import init_db; init_db()"

# 7. 安装 systemd 服务
cp "$PROJECT_DIR/deploy/stock-python-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable stock-python-api
systemctl start stock-python-api

echo "=== Deployment complete ==="
echo "Status: systemctl status stock-python-api"
echo "Logs:   journalctl -u stock-python-api -f"
```

### 7.3 完整 docker-compose.yml（含 Nginx 反向代理）

**文件**: `docker-compose.yml`（扩展版）

```yaml
version: "3.8"

services:
  python-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: stock-python-api
    restart: unless-stopped
    expose:
      - "5000"
    environment:
      - DB_PATH=/data/stocks.db
      - CACHE_DIR=/data/cache
      - LOG_DIR=/data/logs
      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET must be set}
      - DEFAULT_ADMIN_USER=${DEFAULT_ADMIN_USER:-}
      - DEFAULT_ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD:-}
      - CORS_ORIGINS=http://localhost,http://localhost:10086
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - GUNICORN_WORKERS=${GUNICORN_WORKERS:-2}
    volumes:
      - app-data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  nginx:
    image: nginx:1.25-alpine
    container_name: stock-nginx
    restart: unless-stopped
    ports:
      - "${NGINX_PORT:-80}:80"
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      python-api:
        condition: service_healthy

volumes:
  app-data:
    driver: local
```

### 7.4 创建 Nginx 配置

**文件**: `deploy/nginx.conf`（新建）

```nginx
upstream python_api {
    server python-api:5000;
}

server {
    listen 80;
    server_name _;

    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # API 代理
    location /api/ {
        proxy_pass http://python_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
    }

    # 健康检查代理
    location /health {
        proxy_pass http://python_api;
        proxy_set_header Host $host;
    }

    # 其他路径返回 404
    location / {
        return 404;
    }
}
```

### 7.5 验证

```bash
# Docker Compose 完整验证
docker-compose up -d
sleep 10

# 检查服务状态
docker-compose ps
curl http://localhost/health

# 登录测试
curl -X POST http://localhost/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 查看日志
docker-compose logs python-api --tail=20

# 清理
docker-compose down
```

---

# 第四部分：文件变更清单

以下是所有需要新建或修改的文件，标注了操作类型和优先级：

| 操作 | 文件路径 | Phase | 优先级 |
|------|----------|-------|--------|
| **修改** | `backend/__init__.py` | 0 | P0 |
| **修改** | `backend/api/app.py` | 0,3,5 | P0 |
| **新建** | `backend/config.py` | 1 | P0 |
| **新建** | `.env.example` | 1 | P1 |
| **新建** | `.env` | 1 | P1 |
| **修改** | `.gitignore` | 1 | P1 |
| **修改** | `requirements.txt` | 1 | P1 |
| **新建** | `backend/core/logging_config.py` | 2 | P1 |
| **修改** | `backend/services/stock_service.py` | 2 | P2 |
| **修改** | `backend/services/scanner_service.py` | 2,6 | P2 |
| **修改** | `backend/services/scheduler.py` | 2,6 | P2 |
| **修改** | `backend/tasks/market_scan.py` | 2,4 | P2 |
| **修改** | `backend/core/database.py` | 2,3,4 | P1 |
| **新建** | `backend/api/middleware.py` | 3 | P1 |
| **修改** | `backend/services/stock_service.py` | 4 | P2 |
| **新建** | `backend/gunicorn_config.py` | 5 | P1 |
| **重写** | `Dockerfile` | 5 | P1 |
| **重写** | `docker-compose.yml` | 5,7 | P2 |
| **新建** | `backend/entrypoint.sh` | 5 | P2 |
| **新建** | `deploy/stock-python-api.service` | 7 | P3 |
| **新建** | `deploy/deploy.sh` | 7 | P3 |
| **新建** | `deploy/nginx.conf` | 7 | P3 |

---

# 第五部分：验证检查清单

每个 Phase 完成后，执行对应的验证步骤。全部 Phase 完成后执行整体验证。

## Phase 0 验证
- [ ] `python -c "import backend"` 无报错
- [ ] `python -c "from backend.api.app import create_app"` 无报错
- [ ] `python -m backend.api.app` 能启动 Flask 服务器

## Phase 1 验证
- [ ] `python -c "from backend.config import HOST"` 输出配置值
- [ ] `.env` 文件存在且不被 Git 追踪
- [ ] `.gitignore` 包含 `.env`

## Phase 2 验证
- [ ] `logs/` 目录下生成了 `app.log`
- [ ] 日志内容为 JSON 格式
- [ ] 无 `print()` 残留在 backend 代码中（`grep -r "print(" backend/ --include="*.py"` 排除 `dashboard/` 和 `tests/`）

## Phase 3 验证
- [ ] 无 token 访问 `/api/indices` 返回 401
- [ ] 登录成功返回 JWT token
- [ ] 使用 token 可正常访问 API
- [ ] `?limit=abc` 不导致 SQL 注入（返回 20 条或错误，不崩溃）

## Phase 4 验证
- [ ] 删除 `stocks.db` 后启动，数据库自动重建
- [ ] `/api/indices` 在扫描任务执行后返回数据
- [ ] 默认管理员仅在 `.env` 设置了密码时创建

## Phase 5 验证
- [ ] Gunicorn 可启动：`gunicorn "backend.api.app:create_app()"`
- [ ] Docker 镜像构建成功：`docker build -t stock-python-api .`
- [ ] 容器启动后健康检查通过

## Phase 6 验证
- [ ] `/health` 返回 `{"status":"healthy","database":true}`
- [ ] 过期缓存不被使用
- [ ] 并发手动触发不会导致双重扫描

## Phase 7 验证
- [ ] `docker-compose up -d` 启动成功
- [ ] Nginx 代理正常：`curl http://localhost/health`
- [ ] `docker-compose logs` 显示 JSON 格式日志

## 完整冒烟测试

```bash
#!/bin/bash
# 1. 启动
docker-compose up -d && sleep 15

# 2. 健康检查
curl -sf http://localhost/health | python -m json.tool

# 3. 登录
TOKEN=$(curl -sf -X POST http://localhost/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 4. 查询
curl -sf -H "Authorization: Bearer $TOKEN" http://localhost/api/indices | python -m json.tool
curl -sf -H "Authorization: Bearer $TOKEN" http://localhost/api/top_stocks?limit=5 | python -m json.tool
curl -sf -H "Authorization: Bearer $TOKEN" http://localhost/api/stock/600519 | python -m json.tool

# 5. 清理
docker-compose down
echo "=== Smoke test passed ==="
```

---

# 附录 A：完整文件内容参考

以下提供改造后的关键文件的**完整内容**，供初级工程师直接使用。

## A.1 `backend/__init__.py`

```python
# Python package marker - must be empty
```

## A.2 `backend/config.py`

> 见 Phase 1.2 的完整内容

## A.3 `backend/api/app.py`

> 见 Phase 5.2 的完整内容

## A.4 `backend/api/middleware.py`

> 见 Phase 3.1 的完整内容

## A.5 `backend/core/database.py`

> 见 Phase 4.1 的完整内容

## A.6 `backend/core/logging_config.py`

> 见 Phase 2.1 的完整内容

## A.7 `backend/services/scanner_service.py`

> 见 Phase 6.2 的完整内容

## A.8 `backend/gunicorn_config.py`

> 见 Phase 5.1 的修正后内容

## A.9 `Dockerfile`

> 见 Phase 5.3 的完整内容

---

# 附录 B：常见问题与排障

## B.1 `ModuleNotFoundError: No module named 'backend'`

**原因**: 在错误的目录下运行 Python，或缺少 `__init__.py`。

**解决**:
```bash
# 确保在项目根目录（包含 backend/ 文件夹的目录）
cd /path/to/stock_agent
python -c "import backend"
```

## B.2 `SyntaxError` 启动时

**原因**: `__init__.py` 或 `app.py` 中残留 Java 代码。

**解决**: 按 Phase 0 检查并删除所有非 Python 代码。

## B.3 Gunicorn 启动后 502 Bad Gateway

**原因**: 应用在 `create_app()` 中抛出了异常。

**排查**:
```bash
# 直接运行 Python 测试
python -c "from backend.api.app import create_app; app = create_app(); print('OK')"

# 查看 Gunicorn 日志
docker-compose logs python-api
```

## B.4 数据库锁定 `database is locked`

**原因**: SQLite 并发写入冲突。

**解决**:
- 确认 WAL 模式已启用：`PRAGMA journal_mode=WAL`
- 降低 `SCAN_MAX_WORKERS`（如从 20 降到 5）
- 长期方案：迁移到 MySQL/PostgreSQL

## B.5 Sina API 返回空数据

**原因**: 代理环境或频率限制。

**排查**:
```bash
# 检查是否能直接访问
curl -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh600519"

# 如果超时，检查代理设置
echo $HTTP_PROXY $HTTPS_PROXY
```

## B.6 Docker 构建失败 `pip install` 报错

**原因**: 网络问题或版本锁定冲突。

**解决**:
```bash
# 1. 去掉版本号，使用最新稳定版
# 2. 使用国内 pip 镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## B.7 JWT token 验证失败

**原因**: 多个实例的 `JWT_SECRET` 不一致。

**解决**: 确保 `.env` 文件中 `JWT_SECRET` 在所有实例中相同，且不为默认值。

---

> **文档结束**
> 本设计书覆盖了从紧急修复到商业级部署的完整路径。建议按 Phase 顺序逐步实施，每个 Phase 完成后执行对应验证，确认无误后再进入下一个 Phase。如有疑问，请参考附录 B 的排障指南。
