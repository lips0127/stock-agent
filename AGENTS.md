# AGENTS.md

本文件提供本仓库的协作、开发与验收约束。当前产品事实源是 `docs/SPEC.md`；本文件不复制完整产品规格。

## 项目概述

本项目是一个 **个人 A 股研究与风险辅助看板**，用于集中查看数据证据、风险状态、候选池与异步任务运维。

它不是券商、下单系统、自动交易器或投资建议工具。任何未经过严格样本外验证的指标和实验模型都不能被描述为买卖信号。

当前能力按 `docs/SPEC.md` 分为 Core、Beta、Experimental 和 Removed；代码存在不等于已发布。

## 架构

```text
开发：浏览器 → Vite :5173 → Flask API :5000 → SQLite + 外部数据源
                         ↑
                  Flask 可自动启动并 302 到 Vite

生产：浏览器 → 单容器 Docker（Flask / Gunicorn :5000 同时服务 API 与容器内构建的前端产物）→ SQLite + 外部数据源
                  └──────→ frontend/dist
```

- 后端：Python Flask、SQLite、TaskRunner、进程内 APScheduler。

- 前端：Vue 3、Vue Router、Pinia、Element Plus、ECharts。

- 外部源：AkShare、Sina、Tencent、EastMoney、东方财富股吧及可选 LLM 服务。

- 外部源可延迟、限流或失败；页面与接口不得把缓存、部分覆盖或失败伪装成实时正常数据。

## 模块说明

### Python 后端（`backend/`）

**应用与边界**

- `api/app.py` — Flask 工厂、蓝图注册、开发期 Vite 代理和静态回退。

- `api/routes/` — HTTP 路由与 JWT 边界：auth、market、stock、watchlist、ops、sentiment、intraday、vix、vix2、scheduler、tasks、financial、stock_dashboard、tenbag。

- `api/middleware.py` — JWT、CORS、限流与安全响应头（CSP/HSTS）中间件。
- `security_check.py` — 生产就绪安全审计 CLI（`python -m backend.security_check`），entrypoint 启动前强制执行。

- `core/database.py` — SQLite 初始化、兼容和数据访问。

- `core/task_runner.py` — 异步任务的持久化进度、日志、失败与协作式取消。

- `core/logging_config.py` — 日志配置。

**服务与任务**

- `services/stock_service.py`、`scanner_service.py` — 市场、个股与股息扫描数据。

- `services/sentiment_service.py`、`forum_service.py`、`sentiment_indicators_service.py` — 股吧舆情、审计和指标。

- `services/vix_service.py`、`services/fear_greed_tracks.py` — 恐慌贪婪指数（v7 构造分口径，0=极度恐慌 100=极度贪婪）与大小盘拆分轨道（上证50/沪深300/中证500/创业板/科创50，IV 锚与价格一一对应）；`vix2_*` 为未发布实验。

- `services/scheduler.py`、`scheduler_config_service.py` — 当前进程内 APScheduler 与配置。

- `services/financial_service.py`、`report_parser.py` — 财务资料和报告解析。

- `services/watchlist_service.py` — 自选股观察池（Core）：关注列表持久化与带可信元数据的报价聚合。
- `services/tenbag_*` — 后端实验性观察池/财报异动扫描，尚无已发布 UI。

- `tasks/market_scan.py` — 全市场扫描脚本。

### 前端（`frontend/`）

真实路由以 `frontend/src/router/index.js` 为准：

- Core：登录、仪表盘、股票、红利指数、扫描进度、任务运维。

- Beta：舆情、VIX、调度配置、财报解析。

- Experimental：VIX2/v8.1 与 `Vix2TrendChart` 为 2026-07-01 起未提交在研实验；十倍股后端已注册但没有发布页面。

已删除且不得作为现状恢复描述：策略、回测、组合、执行与风控框架（commit `17de516`）；知乎监控与时间线（2026-08-30 移除，原因与边界见 `docs/SPEC.md` 第 5 节）。

## 启动方式

