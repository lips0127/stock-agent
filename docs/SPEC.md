# A 股股息监测系统 — SPEC

## 1. 项目概述

**项目名称**: A 股股息监测系统
**项目类型**: 个人量化工具
**核心功能**: 监控股息率 > 5% 且股价低于 MA120 的 A 股股票
**技术栈**: Python Flask (后端) + Vue 3 + Element Plus (前端) + SQLite

## 2. 系统架构

```
浏览器 → Nginx (80) → Python Flask API (5000) → AkShare / 新浪 / 东方财富
                            ↓
                       SQLite DB (/data/stocks.db)
```

- **开发模式**: 直接运行 `python -m backend.api.app`（不经过 Nginx）
- **生产模式**: Docker Compose 部署，Nginx 反向代理

## 3. 后端模块

### 3.1 API 层 (`backend/api/`)

| 文件 | 职责 |
|------|------|
| `app.py` | Flask 应用工厂：注册 blueprints、CORS、DB 初始化、日志、APScheduler |
| `middleware.py` | JWT token 生成/校验、`login_required` 装饰器、`rate_limit` 限流 |
| `routes/auth.py` | `POST /api/auth/login` — 用户认证 |
| `routes/market.py` | `GET /api/indices`（DB 缓存）、`GET /api/indices/live`（实时）、`GET /api/top_stocks`、`GET /api/all_stocks` |
| `routes/ops.py` | 扫描任务：`POST /api/index_scan`、`POST /api/full_refresh`、`GET /api/tasks` 系列 |
| `routes/stock.py` | `GET /api/stock/<symbol>` — 单只股票详情 |

### 3.2 核心层 (`backend/core/`)

| 文件 | 职责 |
|------|------|
| `database.py` | SQLite 连接管理、DDL 建表（含 `scan_type` 字段迁移）、`authenticate_user`、任务表 CRUD |
| `logging_config.py` | 结构化 JSON 日志（stdout + 文件双输出） |

### 3.3 服务层 (`backend/services/`)

| 文件 | 职责 |
|------|------|
| `stock_service.py` | 股票数据获取（新浪行情、EastMoney URL）、股息率计算核心算法 |
| `scanner_service.py` | 中证红利指数成分股获取、TOP N 高股息股票查询（带缓存） |
| `scheduler.py` | APScheduler 定时任务（工作日 15:30 红利指数扫描）、手动触发接口 |

### 3.4 任务层 (`backend/tasks/`)

| 文件 | 职责 |
|------|------|
| `market_scan.py` | `scan_dividend_index`（红利指数成分股约 100 只）、`scan_all_a_shares`（全市场约 5800+ 只）、`get_all_a_share_codes`（AkShare） |

### 3.5 配置层 (`backend/config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SCAN_MAX_WORKERS` | 20 | 并行扫描线程数 |
| `SCHEDULER_HOUR/MINUTE` | 15/30 | 定时扫描时间 |
| `CACHE_EXPIRE_HOURS` | 6 | AkShare 数据缓存有效期 |
| `DEFAULT_ADMIN_USER/PASSWORD` | admin/admin123 | 默认登录账户 |
| `DATABASE_PATH` | `./stocks.db` | SQLite 路径 |

## 4. 前端模块

### 4.1 路由 (`frontend/src/router/index.js`)

```
/login            → LoginView.vue (无需认证)
/                 → LayoutView.vue (认证壳)
  /dashboard      → DashboardView.vue (嵌套子路由)
  /stocks         → StocksView.vue
  /scan/:taskId   → ScanProgressView.vue
```

LayoutView 提供深色顶栏导航 + 底部持久扫描进度条。

### 4.2 Store (`frontend/src/stores/`)

| 文件 | 职责 |
|------|------|
| `auth.js` | Pinia store：JWT token 管理（localStorage）、登录状态 |
| `task.js` | Pinia store：扫描任务轮询（3s interval）、页面刷新后自动恢复 running 任务 |

### 4.3 视图 (`frontend/src/views/`)

| 文件 | 页面 |
|------|------|
| `LoginView.vue` | 登录页，深色渐变背景，居中白色卡片 |
| `LayoutView.vue` | 布局壳，深色顶栏 + 水平导航菜单 + "刷新红利指数"/"全市场扫描"按钮 + sticky 底部扫描进度条 |
| `DashboardView.vue` | 仪表盘：大盘指数卡片（实时） + TOP20 高股息表格 + 扫描任务日志 |
| `StocksView.vue` | 全量扫描结果：服务端分页表格 + 搜索/筛选 + 股票详情弹窗 |
| `ScanProgressView.vue` | 扫描进度详情：进度概览 + 已扫描股票实时列表 |

### 4.4 组件 (`frontend/src/components/`)

| 文件 | 说明 |
|------|------|
| `IndexCards.vue` | 大盘指数卡片（上涨红色/下跌绿色边框 + ▲/▼箭头，数据来自实时接口） |
| `StockTable.vue` | TOP20 高股息股票表格（含排名列、等宽代码字体） |
| `StockSearch.vue` | 股票详情弹窗（显示股息率标签、分红详情、东方财富外链） |
| `ScanProgressBar.vue` | 底部 sticky 进度条（running/success/failed 三种状态） |
| `TaskLogs.vue` | 可折叠扫描任务日志时间线 |

### 4.5 API 客户端 (`frontend/src/api/index.js`)

基于 Axios 封装，携带 JWT Bearer token，baseURL `/api`。

## 5. API 端点

