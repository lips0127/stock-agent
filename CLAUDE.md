# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

量化工具 — 个人量化系统，集股息率监控、舆情/VIX 情绪分析、财报解析于一体。

## 架构（极简版）

```
浏览器 → Nginx (80) → Python Flask API (5000) → AkShare/Sina/EastMoney
                          ↓
                     SQLite DB (/data/stocks.db)
```

## 模块说明

### Python 后端 (`backend/`)

**API & 核心**
- `api/app.py` — Flask 应用入口
- `api/routes/` — API 路由（auth, market, ops, sentiment, vix, vix2, intraday, financial, scheduler, tasks, stock_dashboard）
- `api/routes/tasks.py` — 统一任务 API（6 个端点：列表/详情/日志/取消/活跃/最近）**【Phase A, 2026-06-10】**
- `core/database.py` — SQLite 数据库操作（task_runs / task_run_logs 等表）
- `core/task_runner.py` — 统一任务执行器（TaskRunner 上下文管理器）**【Phase A, 2026-06-10】**
- `core/task_kinds.py` — 任务类型注册表（kind 枚举）**【Phase A, 2026-06-10】**
- `core/logging_config.py` — 日志配置（RotatingFileHandler + task_id 注入 + 噪声压制）

**数据 & 服务**
- `services/stock_service.py` — 股票数据获取（新浪/EastMoney）
- `services/scanner_service.py` — 股息指数成分股扫描
- `services/scheduler.py` — APScheduler 定时任务（工作日 15:30）
- `services/forum_service.py` — 东财股吧爬虫
- `services/sentiment_service.py` — LLM 情绪分析（LangChain）
- `services/vix_service.py` / `vix2_service.py` — VIX 恐慌指数 + VIX2.0 ML 情绪回归
- `services/financial_service.py` — 财报 PDF 解析
- `tasks/market_scan.py` — 扫描脚本

### 前端 (`frontend/`)
- Vue 3 + Element Plus + Pinia + Vue Router 单页应用
- 页面：仪表盘、全量扫描、红利指数、自选股、舆情监控、VIX、财报解析、任务调度（知乎大V模块已于 2026-08-30 移除，见 docs/SPEC.md 第 5 节）
- 调用 `/api/` 获取数据，生产环境由 Nginx 托管 dist/

## 启动方式

```bash
# 开发模式（推荐，HMR 热更新，无需 build）
# 一条命令拉起 Flask + Vite；浏览器访问 http://localhost:5000 会被 302 到 5173
python -m backend.api.app

# 如果只想跑后端
FRONTEND_DEV_PROXY=false python -m backend.api.app

# 如果想自己手动起 Vite（依旧生效，Flask 检测到 Vite 在跑就直接代理）
cd frontend && npm install && npm run dev
# 然后浏览器访问 http://localhost:5173

# Docker 部署（生产：Nginx 托管 dist/）
docker-compose up --build

# 手动全量扫描
python -m backend.tasks.market_scan
```

**Dev 端口分工**：
- `5000` (Flask)：API + 鉴权 + 静态资源兜底；HTML 路由 302 → 5173
- `5173` (Vite)：源码 + HMR；`/api/*` 反代回 5000
- 用户只需访问 `http://localhost:5000`，自动跳到 5173，体感是单端口

## 数据库

SQLite 文件：`stocks.db`（或 docker-compose 里的 `/data/stocks.db`）

表结构：
- `py_users` — 用户账户
- `stock_daily_metrics` — 每日股票指标
- `market_indices` — 大盘指数
- `scan_tasks` — 扫描任务跟踪（[deprecated] 已迁移至 task_runs）
- `task_runs` — 统一异步任务运行记录（Phase A）
- `task_run_logs` — 统一异步任务日志（milestone/info/warn/error）
- `sentiment_config` — 舆情监控配置
- `forum_posts` — 股吧帖子缓存
- `sentiment_scores` — LLM 情绪评分
- `sentiment_post_labels` / `sentiment_indicators` / `sentiment_top_picks` / `sentiment_filters` — 舆情因子生产线
- `sentiment_universe_*` — 全市场舆情观测台
- `vix_history` — VIX 历史
- `scheduler_task_config` / `scheduler_task_run` — 调度配置与运行记录
- `financial_reports_cache` — 财报解析缓存

## 核心 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/indices` | 大盘指数（DB 缓存） |
| GET | `/api/indices/live` | 大盘指数（实时） |
| GET | `/api/top_stocks?limit=N` | 高股息股票排名（优先取全市场扫描数据） |
| GET | `/api/stock/<symbol>` | 单只股票详情 |
| GET | `/api/all_stocks?scan_type=index\|full` | 分页股票列表（指定 scan_type 时取该类型自身最近一次扫描日期） |
| POST | `/api/index_scan` | 触发红利指数成分股扫描 |
| POST | `/api/full_refresh` | 触发全市场扫描（异步） |
| GET | `/api/logs` | 任务执行日志 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/tasks` | 任务列表（?kind=&status=&limit=） |
| GET | `/api/tasks/active` | 当前运行中的任务 |
| GET | `/api/tasks/recent` | 最近完成的任务 |
| GET | `/api/tasks/<id>` | 任务详情（进度/耗时/milestone） |
| GET | `/api/tasks/<id>/logs` | 增量拉取任务日志 |
| POST | `/api/tasks/<id>/cancel` | 请求取消任务 |

## 开发注意事项

- AkShare 调用通过 `_no_proxy()` 上下文管理器绕过代理
- `market_dividends_cache.json` 缓存高股息扫描结果
- Docker 部署时数据库文件挂载在 `app-data` volume

## 弃用端点（请改用 `/api/tasks/<id>`）

| 旧端点 | 状态 |
|------|------|
| `GET /api/vix/recompute_status` | 410 Gone |
| `GET /api/vix/backfill_status` | 410 Gone |
| `/api/zhihu/*` 全部端点 | 已随知乎模块移除（2026-08-30），不复存在 |

# 核心工作协议 (CRITICAL)
- **设计优先**：在接受任何 Feature 开发或大规模重构任务前，必须先阅读并更新 `docs/SPEC.md`。
- **闭环审计**：在任务结束（准备输出代码或提示完成）前，必须检查代码实现与 `docs/SPEC.md` 是否一致。
- **自动同步**：如果开发过程中逻辑发生了偏离，必须在任务结束前自动发起对 `docs/SPEC.md` 的更新，严禁出现”代码已改、文档未动”的情况。
- **新增异步任务约束**（Phase A, 2026-06-10）：任何新增的后台任务（API 触发 / 定时触发 / 内部线程）必须使用 `backend/core/task_runner.TaskRunner` 包裹。严禁新增内存状态 dict（如 `_BATCH_STATE`）。严禁不返回 `task_run_id` 的异步 API。
- **任务运行追踪统一约束**（Phase B, 2026-06-10）：
  - 所有 `*_state` / `*_status` 内存 dict 必须能通过 task_runs 表查询到等价信息
  - `services/scheduler.track_run(job_id)` 装饰器是定时任务接入 TaskRunner 的标准方式
  - 端点必须返回 `task_id`（32 hex chars），前端用 `GET /api/tasks/<task_id>` 轮询