```bash
# 开发模式：Flask 初始化后自动尝试拉起 Vite；访问 5000 会跳转到 5173。
python -m backend.api.app

# 仅后端。
FRONTEND_DEV_PROXY=false python -m backend.api.app

# 手工前端开发服务器。
cd frontend
npm ci
npm run dev

# 当前 Docker 生产链路：前后端一体单容器，干净环境直接构建（前端在镜像内编译）。
docker compose up -d --build

# 部署与安全细节见 docs/DEPLOY.md；部署前可审计生产就绪度。
python -m backend.security_check

# 手动全市场扫描。
python -m backend.tasks.market_scan
```

端口分工：Flask `5000` 提供 API 与开发回退，Vite `5173` 提供源码/HMR 并代理 `/api/*`，Nginx 生产暴露 `80`。

Docker fresh build 已收敛为单容器三阶段构建（`backend/Dockerfile`），`docker compose up --build` 即完整部署；部署手册见 `docs/DEPLOY.md`。

## 数据库

SQLite 文件为 `stocks.db`；容器中通过 `CACHE_DIR` 使用 `/data` 卷。当前约 25 张表，按域组织：

- 身份：`py_users`。

- 市场与扫描：`stock_daily_metrics`、`market_indices`、`scan_tasks`。

- 舆情及全市场观察：`sentiment_*`、`forum_posts`。

- 风险观察：`vix_history`、`vix_track_history`、`vix2_history`。

- 任务与调度：`task_runs`、`task_run_logs`、`scheduler_task_*`。

- 财报：`financial_reports_cache`、`report_parse_history`。

- 十倍股实验：`tenbag_*`。

表结构以 `backend/core/database.py` 为准。新增或修改数据路径必须保留 source、as-of、freshness、coverage、degraded/error 语义，并遵守 point-in-time 原则。

## 核心 API

无 JWT 的公共 API 仅有：

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/api/login` | canonical 登录接口，成功后签发 JWT。 |
| GET | `/health` | 存活检查。 |

其余业务 API 全部要求 `Authorization: Bearer <JWT>`。代表性分组：

| 域 | 代表路径 |
| --- | --- |
| 市场/股票 | `/api/indices`、`/api/indices/live`、`/api/top_stocks`、`/api/all_stocks`、`/api/stock/<symbol>`、`/api/stock/<symbol>/dashboard`、`/api/market/intraday` |
| 扫描/任务 | `/api/index_scan`、`/api/full_refresh`、`/api/tasks/*` |
| 调度 | `/api/scheduler/configs/*` |
| 舆情 | `/api/sentiment/*` |
| 风险与财报 | `/api/vix/*`、`/api/vix2/*`、`/api/financial/*` |
| 自选股 | `/api/watchlist`（GET/POST）、`/api/watchlist/<code>`（PATCH/DELETE） |
| 实验扫描 | `/api/tenbag/*`（backend-only experimental） |

异步端点必须返回 `task_id`，统一通过 `/api/tasks/<task_id>` 和 `/api/tasks/<task_id>/logs` 查询；不得新增私有轮询协议。

## 开发注意事项

- AkShare 调用通过 `_no_proxy()` / 代理绕过机制处理网络环境；不要绕过既有源失败与降级记录。

- `market_dividends_cache.json` 是缓存，不是实时真值；渲染时应明确时点。

- `TaskRunner` 记录任务状态、进度和日志，但工作线程仍在 Web 进程内；重启不会续跑。

- APScheduler 当前在每个 Flask 进程内启动。Gunicorn 多 worker 会造成重复调度，是 P0 风险；修复前必须确保只有一个调度实例。

- VIX2 进入发布范围前必须完成严格 walk-forward OOS、训练 cutoff 审计、无未来数据和简单基线比较；结论不足时标为“无稳健预测力”。

- 禁止在日志、异常回显、响应或 Git 中出现密码、JWT、Cookie、SMTP secret 或第三方密钥。

- 生产必须使用固定强 JWT 密钥、非默认管理员凭证和受限 CORS；当前 Docker 默认配置尚未达到此要求。

# 核心工作协议 (CRITICAL)

- **设计优先**：在接受任何 Feature 开发或大规模重构任务前，必须先阅读并更新 `docs/SPEC.md`。

- **闭环审计**：在任务结束（准备输出代码或提示完成）前，必须检查代码实现与 `docs/SPEC.md` 是否一致。

- **自动同步**：如果开发过程中逻辑发生了偏离，必须在任务结束前自动发起对 `docs/SPEC.md` 的更新，严禁出现“代码已改、文档未动”的情况。