| Method | Path | 说明 | 认证 |
|--------|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT | 否 |
| GET | `/api/indices` | 大盘指数（DB 缓存，可能滞后） | 是 |
| GET | `/api/indices/live` | 大盘指数（实时从新浪抓取） | 是 |
| GET | `/api/top_stocks?limit=N` | 高股息 TOP 股票排名（优先取全市场扫描结果） | 是 |
| GET | `/api/all_stocks?page=N&size=N` | 全量扫描结果（优先取全市场扫描数据，服务端分页） | 是 |
| GET | `/api/stock/<symbol>` | 单只股票详情 | 是 |
| POST | `/api/index_scan` | 触发红利指数成分股扫描 | 是 |
| POST | `/api/full_refresh` | 触发全市场扫描（异步，返回 task_id） | 是 |
| GET | `/api/tasks` | 最近任务列表 | 是 |
| GET | `/api/tasks/<task_id>` | 单个任务详情 | 是 |
| GET | `/api/tasks/<task_id>/progress` | 任务进度 + 已扫描股票列表 | 是 |
| GET | `/api/logs` | 扫描任务执行日志 | 是 |
| GET | `/api/health` | 健康检查 | 否 |

## 6. 数据库 schema

### `py_users`
```sql
CREATE TABLE py_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### `stock_daily_metrics`
```sql
CREATE TABLE stock_daily_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  code TEXT NOT NULL,         -- 股票代码
  name TEXT,                  -- 股票名称
  price REAL,                 -- 最新价
  dividend_yield REAL,        -- 股息率（%）
  dividend_per_share REAL,    -- 每股分红（元/股）
  scan_type TEXT,             -- 扫描类型：'full'（全市场）或 'index'（红利指数）
  update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(date, code)
);
```

### `market_indices`
```sql
CREATE TABLE market_indices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT,
  value REAL,
  change_amount REAL,
  change_pct REAL,
  UNIQUE(date, symbol)
);
```

### `scan_tasks`
```sql
CREATE TABLE scan_tasks (
  id TEXT PRIMARY KEY,         -- UUID task_id
  type TEXT NOT NULL,          -- 'full' 或 'index'
  status TEXT NOT NULL,        -- 'pending' / 'running' / 'success' / 'failed'
  total INTEGER DEFAULT 0,     -- 总数
  done INTEGER DEFAULT 0,      -- 已完成
  result_count INTEGER,
  error_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## 7. 股息率计算算法

**输入**: 股票代码 `symbol`
**输出**: `{名称, 最新价, 股息率, 每股分红, 分红备注}`

**算法步骤**:

1. 获取所有分红记录：`ak.stock_fhps_detail_em(symbol)` → 按 `报告期` 降序排列
2. 找到最近一个有分红的财年（annual report，分红方案进度为 `实施分配` 或 `董事会决议通过`）
3. 对该财年下的所有记录求和（包含年度分红 + 中期分红等）
4. 获取最新价：`新浪行情 API`
5. 计算 `股息率 = (每股分红 / 最新价) × 100%`
6. 财年备注格式：`FY{年份}`（如 `FY2025`），若无分红则备注为空

**关键判断**: 只取"最近一个有分红的财年"，避免将不同财年的分红数据混合计算，导致股息率虚高。

## 8. 扫描流程

### 8.1 红利指数扫描

```
定时任务（工作日 15:30）或用户点击"刷新红利指数"
  → POST /api/index_scan
  → manual_trigger() → daily_update_task() → scan_dividend_index()
  → get_dividend_index_constituents() [约 100 只]
  → ThreadPoolExecutor(max_workers=20)
  → 批量写入 stock_daily_metrics (scan_type='index')
  → 同时写入 market_indices
```

### 8.2 全市场扫描

```
用户点击"全市场扫描"
  → POST /api/full_refresh
  → 创建 scan_tasks 记录（status=pending）
  → 后台线程启动
    → get_all_a_share_codes() [约 5800+ 股票]
    → ThreadPoolExecutor(max_workers=20)
    → process_single_stock() 每只股票
    → 每 20 只写入 stock_daily_metrics (scan_type='full')
    → 每 max(10, total//20) 只更新 scan_tasks.done
    → task_id 写入响应返回
  → 前端 startPolling(task_id) 3s 轮询
  → 后端 GET /api/tasks/<task_id>/progress
    → 返回 task 状态 + 今日 stock_daily_metrics 结果
  → 扫描完成：进度条显示"查看结果 →"
```

## 9. 开发注意事项

- **代理绕过**: Windows 系统代理会影响 AkShare/requests 请求。使用 `_no_proxy()` 猴子补丁（`requests.Session.request` 方法注入 `proxies={'http': None, 'https': None}`）
- **AkShare 缓存**: `get_top_dividend_stocks()` 有 6 小时缓存
- **实时进度**: 扫描过程中每 20 只股票批量写入 DB，前端通过 `/api/tasks/<task_id>/progress` 实时读取
- **scan_type 区分**: `stock_daily_metrics` 表通过 `scan_type` 字段区分全市场扫描（`full`）和红利指数扫描（`index`）数据，`/api/top_stocks` 和 `/api/all_stocks` 优先取 `full` 数据
- **大盘指数实时性**: `/api/indices` 返回 DB 缓存数据（可能滞后），`/api/indices/live` 实时从新浪抓取
- **Docker 部署**: 数据库文件挂载在 `app-data` volume，避免容器重启丢失数据
- **登录**: 开发环境默认账户 `admin` / `admin123`
