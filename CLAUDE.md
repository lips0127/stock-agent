# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

A 股股息监测系统 — 个人量化工具，监控股息率 > 5% 且股价低于 MA120 的股票。

## 架构（极简版）

```
浏览器 → Nginx (80) → Python Flask API (5000) → AkShare/Sina/EastMoney
                          ↓
                     SQLite DB (/data/stocks.db)
```

## 模块说明

### Python 后端 (`backend/`)
- `api/app.py` — Flask 应用入口
- `api/routes/` — API 路由（auth, market, ops）
- `services/stock_service.py` — 股票数据获取（新浪/EastMoney）
- `services/scanner_service.py` — 股息指数成分股扫描
- `services/scheduler.py` — APScheduler 定时任务（工作日 15:30）
- `tasks/market_scan.py` — 全市场扫描脚本
- `core/database.py` — SQLite 数据库操作
- `core/logging_config.py` — 日志配置
- `dashboard/app.py` — Streamlit 可视化看板（可选）

### 前端 (`frontend/`)
- 单页 HTML 应用，调用 `/api/` 获取数据
- 直接由 Nginx 提供服务

## 启动方式

```bash
# 开发模式（直接运行）
python -m backend.api.app

# Docker 部署
docker-compose up --build

# 手动全量扫描
python -m backend.tasks.market_scan
```

## 数据库

SQLite 文件：`stocks.db`（或 docker-compose 里的 `/data/stocks.db`）

表结构：
- `py_users` — 用户账户
- `stock_daily_metrics` — 每日股票指标（代码、名称、价格、股息率）
- `market_indices` — 大盘指数

## 核心 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/indices` | 大盘指数（上证/深证/创业板等） |
| GET | `/api/top_stocks?limit=N` | 高股息股票排名 |
| GET | `/api/stock/<symbol>` | 单只股票详情 |
| POST | `/api/refresh` | 触发全市场扫描 |
| GET | `/api/logs` | 任务执行日志 |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/health` | 健康检查 |

## 开发注意事项

- AkShare 调用通过 `_no_proxy()` 上下文管理器绕过代理
- `market_dividends_cache.json` 缓存高股息扫描结果
- Docker 部署时数据库文件挂载在 `app-data` volume
