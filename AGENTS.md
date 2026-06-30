# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

量化交易系统 — 个人量化工具，集股息率监控、策略回测、事件驱动交易框架于一体。

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
- `api/routes/` — API 路由（auth, market, ops, sentiment, strategies, backtest, quant）
- `core/database.py` — SQLite 数据库操作（15 张表）
- `core/logging_config.py` — 日志配置

**数据 & 服务**
- `services/stock_service.py` — 股票数据获取（新浪/EastMoney）
- `services/scanner_service.py` — 股息指数成分股扫描
- `services/scheduler.py` — APScheduler 定时任务（工作日 15:30）
- `services/forum_service.py` — 东财股吧爬虫
- `services/sentiment_service.py` — LLM 情绪分析（LangChain）
- `tasks/market_scan.py` — 扫描脚本

**量化交易骨架（Phase 1 完成）**
- `engine/event_bus.py` — 事件总线（内存 pub/sub）
- `engine/events.py` — 10 种事件类型
- `engine/clock.py` — 3 种时钟（Real/Replay/Simulation）
- `strategy/base.py` — 策略基类（on_bar/on_tick/buy/sell）
- `strategy/context.py` — 策略上下文（下单/查持仓/查历史）
- `strategy/registry.py` — 策略注册表（@register 装饰器）
- `strategy/examples/ma_cross.py` — 均线交叉示例策略
- `data/` — Bar 结构 + DataProvider 抽象 + 历史数据(akshare+DB)
- `execution/` — Order 状态机 + AbstractBroker 接口 + PaperBroker
- `portfolio/` — Position 模型 + PortfolioManager
- `risk/` — RiskManager + 风控规则
- `backtest/engine.py` — 回测引擎（事件驱动重放）
- `backtest/metrics.py` — 绩效指标（夏普/回撤/胜率）

### 前端 (`frontend/`)
- Vue 3 + Element Plus + Pinia + Vue Router 单页应用
- 页面：仪表盘、全量扫描、舆情监控、策略管理、回测、组合管理
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

表结构（15 张表）：
- `py_users` — 用户账户
- `stock_daily_metrics` — 每日股票指标
- `market_indices` — 大盘指数
- `scan_tasks` — 扫描任务跟踪
- `sentiment_config` — 舆情监控配置
- `forum_posts` — 股吧帖子缓存
- `sentiment_scores` — LLM 情绪评分
- `strategies` — 量化策略定义
- `historical_bars` — 历史K线缓存
- `signals` — 交易信号记录
- `orders` — 订单记录
- `positions` — 持仓记录
- `portfolio_snapshots` — 组合快照
- `backtest_runs` — 回测运行记录
- `backtest_trades` — 回测交易明细

## 核心 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/indices` | 大盘指数（DB 缓存） |
| GET | `/api/indices/live` | 大盘指数（实时） |
| GET | `/api/top_stocks?limit=N` | 高股息股票排名（优先取全市场扫描数据） |
| GET | `/api/stock/<symbol>` | 单只股票详情 |
| POST | `/api/index_scan` | 触发红利指数成分股扫描 |
| POST | `/api/full_refresh` | 触发全市场扫描（异步） |
| GET | `/api/logs` | 任务执行日志 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/strategies` | 列出已注册策略类型 |
| POST | `/api/backtest/run` | 运行回测（异步） |
| GET | `/api/backtest/runs` | 历史回测记录 |
| GET | `/api/backtest/runs/<id>` | 回测详情 + 交易明细 |
| GET | `/api/quant/portfolio` | 组合快照 |
| GET | `/api/quant/positions` | 持仓列表 |
| GET | `/api/quant/risk/rules` | 风控规则参考 |

## 开发注意事项

- AkShare 调用通过 `_no_proxy()` 上下文管理器绕过代理
- `market_dividends_cache.json` 缓存高股息扫描结果
- Docker 部署时数据库文件挂载在 `app-data` volume

# 核心工作协议 (CRITICAL)
- **设计优先**：在接受任何 Feature 开发或大规模重构任务前，必须先阅读并更新 `docs/SPEC.md`。
- **闭环审计**：在任务结束（准备输出代码或提示完成）前，必须检查代码实现与 `docs/SPEC.md` 是否一致。
- **自动同步**：如果开发过程中逻辑发生了偏离，必须在任务结束前自动发起对 `docs/SPEC.md` 的更新，严禁出现“代码已改、文档未动”的情况。
