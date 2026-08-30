# 量化交易系统 — SPEC

## 1. 项目概述

**项目名称**: 量化交易系统
**项目类型**: 个人量化工具
**核心功能**: 
  - 股息率监控：监控股息率 > 5% 且股价低于 MA120 的 A 股股票
  - 量化交易：事件驱动策略框架 + 回测引擎 + 策略管理
**技术栈**: Python Flask (后端) + Vue 3 + Element Plus (前端) + SQLite

## 2. 系统架构

```
浏览器 → Nginx (80) → Python Flask API (5000) → AkShare / 腾讯 / 新浪 / 东方财富
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
| `routes/stock_dashboard.py` | `GET /api/stock/<symbol>/dashboard` — 公司增强看板：聚合 stock_metrics + 财务数据 + 情绪历史（v6 2026-06-15） |
| `routes/sentiment.py` | 舆情监控 CRUD + LLM 情绪分析 + 标题真实性审计 |
| `routes/zhihu.py` | 知乎大V监控：用户/动态/分析/邮件订阅/SMTP 配置、大V时间线聚合 |
| `routes/intraday.py` | 市场分时K线：A股30分钟K线（新浪API）、港股/美股（yfinance兜底） |

### 3.2 核心层 (`backend/core/`)

| 文件 | 职责 |
|------|------|
| `database.py` | SQLite 连接管理、DDL 建表（含 `scan_type` 字段迁移）、`authenticate_user`、任务表 CRUD |
| `logging_config.py` | 结构化 JSON 日志（stdout + 文件双输出） |

### 3.3 服务层 (`backend/services/`)

| 文件 | 职责 |
|------|------|
| `stock_service.py` | 股票数据获取（行情源级联：腾讯 → 新浪 → 东方财富）、EastMoney URL 生成、股息率计算核心算法 |
| `scanner_service.py` | 中证红利指数成分股获取、TOP N 高股息股票查询（带缓存） |
| `forum_service.py` | 东财股吧爬虫 + 标题真实性审计（fetch_post_full / audit_post_title / audit_posts）+ 网络韧性（`GubaCircuitBreaker` / `_http_get_with_retry` / 并发审计，2026-06-04） |
| `scheduler.py` | APScheduler 定时任务（工作日 15:30 红利指数扫描、16:00 舆情、16:30 VIX、每 2h 知乎、每 2h 论坛预拉）、手动触发接口 |
| `zhihu_service.py` | 知乎大V抓取（用户资料、文章/回答列表、单帖正文 + 缓存到 DB） |
| `zhihu_analyzer.py` | LLM 分析知乎动态，提取看多/看空标的、关键观点、行动建议 |
| `email_service.py` | SMTP 邮件发送（订阅通知 / 摘要 / 测试），记录发送日志 |

### 3.4 数据层 (`backend/data/`)

| 文件 | 职责 |
|------|------|
| `bar.py` | Bar 数据结构（OHLCV） |
| `provider.py` | DataProvider 抽象接口 |
| `intraday.py` | 30分钟K线数据：A股指数（新浪API）、港股/美股（yfinance兜底），支持 symbol/interval/days 参数 |

### 3.5 任务层 (`backend/tasks/`)

| 文件 | 职责 |
|------|------|
| `market_scan.py` | `scan_dividend_index`（红利指数成分股约 100 只）、`scan_all_a_shares`（全市场约 5800+ 只）、`get_all_a_share_codes`（AkShare） |

### 3.12 配置层 (`backend/config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SCAN_MAX_WORKERS` | 20 | 并行扫描线程数 |
| `SCHEDULER_HOUR/MINUTE` | 15/30 | 定时扫描时间 |
| `CACHE_EXPIRE_HOURS` | 6 | AkShare 数据缓存有效期 |
| `DEFAULT_ADMIN_USER/PASSWORD` | admin/admin123 | 默认登录账户 |
| `DATABASE_PATH` | `./stocks.db` | SQLite 路径 |
| `FRONTEND_DEV_PROXY` | `true` | dev 模式自动拉 Vite 子进程 + HTML 路由 302 到 5173 |
| `VITE_PORT` | `5173` | Vite 监听端口 |

### 3.12.1 知乎监控配置 (`backend/config.py` 扩展)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SMTP_HOST` | `smtp.example.com` | SMTP 服务器 |
| `SMTP_PORT` | `465` | SMTP 端口（SSL） |
| `SMTP_USER` | `` | SMTP 登录用户 |
| `SMTP_PASSWORD` | `` | SMTP 密码/授权码 |
| `SMTP_FROM` | `` | 发件人邮箱（默认同 USER） |
| `SMTP_USE_SSL` | `true` | 是否使用 SSL |
| `ZHIHU_CHECK_INTERVAL_HOURS` | `2` | 自动检查知乎更新的间隔（小时） |
| `ZHIHU_NOTIFY_MIN_INTERVAL_HOURS` | `6` | 同一用户两次邮件通知最小间隔，避免打扰 |

## 4. 前端模块

### 4.1 路由 (`frontend/src/router/index.js`)

```
/login            → LoginView.vue (无需认证)
/                 → LayoutView.vue (认证壳)
  /dashboard      → DashboardView.vue (嵌套子路由)
  /stocks         → StocksView.vue
  /dividend-index → DividendIndexView.vue
  /scan/:taskId   → ScanProgressView.vue
  /sentiment      → SentimentView.vue
  /vix            → VixView.vue
  /zhihu          → ZhihuMonitorView.vue
  /zhihu/timeline → ZhihuTimelineView.vue
  /tasks          → TaskSchedulerView.vue
  /financial-report → FinancialReportView.vue
```

LayoutView 提供左侧边栏导航（分组：辅助交易/辅助功能/系统）+ 底部持久扫描进度条。**视觉规范（v2，2026-06-04）**：
- 侧边栏：`--color-bg-glass` 半透明白底 + `backdrop-filter: blur(16px) saturate(180%)` 毛玻璃 + `--shadow-sidebar` 极淡分层阴影
- 激活态：Vercel 风格 — 左侧 2px indigo 条 + `--color-accent-soft` 浅底 + `--color-accent-deep` 深文字
- Logo：克制 indigo 单色渐变（#4f46e5 → #6366f1）+ 0 2px 8px rgba(79,70,229,0.32) 微光晕
- 用户头像：zinc-900 底 + 白首字母 + 微弱 indigo 光晕
- 设计系统主色：indigo-600（#4f46e5），中性色用 zinc 阶（zinc-50/100/200/600/900）
- 涨跌色柔和化：红涨 #e11d48（rose-600），绿跌 #059669（emerald-600）

### 4.1.1 Dev 端口与 HMR（2026-06-04）

dev 模式**单命令启动 + 热更新**：

| 端口 | 服务 | 角色 |
|------|------|------|
| 5000 | Flask | API + 鉴权；HTML 路由 302 → 5173；dist/ 静态兜底 |
| 5173 | Vite | 源码 + HMR；`/api/*` 反代回 5000 |

启动流程（`backend/api/app.py` `create_app`）：
1. 读 `FRONTEND_DEV_PROXY`（默认 `true`）
2. 若启用且 Vite 不在跑且 `node_modules` 已装 → `subprocess.Popen(['npm','run','dev'])` 拉起 Vite 子进程（Windows 用 `CREATE_NO_WINDOW` 避免弹 console）
3. 轮询 `http://localhost:5173` 等待就绪（≤10s）
4. `index` 和 `serve_frontend` 路由对 HTML 请求 302 到 Vite，API 路由不变

环境变量：
- `FRONTEND_DEV_PROXY=true/false`（默认 true）— 关掉则 Vite 不可达时回退 dist/
- `VITE_PORT=5173` — Vite 监听端口
- 关闭 Vite 自动启动但仍想代理：`FRONTEND_DEV_PROXY=true` + 自己 `cd frontend && npm run dev`

**生产部署**：Docker compose 由 Nginx 直接托管 `frontend/dist/`，Flask 只跑 API；与 dev 模式完全解耦。

### 4.2 Store (`frontend/src/stores/`)

| 文件 | 职责 |
|------|------|
| `auth.js` | Pinia store：JWT token 管理（localStorage）、登录状态 |
| `task.js` | Pinia store：扫描任务轮询（3s interval）、页面刷新后自动恢复 running 任务 |

### 4.3 视图 (`frontend/src/views/`)

| 文件 | 页面 |
|------|------|
| `LoginView.vue` | 登录页，深色渐变背景，居中白色卡片 |
| `LayoutView.vue` | 布局壳，左侧毛玻璃侧边栏（Vercel 风格激活条）+ 装饰渐变光晕背景 + sticky 底部扫描进度条；导航分组：辅助交易→仪表盘/全量扫描/红利指数、辅助功能→舆情监控/VIX/知乎大V/财报解析、系统→任务调度 |
| `DashboardView.vue` | 仪表盘（**v2 视觉标杆页**）：渐变光晕背景 + 欢迎头部（icon/meta/管理员 chip + 实时时钟 + 脉冲状态点）+ 4 个 StatCard 横排（默认/强调/默认/动态盈亏色）+ ModernCard glass 装大盘指数 + ModernCard bordered 装高股息股票 + ModernCard 装任务日志 |
| `DashboardView.vue` | 仪表盘：大盘指数卡片（实时） + TOP20 高股息表格 + 扫描任务日志 |
| `StocksView.vue` | 全量扫描结果：服务端分页表格 + 搜索/筛选 + 股票详情弹窗 |
| `ScanProgressView.vue` | 扫描进度详情：进度概览 + 已扫描股票实时列表 |
| `SentimentView.vue` | 舆情监控仪表盘：左栏监控配置（搜索/添加/删除）+ 右栏「最新情绪」手风琴列表（单展开：点行下拉显示**情绪趋势**最近 N 天历史 + **相关帖子**股吧标题列表 + 趋势小标签 ▲▼— + 「立即分析」/「打开股吧」操作；历史按 code 缓存避免重复拉取） |
| `StrategiesView.vue` | 策略管理：展示已注册策略的参数/标的，一键跳转回测 |
| `BacktestView.vue` | 策略回测：配置参数 → 异步运行 → 展示绩效指标 + 交易明细 |
| `PortfolioView.vue` | 组合管理：组合快照 + 持仓列表 + 风控规则参考 |
| `ZhihuMonitorView.vue` | 知乎大V监控：左侧大V列表 + 右侧动态时间线（含 LLM 分析）+ "AI 分析最近10条"按钮 + "大V时间线"跳转 + 邮件订阅 + SMTP 设置 |
| `ZhihuTimelineView.vue` | 大V时间线报表：K线图叠加发言标记 + 统计卡片 + 按日期分组的动态列表 + 立场/用户筛选 |

### 4.4 组件 (`frontend/src/components/`)

| 文件 | 说明 |
|------|------|
| `IndexCards.vue` | 大盘指数卡片（上涨红色/下跌绿色边框 + ▲/▼箭头，数据来自实时接口） |
| `StockTable.vue` | TOP20 高股息股票表格（含排名列、等宽代码字体） |
| `StockSearch.vue` | 股票详情弹窗（显示股息率标签、分红详情、东方财富外链） |
| `ScanProgressBar.vue` | 底部 sticky 进度条（running/success/failed 三种状态） |
| `TaskLogs.vue` | 可折叠扫描任务日志时间线 |
| `KLineChart.vue` | ECharts 蜡烛图 + 散点标记叠加（看多绿三角/看空红三角/中性灰圆/混合橙菱形），支持 dataZoom、tooltip、点击事件 |
| `ui/ModernCard.vue` | 统一卡片组件：header/title/description/extra 插槽 + body 默认插槽，**3 个 variant**（default / glass 毛玻璃 / bordered 加粗边框）+ `hoverable` 抬升变体；过渡 300ms ease-out |
| `ui/PageHeader.vue` | 页面标题栏：title + subtitle + actions 插槽 + **`#icon` 头图插槽**（48×48 indigo-soft 底）+ **`#meta` 内联指标插槽**（带分隔线的小指标 chip），支持 `size="sm|md|lg"` |
| `ui/StatCard.vue` | 统计数字卡片：label + value + 顶部色线 + 5 个 tone（default / up / down / accent / warning / **glass 毛玻璃**）；accent tone 使用 indigo 渐变背景 + hover glow |
| `ui/EmptyHint.vue` | 空状态提示：图标 + 标题 + 描述 + **`#illustration` SVG 插槽** + `carded` 虚线边框变体 |
| `ui/GradientBlob.vue` | 装饰性径向渐变光晕，filter blur，4 个位置（tr/tl/br/bl）+ 3 个尺寸，Dashboard 欢迎区背景用 |

### 4.5 API 客户端 (`frontend/src/api/index.js`)

基于 Axios 封装，携带 JWT Bearer token，baseURL `/api`。

### 4.6 舆情监控因子化闭环（2026-06-29）

舆情监控页不再只是手动列表页，而是“可观测的数据生产线”：目标是每天盘后稳定产出可被前端极端情绪看板消费的 `sentiment_scores` + `sentiment_indicators`，并把数据鲜度、调度健康、热点股票覆盖率直接暴露在页面顶部。

**生产链路**：

```
工作日 16:00 daily_sentiment
  → batch_analyze(enabled sentiment_config)
  → 写 sentiment_scores / sentiment_post_labels / sentiment_indicators

工作日 16:05 daily_top_picks
  → refresh_top_picks(top 100)
  → analyze_top_picks(top N，默认 20，受 SENTIMENT_TOP_PICKS_ANALYZE_LIMIT 控制)
  → 热点股票即使未加入关注列表，也能形成当日情绪样本

工作日 16:35 daily_indicators_recompute
  → recompute_all_for_today()
  → 补齐 EMA3/EMA5、panic/euphoria、momentum_cross
```

**可观测性要求**：

- 页面顶部必须展示「舆情状态总览」：一行研判结论（偏多/偏空/中性，由监控股均分 + 极端信号计数综合判定）、4 个核心指标（监控股今日产出、热门股池覆盖、因子覆盖、极端信号）、关键调度最近状态、guba 熔断/cookie 告警条。
- 页面主体按 tab 分区：我的监控 / 热门股池 / 全市场观测（含指数聚合 + 成分股），首屏只渲染当前 tab。
- `daily_sentiment` / `daily_top_picks` / `daily_indicators_recompute` 的异常必须让 `TaskRunner` 和 `scheduler_task_run` 记录为 `failed`，不能只写日志后返回成功。
- 热门股池列表必须显示最新情绪分、立场、分析日期；没有分析结果时显示“待分析”，避免用户误以为已经纳入因子。卡片描述须显示 daily_top_picks 最近刷新时间与下次定时时间，让「每天定时刷新」可见可验证。
- 手动刷新热门股池可选择同步分析 top N，并通过 `task_id` 进入统一任务台轮询。

**生产可靠性约束（v7, 2026-06-29）**：

- 批量分析进度必须落 `task_runs` 表（`result_json` 存运行中快照 `{done, failed, current, current_name}`），`GET /api/sentiment/batch_analyze_status` 从 DB 读，跨进程可用。严禁新增 `_BATCH_STATE` 类模块级内存 dict（Phase B 约束）。
- `/api/sentiment/universe/progress` 全走 DB 聚合，不依赖进程内内存态。
- `/api/sentiment/latest` 必须用批量查询（`get_sentiment_latest_overview`，3 条 SQL），不得 per-config 循环查（N+1）。
- universe 写 `sentiment_universe_scores` 时，panic/euphoria 信号键名必须与 `sentiment_service` 写入的 `signals_json` 一致（`panic`/`euphoria`/`momentum_cross`），不得用 `panic_2sigma`/`euphoria_2sigma`。
- `analyze_sentiment` 对 LLM 空响应/解析失败必须返回 `_err("parse_error", ...)` 契约错误，不得返回 `None`。
- guba cookie 失效（warmup 后详情页仍返回引导壳）时，`/api/sentiment/circuit_status` 返回 `cookie_stale: true`，前端顶部告警；需人工更新 `_GUBA_BOOTSTRAP_COOKIES` 后重启并 `POST /api/sentiment/circuit_reset` 清除告警。
- `top_picks` 数据源（`ak.stock_zh_a_spot` 新浪源）必须有 3 次指数退避重试；`analyze_top_picks` 必须并发（ThreadPoolExecutor）且支持 `task_runner.check_cancelled()`。

**量化因子口径**：

- `sentiment_scores.score`：0-100，多空有效样本中的看多比例；低分=悲观/恐慌，高分=乐观/狂热。
- `sentiment_indicators`：策略优先消费 `ema3`、`ema5`、`panic_signal`、`euphoria_signal`、`momentum_cross`，而不是直接消费单日 LLM 文本。
- `sentiment_top_picks`：用于发现市场当日交易热度最高的候选股票，默认只分析 top 20 控制 LLM 成本；top 100 仍保留为观察池。

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
| GET | `/api/sentiment/filters` | 获取舆情帖子过滤规则白名单 | 是 |
| POST | `/api/sentiment/filters` | 新增过滤规则 | 是 |
| DELETE | `/api/sentiment/filters/<id>` | 删除过滤规则 | 是 |
| GET | `/api/sentiment/audit?code=xxx&only_mismatch=0` | 获取某股票帖子的审计状态列表 | 是 |
| POST | `/api/sentiment/audit/rerun` | 重跑审计：`{code, reset}`，不传 code 遍历所有监控股 | 是 |
| GET | `/api/sentiment/audit/summary?code=xxx` | 全局 / 单股审计摘要 | 是 |
| POST | `/api/sentiment/posts/<id>/accept_actual` | 接受 actual_title 覆盖 title | 是 |
| POST | `/api/sentiment/posts/<id>/mark_broken` | 标记为垃圾（前端展示时过滤） | 是 |
| POST | `/api/sentiment/posts/<id>/reset` | 重置审计状态为 pending | 是 |
| POST | `/api/sentiment/fetch` | 仅拉取帖子缓存（不调 LLM）：`{stock_code, days, fetch_content, audit}` | 是 |
| GET | `/api/sentiment/top_picks` | 获取最新热门股池；返回 rank/成交额/是否监控/最新情绪分与分析日期 | 是 |
| POST | `/api/sentiment/top_picks/refresh` | 异步刷新热门股池；body: `{top_n, auto_add, analyze_limit}`，返回 `task_id` | 是 |
| POST | `/api/sentiment/top_picks/analyze` | 异步分析当前热门股 top N；body: `{limit}`，返回 `task_id` | 是 |
| GET | `/api/sentiment/health` | 舆情因子生产线健康：覆盖率、数据鲜度、热门股今日分析覆盖、关键调度最近运行与下一次运行 | 是 |
| GET | `/api/zhihu/users` | 监控的知乎用户列表 | 是 |
| POST | `/api/zhihu/users` | 新增知乎用户监控 | 是 |
| DELETE | `/api/zhihu/users/<id>` | 移除监控 | 是 |
| PATCH | `/api/zhihu/users/<id>` | 启用/禁用 / 邮件订阅开关 | 是 |
| POST | `/api/zhihu/users/<id>/refresh` | 立即抓取最新动态 | 是 |
| GET | `/api/zhihu/users/<id>/posts?limit=20` | 该用户最新动态（含 LLM 分析） | 是 |
| GET | `/api/zhihu/posts/<post_id>/analysis` | 单篇 LLM 分析详情 | 是 |
| POST | `/api/zhihu/posts/<post_id>/reanalyze` | 重新跑 LLM 分析 | 是 |
| GET | `/api/zhihu/subscriptions` | 邮件订阅列表 | 是 |
| POST | `/api/zhihu/subscriptions` | 新增订阅 | 是 |
| DELETE | `/api/zhihu/subscriptions/<id>` | 删除订阅 | 是 |
| GET | `/api/zhihu/email_settings` | SMTP 配置（密码脱敏） | 是 |
| POST | `/api/zhihu/email_settings` | 保存 SMTP 配置 | 是 |
| POST | `/api/zhihu/email_test` | 发送测试邮件 | 是 |
| GET | `/api/zhihu/logs?limit=50` | 邮件发送日志 | 是 |
| GET | `/api/zhihu/timeline?days=7` | 近N天所有已分析大V动态（聚合时间线） | 是 |
| GET | `/api/market/intraday?symbol=&interval=30min&days=7` | 市场30分钟K线（上证/深证/创业板/科创50/沪深300/恒生/标普） | 是 |

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

### `forum_posts`
```sql
CREATE TABLE forum_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  forum_type TEXT NOT NULL,
  title TEXT,
  content TEXT,
  author TEXT,
  post_time TEXT,
  url TEXT UNIQUE,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  -- 标题真实性审计字段（v1, 2026-06-04）
  actual_title TEXT,              -- 从 URL 重抓的真实标题
  title_match INTEGER,            -- 1=一致 0=不一致 NULL=未审计
  title_verified_at TIMESTAMP,    -- 审计时间
  audit_status TEXT,              -- 'pending'|'verified'|'mismatch'|'broken'|'manual_accepted'|'manual_rejected'
  audit_note TEXT                 -- 抓取错误信息 / 用户备注
);
CREATE INDEX idx_forum_posts_audit ON forum_posts(stock_code, audit_status);
```

### `sentiment_scores`
```sql
CREATE TABLE sentiment_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  forum_type TEXT NOT NULL,
  date TEXT NOT NULL,
  sentiment TEXT NOT NULL,
  score REAL NOT NULL,
  post_count INTEGER DEFAULT 0,
  summary TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, forum_type, date)
);
```

### `sentiment_filters`
```sql
CREATE TABLE sentiment_filters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filter_key TEXT NOT NULL UNIQUE,
  filter_type TEXT NOT NULL DEFAULT 'title_keyword',
  description TEXT,
  enabled INTEGER DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
预置过滤关键词：转发、阅读、股吧、收藏、发表于（入库前过滤 + LLM 层二次过滤）

### `zhihu_users` / `zhihu_posts` / `zhihu_analyses` / `zhihu_email_subscriptions` / `zhihu_email_log`
详见 §10.4。

## 7. 股息率计算算法

**输入**: 股票代码 `symbol`
**输出**: `{名称, 最新价, 股息率, 每股分红, 分红备注}`

**算法步骤**:

1. 获取所有分红记录：`ak.stock_fhps_detail_em(symbol)` → 按 `报告期` 降序排列
2. 找到最近一个有分红的财年（annual report，分红方案进度为 `实施分配` 或 `董事会决议通过`）
3. 对该财年下的所有记录求和（包含年度分红 + 中期分红等）
4. 获取最新价：行情源级联（`腾讯 qt.gtimg.cn（HTTPS，最稳定）` → `新浪 hq.sinajs.cn` → `东方财富 push2.eastmoney.com`），每个源带浏览器 UA 和指数退避重试
5. 计算 `股息率 = (每股分红 / 最新价) × 100%`
6. 财年备注格式：`FY{年份}`（如 `FY2025`），若无分红则备注为空

**关键判断**: 只取"最近一个有分红的财年"，避免将不同财年的分红数据混合计算，导致股息率虚高。

## 8. 扫描流程

### 8.1 红利指数扫描

```
定时任务（工作日 15:30）或用户点击"红利指数扫描"
  → POST /api/index_scan
  → manual_trigger() → daily_update_task() → scan_dividend_index()
  → get_dividend_index_constituents() [约 100 只]
  → ThreadPoolExecutor(max_workers=20)
  → 批量写入 stock_daily_metrics (scan_type='index')
  → 同时写入 market_indices
```

**专属页面（2026-06-28）**: 侧边栏「辅助交易 → 红利指数」(`/dividend-index`, `DividendIndexView.vue`) 提供轻量入口——不跑全量即可快速观测高股息。页面调用 `GET /api/all_stocks?scan_type=index`，按 `scan_type='index'` **自身最近一次**扫描日期取数，避免被当日全市场扫描（`full`）掩盖（旧逻辑下 `/api/all_stocks`、`/api/top_stocks` 在当日存在 `full` 数据时会优先返回 `full`，导致红利指数结果"消失"）。页面内含「运行红利指数扫描」按钮，复用 `POST /api/index_scan` + taskStore 轮询。

### 8.2 全市场扫描

```
用户点击"全市场扫描"
  → POST /api/full_refresh
  → 创建 scan_tasks 记录（status=pending）
  → 后台线程启动
    → get_all_a_share_codes() [约 5800+ 股票，已按名称剔除 ST/*ST/退市]
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

- **代理绕过**: 详见 [§ 9A](#9a-网络层代理强制直连2026-06-15)。旧版 `_no_proxy()` 猴子补丁机制已弃用，统一由 `backend/core/proxy_bypass.install_proxy_bypass()` 在启动期一次性 patch。`with _no_proxy():` 语法保留为 no-op，向后兼容 30+ 处现有调用点。
- **`_no_proxy()` 不变量（v2，2026-06-04 → 2026-06-15 弃用）**：历史实现必须满足 — (1) 模块级缓存**真正的原始** `Session.request`（避免 patch 后再读"当前"引用导致自递归）；(2) **线程局部计数**实现可重入 + 跨线程隔离（旧版在嵌套 / 多线程并发下会无限递归 `RecursionError`，2026-06-04 凌晨知乎后台任务踩坑，已修复）。2026-06-15 改为启动期全局 patch 后，这两个不变量已不再需要 — 新代码**不要**重新引入 monkey-patch `_no_proxy()` 机制。
- **AkShare 缓存**: `get_top_dividend_stocks()` 有 6 小时缓存
- **实时进度**: 扫描过程中每 20 只股票批量写入 DB，前端通过 `/api/tasks/<task_id>/progress` 实时读取
- **scan_type 区分**: `stock_daily_metrics` 表通过 `scan_type` 字段区分全市场扫描（`full`）和红利指数扫描（`index`）数据，`/api/top_stocks` 和 `/api/all_stocks` 默认优先取 `full` 数据；`/api/all_stocks?scan_type=index|full` 可强制按指定类型取其自身最近一次扫描日期的数据（红利指数页用之）
- **ST/退市股排除（2026-06-28）**: ST/*ST/退市股价格已崩塌（退市整理期常 <1 元），但历史分红仍按往年正常水平计算，会得到 100%+ 异常股息率污染高股息排名，且本身有退市风险。判定见 `stock_service.is_risk_stock`（名称含 `ST` 或 `退`）。两层排除：(1) 扫描层 `get_all_a_share_codes` 按名称剔除，不写入 DB；(2) 展示层 `/api/top_stocks` 与 `/api/all_stocks` 用 `name NOT LIKE '%ST%' AND name NOT LIKE '%退%'` 兜底过滤历史遗留行
- **大盘指数实时性**: `/api/indices` 返回 DB 缓存数据（可能滞后），`/api/indices/live` 实时从新浪抓取
- **Docker 部署**: 数据库文件挂载在 `app-data` volume，避免容器重启丢失数据
- **登录**: 开发环境默认账户 `admin` / `admin123`

## 9A. 网络层：代理强制直连（2026-06-15）

### 背景

用户本地（Windows 11）开 Clash 系统代理 `127.0.0.1:7890`。
`requests` / `akshare` 默认会从 Windows 注册表读系统代理，
导致 `*.eastmoney.com` / `82.push2.eastmoney.com` / `*.sina.com.cn`
等域全部经 Clash 出网。Clash 又因目标 IP 被规则判为「直连」→ 
`Remote end closed connection without response`（典型症状：盘后
`top_picks_service` 拉全市场行情失败）。

### 实现：`backend/core/proxy_bypass.py`

`install_proxy_bypass()` 在 `backend.api.app` import 阶段（`import
requests as _requests` 之后、blueprint import 链之前）执行一次，
做三件事：

1. **清空代理 env**：`HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` /
   `https_proxy` / `ALL_PROXY` / `all_proxy` 全部 `os.environ.pop`。
   `NO_PROXY` 保留。
2. **patch `requests.Session.request` / `Session.send`**：闭包捕获
   模块级原始方法，强制把 `proxies` 置为 `{http: None, https: None}`。
   `akshare` 内部也走 `requests.sessions`，这一层覆盖所有 akshare 调用。
3. **patch `urllib3.HTTPSConnectionPool.urlopen`**：防御性兜底，覆盖
   未来可能绕过 `requests` 直接 `urllib3.PoolManager` 的代码。

幂等：多次调用安全。

### 兼容性

- `backend/services/stock_service.py` 里的 `_no_proxy()` 上下文管理器
  **保留为 no-op**：`with _no_proxy():` 在 30+ 处现有调用点 0 改动
  继续工作（语义：显式标注"这里不应当走代理"；实际保护由全局 patch
  提供）。
- SMTP：`backend/services/email_service.py` 调用前显式
  `os.environ.pop('SMTP_PROXY', None)` 兜底（Win 系统代理不走 SMTP，
  但 `SMTP_PROXY` env 可能由其他工具链设置）。代理日志可能泄露邮件
  密码，故必须显式禁止。

### 移除的旧 hack

- `backend/data/historical.py` 的 `for force_direct in (False, True):`
  临时 env-var 备份/恢复机制 — **删除**，改用全局 patch。
- `backend/services/stock_service.py` 的 `_TRUE_ORIG_REQUEST` /
  `_state` / `_patched_request` 50 行实现 — **删除**，简化为 no-op
  上下文管理器。

## 9B. 数据源：弃用东财 push2 域（2026-06-16）

### 背景

修复 § 9A 之后，`82.push2.eastmoney.com` / `push2.eastmoney.com` /
`push2his.eastmoney.com` 三个域在用户本地网络下持续 RST（裸 socket /
curl 同样 `Failure when receiving data from the peer`，与代理无关）。
受影响接口：

- `ak.stock_zh_a_spot_em` → `82.push2.eastmoney.com`
- `ak.stock_zh_a_hist` → `push2his.eastmoney.com`
- `_get_eastmoney_hq` → `push2.eastmoney.com`

### 替代方案

| 原调用 | 替代 | 数据源 |
|---|---|---|
| `ak.stock_zh_a_spot_em` | `ak.stock_zh_a_spot` | 新浪（hq.sinajs.cn） |
| `ak.stock_zh_a_hist` | `ak.stock_zh_a_daily` | 新浪 |
| `_get_eastmoney_hq` | **直接删除** | 兜底链：tencent → sina |

注意：新浪源 code 列带前缀（`bj920000` / `sh600000` / `sz000001`），
需 `raw.str[2:].where(raw.str[:2].isin(['sh','sz','bj']), raw)` 剥成
纯 6 位。东财源 `stock_zh_a_spot_em` 是纯 6 位，无须剥前缀。

### 受影响文件

- `backend/services/top_picks_service.py` — 改 `ak.stock_zh_a_spot()` + 剥前缀
- `backend/services/universe_service.py` — 改 `ak.stock_zh_a_spot()` + `spot_filter` 方法 + 剥前缀；chinext 指数定义 `akshare_method` 从 `spot_em_filter` 改为 `spot_filter`
- `backend/tasks/market_scan.py` — 改 `ak.stock_zh_a_spot()` + 剥前缀
- `backend/data/historical.py` — 备选源从 `stock_zh_a_hist` 改为 `stock_zh_a_daily`（同接口不同 prefix，互为兜底）；删 `_parse_eastmoney_df` / `pd_timestamp_to_datetime`（dead code）
- `backend/services/stock_service.py` — `_get_eastmoney_hq` 改为永远抛 `ConnectionError`（占位）；`get_stock_metrics` 兜底链移除 eastmoney；`latest_price <= 0` 兜底改用 `ak.stock_zh_a_daily` + `iloc[-1]["close"]`
- `backend/api/routes/sentiment.py` — 自动取名 fallback 改用 `_get_tencent_hq` 替换 `_get_eastmoney_hq`

## 10. 知乎大V监控

### 10.1 目标

监控用户关注的若干知乎大V（如 `hongliqi` 洪灏），抓取他们最近发布的文章/回答，调用 LLM 提取**看多/看空标的、关键观点、行动建议**及**原链接**，在前端时间线展示；当有更新且用户配置了邮件订阅时，通过 SMTP 发送通知。

### 10.2 抓取策略

**入口 URL**：`https://www.zhihu.com/people/{url_token}`，从 URL 末段提取 `url_token`（如 `hongliqi`）。

**抓取端点**（知乎官方 API，公开匿名可读）：

| 用途 | URL | 备注 |
|------|-----|------|
| 用户资料 | `https://www.zhihu.com/api/v4/members/{url_token}` | 头像、签名、粉丝数 |
| 文章列表 | `https://www.zhihu.com/api/v4/members/{url_token}/articles?limit=20&offset=0` | 已发布文章 |
| 回答列表 | `https://www.zhihu.com/api/v4/members/{url_token}/answers?limit=20&offset=0` | 回答过的问题 |
| 单篇内容 | `https://www.zhihu.com/api/v4/articles/{id}` | 文章完整 HTML |

**反爬措施**：

- 必须设置真实 `User-Agent`（Chrome 120+）
- 携带 `Referer: https://www.zhihu.com/people/{url_token}` 防 referer 校验
- 单用户 2 秒以上间隔；批量用户 1.5 秒
- 单次抓取失败 3 次重试后退避
- 抓取后立即写入 DB（`INSERT OR IGNORE ON CONFLICT url`），已存在的不会重复入库
- 文本提取：从 `content` 字段（HTML）剥离标签，保留正文段落；超过 4000 字截断

**降级**：API 抓取失败时记录警告日志，不中断整个流程；下次调度再尝试。

### 10.3 数据流

```
定时任务（每 2h）/ 用户手动"刷新"
  → POST /api/zhihu/users/{id}/refresh
  → zhihu_service.fetch_user_activities(url_token)
  → 增量写入 zhihu_posts
  → 对新增 post 调用 zhihu_analyzer.analyze_post()
  → 写入 zhihu_analyses
  → 如果有未发送过的新分析 + 该用户 email_notify=1 + 订阅者邮箱存在
     → email_service.send_notification()
     → 记录 email_send_log
```

### 10.4 数据库 schema

```sql
-- 监控的知乎用户
CREATE TABLE zhihu_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url_token TEXT UNIQUE NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  headline TEXT,                  -- 个人简介/签名
  follower_count INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 1,
  email_notify INTEGER DEFAULT 1,
  last_checked_at TIMESTAMP,
  last_notified_at TIMESTAMP,     -- 上次邮件通知时间，节流用
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 知乎动态
CREATE TABLE zhihu_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url_token TEXT NOT NULL,
  post_id TEXT NOT NULL,          -- Zhihu 端 ID
  post_type TEXT NOT NULL,        -- 'article' | 'answer' | 'pin'
  title TEXT,
  excerpt TEXT,                   -- 列表摘要
  content_text TEXT,              -- 纯文本正文（用于 LLM）
  url TEXT UNIQUE,
  voteup_count INTEGER DEFAULT 0,
  comment_count INTEGER DEFAULT 0,
  created_at_original TIMESTAMP,  -- 知乎上的发布时间
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_zhp_token_time ON zhihu_posts(url_token, created_at_original DESC);

-- LLM 分析结果
CREATE TABLE zhihu_analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  url_token TEXT NOT NULL,
  stance TEXT,                    -- 'bullish' | 'bearish' | 'neutral' | 'mixed'
  stance_assets TEXT,             -- JSON: [{"asset":"黄金","stance":"bullish","reason":"..."}]
  sectors TEXT,                   -- JSON: ["科技","金融"]
  summary TEXT,                   -- 60字以内总结
  action_suggestion TEXT,         -- 60字以内建议
  key_points TEXT,                -- JSON 数组，每条 1 行
  confidence INTEGER DEFAULT 50,  -- 0-100
  raw_response TEXT,
  model_name TEXT,
  analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(post_id)
);

-- 邮件订阅
CREATE TABLE zhihu_email_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  url_tokens TEXT DEFAULT '[]',   -- JSON 数组，限定只接收哪些大V；空 = 全部
  enabled INTEGER DEFAULT 1,
  verified INTEGER DEFAULT 0,     -- 验证状态（首次发件后置 1）
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 邮件发送日志
CREATE TABLE zhihu_email_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  subject TEXT,
  url_token TEXT,
  post_ids TEXT,                  -- JSON 数组
  status TEXT NOT NULL,           -- 'success' | 'failed'
  error_message TEXT,
  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 10.5 LLM 分析 prompt

输入：单篇知乎文章/回答的标题 + 正文（截断 3000 字）。

输出 JSON（v2，2026-06-04 升级）：

```json
{
  "stance": "bullish | bearish | neutral | mixed",
  "stance_assets": [
    {"asset": "中际旭创", "code": "300308", "category": "cn_stock", "stance": "bullish", "reason": "AI 光模块龙头"},
    {"asset": "腾讯",      "code": "00700",  "category": "hk_stock", "stance": "bullish", "reason": "估值修复"},
    {"asset": "沪深300",              "category": "index",     "stance": "neutral", "reason": "横盘"},
    {"asset": "黄金",                 "category": "commodity", "stance": "bearish", "reason": "避险情绪回落"}
  ],
  "sectors": ["科技","金融"],
  "summary": "60字内总结",
  "action_suggestion": "60字内建议（如'减仓黄金、加仓中证A50'）",
  "key_points": ["要点1","要点2","要点3"],
  "confidence": 70
}
```

**v2 资产提取规则**：
- **优先级**：个股（有 code）> 指数/ETF > 板块 > 大类
- **必填字段**：`asset`（名称，最长 30 字）、`category`（枚举）、`stance`、`reason`（20 字内）
- **可选字段**：`code`（A 股 6 位数字 / 港股 5 位数字 / 美股 1-5 位大写字母）
- **`category` 枚举**：`cn_stock | hk_stock | us_stock | index | etf | commodity | fx | crypto | bond | sector`
- **立场一致性**：对不同资产持相反立场时，stance 必须为 `mixed`；同一资产去重（按"最新+最具体"原则）
- 任何对市场/个股/行业的具体看多看空都必须有 stance_assets 条目；不能把多个股票合并到"A股"一类

实现细节：
- 复用 `sentiment_service` 中的 `_get_llm()`（DeepSeek / MiniMax / 火山云）
- 显式声明"忽略点赞寒暄、不构成投资建议的免责内容"
- 同样支持 `<think>...</think>` 剥离 + JSON 解析容错
- `_validate_result` 容错：未知 category 通过 `_CATEGORY_NORMALIZE` 映射表规范化；老数据（无 code/category）自动留空，前端走 `extractCodeFromName` 兜底

### 10.6 邮件通知

**SMTP 配置**（通过 `.env` 或前端"邮箱设置"面板写入 DB 单行配置）：

| 字段 | 说明 |
|------|------|
| `smtp_host` | SMTP 服务器，如 `smtp.qq.com` |
| `smtp_port` | 465 (SSL) / 587 (STARTTLS) |
| `smtp_user` | 登录账号 |
| `smtp_password` | 授权码/密码 |
| `smtp_use_ssl` | 1 / 0 |

DB 配置优先于 env，env 仅作为兜底。

**通知时机**：
- 调度任务发现新动态 → 触发 LLM 分析
- 分析完成 → 若该用户 `email_notify=1` 且上次通知距今 ≥ `ZHIHU_NOTIFY_MIN_INTERVAL_HOURS`（默认 6h）
- 查询所有启用的订阅 → 发送
- 发送内容：HTML 邮件，含**大V昵称、新动态标题、sticker 色标的看多/看空/中性、原链接、行动建议摘要**

**节流**：
- 同一 `url_token` 6 小时内最多发一封通知
- 同一订阅邮箱同一批动态只发一封（合并多用户）

### 10.7 API 端点

| Method | Path | 说明 | 认证 |
|--------|------|------|------|
| GET | `/api/zhihu/users` | 监控用户列表（含最新动态计数） | 是 |
| POST | `/api/zhihu/users` | 新增监控：`{url_token}` 或完整 URL | 是 |
| DELETE | `/api/zhihu/users/<id>` | 移除监控 | 是 |
| PATCH | `/api/zhihu/users/<id>` | 更新 enabled / email_notify | 是 |
| POST | `/api/zhihu/users/<id>/refresh` | 立即抓取该用户最新动态 | 是 |
| GET | `/api/zhihu/users/<id>/posts?limit=20` | 该用户最新动态（含分析） | 是 |
| GET | `/api/zhihu/posts/<post_id>/analysis` | 获取单篇分析详情 | 是 |
| POST | `/api/zhihu/posts/<post_id>/reanalyze` | 重跑 LLM 分析 | 是 |
| GET | `/api/zhihu/subscriptions` | 邮件订阅列表 | 是 |
| POST | `/api/zhihu/subscriptions` | 新增订阅 | 是 |
| DELETE | `/api/zhihu/subscriptions/<id>` | 移除订阅 | 是 |
| GET | `/api/zhihu/email_settings` | 读取 SMTP 配置（密码脱敏） | 是 |
| POST | `/api/zhihu/email_settings` | 保存 SMTP 配置 | 是 |
| POST | `/api/zhihu/email_test` | 发一封测试邮件：`{email}` | 是 |
| GET | `/api/zhihu/logs?limit=50` | 邮件发送日志 | 是 |
| GET | `/api/zhihu/timeline?days=7` | 近N天所有已分析大V动态聚合时间线 | 是 |

### 10.8 调度任务

`scheduler.py` 启动时注册：

```
zhihu_check_task: every ZHIHU_CHECK_INTERVAL_HOURS hours
  → 遍历 zhihu_users (enabled=1)
  → 调用 zhihu_service.fetch_user_activities(url_token)
  → 增量分析（仅对新增 post）
  → 触发邮件通知（节流后）
```

### 10.9 前端页面

**路径**：`/zhihu`

**LayoutView 导航**：位于"辅助功能"分组下"知乎大V"菜单项。

**页面分区**：
- 顶部：新增监控表单（粘贴知乎个人主页 URL）+ 邮箱设置入口
- 左侧：监控大V列表（头像 + 昵称 + 最后检查时间 + 新动态数 badge）
- 右侧选中后：时间线展示该大V所有动态（按发布时间倒序），每条卡片显示：
  - 类型标签（文章/回答）+ 发布时间 + 点赞/评论数
  - 标题 + 摘要
  - **LLM 分析结果卡片**：整体立场 tag、看多/看空/中性资产 chips、关键观点列表、行动建议
  - 原链接 → 知乎打开
- 底部：邮件订阅列表 + "新增邮箱" + SMTP 设置弹窗

**交互**：
- 列表项"刷新"按钮触发立即抓取
- 卡片"重新分析"按钮重跑 LLM
- 邮件订阅内联"发送测试"按钮
- 邮件发送日志折叠面板

### 10.10 风险与边界

- **反爬措施（实测发现）**：知乎 `/people/{token}/posts`、`/pins` 等动态接口对纯 HTTP 请求返回 403（650 字节固定拦截页），**带登录态 cookie 也挡**（2026-06-30 实测 `ZHIHU_COOKIE` 含 `z_c0` 仍 403）。处理（v4, 2026-06-30）：
  1. **反爬熔断器** `ZhihuCircuitBreaker`（`zhihu_service.py`）：连续 5 次 403 → 打开熔断，后续 `refresh_user` 静默跳过（返回 `circuit_open`，`fetched=0`），冷却 600s 后半开探测。避免旧逻辑每 tick 8 用户 × 3 端点 × 3 重试 = 72 条 WARNING 刷屏。
  2. **403 不重试**：确定性反爬，重试纯浪费。仅 429/503 限流才指数退避重试。
  3. **携带 `ZHIHU_COOKIE`**（若配置）：部分 SSR 页面对登录态仍认，能救一个是一个；不强制依赖。
  4. **冷启动不立即跑 `zhihu_check`**：`scheduler.py` 仅 `forum_prefetch` 启动即跑（guba 列表页不依赖 cookie，可 warm 缓存）；`zhihu_check` 走正常调度，避免每次重启砸一片 403。
  5. `POST /api/zhihu/users` 在抓取失败时仍保存监控记录（url_token + 占位资料），后续刷新再补全
  6. `zhihu_users.last_error` 字段记录最后一次失败原因
- **安全要求**：`ZHIHU_COOKIE` **绝不能** commit 到 git，`.env` 必须在 `.gitignore` 中；建议用专门小号，避免暴露主账号；浏览器退出登录会立刻使 `z_c0` 失效
- **已知大V的 url_token**：用户输入的 `https://www.zhihu.com/people/{token}` 末段需为**真实账号**的 url_token，不是显示名。如 `hongliqi`（洪灝）若不通，请通过浏览器登录后查看个人主页 URL 确认。
- 隐私：仅抓取公开内容；存储的 `content_text` 用于二次分析，不外发
- 频率控制：调度间隔默认 2 小时（`ZHIHU_CHECK_INTERVAL_HOURS`）；用户间间隔 1.5s；前端"刷新"按钮无冷却（由后端 worker 串行执行）
- 邮件安全：SMTP 密码入库时使用 base64 简单脱敏（仅防明文泄露），前端回显时只显示末 4 位
- LLM 复用：直接 import `sentiment_service._get_llm()`，沿用 DeepSeek / MiniMax / 火山云三选一

### 10.11 实现状态（v1，2026-06-01）

| 模块 | 文件 | 状态 |
|------|------|------|
| DB 表 (5 张) | `backend/core/database.py` | ✅ 完成 |
| Zhihu 抓取 | `backend/services/zhihu_service.py` | ✅ 完成（含反爬 + 防错位） |
| LLM 分析 | `backend/services/zhihu_analyzer.py` | ✅ 完成 v2（v2 资产提取：个股 code + category 枚举） |
| SMTP 邮件 | `backend/services/email_service.py` | ✅ 完成（DB + env 双层） |
| API 路由 (16 条) | `backend/api/routes/zhihu.py` | ✅ 完成 |
| 调度任务 | `backend/services/scheduler.py` | ✅ 完成（每 2h 启动后立即跑一次） |
| 前端页面 | `frontend/src/views/ZhihuMonitorView.vue` | ✅ 完成 |
| 菜单/路由/API 客户端 | LayoutView / router / api | ✅ 完成 |
| "AI分析最近10条"按钮 | `frontend/src/views/ZhihuMonitorView.vue` | ✅ 完成（v2, 2026-06-02） |
| 大V时间线报表 | §10.12 全部模块 | ✅ 完成（v3, 2026-06-04「非股票过滤 + 资产标签上图表」） |
| 文档同步 | `docs/SPEC.md` §10 | ✅ 完成 |

**已知限制**：
- 当前代码未实现 `pin`（想法）抓取，仅抓 article + answer（占所有公开动态的 95%+）
- cookie 注入已实现（读 `ZHIHU_COOKIE` env），无 cookie 时 articles/answers 返回 None，profile 仍可拿到部分数据（CDN 错位）

**手动验证清单**：
1. 启动后端：`python -m backend.api.app`
2. 登录后访问 `/zhihu`
3. 添加 `https://www.zhihu.com/people/hongliqi`，观察抓取结果
4. 在"邮箱设置"配置 SMTP，点"测试"按钮验证
5. 添加订阅邮箱 → 触发刷新 → 收到邮件

### 10.12 大V时间线报表（v2，2026-06-02）

**目标**：将所有监控大V近N天的已分析动态汇总成时间线报表，叠加A股/港股/美股30分钟K线图，可视化大V唱多/唱空与市场走势的对照关系。

**过滤规则**（v3，2026-06-04 新增）：时间线**仅展示与股票/投资相关的动态**，过滤掉纯生活/职场/科普类内容。一条动态被视为「股票相关」当且仅当满足任一条件：
  1. `stance` 为 `bullish` / `bearish` / `mixed`（非中性立场）
  2. `stance_assets` 非空（提到 A股/港股/美股/黄金/加密等具体资产）
  3. `sectors` 非空（提到科技/金融/医药等行业）

  中性立场 + 无资产 + 无行业的动态被过滤；其余全部保留。实现位于 `database.py::_is_stock_related` + `get_zhihu_timeline_posts`（Python 层 JSON 解析后过滤）。

**页面路径**：`/zhihu/timeline`

**页面分区**：
- 顶部：时间范围选择（3/7/14天）+ 刷新按钮
- 统计行：总动态数、看多数、看空数、中性数、数据源警告
- K线图区：
  - 指数切换器（上证/深证/创业板/科创50/沪深300）— 使用 el-segmented
  - ECharts 蜡烛图，每根30分钟，红涨绿跌（中国习惯）
  - 大V发言标记散点叠加在对应时间点的收盘价位置：
    - ▲ 绿色三角 = 看多
    - ▼ 红色三角 = 看空
    - ◆ 橙色菱形 = 混合
    - ● 灰色圆 = 中性
  - **每个散点上方显示「主资产」标签**（v3 新增）：个股 code（如 `300308` / `00700` / `NVDA`）最优先，回退到资产简称；`hideOverlap: true` 自动避让
  - 内置 dataZoom（滚轮缩放+底部滑块）、crosshair tooltip（OHLC + 该时间点发言 + **top 3 资产 chips 含 code/名称/立场/理由**）
  - 点击散点弹出大V观点面板（v3 新增）：显示**全部** stance_assets chips（每个含 code + 名称 + 立场 + hover 理由）
- 图例行：解释各符号/颜色含义
- 动态时间线列表：
  - 按日期分组（倒序），日期标题 sticky
  - 立场筛选（看多/看空/中性/混合）+ 大V筛选
  - 每条卡片：左侧竖线色标、时间、头像+昵称、立场标签+置信度、类型标签、标题链接、LLM摘要、**标的资产 chips**（code 与名称分隔显示，hover 显示理由）

**后端实现**：

| 模块 | 文件/函数 | 说明 |
|------|-----------|------|
| DB 查询 | `database.py::get_zhihu_timeline_posts(days)` | JOIN zhihu_posts + zhihu_analyses + zhihu_users，JSON字段解析；过滤掉非股票类动态（见上方过滤规则） |
| K线数据 | `data/intraday.py::get_intraday_bars(symbol, interval, days)` | A股指数走新浪API；港股/美股走 yfinance；支持 sh000001/sz399001/sz399006/sh000688/sh000300/int:hsi/int:spx |
| API 端点 | `routes/zhihu.py` → `GET /api/zhihu/timeline?days=7` | 聚合时间线，datetime 序列化为 ISO 格式字符串 |
| API 端点 | `routes/intraday.py` → `GET /api/market/intraday?symbol=&interval=30min&days=7` | 返回 `{bars: [{time, open, close, low, high, volume}], source, warning, error}` |
| 路由注册 | `app.py` | 注册 `intraday_bp` |

**前端实现**：

| 模块 | 文件 | 说明 |
|------|------|------|
| 依赖 | `package.json` | echarts + vue-echarts |
| API 函数 | `api/index.js` | `getZhihuTimeline(days)` + `getMarketIntraday(symbol, interval, days)` |
| K线组件 | `components/KLineChart.vue` | ECharts 封装：candlestick + scatter 多系列叠加，emit('postClick') |
| 时间线页面 | `views/ZhihuTimelineView.vue` | 完整报表页：统计卡片 + K线图 + 筛选 + 分组动态列表 |
| 路由 | `router/index.js` | `GET /zhihu/timeline` → `ZhihuTimelineView.vue` |
| 入口按钮 | `views/ZhihuMonitorView.vue` | "📊 大V时间线" 按钮 → `$router.push('/zhihu/timeline')` |

**已知限制**：
- 港股/美股30分钟K线依赖 yfinance，若网络不通则返回日线兜底（`source: 'yfinance_daily_fallback'`）
- 新浪API仅返回最近约40根30分钟K线（约5个交易日），请求14天时可能数据不完整（返回 `warning` 提示）
- 时间线仅展示已 LLM 分析的动态，未分析的不会出现
- 大V发言标记按 `created_at_original` 匹配到最近一根K线，精确到30分钟级别
- 前端 ECharts 约 1MB（gzipped ~340KB），首屏加载时按需加载（vue-echarts + 懒路由 import）

**手动验证清单**：
1. `GET /api/zhihu/timeline?days=7` 返回已分析动态数组
2. `GET /api/market/intraday?symbol=sh000001&interval=30min&days=7` 返回K线数据
3. 前端 `/zhihu/timeline` 页面：K线图渲染正常、散点标记在正确位置、时间线列表可按条件筛选

## 11. VIX 恐慌指数（v2, 2026-06-04）

### 11.1 目标

构建一个面向 A 股市场的 VIX 恐慌指数 + 恐惧贪婪综合指数，每日盘后计算一次并存入历史表，前端在 Dashboard 展示核心卡片，并提供独立详情页用于深度观察。

### 11.2 组成成分与权重

| 指标 | 来源 | 权重 | 缺失兜底 |
|------|------|------|----------|
| 50ETF 期权隐含波动率（IV） | `ak.index_option_50etf_qvix()` | 40% | 回退到 RV blended，打标记 `vix_source: rv_fallback` |
| 已实现波动率（RV）变化 | 沪深300 + 中证1000 Garman-Klass | 15% | 中性 50 分 |
| 50ETF 期权 PCR | akshare 1.18.30 **无接口** | 10% | 中性 50 分（`pcr_source: unavailable`） |
| 北向资金净流入 | 沪股通+深股通 | 15% | 中性 50 分（`north_source: unavailable`） |
| 融资余额 | 上交所+深交所 | 10% | 中性 50 分（`margin_source: unavailable`） |
| 涨跌停数量比 | 涨停池+跌停池 | 10% | 中性 50 分（`limit_source: unavailable`） |

各分量先通过 sigmoid 类函数映射到 0-100（0=极度恐惧，100=极度贪婪），再加权求和得到 fear_greed 综合分。

**FG 预期范围分析（重要）**：

- 6 个分量权重：IV 40% / RV 15% / PCR 10% / North 15% / Margin 10% / Limit 10%
- **理论极值**：IV 极恐慌 (score=5) + 其他全 50 → **FG=32.5**；IV 极贪婪 (score=95) + 其他全 50 → **FG=68.0**
- **典型窄带**：当 4-5 个分量都缺失（兜底 50）时，FG 主要被 IV 单一驱动，波动范围收窄到约 **50-68**
- **当前 A 股状态**（2026-04-2026-06）：QVIX 持续在 14-19（偏贪婪），涨停数远多于跌停，三个独立证据一致指向「偏贪婪、缺乏极端情绪」→ **FG 落在 55-62 是真实反映，不是算法 bug**
- **数据完整时**：当 6 个分量全部真实，FG 波动范围可达 **30-80**，能捕捉到极端恐慌（如 2020 年 3 月、2022 年 4 月那种 80+ 涨停 + 资金外逃）

**判断 FG 是否可信**：
- `data_quality.real >= 5` → FG 高度可信
- `data_quality.real = 3-4` → FG 仅供参考，被 IV 单一驱动
- `data_quality.real <= 2` → FG 不可信（IV 也缺失），前端应隐藏 FG 数字

### 11.3 数据源 (`backend/data/vix_sources.py`)

| 函数 | AkShare 接口 | 备注 |
|------|------------|------|
| `fetch_50etf_qvix(days=60)` | `ak.index_option_50etf_qvix()` | QVIX 日线，可取历史 |
| `fetch_index_daily(symbol, days=90)` | `ak.stock_zh_index_daily()` | HS300 / ZZ1000 日线 |
| `fetch_north_net_flow(date_str)` | **3 级降级链**（v2） | 详见下表 |
| `fetch_margin_balance()` | `ak.macro_china_market_margin_sh/sz` | 原始单位元，除以 1e8 转亿 |
| `fetch_limit_counts(date_str)` | `ak.stock_zt_pool_em/dtgc_em` | **日期格式 YYYYMMDD 无连字符** |

**`fetch_north_net_flow` 3 级降级链**（v2, 2026-06-04 升级）：

| 优先级 | 接口 | 返回 | 失败原因 |
|--------|------|------|----------|
| 1 | `ak.stock_hsgt_hist_em()` | 当日"成交净买额"列（行级） | 1.18.30 自 2024-08 后大量 NaN，但取更早日期可正常 |
| 2 | `ak.stock_hsgt_fund_min_em()` | 沪股通+深股通最后 1 根 bar 净买额 | 盘中可能延迟 0 |
| 3 | `ak.stock_hsgt_fund_flow_summary_em()` | row 0（沪北向）+ row 2（深北向）"成交净买额"列 | 数据源仅含实时，部分时段为 0 |

返回结构：`{"north_net": float, "source": "hist"|"min"|"summary"}`，三源全失败返回 `None`（上层按中性 50 处理 + data_quality 标记 unavailable）。

**PCR 数据源（v2 修订）**：akshare 1.18.30 中 `index_option_50etf_qvix` 只给 QVIX 一个值，未暴露 put/call 持仓数据；其他候选接口（`option_daily_50etf_qvix`、`option_risk_indicator_50etf` 等）均不存在。**PCR 当前固定为 None**，由 `_pcr_to_score(None) = 50` 兜底，`pcr_source: unavailable` 标识。后续可接聚宽/米筐/同花顺等外部数据源。

**降级策略（统一）**：任一数据源失败时该分量得 50 分（中性），不抛错中断整体计算；同时在 components 里记 `xxx_source: unavailable|real|hist|min|summary`，前端通过 `data_quality.signals` 知道缺失了哪些维度。

### 11.4 计算服务 (`backend/services/vix_service.py`)

| 函数 | 职责 |
|------|------|
| `garman_klass_rv(df, window=30)` | Garman-Klass 波动率估计（年化 %） |
| `blended_rv(rv_hs300, rv_zz1000)` | 70% 沪深300 + 30% 中证1000 加权，缺失一侧用另一侧 |
| `_vix_to_score/_pcr_to_score/_north_to_score/_margin_change_to_score/_limit_ratio_to_score/_rv_change_to_score` | 6 个 sigmoid 归一化函数，0-100 |
| `compute_fear_greed(components)` | 加权合成 fear_greed（0=极度恐惧，100=极度贪婪） |
| `classify_vix_regime(vix)` | VIX → regime 5 档分类 |
| `compute_today_snapshot(date_str=None)` | 计算某日完整快照（含 components 全部 source 标记） |
| `compute_and_store(date_str=None)` | 落库到 `vix_history` 表（INSERT OR REPLACE by date） |
| `backfill_vix_history(days, skip_existing)` | **v2 新增**：回填过去 N 个**交易日**（自动跳过周末 + A 股法定节假日）；线程锁；v4 默认覆盖旧值，传 `skip_existing=true` 时跳过已存在 |
| `get_backfill_status()` | 回填进度查询 |
| `snapshot_to_api(snap_dict)` | API 序列化层（**v2 新增** `data_quality` + `vix_source` + 各 `*_source` 字段） |
| `get_latest_api()` / `get_history_api(days)` | API 顶层封装 |

**regime 分级**（基于 VIX 值）：`<14` extreme_greed / `14-18` greed / `18-24` neutral / `24-32` fear / `>32` extreme_fear

**百分位**：`vix` 在近 1 年（≥240 个交易日）历史中的百分位排名。

**VIX 主体回退（v2 修订）**：之前是静默 `vix = iv if iv else rv_blended`，现在改为显式标记：

| 情况 | `vix` 值 | `vix_source` |
|------|---------|--------------|
| 50ETF QVIX 命中 | iv_50etf | `iv` |
| QVIX 缺失，RV blended 可用 | rv_blended | `rv_fallback`（前端显示 ⚠️） |
| QVIX + RV 都缺失 | null | `none`（不入库 / 入库但前端提示无数据） |

### 11.5 数据库 schema

```sql
CREATE TABLE vix_history (
  date TEXT PRIMARY KEY,         -- YYYY-MM-DD
  iv_50etf REAL,                 -- 50ETF QVIX
  pcr REAL,                      -- 50ETF 期权 put/call（v2: 恒为 NULL，待接入外部源）
  rv_hs300 REAL,                 -- 沪深300 已实现波动率 (%)
  rv_zz1000 REAL,                -- 中证1000 已实现波动率 (%)
  rv_blended REAL,               -- 70/30 加权
  north_net REAL,                -- 北向资金净流入 (亿元)
  margin_balance REAL,           -- 融资余额 (亿元)
  limit_up_count INTEGER,
  limit_down_count INTEGER,
  vix REAL,                      -- = iv_50etf（v2: 或 rv_blended 回退）
  fear_greed REAL,               -- 0-100 综合情绪
  regime TEXT,                   -- extreme_greed/greed/neutral/fear/extreme_fear
  percentile REAL,               -- 近 1 年百分位
  components_json TEXT,          -- v2: 含各分量 source 标记 + score
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_vix_date ON vix_history(date DESC);
```

### 11.6 API 端点

| Method | Path | 说明 | 认证 |
|--------|------|------|------|
| GET | `/api/vix` | 当日 VIX 快照（latest row） | 是 |
| GET | `/api/vix/history?days=60` | 近 N 天历史（默认 60）；响应另带 `db_total_days` 字段为 DB 实际行数（不受 `days` 截断），前端用其判断下拉是否需要回填 | 是 |
| POST | `/api/vix/recompute` | 触发重算（异步） | 是 |
| GET | `/api/vix/recompute_status` | 轮询重算状态 `{running, last_completed_at}` | 是 |
| POST | `/api/vix/backfill` | **v2 新增**：回填历史。body: `{days: 30, skip_existing: false}`（v4 默认覆盖旧值以补齐 spot / 新公式） | 是 |
| GET | `/api/vix/backfill_status` | **v2 新增**：轮询回填进度 `{running, total, done, skipped, failed, last_error}` | 是 |

**响应示例**（`/api/vix`，v2 包含 data_quality）：

```json
{
  "date": "2026-06-04",
  "vix": 17.51,
  "vix_source": "iv",
  "fear_greed": 58.5,
  "regime": "greed",
  "iv_50etf": 17.51,
  "pcr": null,
  "pcr_source": "unavailable",
  "rv_hs300": 14.32,
  "rv_zz1000": 18.65,
  "rv_blended": 15.59,
  "north_net": null,
  "north_source": "unavailable",
  "margin_balance": 28843.26,
  "margin_source": "real",
  "limit_up_count": 66,
  "limit_down_count": 11,
  "limit_source": "real",
  "percentile": 50.0,
  "data_quality": {
    "total": 6,
    "real": 4,
    "missing": 2,
    "signals": {
      "vix": true, "rv_chg": true, "pcr": false,
      "north": false, "margin": true, "limit": true
    }
  },
  "components": { ... }
}
```

### 11.7 调度任务 (`backend/services/scheduler.py`)

```
daily_vix_task: cron weekday 16:30
  → vix_service.compute_and_store()
  → 线程局部锁 _recompute_lock 防止与手动 POST 并发
```

设计理由：16:00 跑完舆情，16:30 跑 VIX 错开高峰。

**回填不进入调度**：仅手动 `POST /api/vix/backfill`，避免重复拉取触发限流。

### 11.8 前端页面

**Dashboard 卡片**（`DashboardView.vue`）：横向三栏布局 — 左 VixGauge（半圆 SVG 仪表盘，4 段色渐变 + 阈值刻度 + 指针），中 恐惧贪婪综合指数（0-100 进度条 + 6 个子指标 chip：IV 50ETF / RV HS300 / RV ZZ1000 / 涨跌停比 / 融资余额 / 北向资金），右 VixTrendChart（ECharts 折线 + 阈值带 + 副轴 FG）；数据为空时 EmptyHint 引导「立即计算 VIX」。**v2 新增**：卡片底部 data_quality 横条（`✅ 4/6` 或 `⚠️ 4/6 缺失：PCR / 北向资金`），点「详情」跳 `/vix` 详情页。

**独立详情页**（`/vix` → `VixView.vue`）：
- 顶部 PageHeader 含 icon=🌡️、meta（数据日期 + regime tag）、actions（时间窗口下拉 30/60/90 天 + 刷新 + **回填 N 天** + 立即重算）
- 4 个 StatCard：VIX / 恐惧贪婪 / 百分位 / 涨跌停比（不同 tone）
- **v2 新增**：data_quality 横幅 — 显示 `4/6` 完整度 + 缺失分量 chips + VIX 主体回退 tag
- **v2 新增**：回填进度条（el-progress + 跳过/失败计数）
- 主趋势图（height=320）
- 6 格分项明细（IV 50ETF / RV HS300 / RV ZZ1000 / 融资余额 / 北向资金 / PCR）— 每张卡片一个 big-num
- 阈值参考表（5 行：极度贪婪/贪婪/中性/恐慌/极度恐慌，含策略含义）
- 数据为空时底部 EmptyHint

**菜单入口**：侧边栏「辅助功能」分组下，舆情监控 与 知乎大V 之间，label="VIX 恐慌指数"。

### 11.9 实现状态（v2, 2026-06-04）

| 模块 | 文件 | 状态 |
|------|------|------|
| DB 表 | `backend/core/database.py` | ✅ |
| 数据源 v1 | `backend/data/vix_sources.py` | ✅ |
| 数据源 v2（north 3 级降级） | `backend/data/vix_sources.py` | ✅ |
| 计算服务 v1 | `backend/services/vix_service.py` | ✅ |
| 计算服务 v2（vix 显式回退 + data_quality） | `backend/services/vix_service.py` | ✅ |
| **回填功能** | `backend/services/vix_service.py::backfill_vix_history` | ✅ |
| API 路由 v1 | `backend/api/routes/vix.py` | ✅ |
| API 路由 v2（backfill + 状态） | `backend/api/routes/vix.py` | ✅ |
| 调度任务 | `backend/services/scheduler.py` | ✅ |
| 仪表盘卡片 | `DashboardView.vue` | ✅ |
| 仪表盘组件 | `VixGauge.vue` + `VixTrendChart.vue` | ✅ |
| 独立详情页 v1 | `VixView.vue` | ✅ |
| **独立详情页 v2**（data_quality + 回填按钮 + 进度） | `VixView.vue` | ✅ |
| 路由/侧边栏 | `router/index.js` + `LayoutView.vue` | ✅ |
| API 客户端 v1 | `api/index.js` | ✅ |
| **API 客户端 v2**（backfillVix + getVixBackfillStatus） | `api/index.js` | ✅ |

**已知限制**：
- **PCR 永久 unavailable**：akshare 1.18.30 无 50ETF 期权 put/call 数据接口，需接外部数据源
- **north_net 在 akshare 1.18.30 下数据源碎片化**：`hist_em` 2024-08 后 NaN，`fund_min_em` 盘中可能 0，`fund_flow_summary_em` row 0/2 部分时段为 0；三源全失败的概率在盘中段较高，盘后基本可用
- **FG 在 4-6 个分量缺失时波动范围收窄**：典型窄带 50-68（理论极值 32.5-68.0），详细分析见 §11.2
- **50ETF QVIX 在收盘后可能延迟更新（T+1）**
- **百分位基于近 1 年历史（≥240 个交易日）**，新系统前 240 天该字段为 None
- **回填是阻塞的**（daemon thread 串行），90 天约需 3-5 分钟（每交易日 ~2-3 秒）；自动跳过周末 + A 股法定节假日（2025-2026 硬编码列表，后续可接 tushare 交易日历）

**手动验证清单**（v2）：
1. 后端启动后 `POST /api/vix/backfill {"days": 30}` 触发回填
2. 轮询 `GET /api/vix/backfill_status` 看到 `done` 递增，最终 `running: false`
3. `GET /api/vix/history?days=30` 返回 25 条左右数据（25 个交易日）
4. 前端 `/vix` 详情页：data_quality 横幅正确显示 4/6 + 缺失分量为 PCR / 北向资金
5. 前端 `/dashboard` 卡片底部 data_quality 提示 + 跳详情按钮工作
6. 回填进度条：el-progress 平滑推进，完成后 3 秒自动消失
7. **回归**：原有 `POST /api/vix/recompute` + `GET /api/vix/recompute_status` 仍正常

---

## 11A. VIX 算法 v3 — 现货位置维度（2026-06-04）

### 11A.1 设计动机

v2 算法在 6 个分量（IV / RV / PCR / 北向 / 融资 / 涨跌停）上都是"波动 + 资金 + 情绪"类指标，**没有任何一个分量反映"现货已涨到哪/已跌到哪"**。

**典型误判案例**：2025-08-25 上证收 3883.56（阶段新高，+9.97% 偏离 ma60），50ETF 期权 QVIX 升到 25.78（机构套保需求），VIX 类算法把这一日标成 `fear`（FG=39.7）。**但现货层面这是顶部风险，不是底部机会**。

v3 引入**现货位置维度**，3 个子信号综合后形成 spot_score（0-100），与 VIX 类 fear_greed **加权合成单一 composite_score**，统一输出 5 档 regime。这样 4/7 暴跌 → `extreme_fear`（真底部），8/25 顶部 → `greed/extreme_greed`（顶替 VIX-only 的 fear）。

### 11A.2 现货位置子信号

| 子信号 | 公式 | 含义 |
|---|---|---|
| `spot_ma60_dev` | `(close - ma60) / ma60 × 100` | 当前位置偏离 60 日均线 %（负=超跌/底部，正=超涨/顶部） |
| `spot_mom_5d` | `pct_change(5) × 100` | 5 日累计涨跌幅 %（短期动量） |
| `spot_mom_20d` | `pct_change(20) × 100` | 20 日累计涨跌幅 %（中期动量） |
| `spot_new_high_ratio_20d` | `rolling(20).apply(close == max) / 20` | 过去 20 日中创 20 日新高的日数占比（趋势强度 0-1） |

**数据源**：`ak.stock_zh_index_daily_tx('sh000001')`（腾讯财经，1990-至今全量历史；比 akshare em 接口的 ~200 行滚动窗口长得多，能稳定形成 ma60）。

**`_spot_to_score` 阈值**（激进档，验证后定档）：

| 条件 | spot_score |
|---|---|
| ma60_dev ≤ -3% AND mom_20d ≤ -3% AND hi20 ≤ 0.15 | 5-15（**极端底部**） |
| ma60_dev ≤ -1.5% AND mom_20d ≤ -1.5% | 25-35（底部观察） |
| -1.5% < ma60_dev < +3% 且 mom_20d -1.5% ~ +3% | 45-55（中性） |
| ma60_dev ≥ +3% AND mom_20d ≥ +3% AND hi20 ≥ 0.45 | 65-75（顶部观察） |
| ma60_dev ≥ +6% AND mom_20d ≥ +6% AND hi20 ≥ 0.55 | 85-95（**极端顶部**） |

**关键点**：3 条件 AND 才触发极值档（避免假信号）；中间区基于 ma60_dev 的 sigmoid 中心 0.75% 映射。

### 11A.3 合成单一信号

```
composite_score = 0.4 × fear_greed + 0.6 × spot_score
```

权重 VIX 类 40% + 现货 60%（**现货位置更直接反映"当前位置"，权重大于情绪面**）。任一维度 None 时退回到另一维度。

**regime 分级**（与 v2 保持 5 档一致，便于前端统一色卡）：

| composite_score 范围 | regime |
|---|---|
| 0-25 | `extreme_fear` |
| 25-45 | `fear` |
| 45-55 | `neutral` |
| 55-75 | `greed` |
| 75-100 | `extreme_greed` |

### 11A.4 关键验证（2026-06-04 历史回放）

| 日期 | 上证 | QVIX | v2 FG | v2 regime | spot_dev | spot_mom20d | spot_hi20 | **composite** | **v3 regime** |
|------|------|------|-------|-----------|----------|-------------|-----------|---------------|---------------|
| 2025-04-07 关税暴跌 | -6.56% | ~38 | ~27 | extreme_fear | -6.56% | -8.18% | 0.15 | ~20 | **extreme_fear ✓** |
| 2025-08-25 顶部 | +9.97% | 25.78 | 39.7 | fear | +9.97% | +7.94% | 0.70 | **71.0** | **greed ✓** |
| 2025-08-27 暴跌 | +7.14% | 24.14 | 42.4 | fear | +7.14% | +5.11% | 0.60 | **64.2** | **greed ✓** |
| 2025-09-15 暴跌 | +5.91% | 20.15 | 49.5 | neutral | +5.91% | +3.55% | 0.20 | **55.0** | **neutral**（中期趋势未坏） |
| 2026-03-23 大底 | -6.38% | 42.16 | 27.3 | extreme_fear | -6.38% | -6.58% | 0.10 | **20.4** | **extreme_fear ✓** |

**对比关键点**：
- **8/25 v2 误判 fear → v3 正确判 greed**（现货已 +10% 偏离 ma60，三信号全部触发极端顶部）
- **4/7 和 3/23 两个真底部**：v2 和 v3 都判 extreme_fear（现货超跌 + IV 飙升，一致）
- **8/27 / 9/15 暴跌**：v2 标 fear，v3 标 greed/neutral（中期趋势未坏，是高位回调不是趋势反转）

### 11A.5 数据库 schema 增量

```sql
ALTER TABLE vix_history ADD COLUMN spot_close REAL;
ALTER TABLE vix_history ADD COLUMN spot_ma60_dev REAL;
ALTER TABLE vix_history ADD COLUMN spot_mom_5d REAL;
ALTER TABLE vix_history ADD COLUMN spot_mom_20d REAL;
ALTER TABLE vix_history ADD COLUMN spot_new_high_ratio REAL;
ALTER TABLE vix_history ADD COLUMN composite_score REAL;
ALTER TABLE vix_history ADD COLUMN composite_regime TEXT;
```

迁移通过 `try/except OperationalError` 幂等执行（仿照 §forum_posts 的 `audit_*` 列迁移模式）。

### 11A.6 API 响应增量

`/api/vix` 响应新增字段：

```json
{
  "vix_only_regime": "fear",          // v2 旧版 VIX 5 档（保留兼容）
  "regime": "greed",                  // v3 主标签 = composite 5 档
  "spot": {
    "close": 3883.56,
    "ma60_dev": 9.97,
    "mom_5d": 4.17,
    "mom_20d": 7.94,
    "new_high_ratio": 0.7,
    "source": "real"
  },
  "composite": {
    "score": 71.0,
    "regime": "greed",
    "vix_fg": 39.7,        // VIX 类 fear_greed
    "spot_score": 91.5     // spot_score（0-100）
  },
  "data_quality": { "total": 7, ... }  // v2: 6 个分量；v3: 7 个（加 spot）
}
```

### 11A.7 前端升级

**VixView.vue**：
- 顶部 KPI 5 个 StatCard（原 4 个 + 新增**综合位置**；tone 随分值 5 档）
- 趋势图 legend 加 **Composite** 第 3 条线（次 y 轴 0-100，indigo-950 颜色 #1e1b4b）
- **新增「市场位置信号」ModernCard**（bordered 变体）：4 个子信号（ma60 偏离 / 5 日动量 / 20 日动量 / 20 日新高比例）+ 底部 verdict 横条（5 档动态文案 + 颜色）
  - extreme_fear: "极度恐慌 · 强烈买入信号"（rose 底，提示分批布局）
  - fear: "恐慌区间 · 谨慎观察"
  - neutral: "中性震荡"
  - greed: "贪婪区间 · 警惕风险"
  - extreme_greed: "极度贪婪 · 顶部风险"（emerald 底，建议减仓）

**VixTrendChart.vue**：tooltip 增 3 行（VIX / 恐惧贪婪 / 综合位置），series 加 `Composite` 副轴线。

### 11A.8 实现状态（v3, 2026-06-04）

| 模块 | 文件 | 状态 |
|------|------|------|
| 现货数据源（TX 全量） | `backend/data/vix_sources.py::fetch_index_daily_tx` | ✅ |
| 现货信号计算 | `compute_spot_signals_from_df` + `get_spot_signals_for_date` | ✅ |
| DB schema 增量（7 列） | `backend/core/database.py` | ✅ |
| 评分函数 | `_spot_to_score` / `compute_composite_score` / `classify_composite_regime` | ✅ |
| `VixSnapshot` 扩展 | `backend/services/vix_service.py` | ✅ |
| `snapshot_to_api` 输出新结构 | 同上 | ✅ |
| `compute_today_snapshot` 改造（days=400 拉数据） | 同上 | ✅ |
| 250 天回填 | `backfill_vix_history(days=250, skip_existing=False)` | ✅ |
| 前端 VixView 新增 StatCard + 位置卡片 | `frontend/src/views/VixView.vue` | ✅ |
| 前端 VixTrendChart 加 Composite 线 | `frontend/src/components/VixTrendChart.vue` | ✅ |
| 文档同步 | `docs/SPEC.md` §11A | ✅ |

**已知限制**：
- **现货数据接口切换**：原 `ak.stock_zh_index_daily`（em）数据窗口约 200 行，2025-04-25 ~ 2026-06-04；v3 改用 `ak.stock_zh_index_daily_tx`（腾讯）覆盖 1990 至今，能稳定支持 250 天回填的 ma60 窗口
- **极端顶部/底部仅在 3 条件 AND 时触发**：避免单日异常跳价假信号（用户 2025-09 月那类"误判"已被消解）
- **当前 A 股状态**（2026-06）：composite 大多落在 50-60 中性偏贪区，理论上 IV 极恐慌时 composite 可跌破 20，IV 极贪婪时 composite 也难以突破 80（除非现货也极端）

## 11B. VIX 算法 v4 — 离散度增强与敏感视图（2026-06-08）

**问题背景**：用户在 `/vix` 详情页观察到 2026-03-23 能识别为市场底部，但普通交易日的曲线离散度不足；恐惧贪婪指数在非疯狂行情下长期压在很窄区间，实盘可用性偏弱。

**根因**：
- `PCR` 当前不可用、`north` 经常不可用，旧算法仍按 50 分纳入加权，等于把 25% 权重固定拉向中性，压缩 `fear_greed` 波动。
- `_vix_to_score` 的 sigmoid 斜率偏平，50ETF QVIX 在 14-20 的常态区间分差不足。
- 前端趋势图只画绝对值，03-23 这种尖峰会扩大 Y 轴范围，让普通日期视觉上接近一条直线。
- 历史 `spot` 维度若回填时 `skip_existing=true`，旧行不会被补齐，`composite_score` 会退回 `fear_greed`。

**后端 v4 规则**：
- `compute_fear_greed` 改为“可用分量动态归一”：真实可用的分量按原始权重重新归一；不可用分量不再以 50 分稀释。若所有分量都不可用才返回 50。
- `vix` 分量映射由 `100 / (1 + exp(0.18 * (vix - 22)))` 调整为 `100 / (1 + exp(0.24 * (vix - 21)))`，提高 14-20 区间灵敏度，同时保留 32+ 极端恐慌低分。
- `components_json` 增加 `fg_scores` 与 `fg_available_weights`，用于审计每个分量得分和本次实际参与权重。

**前端 v4 规则**：
- `VixTrendChart.vue` 增加视图切换：
  - `绝对`：原始 VIX / FG / Composite，用于阈值和策略语义。
  - `敏感`：VIX 采用 winsorized robust z-score 映射到 0-100 的相对压力，FG / Composite 用当前窗口 min-max 放大到 0-100；用于观察普通交易日离散度。
- 敏感视图不改变后端指标含义，只改变曲线观察尺度；tooltip 同时展示原始值和敏感值。
- 详情页文案明确“敏感视图用于观察离散度，策略判读仍以绝对值与综合位置为准”。

**修复建议**：上线后对近 90-250 天执行 `POST /api/vix/backfill {"days": 250, "skip_existing": false}`，覆盖旧行以补齐 `spot` 与 v4 `fg_scores`。

## 11C. VIX 算法 v5 — 重构（2026-06-09）

### 11C.1 设计动机

v4 及之前版本存在以下结构性问题：

1. VIX 主体仅依赖 50ETF QVIX，样本偏差严重
2. 阈值使用硬编码绝对值（VIX<14 极贪），不随市场状态自适应
3. PCR 固定为 None（未发现 `option_daily_stats_sse` 接口）
4. 北向资金已停止披露但仍占 15% 权重
5. 现货位置分使用 5 档离散 AND 逻辑，输出跳变
6. 多个标签口径不一致（regime 用 composite，percentile 用 VIX）

### 11C.2 核心变更

| # | 变更 | 旧 | 新 |
|---|------|-----|-----|
| 1 | 合成 VIX | 50ETF QVIX 单一值 | 5 ETF (50/300/500/创业板/科创) 等权平均 |
| 2 | Sigmoid 中心 | 固定值 21 | 滚动 Z-Score 自适应 |
| 3 | PCR 数据 | 永远 None | `option_daily_stats_sse` 真实数据 |
| 4 | 北向资金 | 权重 15% | 删除 |
| 5 | 现货位置分 | 5 档离散 AND | 3 子信号加权 sigmoid 连续映射 |
| 6 | 统一输出 | 多重标签口径 | composite_score + 滚动百分位 |
| 7 | 阈值 | 硬编码绝对值 | 基于近 252 日滚动百分位 |

### 11C.3 新权重表

| 分量 | 权重 | 数据源 |
|------|------|--------|
| 合成 VIX | 35% | 5 ETF QVIX 等权 |
| RV 变化 | 15% | HS300+ZZ1000 Garman-Klass |
| PCR | 15% | 上交所 option_daily_stats_sse |
| 融资融券 | 15% | 沪深两市 macro_china_market_margin |
| 涨跌停比 | 20% | 涨停池+跌停池 |

北向资金 15% 权重被重新分配到合成 VIX（+5%）和涨跌停比（+10%）。

### 11C.4 新 Regime 阈值（基于滚动百分位）

| 百分位 | Regime | 策略含义 |
|--------|--------|----------|
| 0-10% | extreme_fear | 市场极度恐慌，关注买入机会 |
| 10-30% | fear | 偏恐慌 |
| 30-70% | neutral | 中性震荡 |
| 70-90% | greed | 偏贪婪 |
| 90-100% | extreme_greed | 极度贪婪，警惕顶部风险 |

### 11C.5 数据源新增

`backend/data/vix_sources.py` 新增两个函数：

| 函数 | AkShare 接口 | 用途 |
|------|------------|------|
| `fetch_multi_etf_qvix(days=60)` | 5 个 `index_option_*_qvix()` | 5 ETF QVIX → 合成 VIX |
| `fetch_pcr(date_str)` | `ak.option_daily_stats_sse(date=YYYYMMDD)` | 50ETF 成交量/持仓量 PCR |

`fetch_north_net_flow` 保留函数代码（外部可能仍引用），但 v5 算法不再调用。

### 11C.6 Z-Score 动态中心

`_vix_to_score(vix, zscore)` 新增可选 `zscore` 参数：
- Z=0 → score=50（中性）
- Z=+2 → score≈12（恐慌）
- Z=-2 → score≈88（贪婪）

Z-Score 从 `vix_history` 表取最近 252 天的 `vix` 列计算；不足 20 天时回退到固定中心 21 的旧公式（保持 v4 行为）。

### 11C.7 现货位置分（连续化）

`_spot_to_score(spot)` 由 5 档离散 AND 逻辑改为加权 sigmoid 连续映射：

| 子信号 | 权重 | sigmoid 中心 / 斜率 |
|--------|------|-------------------|
| ma60_dev | 50% | 0%，k=0.3 |
| mom_20d | 30% | 0%，k=0.2 |
| new_high_ratio | 20% | 线性 0→30 / 0.5→65 / 1.0→95 |

输出在 5-95 区间平滑连续，不再跳变。

### 11C.8 数据库 schema 增量（v5, 2026-06-09）

```sql
ALTER TABLE vix_history ADD COLUMN iv_300etf REAL;
ALTER TABLE vix_history ADD COLUMN iv_500etf REAL;
ALTER TABLE vix_history ADD COLUMN iv_cyb REAL;
ALTER TABLE vix_history ADD COLUMN iv_kcb REAL;
ALTER TABLE vix_history ADD COLUMN pcr_volume REAL;
ALTER TABLE vix_history ADD COLUMN pcr_oi REAL;
ALTER TABLE vix_history ADD COLUMN pcr_call_volume INTEGER;
ALTER TABLE vix_history ADD COLUMN pcr_put_volume INTEGER;
ALTER TABLE vix_history ADD COLUMN pcr_source TEXT;
ALTER TABLE vix_history ADD COLUMN vix_zscore REAL;
ALTER TABLE vix_history ADD COLUMN vix_source TEXT;
ALTER TABLE vix_history ADD COLUMN composite_percentile REAL;
ALTER TABLE vix_history ADD COLUMN margin_source TEXT;
ALTER TABLE vix_history ADD COLUMN limit_source TEXT;
```

新数据库函数：`get_vix_history_for_zscore(days=252)` 取最近 N 天的 vix 数值列表（用于 Z-Score 计算）。

`upsert_vix_history()` 扩展为写入上述全部新列。

### 11C.9 API 响应增量

`/api/vix` 响应新增字段：

```json
{
  "date": "2026-06-09",
  "vix": 26.7,                      // 5 ETF 等权合成 VIX
  "vix_source": "multi_etf",         // multi_etf | 50etf_only | none
  "vix_zscore": 0.35,                // 滚动 Z-Score
  "vix_etf_count": 5,                // 当前实际有效的 ETF 数
  "iv_50etf": 18.5, "iv_300etf": 20.0, "iv_500etf": 25.0,
  "iv_cyb": 30.0, "iv_kcb": 40.0,
  "pcr_volume": 0.95, "pcr_oi": 0.88,
  "pcr_call_volume": 100000, "pcr_put_volume": 95000,
  "pcr_source": "sse",
  "composite_score": 56.0,
  "composite_regime": "neutral",
  "composite_percentile": 55.0,
  "regime": "neutral",               // v5: = composite_regime（统一标签）
  "vix_only_regime": "neutral",      // 保留兼容
  "percentile": 55.0,                // v5: = composite_percentile（统一口径）
  "spot": { "close": 3200.0, "ma60_dev": 1.5, "mom_5d": 0.8,
            "mom_20d": 2.1, "new_high_ratio": 0.25, "source": "real" },
  "data_quality": {
    "total": 6, "real": 6, "missing": 0,
    "signals": {"vix": true, "rv_chg": true, "pcr": true,
                "margin": true, "limit": true, "spot": true}
  }
  // 不再包含 north_net / north_source
}
```

### 11C.10 前端升级

**Dashboard `VixGauge.vue`（v5）**：
- `value` prop 改为 `composite_score`（0-100），量程默认 0-100（旧版 10-40）
- 阈值刻度改为百分位 10/30/70/90（基于 regime）
- 中心数值下方新增「合成 VIX xx.xx  Z=+0.3」副标题
- 颜色语义反转：恐慌 = 绿色（机会），贪婪 = 红色（风险）

**DashboardView.vue**：
- 子指标 chip 从 6 个改为 5 个：北向资金 → PCR 成交量
- `data_quality` 缺失标签从 `北向资金` 改为 `现货位置`（v5 total=6：5 分量 + 现货位置）

**`VixTrendChart.vue`（v5）**：
- 新增 Percentile series（紫色虚线，右 Y 轴 0-100）
- 阈值带改为 0-10/10-30/30-70/70-90/90-100 5 档色带
- tooltip 新增 Z-Score + 百分位 + 情绪（按百分位）显示
- 副轴改名为「综合/百分位」

**`VixView.vue`（v5）**：
- 顶部 5 个 StatCard：合成 VIX / 综合位置 / 滚动百分位 / 恐惧贪婪 / 涨跌停比
- 新增「多 ETF 隐含波动率」卡片（5 个 ETF IV 柱状条）
- 分项明细从 6 格改为 5 格（删除北向资金；PCR 改为成交量+持仓量双值；涨跌停改为 涨停/跌停 双值）
- 阈值参考表改为百分位 0-10/10-30/30-70/70-90/90-100
- data_quality 横幅 `total=6`

### 11C.11 上线步骤

1. **数据迁移**：v5 ALTER TABLE 在 `init_db()` 中幂等执行；旧列数据自动保留
2. **历史回填**：执行 `POST /api/vix/backfill {"days": 250, "skip_existing": false}`，覆盖旧行以补齐 v5 新字段（`pcr_*`、`iv_*etf`、`vix_zscore`、`composite_percentile` 等）
3. **回归验证**：
   - `GET /api/vix` 响应包含 `pcr_source: "sse"`（非 `unavailable`）
   - `GET /api/vix` 响应不包含 `north_net` / `north_source`
   - `data_quality.total = 6`
   - `vix_source = "multi_etf"`（非 `iv`）

### 11C.12 回滚方案

如 v5 上线后出现问题：
1. `git checkout` 恢复 `backend/services/vix_service.py`、`backend/data/vix_sources.py`、`backend/core/database.py`
2. 前端恢复 `VixGauge.vue`、`VixTrendChart.vue`、`VixView.vue`、`DashboardView.vue`
3. 重启 Flask
4. 执行 `POST /api/vix/backfill {"days": 250, "skip_existing": false}` 用旧算法重新计算历史数据
5. v5 新增的 DB 列保留为 NULL，不影响旧代码读取

### 11C.13 实现状态（v5, 2026-06-09）

| 模块 | 文件 | 状态 |
|------|------|------|
| 数据源 v5（多 ETF QVIX + PCR） | `backend/data/vix_sources.py` | ✅ |
| 数据库 v5 schema 迁移 | `backend/core/database.py` | ✅ |
| 计算服务 v5（重写） | `backend/services/vix_service.py` | ✅ |
| Dashboard VixGauge 升级 | `frontend/src/components/VixGauge.vue` | ✅ |
| Dashboard 子指标调整 | `frontend/src/views/DashboardView.vue` | ✅ |
| 趋势图新增 Percentile | `frontend/src/components/VixTrendChart.vue` | ✅ |
| 详情页重写 | `frontend/src/views/VixView.vue` | ✅ |
| API 路由（无需改动） | `backend/api/routes/vix.py` | ✅（现有端点透传新结构） |
| API 客户端（无需改动） | `frontend/src/api/index.js` | ✅ |
| 文档 | `docs/SPEC.md` §11C | ✅ |

**已知限制**：
- **多 ETF QVIX 数据可用性**：5 个 ETF 的 QVIX 接口分别由不同交易所发布，部分 ETF（如科创 50ETF）在某些日期可能缺失；任一缺失时 `vix_etf_count` 减 1，但合成 VIX 仍基于剩余可用 ETF
- **PCR 数据**：上交所 `option_daily_stats_sse` 在期权到期日可能不发布；此时 PCR 退回到 50 分（中性），`pcr_source: unavailable`
- **Z-Score 在新系统前 252 天**：`compute_vix_zscore` 数据不足 20 天时返回 0.0（中性）
- **regime 基于百分位而非绝对值**：跨系统/跨周期比较时不再直观（同一数值的 regime 可能不同）

## 11D. VIX 算法 v6 — 合成生效 + 敏感度增强（2026-06-28）

### 11D.1 设计动机

v5 设计完整，但上线后存在三类问题（本次排查实证）：

1. **多 ETF 合成从未生效（P0 bug）**：`fetch_multi_etf_qvix` 判断 `"iv_close" in df.columns`，但 akshare 的 `index_option_300etf_qvix()` 等函数返回列名是 `close`（仅 `fetch_50etf_qvix` 单独 rename 成 `iv_close`）。结果 5 个 ETF 全被跳过，函数永远返回 `None`，VIX 主体一直回退到单一 50ETF。前端显示「当前 0 个有效」「VIX 主体回退 iv」即此因。
2. **平稳日不敏感**：① 受 bug 影响，VIX 主体是波动最低的宽基 50ETF；② composite = FG×40% + 现货×60%，FG 里 VIX 仅 35% → VIX 对 composite 实际贡献仅约 14%，平稳日微动被现货位置淹没。
3. **回填性能**：`get_spot_signals_for_date` 每个交易日都重拉腾讯全量历史（~50s/天），250 天回填需 ~4h，按钮形同虚设。

### 11D.2 核心变更

| # | 变更 | 旧 (v5) | 新 (v6) |
|---|------|---------|---------|
| 1 | 多 ETF 列名 | `iv_close`（不存在）→ 合成失效 | `close`（正确）→ 5 ETF 真正等权合成 |
| 2 | 合成 VIX 序列 | 仅取末值 | 按日期对齐的 synthetic 序列，附带 prev/high/low |
| 3 | VIX 日变化率信号 | 无 | 新增 `_vix_change_to_score`（权重 12%） |
| 4 | VIX 日内振幅信号 | 无 | 新增 `_vix_swing_to_score`（权重 8%） |
| 5 | FG 权重 | VIX35/RV15/PCR15/Margin15/Limit20 | VIX25/VIXchg12/VIXswing8/RV12/PCR13/Margin10/Limit20 |
| 6 | composite 拆分 | FG40% + 现货60% | FG50% + 现货50% |
| 7 | 回填性能 | 每天重拉全量历史（~50s/天） | 腾讯全量历史 60s TTL 进程缓存（整轮拉一次） |

变更后 VIX 对 composite 的实际贡献从约 14% 提升到约 22.5%（FG 内 VIX 类 45% × composite 内 FG 50%），且变化率/振幅快信号让平稳日的边际情绪转向可被捕捉。

### 11D.3 v6 FG 权重表

| 分量 | 权重 | 数据源 | 缺失兜底 |
|------|------|--------|----------|
| 合成 VIX（水平，Z-Score 中心） | 25% | 5 ETF QVIX 等权 | 中性 50 |
| VIX 日变化率 | 12% | synthetic 日环比 | 中性 50（无 prev 时） |
| VIX 日内振幅 | 8% | synthetic high/low 等权 | 中性 50 |
| RV 变化 | 12% | HS300+ZZ1000 Garman-Klass | 中性 50 |
| PCR | 13% | 上交所 option_daily_stats_sse | 中性 50 |
| 融资融券变化 | 10% | 沪深两市 margin | 中性 50 |
| 涨跌停家数比 | 20% | 涨停池+跌停池 | 中性 50 |

缺失分量权重按 active_weight 归一化分摊到可用分量。

### 11D.4 新信号算法

```
_vix_change_to_score(curr, prev):  # VIX 上升=恐慌=低分
    chg% = (curr - prev) / prev × 100
    return 100 / (1 + exp(0.12 × chg))      # chg=+10%→23, 0→50, -10%→77

_vix_swing_to_score(high, low, close):     # 盘中振幅大=恐慌=低分
    swing% = (high - low) / close × 100
    return clamp(50 - (swing - 6) × 4, 5, 95)  # swing=6%→50, 16%→10
```

注：`synthetic_high/low` 为各 ETF 当日 high/low 的等权（非同时点极值），偏保守高估，仅作相对信号使用。

### 11D.5 数据源/服务/前端改动

| 模块 | 文件 | 改动 |
|------|------|------|
| 数据源 | `backend/data/vix_sources.py` | `fetch_multi_etf_qvix` 修列名 bug + 返回 synthetic 序列(prev/high/low) + `as_of` 参数；`fetch_index_daily_tx` 加 60s TTL 缓存 |
| 计算服务 | `backend/services/vix_service.py` | 新增 `_vix_change_to_score`/`_vix_swing_to_score`；`compute_fear_greed` v6 7 分量权重；`compute_composite_score` 50/50；snapshot 计算变化率/振幅；`snapshot_to_api` 暴露 `vix_change_pct`/`vix_swing_pct`；`_version=v6` |
| 前端详情页 | `frontend/src/views/VixView.vue` | 合成 VIX 卡片新增「日变化/振幅」行；轮询改用 `getTask(taskId)`（旧 `*_status` 端点已 410） |
| 前端仪表盘 | `frontend/src/views/DashboardView.vue` | 重算轮询改用 `getTask(taskId)` |
| 前端 API | `frontend/src/api/index.js` | 删除 `getVixRecomputeStatus`/`getVixBackfillStatus`（指向 410 端点） |

### 11D.6 已知限制

- `synthetic_high/low` 为各 ETF 极值等权，非同一时点，振幅信号偏保守
- 全量 v6 回填前，历史 `vix` 仍是旧单 50ETF 基线（~17），与新合成（~33）混算会使 Z-Score/百分位短时失真；**全量回填覆盖后自愈**
- 腾讯历史缓存 TTL 60s：单次回填整轮共享一份，跨任务/盘后实时计算不受影响

## 11E. VIX 算法 v6.1 — 评审采纳调整（2026-06-28）

### 11E.1 背景

v6 上线后将设计提交 GPT / Gemini 双评审，两者结论高度收敛：方向对（这是「A股恐惧贪婪/风险偏好指数」而非严格 CBOE VIX 复制品），但有 5 处可立刻改进。v6.1 全部采纳。ML 自动定权重的方向另案处理（不在本次范围）。

### 11E.2 五项调整

| # | 调整 | v6 | v6.1 | 理由 |
|---|------|-----|------|------|
| 1 | ETF 合成权重 | 等权（各 20%，创业板+科创占 40%） | 50/300/500/创业板/科创 = 20/30/20/15/15% | 等权让高波动的成长 ETF 过度主导，把「全市场恐慌」做成「成长股恐慌」；改代表性加权（市值+期权流动性深度）。权重按当日可用 ETF 重新归一化 |
| 2 | 宽基/成长拆分 | 无 | 新增 `vix_broad`(50+300+500) / `vix_growth`(创业板+科创) / `vix_growth_premium`(成长−宽基) | 区分系统性风险 vs 风格杀估值。如 2026-06-26：synthetic 31.1，但 broad 23.9 / growth 47.9 / premium +24，说明是成长局部恐慌而非全市场冰点 |
| 3 | composite 拆分 | FG 50% + 现货 50% | FG 60% + 现货 40% | FG（期权 IV/PCR）前瞻，现货均线/动量同步且与涨跌停/融资重复计量；提高前瞻话语权，避免趋势行情被现货拖偏 |
| 4 | 快信号权重 + 平滑 | 变化率 12% + 振幅 8% = 20%，单日值 | 变化率 9% + 冲击 6% = 15%；变化率做 2 日平滑 | 快信号噪声大；降权 + 平滑过滤单日扰动，回补给 VIX 水平（25%→30%） |
| 5 | 日内振幅算法 | 先拼各 ETF high/low 等权再算振幅 | 单 ETF 各自振幅% → 加权（重命名「跨 ETF 波动冲击强度」） | 各 ETF 极值非同时点，先拼会造出「虚假全天恐慌」；正确顺序是单 ETF 标准化→合成 |

### 11E.3 v6.1 FG 权重表

| 分量 | 权重 | 备注 |
|------|------|------|
| 合成 VIX（水平，Z-Score 中心） | 30% | 代表性加权 |
| VIX 日变化率（2 日平滑） | 9% | 快信号，从序列内派生 |
| VIX 波动冲击强度 | 6% | 单 ETF 振幅%加权 |
| RV 变化 | 12% | HS300+ZZ1000 Garman-Klass |
| PCR | 13% | 上交所 option_daily_stats_sse |
| 融资融券变化 | 10% | 沪深两市 margin |
| 涨跌停家数比 | 20% | 涨停池+跌停池 |

`composite = FG × 60% + 现货位置 × 40%`。VIX 类对 composite 实际贡献约 27%（FG 内 VIX 相关 45% × 60%）。

### 11E.4 实现要点

- `vix_sources.fetch_multi_etf_qvix`：`ETF_WEIGHTS` 加权 + `_weighted_last` 按可用列归一化；返回 `broad/growth/growth_premium/swing_pct/synthetic_prev2`
- 变化率 2 日平滑全部从 QVIX 序列内派生（用 `synthetic_prev`/`synthetic_prev2`），**回填顺序无关**，不依赖 DB 中可能未就位的行
- `recompute_percentiles()`：回填收尾统一按 point-in-time（该行往前 252 交易日）口径重算 `composite_percentile` + `composite_regime`，修正 oldest→newest 回填早期行的百分位失真
- 数据边界拓展至 **2025-01-01**（356 交易日）；前端下拉新增 360 天选项
- `_version = "v6.1"`；新增 API 字段 `vix_broad`/`vix_growth`/`vix_growth_premium`

### 11E.5 未采纳 / 留待后续

- **ML 自动定权重**（用户提出）：以「输入=各分量权重，目标=预测未来 7 天指数涨跌」训练模型。结论是**另开会话单独做**，且应作为独立「预测叠加层」而非替换可解释的温度计主输出（避免身份危机：温度计描述「现在多恐慌」vs 预测器预测「未来涨跌」）。关键约束：7 天重叠标签样本自相关需 purged walk-forward 验证；QVIX 可回溯 2015，但 PCR/涨跌停/融资的联合可用历史待验证

## 11F. VIX 2.0 — 机器学习因子权重（2026-06-29）

### 11F.1 背景与定位

v6.1 是**手工定权重**的恐惧贪婪温度计，衡量「当前波动/情绪强度」，但**不衡量「这个位置作为底/顶有多好」**。实证矛盾：2025-04-07（关税冲击大底）composite_pct 仅 1.6%，2026-03-23（另一次大底）1.2%，更深的 4-07 反而读数略高——原始 IV 只反映预期波动，没有前瞻收益校准。

VIX 2.0 = 用机器学习从历史学到「哪些因子、以多大权重，最能提前识别底/顶」，产出与**前瞻市场结果**对齐的 0-100 分。**关键约束：v6.1 完全不动**，VIX 2.0 作为并行第二套指标（独立表 / 独立 API / 前端独立卡片），两套可同屏对比。完整设计书见 `docs/vix2-ml-design.md`。

### 11F.2 方法选型

| 维度 | 选择 | 理由 |
|------|------|------|
| 标签 | 三隘栏（Triple-Barrier, López de Prado） | 用止盈/止损/时间三 barrier 给每天打「未来涨/跌」标签，天然对齐底/顶，比固定 N 日收益稳健 |
| 模型 | 正则化逻辑回归（L2, class_weight='balanced'） | 可解释——直接产出每因子学习权重，正好对应「用 ML 找因子权重」诉求；样本不多时比树/DL 稳健 |
| 数据 | 长历史核心因子（11 个，回溯 2016-02） | QVIX 可回溯 2015-02，252 日 Z-Score 窗口后有效样本从 2016-02 起，~2500 行 |

### 11F.3 因子集（core）

`qvix_50` / `qvix_50_z`(252日Z) / `qvix_50_chg5` / `rv_hs300`(GK) / `rv_qvix_spread`(方差风险溢价) / `ma60_dev` / `mom_20d` / `mom_60d` / `new_high_ratio` / `drawdown_252` / `dist_low_252`。全部 point-in-time（trailing 窗口，无未来泄漏）。增强因子（多 ETF/PCR/涨跌停/融资）放 `feature_set='enhanced'` 留待后续。

### 11F.4 标签与分数

三隘栏：`entry=close[t]`，`upper=entry*(1+pt*scale)`，`lower=entry*(1-sl*scale)`，`vertical=t+H`；默认 pt=sl=0.05，H=20，barrier 按近 20 日日波动率动态缩放（clip 0.5~3×）。先触 upper→label=+1（底侧），先触 lower→-1（顶侧），到期按方向。训练目标 `P(label=+1)`；**VIX2 score = (1−P_up)×100**，与 v6.1 同口径（低分=恐慌=机会）。regime 沿用 `classify_by_percentile`（近 252 日滚动百分位）。

### 11F.5 防泄漏

特征仅用 t 日收盘后已知信息；标签用 t 之后 H 日未来价；CV 用 `TimeSeriesSplit`（前段训练→后段验证，**禁止随机 KFold**）；最近 252 样本留作纯样本外评估。`StandardScaler → LogisticRegression(C=网格搜索, ROC-AUC 选优)`；固定 `random_state=42` 保证复现。

### 11F.6 工程落地

| 项 | 内容 |
|----|------|
| 文件 | `services/vix2_features.py`（因子）/ `vix2_labels.py`（三隘栏）/ `vix2_model.py`（训练/CV/落盘/加载/推断）/ `vix2_service.py`（推断·回填·百分位编排）/ `api/routes/vix2.py`（5 端点）/ `scripts/train_vix2.py`（离线训练 CLI） |
| 落盘 | `data/models/vix2_<version>.joblib`（Pipeline）+ `.json`（元数据+权重+scaler）+ `vix2_latest.json`（生效指针） |
| DB 表 | `vix2_history`（date PK / p_up / score / percentile / regime / model_version / features_json）——独立于 vix_history |
| task_kind | `vix2_train` / `vix2_backfill`（均走 TaskRunner，返回 32-hex task_id） |
| 调度 | 接在 `daily_vix_task` 中 v6.1 之后：推断当日 → 重算百分位；模型未训练则静默跳过 |

### 11F.7 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/vix2` | 最新快照 + 模型状态 |
| GET | `/api/vix2/history?days=365` | 历史序列 |
| GET | `/api/vix2/model` | 模型元数据 + 因子权重（前端权重条形图） |
| POST | `/api/vix2/train` | 触发离线重训（TaskRunner，返回 task_id） |
| POST | `/api/vix2/backfill` | 用当前模型回填历史 score（TaskRunner，返回 task_id） |

前端 `VixView.vue` 新增「VIX 2.0（机器学习）」卡片：大数字 score + regime tag + P_up/百分位、模型信息行（version/OOS-AUC/CV-AUC/样本/训练区间）、因子权重双向条形图（按 |系数| 排序）、重训/回填按钮（task 轮询）。

### 11F.8 实验结论：当前因子集无稳健预测力（如实呈现，2026-06-29）

**定位：实验性特性，不可用于交易。** 经过完整的 barrier 参数扫描 + 严格的 embargoed walk-forward 验证，结论是：当前 11 个线性因子对 A 股 2016–2026 大底/大顶 **没有稳健的前瞻预测力**。

**首版 core 模型**（pt=sl=0.05, H=20）：CV-AUC≈0.47，OOS-AUC≈0.51，接近随机；在两个已知大底把 3-23 排得比 4-07 更极端，不满足设计书 §6「相对排序更合理」验收标准。

**barrier 参数扫描**（`scripts/sweep_vix2.py`，40 组配置：H∈{10,20,40,60} × 5 组 pt/sl × rv∈{T,F}）：
- CV-AUC 全程 0.40–0.48（普遍低于随机）。
- 单切分 OOS-AUC 仅在 H=60 时升到 0.60–0.65（如 pt=0.1/sl=0.07/H=60 达 0.65）。**但这是重叠标签（overlapping labels）造成的人为假象**——长 horizon 下测试窗内独立观测极少，AUC 被自相关抬高。

**embargoed walk-forward 验证**（`scripts/robust_vix2.py`，对 4 个候选切 6 个连续 OOS 区块，每块训练时扣除 H 天 embargo 杜绝标签泄漏）：
- 全部候选跨块均值 AUC ≈ 0.49–0.50，区块间剧烈摆动（如 H=60 那个「0.65」配置实测 blocks=[0.531, 0.521, 0.513, 0.311, 0.4, 0.668] → mean=0.491±0.112）。
- 真信号应跨块稳定 >0.5；这里塌回 ~0.5，确认单切分 0.65 是假象而非真信号。

**结论：基础设施（特征/标签/训练/落盘/推断/API/前端/调度）已完整可用且可复现，但当前因子集无法产生可交易的信号，整个特性按「实验性 / 接近随机 / 不可作为交易依据」对待。** v6.1 行为完全未变（vix_history 未被触碰）。前端 VIX2 卡片采用用户导向的「研究状态面板」：优先展示“当前不能用于交易 / 为什么不能用 / 今天读数只能如何看”，把模型版本、样本区间、因子权重折叠到研究细节里，避免用户把单日分数或权重条误读成交易信号。

后续若要继续：需引入非线性模型或增强因子集（基本面/资金面/跨市场）、或改用事件研究式标签，并保留 embargoed walk-forward 作为唯一可信的验收口径——单切分 OOS-AUC 在长 horizon 下不可信。

### 11F.9 赛道 A 研究 spike：跨市场因子 + 非线性模型（2026-06-29）

按「先过模型有效性闸门、再工程化」原则，对赛道 A（提升预测力）做了不落盘、不改生产代码的研究 spike（`scripts/spike_vix2_xmkt.py`）。

**新增长历史跨市场因子**（均回溯 >2016，不截断 2504 样本；覆盖率 86.4%）：恒指 5 日收益 / 20 日已实现波动、美债 10Y 水平（滞后 1 交易日防前视）、美债 10Y 20 日变化、中美 10Y 利差、人民币中间价 20 日动量。

**embargoed 6-block walk-forward 结果（核心口径 H=20）**：

| 配置 | core-only | core+xmkt（线性） | core+xmkt（HistGBDT） |
|------|-----------|-------------------|------------------------|
| pt=0.07/sl=0.05/H=20 | 0.497 ± 0.073 | 0.526 ± 0.129 | — |
| pt=0.05/sl=0.05/H=20/rv | 0.493 ± 0.079 | 0.516 ± 0.127 | **0.522 ± 0.065** |

**结论（仍未过闸门）**：跨市场因子给短 horizon 带来**边际且高方差**的提升（线性均值 +0.02～0.03，但 std 几乎翻倍）；非线性 HistGBDT 在 core+xmkt 上拿到目前最优、方差最小的 **0.522 ± 0.065**，但仍低于设计书 §6 的 0.55 验收线，且所有配置在第 5 区块仍塌到 ~0.40–0.49。**判定：方向正确（跨市场 + 非线性优于纯线性 core），但单凭这两步尚不足以让 VIX2.0 通过有效性闸门、进入工程硬化阶段。** 维持「实验性 / 不可交易」定位不变；下一步候选为标签改造（A3，前瞻分位/事件研究）+ 更厚因子集，仍以 embargoed walk-forward 均值稳定 >0.55 为唯一放行标准。

### 11F.10 严肃交易因子研究框架（替代玩具事件研究，2026-06-29）

目标不是让单一 VIX/VIX2 数字直接发出买卖信号，而是构造一个**可被严格验证、可进入策略回测的市场择时因子**。第一原则：所有结论必须来自样本外预测，不接受事后分桶描述性统计作为“因子有效”。

**交易定义（防止目标漂移）**：
- 交易时点：t 日收盘后得到 VIX/恐慌贪婪与市场数据，t+1 开盘/收盘执行。
- 预测目标：未来 `20` 个交易日上证综指/沪深300超额收益或风险调整收益；辅助看 `5/10/60` 日。
- 因子输出：连续分数 `vix_alpha_score`（越高=越适合提高权益仓位），不是离散提示语。
- 用途：仓位调节/择时过滤，而非单独替代选股或交易系统。

**可用特征池**：
- v6.1 历史特征：`composite_percentile`、`composite_score`、`fear_greed`、`vix_zscore`、`vix_change_pct`、`vix_swing_pct`
- 现货确认：`spot_ma60_dev`、`spot_mom_5d`、`spot_mom_20d`、`spot_new_high_ratio`
- 长历史波动/位置特征：复用 VIX2 core features（QVIX、RV、动量、回撤、距底）
- 跨市场特征：恒指、美债10Y（滞后1交易日）、中美利差、人民币中间价

**研究方法**：
1. 构造 point-in-time 数据集，所有特征必须在 t 日收盘后可知；美债类滞后 1 个 A 股交易日。
2. 标签采用未来收益分位/风险调整收益，不再只用三隘栏分类：
   - 回归标签：`fwd_ret_20d / realized_vol_20d`
   - 排序标签：未来 20 日收益在滚动窗口内的分位
   - 分类标签：未来 20 日收益是否跑赢中性阈值
3. 模型先做三档：
   - 线性基线：Ridge/Logistic（可解释）
   - 非线性：HistGradientBoosting / XGBoost-like 浅树（捕捉状态交互）
   - 简单规则基线：v6.1 composite_percentile 反向分数
4. 验证必须使用 purged/embargoed walk-forward，输出每个 OOS 区块的**预测序列**，再计算：
   - Rank IC / Pearson IC（预测分数 vs 未来收益）
   - Top-Bottom 分层收益差
   - 策略收益（仅基于 OOS 预测）：高分加仓、低分降仓
   - 跨年份稳定性、换手、最大回撤、夏普

**生产化闸门**：
- OOS Rank IC 均值 > 0.03，且至少 60% OOS 区块为正；
- Top-Bottom 20 日未来收益差 > 2%，且不是单一年份贡献；
- OOS 策略夏普 > buy-and-hold，最大回撤下降；
- 加入交易成本/滑点后仍有效；
- 所有结果能一键复现，不能手工挑年份/挑参数。

**2026-06-29 严格 OOS 结论**：`scripts/research_vix_alpha.py` 的直接收益/风险调整收益 alpha 路线未过闸门，baseline/core/core+xmkt/GBDT 的 OOS Rank IC 均为负或弱负，训练期自适应方向也没有识别出可交易反向关系。`scripts/research_vix_risk_factor.py` 修正回撤标签后显示：未来 20 日最大回撤预测未过闸门，Top-Bottom 回撤差为负或不稳定；但未来 20 日实现波动率预测显著有效，`baseline_qvix_risk` OOS RiskIC=0.3369、5/5 区块为正、Top-Bottom vol spread=3.69pct，`core_xmkt_risk_linear` OOS RiskIC=0.1898、4/4 区块为正、Top-Bottom vol spread=2.41pct，并在简单降仓策略中 Sharpe 0.76 vs buy-hold 0.40、最大回撤 -17.90% vs -28.09%。判定：VIX/恐慌指数暂不作为收益 alpha；可继续推进为 `vix_vol_risk_score`/风险预算因子，用于高预期波动期降低权益仓位或杠杆。

**2026-06-29 稳健性复核**：`scripts/research_vix_vol_risk_robustness.py` 覆盖上证综指/沪深300、10/20/60 日 horizon、q60/q70/q80 三组阈值、0/5/10bps 成本。结论：10/20 日波动率风险预测稳健通过候选门槛，60 日不稳定，不进入生产口径。上证 H10/H20：`baseline_qvix` RiskIC≈0.343/0.337、5/5 区块为正、Top-Bottom vol spread=5.56/3.69pct；`core_xmkt_linear` RiskIC≈0.333/0.190、4/4 区块为正、10bps 成本后仍提升 Sharpe 并降低最大回撤。沪深300 H10/H20：`baseline_qvix` RiskIC≈0.386/0.350，`core_xmkt_linear` RiskIC≈0.330/0.111，均 100% 区块为正；但 QVIX 基线只改善回撤、不改善收益/Sharpe，core+xmkt 风险预算规则在 10bps 成本后仍明显改善 Sharpe 与最大回撤。生产候选为 `vix_vol_risk_score`：当前 live API 先服务最稳定、可解释、无需离线模型落盘的 QVIX 252 日 percentile 基线（默认 H=20 风险预算口径），并在 validation 中保留 core+xmkt linear 的研究证据；core+xmkt live 模型需完成训练产物序列化后再接入。输出风险等级与建议权益仓位上限，不输出买卖信号。

**UI 原则**：在未过上述闸门前，前端只显示“研究中/未通过/可进入下一阶段回测”，不得显示暗示交易的买卖文案。通过后才允许把 `vix_alpha_score` 作为仓位建议输入展示。`vix_vol_risk_score` 只允许展示为“未来波动率风险/仓位上限参考”，不得显示为确定性买卖信号。

### 11G. 恐惧贪婪构造效度重建（v7.0 手工版 + VIX2 重定向，2026-06-29）

**问题**：v6.1 恐惧贪婪指数在两个真实事件上失效，暴露的不是权重没调好，而是构造原理缺陷：
1. **2025-04-07（上证 3096，关税千股跌停）应最恐慌，但 fg=16.3；2026-03-23（上证 3813）价格高得多，fg=15.6 反而略更恐**。根因：指数锚定 IV *水平*（3-23 IV=51 > 4-07 IV=42），而真正的恐慌信号是价格回撤深度 + 跌停广度 + IV *飙升幅度*。4-07 当天 `limit_source != real`，跌停广度分量落到中性 50，最 decisive 的信号被静默丢弃。
2. **2025-08 单边上涨（均线之上 6–10%、动量强劲）却进恐慌区**。根因：IV 从 20 涨到 31，`vix_score` 被推到极恐，而 VIX 在合成里占 60%，与现货贪婪分量抵消后合成分卡在 50。上涨趋势里的 IV 上升是行情波动放大，不是恐慌——构造无法区分“下跌恐慌”与“上涨波动”。
3. **结构性死分量**：`rv_change_score` 全样本恒为 5.0（地板 bug）；`margin_change_score`/`limit_score` 长期 = 50（数据源非 real）。所谓 7 分量合成实际只有 IV + PCR 起作用，权重归一化后 IV 一家独大。

**Construct-truth 恐惧分（两版共用真相定义）**：在 `backend/services/fear_greed_truth.py` 定义一个“市场真实情绪”的可计算锚，显式去耦 IV 水平：
- **价格回撤锚（主导）**：close 距 trailing 60/252 日高点的回撤深度。越深越恐。这是修正两个案例的根基——4-07 深回撤应极恐、8 月在高位应无恐。
- **趋势/体制门控**：均线之上 + 正动量 → 抑制恐惧（消灭 8 月假恐慌）；均线之下 + 负动量 → 放大。
- **IV 飙升（变化率，非水平）**：QVIX 5 日变化率。突发飙升 → 恐慌，区分“崩盘 IV 跳”与“上涨 IV 漂”。
- **广度崩塌**：跌停家数 / 下跌广度。4-07 的 decisive 信号；缺失时显式降权并标记，不静默中性。
- **IV 水平仅作次级、体制门控后贡献**：仅在下跌体制里给 IV 水平话语权。

**事件锚点校验集（construct validity，不是 alpha 验证）**：
- 已知大底日应排到极恐分位：2025-04-07（3096）、2024 年内深底待补；
- 已知大顶/高位日应排到极贪分位：2025-08 中下旬高位、2026-03 反弹高位；
- 上涨波段不应进恐区（8 月反例）；
- 底部单调性：回撤越深 + 跌停广度越大 → 越恐慌，单调成立；
- 方向性 sanity：极恐后未来 20 日收益均值 > 0、极贪后 < 0（不要求强 alpha，只验方向常识）。

**Track A — v7.0 手工恐惧贪婪重建**：
1. 修死分量（`rv_change_score` 地板 bug；涨跌停/融资缺失时显式降权+标记，不静默中性）；
2. 加价格体制锚 + 上涨趋势 IV 抑制门控；
3. 底部单调性约束；
4. 用同一套锚点 + 与 construct-truth 的 rank 相关做构造效度校验；
5. 通过后冻结 v7.0，落库新列、前端 v6.1/v7.0 同屏对比，每日盘后打分，保留 v6.1 直到 v7.0 稳定。

**Track B — VIX2 重定向**：VIX2 特征已含 `drawdown_252`/`ma60_dev`/`mom_20d`/`qvix_50_chg5`/`dist_low_252`（价格体制 + IV 飙升），缺的不是特征是**标签**。当前三隘栏标签是“未来涨跌方向”（收益 alpha 目标，已证明失败，且把 v6.1 的 IV 水平坑在 ML 里重踩）。重定向：把训练目标从 `P(未来涨)` 改为 **regression 逼近 construct-truth 恐惧分**（`vix2_truth_labels.build_truth_labeled_dataset` + `vix2_model.train_truth_model`，StandardScaler→Ridge，TimeSeriesSplit 选 alpha），VIX2 分数即变为“学习到的真实情绪状态估计”。**已验证（2026-06-29）**：旧 VIX2 三隘栏 OOS-AUC≈0.49、与 truth rank-IC=-0.37（反指）；重定向 Ridge 模型 CV R2=0.76、纯样本外 R2=0.85、MAE=4.25、RankIC=0.87，全样本与 truth rank-IC=0.925。学到的权重合理：`ma60_dev` 强负权（上涨抑制恐惧）、`qvix_50_z`/`rv_hs300`/`qvix_50_chg5` 正权（IV 飙升增恐）、`drawdown_252` 负权（回撤越深越恐）。锚点日验证：4-07 truth 88.6→预测 88.8、8-22 truth 3.7→预测 0、3-23 truth 84.9→预测 100。重定向 VIX2 已落盘为 `vix2-truth-*`，作为情绪因子候选展示。

**口径约束**：v7.0 / VIX2 重定向版均只作为“市场情绪/风险位置参考”展示，不得显示为确定性买卖信号；`vix_vol_risk_score`（10/20 日波动率风险预算）保持独立、不与此情绪指数混用。

## 11H. VIX 算法 v8 — 大小盘分离 + 未来因子修复 + VIX2 walk-forward OOS（2026-07-01）

**背景**：v6.1 经审计存在两类问题：(1) 回填历史时 RV / 融资融券 / Z-Score 不按目标日截断，引入未来因子，污染历史 composite 曲线；(2) composite 把情绪面（期权 IV/PCR/融资/涨跌停）与现货价格面合成一条线，掩盖了大小盘情绪分化。v8 一次性修复。

**1. 未来因子（look-ahead）修复**：
- `fetch_index_daily` / `fetch_index_daily_tx` 新增 `as_of` 参数，回填历史日 d 时截断到 `date <= d`，RV/现货信号全部 point-in-time。
- `fetch_margin_balance` 新增 `as_of`，按日期列取 `<= d` 的最后一行（旧实现永远取今天 `iloc[-1]`）。
- Z-Score / 百分位改用 PIT DB helper：`get_vix_column_before(date_str, col, days)` 取 `date < d` 的历史，`get_vix_latest_before(date_str)` 取前一交易日（融资融券环比）。实时路径（今日）等价取最近 N 行，回填路径严格不含未来。
- `recompute_percentiles` 改为按「该行及之前 window 个交易日」point-in-time 全表重算两条轨道百分位。

**2. 大小盘分离（废弃 composite 合成）**：
- 废弃 `composite = 0.6·FG + 0.4·spot`。改为两条独立轨道：
  - **大盘轨道**：50ETF + 300ETF QVIX + 沪深300 RV + 沪深300 现货
  - **小盘轨道**：500ETF + 创业板 + 科创50 QVIX + 中证1000 RV + 中证1000 现货
- 每条轨道各自 `VIX / Z-Score / FG(纯 cap 信号) / percentile / regime`。`compute_track_fg` 仅用 IV 水平(Z) + IV 变化率 + IV 跨标的振幅 + RV 变化（权重 0.45/0.15/0.10/0.30）。
- PCR / 融资融券 / 涨跌停 是全市场信号，无法区分大小盘，降级为参考展示，不再进 FG。现货位置分（`large_spot_score`/`small_spot_score`）单独展示，不再参与 FG。
- 新增列（vix_history）：`large_vix/large_zscore/large_fg/large_percentile/large_regime/large_rv/large_spot_score` + 对应 `small_*`。旧 `composite_*`/`fear_greed`/`vix` 字段保留并 alias 到大盘轨道，保证旧前端/仪表盘不崩。
- `fetch_multi_etf_qvix` 新增 `large/small/large_prev/large_prev2/small_prev/small_prev2/large_swing/small_swing` 输出。
- 前端 `VixTrendChart` 改为同屏绘 6 条线（大盘/小盘 × VIX/FG/百分位）。

**3. VIX 2.0 walk-forward OOS 回填（修复 in-sample 回放）**：
- 旧 `backfill_vix2` 用 final 模型（全量含目标日标签训练过）回填，历史曲线对训练期 in-sample，不能当实盘表现。
- 新 `backfill_vix2_walkforward`（`POST /api/vix2/backfill_walkforward`）：按 60 交易日分块，每块用「块首日前一天」之前的数据训练 Ridge 真值模型（`train_truth_at_cutoff`，每块独立 TimeSeriesSplit 选 alpha），推断整块。truth 标签是 trailing 派生（无未来），故 cutoff 即严格 OOS。
- 新增列（vix2_history）：`fear_truth/truth_percentile/truth_model_version/truth_train_cutoff`。`truth_train_cutoff` 标注该点模型最后见到的训练日，便于审计。
- 前端新增 `Vix2TrendChart`：绘制 walk-forward OOS 真值分（主曲线）+ 滚动百分位 + 旧 in-sample 分（虚线对照），tooltip 显示训练截止日。VixView「OOS 回填」按钮触发。

**4. 根线含义（v8 后）**：
- **VIX**：单条轨道的代表性加权 QVIX 水平（期权市场定价的前瞻波动预期）。
- **FG**：纯 cap 信号融合分（IV 水平/变化/振幅 + RV 变化），0-100。
- **percentile**：该轨道 FG 在过去 252 日的 point-in-time 百分位，消除绝对值漂移，驱动 5 档 regime。
- （composite 已废弃；现货位置分作为参考线单独展示。）

## 11. 舆情标题真实性审计（v1, 2026-06-04）

### 11.1 目标

构建一个面向 A 股市场的 VIX 恐慌指数 + 恐惧贪婪综合指数，每日盘后计算一次并存入历史表，前端在 Dashboard 展示核心卡片，并提供独立详情页用于深度观察。

### 11.2 组成成分与权重

| 指标 | 来源 | 权重 | 计算 |
|------|------|------|------|
| 50ETF 期权隐含波动率（IV） | `ak.index_option_50etf_qvix()` | 40% | 直接读 QVIX 年化值 |
| 已实现波动率（RV）变化 | 沪深300 + 中证1000 Garman-Klass | 15% | 与 20 日均值比较 |
| 50ETF 期权 PCR | 50ETF 期权 put/call 比 | 10% | 当日值 |
| 北向资金净流入 | 沪股通+深股通 | 15% | 当日净流入 |
| 融资余额 | 上交所+深交所 | 10% | 较 5 日前变化率 |
| 涨跌停数量比 | 涨停池+跌停池 | 10% | (涨停-跌停)/(涨停+跌停) |

各分量先通过 sigmoid 类函数映射到 0-100（0=极度恐惧，100=极度贪婪），再加权求和得到 fear_greed 综合分。

### 11.3 数据源 (`backend/data/vix_sources.py`)

| 函数 | AkShare 接口 | 备注 |
|------|------------|------|
| `fetch_50etf_qvix()` | `ak.index_option_50etf_qvix()` | QVIX 实时值 |
| `fetch_index_daily(symbol)` | `ak.stock_zh_index_daily()` | 用于 Garman-Klass RV 计算 |
| `fetch_north_net_flow()` | `ak.stock_hsgt_fund_min_em()` | 1.18.30 兼容性最好；不稳定时返回 None |
| `fetch_margin_balance()` | `ak.macro_china_market_margin_sh/sz` | 原始单位元，除以 1e8 转亿 |
| `fetch_limit_counts(date_str)` | `ak.stock_zt_pool_em/dtgc_em` | **日期格式 YYYYMMDD 无连字符** |

**降级策略**：任一数据源失败时该分量得 50 分（中性），不抛错中断整体计算。

### 11.4 计算服务 (`backend/services/vix_service.py`)

| 函数 | 职责 |
|------|------|
| `garman_klass_rv(df)` | Garman-Klass 波动率估计（年化 %） |
| `blended_rv(hs300, zz1000)` | 70% 沪深300 + 30% 中证1000 加权 |
| `_vix_to_score/_pcr_to_score/_north_to_score/_margin_to_score/_limit_to_score/_rv_chg_to_score` | 6 个 sigmoid 归一化函数，0-100 |
| `compute_fear_greed(components)` | 加权合成 fear_greed（0=极度恐惧，100=极度贪婪） |
| `compute_today_snapshot()` | 计算当日完整快照（含所有原始字段 + 派生指标 + components_json） |
| `compute_and_store()` | 落库到 `vix_history` 表（INSERT OR REPLACE by date） |
| `snapshot_to_api(row)` / `get_latest_api()` / `get_history_api(days)` | API 序列化层 |

**regime 分级**（基于 VIX 值）：`<14` extreme_greed / `14-18` greed / `18-24` neutral / `24-32` fear / `>32` extreme_fear

**百分位**：`vix` 在近 1 年（≥240 个交易日）历史中的百分位排名。

### 11.5 数据库 schema

```sql
CREATE TABLE vix_history (
  date TEXT PRIMARY KEY,         -- YYYY-MM-DD
  iv_50etf REAL,                 -- 50ETF QVIX
  pcr REAL,                      -- 50ETF 期权 put/call
  rv_hs300 REAL,                 -- 沪深300 已实现波动率 (%)
  rv_zz1000 REAL,                -- 中证1000 已实现波动率 (%)
  rv_blended REAL,               -- 70/30 加权
  north_net REAL,                -- 北向资金净流入 (亿元)
  margin_balance REAL,           -- 融资余额 (亿元)
  limit_up_count INTEGER,
  limit_down_count INTEGER,
  vix REAL,                      -- = iv_50etf（主指标）
  fear_greed REAL,               -- 0-100 综合情绪
  regime TEXT,                   -- extreme_greed/greed/neutral/fear/extreme_fear
  percentile REAL,               -- 近 1 年百分位
  components_json TEXT,          -- 6 个分量原始值 + score JSON 串
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_vix_date ON vix_history(date DESC);
```

### 11.6 API 端点

| Method | Path | 说明 | 认证 |
|--------|------|------|------|
| GET | `/api/vix` | 当日 VIX 快照（latest row） | 是 |
| GET | `/api/vix/history?days=60` | 近 N 天历史（默认 60）；响应另带 `db_total_days` 字段为 DB 实际行数（不受 `days` 截断），前端用其判断下拉是否需要回填 | 是 |
| POST | `/api/vix/recompute` | 触发重算（异步） | 是 |
| GET | `/api/vix/recompute_status` | 轮询重算状态 `{running, last_completed_at}` | 是 |

**响应示例**（`/api/vix`）：

```json
{
  "date": "2026-06-04",
  "iv_50etf": 17.51,
  "pcr": 0.85,
  "rv_hs300": 14.32,
  "rv_zz1000": 18.65,
  "rv_blended": 15.59,
  "north_net": 24.5,
  "margin_balance": 28758.3,
  "limit_up_count": 66,
  "limit_down_count": 11,
  "vix": 17.51,
  "fear_greed": 62.3,
  "regime": "greed",
  "percentile": 28.5,
  "components_json": "{\"iv\":{\"raw\":17.51,\"score\":65.2},...}"
}
```

### 11.7 调度任务 (`backend/services/scheduler.py`)

```
daily_vix_task: cron weekday 16:30
  → vix_service.compute_and_store()
  → 线程局部锁 _recompute_lock 防止与手动 POST 并发
```

设计理由：16:00 跑完舆情，16:30 跑 VIX 错开高峰。

### 11.8 前端页面

**Dashboard 卡片**（`DashboardView.vue`）：横向三栏布局 — 左 VIXGauge（半圆 SVG 仪表盘，4 段色渐变 + 阈值刻度 + 指针），中 恐惧贪婪综合指数（0-100 进度条 + 6 个子指标 chip：IV 50ETF / RV HS300 / RV ZZ1000 / 涨跌停比 / 融资余额 / 北向资金），右 VixTrendChart（ECharts 折线 + 阈值带 + 副轴 FG）；数据为空时 EmptyHint 引导「立即计算 VIX」。

**独立详情页**（`/vix` → `VixView.vue`）：
- 顶部 PageHeader 含 icon=🌡️、meta（数据日期 + regime tag）、actions（时间窗口下拉 30/60/90 天 + 刷新 + 立即重算）
- 4 个 StatCard：VIX / 恐惧贪婪 / 百分位 / 涨跌停比（不同 tone）
- 主趋势图（height=320）
- 6 格分项明细（IV 50ETF / RV HS300 / RV ZZ1000 / 融资余额 / 北向资金 / PCR）— 每张卡片一个 big-num
- 阈值参考表（5 行：极度贪婪/贪婪/中性/恐慌/极度恐慌，含策略含义）
- 数据为空时底部 EmptyHint

**菜单入口**：侧边栏「辅助功能」分组下，舆情监控 与 知乎大V 之间，label="VIX 恐慌指数"。

### 11.9 实现状态

| 模块 | 文件 | 状态 |
|------|------|------|
| DB 表 | `backend/core/database.py` | ✅ |
| 数据源 | `backend/data/vix_sources.py` | ✅ |
| 计算服务 | `backend/services/vix_service.py` | ✅ |
| API 路由 | `backend/api/routes/vix.py` | ✅ |
| 调度任务 | `backend/services/scheduler.py` | ✅ |
| 仪表盘卡片 | `DashboardView.vue` | ✅ |
| 仪表盘组件 | `VixGauge.vue` + `VixTrendChart.vue` | ✅ |
| 独立详情页 | `VixView.vue` | ✅ |
| 路由/侧边栏 | `router/index.js` + `LayoutView.vue` | ✅ |
| API 客户端 | `api/index.js` (getVix/getVixHistory/recomputeVix/getVixRecomputeStatus) | ✅ |

## 11. 舆情标题真实性审计（v1, 2026-06-04）

**目标**：解决东财股吧 `post_title` 字段（来自 `article_list` JSON）与实际帖子页面 `/news,code,post_id.html` 标题不一致的问题。用户打开链接看到的标题经常和列表页不一样，导致 LLM 拿到的标题是错的。

**核心思路**：在 LLM 分析时自动重抓每条帖子的 URL 拿真实标题，与 DB 存储的标题对比。不一致时用真实标题喂给 LLM（而非错误标题），并把审计结果存到 DB 供前端展示。

### 11.1 数据流

```
触发分析（手动 / 调度）→ fetch_forum_posts（拉帖子）
                       ↓
                audit_posts 批量审计
                  ↓ 对每条帖子调 audit_post_title
                  ↓ fetch_post_full 重抓 URL → 拿 actual_title
                  ↓ 与 stored_title 对比 → 写 DB (audit_status, title_match, actual_title)
                       ↓
                标题不一致时 → _build_posts_text 用 actual_title 替代
                       ↓
                LLM 分析（看到的是真实标题）
                       ↓
                sentiment_scores + 返回 audit 摘要
```

### 11.2 审计状态机

| 状态 | 含义 | 触发条件 |
|------|------|---------|
| `pending` | 尚未审计 | 初始 / 重置后 / 抓取失败 |
| `verified` | 标题一致 | 抓取成功 + title_match=1 |
| `mismatch` | 标题不一致 | 抓取成功 + title_match=0 |
| `manual_accepted` | 用户接受 actual_title | 调用 `POST /api/sentiment/posts/<id>/accept_actual` |
| `broken` | 标记为垃圾 | 调用 `POST /api/sentiment/posts/<id>/mark_broken`（前端展示时过滤） |

### 11.3 实现要点

- **不阻塞 LLM 分析**：审计抓取失败时 `audit_status='pending'`，fallback 用原 `title`
- **缓存命中不重复审计**：`analyze_sentiment` 1 小时内的缓存命中分支不重跑审计（避免额外开销）
- **批量审计跳过已完成**：已 `verified` / `manual_accepted` / `broken` 的帖子跳过（前端"重跑审计"按钮可强制覆盖：`{reset: true}`）
- **审计与 LLM 解耦**：`POST /api/sentiment/audit/rerun` 可单独跑审计不调 LLM
- **代理处理**：复用 `_no_proxy()` 上下文管理器（`forum_service.py:13`）
- **请求频率**：0.3s 间隔（与现有 `fetch_post_content` 一致）

### 11.4 前端 UI 行为

- 帖子列表每条显示审计 badge：✓ 绿（一致）/ ⚠ 琥珀（不一致，会脉冲动画）/ ? 灰（未审计）/ 🚫 红（已标记垃圾）
- 不一致时，点击 badge 或帖子展开 diff 面板：
  - DB 标题（删除线）
  - 实际标题（红字高亮）
  - 操作按钮：[接受实际标题] [标记为垃圾] [重置审计] [收起]
- 帖子列表上方「只显示不一致」复选框 + 「重跑审计」按钮
- 列表头部 audit-pill：「⚠ N 不一致」（仅当有 mismatch 时显示）

### 11.5 手动验证清单

1. 启动后端：`python -m backend.api.app`
2. 访问 `/sentiment`，添加一只股票并跑一次分析
3. 帖子列表看到审计 badge，部分为 ⚠
4. 制造不一致场景：
   ```sql
   UPDATE forum_posts SET title = '【伪造】测试不一致' WHERE id = (SELECT id FROM forum_posts LIMIT 1);
   ```
5. 点「重跑审计」→ 该帖子变为 ⚠ 状态
6. 点 badge 展开 diff → 点「接受实际标题」→ title 被 actual_title 覆盖，badge 变 ✓
7. 跑分析时 LLM 输入用的是 actual_title（可在日志中验证）

**已知限制**：
- 审计耗时与帖子数线性相关（~0.3s/条），20 条帖子约 6s 额外开销
- `north_net` 在 akshare 1.18.30 下偶发返回空，已 graceful 处理（None → 50 分）
- 50ETF QVIX 在收盘后可能延迟更新（T+1）
- 百分位基于近 1 年历史（≥240 个交易日），新系统前 240 天该字段为 None

**手动验证清单**：
1. 后端 `python -m backend.api.app` 启动后 `POST /api/vix/recompute` 触发重算
2. 1-2 分钟后 `GET /api/vix/recompute_status` 返回 `running: false`
3. `GET /api/vix` 返回当日完整快照
4. `GET /api/vix/history?days=30` 返回历史数组
5. 前端 `/dashboard` VIX 卡片三栏布局正常渲染
6. 前端 `/vix` 详情页 4 个 StatCard + 主趋势图 + 6 格分项 + 阈值表全部正常

## 12. guba 详情页反爬对抗（v2, 2026-06-06）

**问题现象**（2026-06-06 用户报告）：

```
[Thread-279 (_run_all)] INFO  forum_service - 标题审计完成: 74 审计, 0 一致, 0 不一致, 74 抓取失败
[Thread-279 (_run_all)] INFO  sentiment - 审计重跑完成: {'audited': 74, 'matched': 0, 'mismatched': 0, 'fetch_errors': 74}
```

74 条帖子全部 `fetch_errors`，重跑审计功能看似完全失效。

### 12.1 根因分析

排查过程（按时间顺序）：

1. **熔断器未触发** —— `circuit_state['state']` 一直是 `closed`，不是熔断导致
2. **HTTP 状态码正常** —— 直接 `curl` `https://guba.eastmoney.com/news,600584,1721863647.html` 返回 200，不是 4xx/5xx
3. **响应体异常** —— 长度仅 2826 字节，HTML 内容是：
   ```html
   <!DOCTYPE html><html lang="en"><head>...
   <meta name="applicable-device" content="mobile"/>
   <link rel="stylesheet" href="//gbfek.dfcfw.com/deploy/fd_guba_validate/work/assets/validate.css"/>
   <script src="//cfgpassport2.eastmoney.com/captcha/scripts/em_capt.js"></script>
   <script type="module" crossorigin="" src="//gbfek.dfcfw.com/deploy/fd_guba_validate/work/assets/validate.js"/>
   <body><div id="root"></div></body>
   ```
4. **验证壳 vs 正常页** —— 正常详情页应包含 `var post_article = {...}`（21KB+），验证壳没有这个 JSON 变量
5. **关键发现** —— 列表页（`/list,X.html`）**不受影响**（183KB 正常返回），仅详情页（`/news,X,Y.html`）被拦
6. **进一步定位** —— 用 Playwright 真实浏览器打开同一 URL，**能正常加载**（title=周一不-5开我倒立洗头_长电科技(600584)股吧_…），且浏览器 cookie jar 包含：
   - `qgqp_b_id`, `st_nvi`, `nid18`, `gviem`（guba 核心反爬 cookie）
   - `st_si`, `st_pvi`, `st_sp`, `st_inirUrl`, `st_sn`, `st_psi`, `st_asi`（eastmoney st_* 系列）
7. **用 Playwright 拿到的 cookie 直接 `requests.get` 同一 URL** → 返回 21046 字节，**有 post_article JSON** ✓

**结论**：guba 详情页（`/news,X,Y.html`）自 2026-06 起对**未携带 anti-bot cookie 的纯 HTTP 请求**返回 2826 字节的"反爬引导壳"，真正的内容需要浏览器先建立 `qgqp_b_id` / `nid18` / `gviem` 等 cookie 会话。**这跟"滑块验证码"是两回事**——cookie 由 guba 域在浏览器首次访问时通过 JS 颁发，纯 HTTP 客户端永远拿不到。

### 12.2 修复方案

**核心改动**（`backend/services/forum_service.py:26-95`）：

1. **模块级 `requests.Session`** —— `_GUBA_SESSION`，所有 guba 请求复用同一会话（`requests.Session` 自动维护 cookie jar）
2. **Bootstrap cookies 启动注入** —— 进程启动时直接注入从真实浏览器提取的 anti-bot cookies：
   ```python
   _GUBA_BOOTSTRAP_COOKIES = {
       "qgqp_b_id": "3887f38c95c6219c78d2d464d13dc25b",
       "st_nvi": "YdymadBWtzSdSD6mf1GEVb9eb",
       "nid18": "0aef0cce8a96f5f392327a39a2262793",
       "gviem": "I62K01Ig9bRhbCKTIvTSn70c6",
       "st_si": "83268578334050",
       "st_pvi": "06154531581302",
       "st_sp": "2026-06-06 12:59:54",
       "st_inirUrl": "https://guba.eastmoney.com/list,600584.html",
       "st_sn": "1",
       "st_psi": "20260606131646400-117001354293-2377644603",
       "st_asi": "delete",
   }
   _inject_bootstrap_cookies()  # domain=.eastmoney.com
   ```
   这些 cookie 来自真实浏览器会话，**不绑定用户**（guba 域通用反爬标识），跨帖子/跨股票复用验证通过
3. **冷启动兜底** —— `_http_get_with_retry` 检测响应是 2.8KB 引导壳（cookie 失效）时，调用 `_warmup_guba_session()` 重新注入并重试 1 次
   - **v8 2026-06-30 刷屏修复**：warmup 只是重新注入同一组硬编码 cookie，无法真正刷新。旧逻辑每个详情页请求都做 warmup + 打 2 行日志，1000+ 只股票刷屏。改为：一旦判定 `_COOKIE_STALE=True`，后续请求**静默降级**返回引导壳（上层 `fetch_post_full` 转 `fetch_error`，列表页标题仍可用），不再 warmup、不打日志；一次性 error 告警节流到每 5 分钟一次（防多线程竞争重复打）。
4. **编码修正** —— guba 服务端不返回 `charset`，`requests` 会按 ISO-8859-1 兜底导致中文乱码。在 `fetch_post_full` 强制 `r.encoding = "utf-8"`（guba 实际就是 UTF-8）

**辅助改动**（`fetch_post_full`，`forum_service.py:490-580`）：

5. **转发/转载帖处理** —— 列表页给的长格式 `post_id`（17xxxxxxxx）已被 guba 改用短格式（10xxxxxxxx）。`fetch_post_full` 现在请求长 ID 但实际拿回的是**另一篇帖子**的 `post_article`，其中 `post_title="转发"`、`source_post_title=<原帖标题>`。新增转发检测：自动取 `source_post_title` 作为 `actual_title`
6. **"帖子不存在" 软失败** —— guba 对部分长 ID 返回 "很抱歉，您访问的帖子不存在" 占位页。审计时识别这种情况，标 `pending` 而非 `mismatch`（避免用户被假阳性惊扰）

### 12.3 验证结果

修复前 → 修复后（同一组 30 条帖子）：

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| `audited` | 0 (熔断或报错) | 30 |
| `fetch_errors` | 74 / 74 | 0 |
| `matched` | 0 | 0~少数（真实标题一致） |
| `mismatched` | 0 | 多数（guba URL 改短 ID，返回的是不同帖子） |
| `pending` | 74 | 少量（"帖子不存在"占位） |

**fetch_errors 从 74/74 降到 0/30**，审计从"完全不可用"恢复为"能跑通但有少量 guba URL 别名失效"——后者是 guba 反爬升级带来的**功能性退化**（用户实际看到的列表页标题仍是正确的），可通过前端"接受实际标题 / 标记为垃圾"人工通路补齐。

### 12.4 已知遗留问题

- **guba URL 别名失效**（无法在代码层修复）：详情页 URL `/news,X,Y.html` 用列表页的长 ID 拼出来的，但 guba 后端实际只承认短 ID。表现为访问 URL 经常返回**别的帖子**的 `post_article`，导致 `mismatch`。临时缓解：审计逻辑会把"实际标题≠存储标题"的 case 全标 mismatch，前端用户可手动 accept。
- **Bootstrap cookie 过期**：从真实浏览器提取的 cookie 长期可能失效。如果出现"突然 100% fetch_errors"现象，手动 `POST /api/sentiment/circuit_reset` 重置熔断器 + 从浏览器重新提取 cookie 更新 `_GUBA_BOOTSTRAP_COOKIES` 常量。

## 13. 舆情监控网络韧性（v2, 2026-06-04）

**目标**：解决 `guba.eastmoney.com` 在用户环境频繁超时（15s × N 条帖子）拖垮整个舆情分析流的问题。让抓取在网络抖动/不可达时**优雅降级**：
1. **熔断**（Circuit Breaker）：发现 guba 不可达就 short-circuit，省掉 15s×N 的等待
2. **重试**（Retry）：在 connection reset / timeout / 5xx 时指数退避
3. **并发**（Concurrency）：审计时多线程并行抓取
4. **预拉**（Prefetch）：调度时提前拉帖子，避开用户访问高峰
5. **解耦**（Fetch-only）：把「爬取」和「分析」拆开

### 13.1 触发场景

- guba.eastmoney.com 在用户网络下经常 `connect timeout=15`（每次 15s 等待 + 20 条帖子 = 5 分钟）
- 瞬时 `ConnectionResetError` / `ChunkedEncodingError` 偶发
- 5xx 服务端错误（guba 偶发 502/503）

### 13.2 熔断器（`GubaCircuitBreaker`，`backend/services/forum_service.py:42-126`）

**状态机**：`closed → open → half_open → closed`

| 状态 | 行为 |
|------|------|
| `closed` | 正常放行请求 |
| `open` | fast-fail：直接 raise `CircuitOpenError`（< 1ms），不发起 HTTP |
| `half_open` | 允许 1 个探测请求；成功 → closed，失败 → 重新 open |

**触发条件**（`closed` → `open`）：连续 `GUBA_CB_FAILURE_THRESHOLD`（默认 3）次失败。
**冷却**：`GUBA_CB_COOLDOWN_SECONDS`（默认 60s）后允许探测。
**失败判定**：仅 `requests.RequestException`（ConnectionError / Timeout / ChunkedEncodingError）计为失败；4xx（除 429）不计（避免反爬误判）。

```python
_GUBA_CIRCUIT = GubaCircuitBreaker()  # 模块级单例

_GUBA_CIRCUIT.call(_do)  # 所有 guba 请求都走这里
```

### 13.3 重试（`_http_get_with_retry`，`forum_service.py:128-178`）

封装 `_GUBA_CIRCUIT.call` + 指数退避：

```python
def _http_get_with_retry(url, headers, timeout, retries=None, backoff=None):
    # 默认 retries=1, backoff=0.5
    # 网络错误 / 5xx / 429 → 指数退避（0.5s → 1.0s → 2.0s）
    # CircuitOpenError → 不重试，直接抛
```

**调用方**：`fetch_post_list`（15s timeout）、`fetch_post_full`（10s timeout）全部走此函数。

### 13.4 并发审计（`audit_posts`，`forum_service.py:552-694`）

v1 串行 + `time.sleep(0.3)` → v2 `ThreadPoolExecutor(max_workers=4)`：

- 20 条帖子，串行 ~30s → 并发 ~7.5s（4× 加速）
- 熔断短路：`CircuitOpenError` 立即取消剩余 future
- 失败隔离：单条帖子异常不影响其他帖子

```python
def audit_posts(posts, forum_type="eastmoney", max_workers=None):
    # 默认 max_workers=GUBA_AUDIT_MAX_WORKERS (4)
    # 跳过已 verified / manual_accepted / broken
    # 熔断中 → summary 标 circuit_open=True, skipped 全部
```

### 13.5 调度预拉（`forum_prefetch_task`，`backend/services/scheduler.py:160-218`）

每 `GUBA_PREFETCH_INTERVAL_HOURS`（默认 2h）跑一次，启动时立即跑：

```python
for cfg in get_sentiment_configs():
    if _GUBA_CIRCUIT.state["state"] == "open":
        break  # 熔断中跳过本轮
    posts, _ = fetch_forum_posts(
        cfg["stock_code"], cfg["forum_type"],
        days=3, fetch_content=False, audit=False,  # 关键：跳过内容和审计
    )
```

**节省 80% 网络**：只走 `fetch_post_list` 一两个 HTTP 请求，不抓正文、不审计。

### 13.6 仅拉取接口（`POST /api/sentiment/fetch`，`backend/api/routes/sentiment.py:404-449`）

把「爬取」和「分析」解耦，方便前端 warm up 缓存 / 调试：

```json
// Request
{ "stock_code": "600519", "days": 3, "fetch_content": true, "audit": true }

// 200 Response
{
  "code": "600519",
  "posts_count": 20,
  "circuit_state": { "state": "closed", "failures": 0, "cooldown_remaining": 0 },
  "audit": { "audited": 20, "matched": 17, "mismatched": 3, "fetch_errors": 0, "skipped": 0 },
  "posts": [ /* 前 50 条带审计字段的帖子 */ ]
}

// 503 Response (熔断)
{
  "error": "guba.eastmoney.com 暂时不可达，已熔断",
  "circuit_state": { "state": "open", "failures": 3, "cooldown_remaining": 47 },
  "retry_after_seconds": 47
}
```

**配套端点**：
- `GET /api/sentiment/circuit_status`：查询当前熔断器状态
- `POST /api/sentiment/circuit_reset`：手动重置熔断器（运维 / 调试）

### 13.7 analyze_sentiment 降级（`backend/services/sentiment_service.py:236-265`）

`analyze_sentiment` 在抓取阶段捕获 `CircuitOpenError` / `RequestException`，**静默降级**使用 DB 缓存：

```python
try:
    posts, audit_summary = fetch_forum_posts(...)
except (CircuitOpenError, requests.RequestException) as e:
    logger.warning(f"抓取帖子失败: {e}，降级使用 DB 缓存")
    posts = get_recent_posts(code, forum_type, limit=30)
    audit_summary = {"circuit_open": True, ...}
```

**用户视角**：分析不中断（用旧帖子），只是审计摘要带 `circuit_open: true` 提示。

### 13.8 前端 UI 行为（`frontend/src/views/SentimentView.vue`）

- **熔断器徽章**（PageHeader）：检测到 `open` → 红色脉冲徽章「guba 熔断 47s」；`half_open` / 有失败次数 → 琥珀色徽章；点击徽章 → 调 `circuit_reset` 重置
- **「仅拉取」按钮**（每只股票详情操作栏）：紧邻「立即分析」，调 `fetchForumPostsOnly`，成功 toast「已拉取 N 条，M 条标题不一致」，503 时 warning toast 显示剩余冷却时间

### 13.9 配置项（`backend/config.py`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `GUBA_CB_FAILURE_THRESHOLD` | 3 | 连续 N 次失败后熔断 |
| `GUBA_CB_COOLDOWN_SECONDS` | 60 | 熔断冷却时间（秒） |
| `GUBA_HTTP_RETRIES` | 1 | HTTP 重试次数（不含首次） |
| `GUBA_HTTP_RETRY_BACKOFF` | 0.5 | 重试退避基数（秒，指数） |
| `GUBA_AUDIT_MAX_WORKERS` | 4 | 审计并发线程数 |
| `GUBA_PREFETCH_INTERVAL_HOURS` | 2 | 调度预拉间隔（小时） |

### 13.10 实现状态

| 模块 | 文件 | 状态 |
|------|------|------|
| 熔断器 | `backend/services/forum_service.py` | ✅ |
| 重试 | `backend/services/forum_service.py` | ✅ |
| 并发审计 | `backend/services/forum_service.py` | ✅ |
| 调度预拉 | `backend/services/scheduler.py` | ✅ |
| 仅拉取接口 | `backend/api/routes/sentiment.py` | ✅ |
| 熔断状态接口 | `backend/api/routes/sentiment.py` | ✅ |
| analyze 降级 | `backend/services/sentiment_service.py` | ✅ |
| 配置项 | `backend/config.py` | ✅ |
| API 客户端 | `frontend/src/api/index.js` | ✅ |
| 熔断徽章 | `SentimentView.vue` PageHeader | ✅ |
| 「仅拉取」按钮 | `SentimentView.vue` 操作栏 | ✅ |
| 文档 | `docs/SPEC.md` §13 | ✅ |

### 13.11 手动验证清单

1. **熔断触发**：
   ```bash
   # 断网 / 改 hosts 让 guba 不可达
   # 触发 3 次分析 → 第三次后熔断打开
   curl -X POST http://localhost:5000/api/sentiment/fetch \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"stock_code": "000333"}'
   # 第一次: 15s 超时（fetch_error）
   # 第二次: 15s 超时
   # 第三次: 立即返回 503（circuit_open）
   ```
2. **熔断状态查询**：
   ```bash
   curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/circuit_status
   # {"state": "open", "failures": 3, "cooldown_remaining": 47}
   ```
3. **熔断恢复**：
   ```bash
   # 等 60s
   curl -X POST http://localhost:5000/api/sentiment/circuit_reset
   # 后续请求 → 探测 → closed
   ```
4. **并发加速**：
   - 制造 20 条 pending 帖子
   - 触发分析 → 审计日志显示耗时从 ~6s 降到 ~1.5s
5. **调度预拉**：
   ```bash
   python -c "from backend.services.scheduler import forum_prefetch_task; forum_prefetch_task()"
   # 日志: "论坛预拉开始: 3 只股票" → "ok=3 fail=0"
   # DB: forum_posts 新增 ~20 条
   ```
6. **降级验证**：
   - 熔断状态下调 `/api/sentiment/analyze`
   - 返回结果仍含 `sentiment` / `score`（基于旧 DB 帖子）
   - `audit.circuit_open = true`

---

### 13.12 站内查看缓存帖子（v3, 2026-06-04）

**问题**：v2 的熔断器解决了"失败变快"，但用户实际看到的是——`SentimentView` 帖子列表里的 `<a target="_blank">` 全都跳向 `https://guba.eastmoney.com/...`，guba 不可达的环境下这些链接全是死的。"帖子也访问不了"。

**修复**：让点击帖子在站内弹窗显示 DB 缓存内容，不再依赖 guba 可达。

**后端**：
- `backend/core/database.py`：
  - `get_post_by_id(post_id)` 补 `content` 字段（之前没返回，仅返回 metadata + audit）
  - 新增 `update_post_content(post_id, content)`
- `backend/api/routes/sentiment.py`：
  - `GET /api/sentiment/posts/<post_id>` — 返回单条帖子全量缓存（id/title/actual_title/audit_status/content/url/author/post_time）
  - `POST /api/sentiment/posts/<post_id>/refresh_content` — 手动重抓正文 + 同步审计字段；熔断打开时 503 + `circuit_state`

**前端**：
- `frontend/src/api/index.js` 新增 `getSentimentPost` / `refreshSentimentPostContent`
- `SentimentView.vue`：
  - 帖子标题 `<a href=p.url target=_blank>` 改为 `<a @click.prevent="openPostDialog(p, item)">`
  - 新增 `el-dialog` (`post-dialog`)：标题 / 审计 badge / 作者 / 发布时间 / 标题 diff / 正文 (`white-space: pre-wrap`) / `[重新抓取正文] [在 guba 打开]`
  - 无正文时显示 `post-dialog__empty` 提示，引导点「重新抓取」

**端点表**（§5 同步）：

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/sentiment/posts/<id>` | 单条帖子缓存（v3, 含 content） |
| POST | `/api/sentiment/posts/<id>/refresh_content` | 手动重抓正文（走熔断/重试） |

**实现状态**：

| 模块 | 文件 | 状态 |
|------|------|------|
| `get_post_by_id` 加 content | `backend/core/database.py:885` | ✅ |
| `update_post_content` | `backend/core/database.py` | ✅ |
| `GET /posts/<id>` | `backend/api/routes/sentiment.py` | ✅ |
| `POST /posts/<id>/refresh_content` | `backend/api/routes/sentiment.py` | ✅ |
| 前端 API | `frontend/src/api/index.js` | ✅ |
| `el-dialog` + 处理函数 | `SentimentView.vue` | ✅ |

**手动验证**：
```bash
# 1. 直接看缓存（200，含 content）
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/posts/11071
# {"id":11071,"content":"...","author":"...",...}

# 2. 重抓（熔断 open 时返回 503）
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/sentiment/posts/11071/refresh_content
# 503: {"circuit_state":{"state":"open",...},"error":"guba 不可达，已熔断"}
```

## 14. 舆情监控 v3 算法升级（2026-06-06）

**目标**：在保留 v1/v2 已有能力（标题审计、熔断降级）的基础上，把舆情模块从"LLM 算 score 的黑盒"升级成"LLM 只打标 + Python 算 score + 时序因子 + 极端情绪信号 + 热门股池"的完整量化因子系统。

### 14.1 设计动机

v2 的核心问题：
1. **LLM 心算 13,707 字**：让模型算 `bullish/(bullish+bearish)×100`，MiniMax-M3 输出 13K 字 thinking 链，110s/只
2. **错误信息撒谎**：`/api/sentiment/analyze` 失败时一律返回 500 + "API Key 或网络"，与真实原因（熔断/无帖子）不符
3. **无时序视角**：每天的 score 独立保存，捕捉不到"连续 3 天恐慌爆发"这种**最重要的信号**

v3 的解法：
- **math 外移**：LLM 只输出 `[{id, label}]` 数组，score / sentiment 全部 Python 算
- **精细化错误**：5 种失败原因 → 不同 HTTP 状态码（503 vs 500）+ 准确文案
- **时序聚合**：EMA3/5、panic 2σ、euphoria 2σ、momentum cross
- **极端情绪看板**：panic/euphoria 信号经 `get_latest_signals` 暴露到前端「今日极端情绪」面板
- **热门股池**：每日 16:05 自动从东财拉成交额 top 100 写入 sentiment_top_picks

### 14.2 4 分类标签体系

```
1  (看多):  明确看多 / 持有盈利者的亢奋 / 喊"加仓" / 看好后市
0  (中性):  客观陈述 / 询问交流 / 无明显情绪偏向
-1 (看空):  割肉 / 绝望 / 极度恐慌 / 骂主力 / 持续看跌
99 (噪声):  广告 / 推广 / 抽奖 / 无意义玩梗 / 与该股无关的跨板块水帖
```

**与 v2 的区别**：v2 是 3 分类（看多/看空/中性），LLM 经常被广告帖逼着硬选 0；v3 显式给 99 出口，LLM 不必为垃圾帖"猜情绪"。

### 14.3 提示词工程（v3）

#### 14.3.1 反讽识别规则
A 股特有难点：股吧大量反话正说、正话反说。v3 在 prompt 里硬编码 4 条反讽识别规则：

```
1. 股票大跌或遭遇利空时，"感谢主力送温暖"、"再来三个跌停老子刚好补仓"、
   "主力全家身体健康"、"感恩主力" 等是极度绝望的反讽 → -1
2. 套牢盘骂主力、骂管理层、诅咒式发言 → -1
3. 问句（如"明天开盘怎么看？"、"周一怎么办？"）若无明确倾向 → 0
4. 严格区分"反讽"与"真心夸奖"：结合股票近期走势判断
```

#### 14.3.2 5-shot 案例
```
[1] "明天涨5个点" → 1
[2] "今天又跌了，主力真 tm 恶心" → -1
[3] "感谢主力送温暖，让我的成本又降低了" → -1（反讽）
[4] "明天开盘怎么看？有没有大哥说说" → 0
[5] "加微信送牛股，888 立即领取" → 99
```

**为什么放案例不放更多规则**：规则越多 LLM 越糊涂；5 个典型样本能稳定锚定 4 分类边界。

#### 14.3.3 LLM 配置（v3 性能调优）

| 参数 | v2 | v3 | 收益 |
|------|-----|-----|------|
| max_tokens | 16,384 | 512 → **1024**（v8 2026-06-30） | LLM 不再"够用就行"地灌满；512 在 30+ 条帖子时被 minimax 换行/markdown 输出截断，丢尾 `]` → 解析失败 78% |
| streaming | True | False | 批量场景关流式，省网络往返 |
| temperature | 0.3 | 0.1 | 标签更稳定 |
| thinking | 默认开 | **关（extra_body={"thinking":{"type":"disabled"}}，v4 2026-06-08 改用 langchain 原生字段）** | 单只 110s → **2.2s** |
| 解析容错 | 30+ 行正则 | 15 行 JSON 解析 | 代码 -50% |
| 截断恢复 | 无 | **v8：无闭合 `]` 时找最后一个完整 `}` 截断补 `]` 重试** | max_tokens 仍偶发截断时不再整只失败 |
| 截断自适应重试 | 无 | **v8：检测到输出截断时按 max_tokens 2x/4x 重试（上限 4096），拿回完整标签集；到上限仍截断则交由解析器截断恢复兜底** | 超活跃股（100+ 帖）不丢尾部标签、不致得分偏倚 |

**实测收益**：单只股票分析从 110s/13,707 字 → 预计 10-15s/~1KB；14 只 × 5 workers 批量从 ~8.5min → ~1min。

### 14.4 评分算法（math 外移）

**核心原则**：LLM 100% 决策 → 数学 100% 由 Python 算。

```python
def _aggregate_labels(labels: list[int]) -> dict:
    bullish  = count(labels == 1)
    bearish  = count(labels == -1)
    neutral  = count(labels == 0)
    noise    = count(labels == 99)
    valid    = bullish + bearish       # 中性不算分母
    score    = round(bullish / valid * 100, 1) if valid else 50.0
    sentiment = "乐观" if score >= 60 else "悲观" if score <= 40 else "中性"
    return {bullish, bearish, neutral, noise, score, sentiment, ...}
```

**为什么这样分母**：
- 噪声（99）剔除：不污染情绪
- 中性（0）不计入分母：A 股中性帖大多是"看热闹"或"问问题"，不应稀释多空信号
- 仅 bullish / bearish 算比：直接反映多空力量对比

### 14.5 时序因子（EMA / 2σ / 动量）

#### 14.5.1 EMA（指数移动平均）

```
ema(period=N) = alpha * today + (1 - alpha) * ema_yesterday
alpha = 2 / (N + 1)
```

存 `ema3`（短周期，敏感）/ `ema5`（长周期，平滑），用于：
- **Momentum cross**：EMA3 上穿 EMA5 → 多头动量确认

#### 14.5.2 Panic 2σ 检测

```
今日 bearish_n > 30日 bearish_n 均值 + 2 × 30日 std  → panic_signal=1
```

**直觉**：当"看空"帖子的绝对量突破 30 日正常范围 2σ 以上时，**散户已极度恐慌**，往往是底部信号（A 股反向指标）。

#### 14.5.3 Euphoria 2σ 检测

```
今日 bullish_n > 30日 bullish_n 均值 + 2 × 30日 std  → euphoria_signal=1
```

**直觉**：当"看多"帖子暴增突破 2σ 时，**散户已极度狂热**，往往是顶部信号。

#### 14.5.4 公式备注

- **30 日窗口**：覆盖一个完整情绪周期（散户情绪 3-4 周一个轮回）
- **总体标准差（pstdev）**：而非样本标准差，小样本更敏感
- **数据不足保护**：len(history) < 2 时 std=None → 不触发信号

### 14.6 错误响应精细化

| 失败原因 | HTTP | 文案 | 客户端处理 |
|---------|------|------|----------|
| `circuit_open` | 503 | "guba 暂时不可达（熔断中），且无本地缓存" | 显示「熔断中」+ 倒计时 |
| `network_error` | 503 | "网络异常且无缓存: ..." | 重试 |
| `no_posts` | 503 | "帖子全部被过滤规则剔除" | 检查数据源 |
| `no_llm` | 503 | "未配置 LLM API Key" | 提示配 Key |
| `parse_error` | 500 | "LLM 返回解析失败: ..." | 重试或换模型 |
| `internal` | 500 | "分析过程异常: ..." | 看日志 |

**关键修复**：v2 的 `circuit_open` 被错报成 500 + "API Key"，让用户误以为密钥坏了；v3 直接 503 + 真实原因。

### 14.7 数据流（v3 全链路）

```
每日 16:00  scheduler
    │
    ▼
batch_analyze(codes)
    │
    ▼
[每只] analyze_sentiment(code)
    ├─ fetch_forum_posts (guba + 熔断器)
    ├─ _build_posts_text (max 1800 字, 审计过的标题)
    ├─ LLM (json_object 模式, [{id, label}])
    ├─ _parse_labels_response (容错解析)
    ├─ _aggregate_labels (Python 算 score)
    ├─ _compute_indicators (EMA / panic / euphoria)
    ├─ 写 sentiment_scores (含 bullish_n 等 4 分类 + signals_json)
    ├─ 写 sentiment_post_labels (每条帖子一条记录)
    └─ 写 sentiment_indicators (时序因子)

每日 16:05  scheduler
    └─ daily_top_picks_task → 拉东财 top 100 → sentiment_top_picks

每日 16:35  scheduler
    └─ daily_indicators_recompute_task → 兜底重算（应对部分股票当天因熔断没跑成功）

GET /api/sentiment/latest
    └─ 拼装：sentiment_scores + sentiment_indicators + forum_posts
```

#### 14.7.1 批量死锁防御（v5, 2026-06-08）

**问题背景**：手动触发「我的关注」批量分析（15 只）时，单只股票在以下环节可能挂死：
- guba 抓取（15s timeout × N 个帖子 × retry）→ 最坏 60-90s
- LLM 推理（MiniMax-M3 默认 60s timeout，且服务端偶发响应慢）
- 网络堵塞或 API 限流

由于 `ThreadPoolExecutor(max_workers=5)` 只能并发 5 只，剩下 10 只排队等待。
若先头几只任意一只挂死（60s+），它会**占住 worker 不放**，后续 14 只全部被卡住。
12/15 这种进度值就是「3 只成功、4 只失败、1 只挂死、剩下 7 只在等空 worker」的快照。

**修复方案（三层防御）**：

1. **后端 per-future deadline**：
   - `SENTIMENT_BATCH_PER_STOCK_TIMEOUT` 默认 90s（环境变量可调）
   - 循环中用 `concurrent.futures.wait(timeout=…)` + `FIRST_COMPLETED` 轮询 in-flight future
   - 单只超过 deadline 仍 done=False → 强制标记 failed，UI 立刻推进
   - 整体批次上限 `SENTIMENT_BATCH_TOTAL_TIMEOUT` 默认 600s（10 分钟）
   - 超出后所有剩余 in-flight 一律 failed，避免长时间挂后台

2. **LLM timeout 缩短**：
   - `ChatOpenAI(timeout=60)` → `timeout=30`（`SENTIMENT_LLM_TIMEOUT` 可调）
   - thinking 模式关闭后单次标签任务正常 5-10s；30s 仍未响应就是 LLM 服务端异常，应主动放弃

3. **前端 stuck 检测**：
   - 轮询时记录 `current` 上次变化时间
   - 超过 60s current 没变 → 在进度条显示 `⚠️ 卡住中` 徽章 + 弹一次 ElMessage 警告
   - 提示「后端将自动跳过」，与后端 per-stock deadline 互为冗余

**结果**：即使 300308 中际旭创这种股票 LLM 一直挂死，剩余 14 只在 90s 后继续推进，UI 不会卡在 12/15。

### 14.8 数据库 schema 变更

```sql
-- sentiment_scores 加 5 列
ALTER TABLE sentiment_scores ADD COLUMN bullish_n INTEGER DEFAULT 0;
ALTER TABLE sentiment_scores ADD COLUMN bearish_n INTEGER DEFAULT 0;
ALTER TABLE sentiment_scores ADD COLUMN neutral_n INTEGER DEFAULT 0;
ALTER TABLE sentiment_scores ADD COLUMN noise_n INTEGER DEFAULT 0;
ALTER TABLE sentiment_scores ADD COLUMN signals_json TEXT;

-- 帖子级标签（v3 新增）
CREATE TABLE sentiment_post_labels (
  id, stock_code, post_id, forum_type, date,
  label INTEGER,  -- 1/0/-1/99
  model TEXT, raw_response TEXT,
  UNIQUE(stock_code, post_id, date)
);

-- 热门股池（v3 新增）
CREATE TABLE sentiment_top_picks (
  id, stock_code, stock_name, rank, amount,
  source TEXT DEFAULT 'volume_top100',
  auto_added INTEGER DEFAULT 0,
  snapshot_date TEXT,
  UNIQUE(stock_code, snapshot_date)
);

-- 时序因子（v3 新增）
CREATE TABLE sentiment_indicators (
  id, stock_code, date,
  score REAL, ema3 REAL, ema5 REAL,
  bullish_ma30 REAL, bullish_std30 REAL,
  bearish_ma30 REAL, bearish_std30 REAL,
  panic_signal INTEGER, euphoria_signal INTEGER, momentum_cross INTEGER,
  UNIQUE(stock_code, date)
);
```

### 14.10 热门股自动发现

**v3 新增能力**：自动追踪"全市场成交额 top 100"，让用户看到每天资金扎堆在哪里。

#### 数据源
- `akshare.stock_zh_a_spot_em()`：东方财富全市场实时行情
- 排序字段：成交额（amount）
- 取前 N（默认 100，可选 50/100/200/500）

#### 调度
- 每日 16:05 跑一次（早于 VIX 16:30，避开数据源竞争）
- API：`GET /api/sentiment/top_picks` / `POST /api/sentiment/top_picks/refresh`
- 可选 `auto_add=true`：自动把新出现的 top 100 加入 sentiment_config（默认 false，避免噪音）

#### 与 sentiment_config 关系
- sentiment_config：用户**主动选**的股
- sentiment_top_picks：**自动发现**的热门股
- 前端在 top_picks 列表里标注 `is_monitored`（是否已在 config 中），用户可一键「添加监控」

### 14.11 实现状态（v3, 2026-06-06）

| 模块 | 文件 | 状态 |
|------|------|------|
| 4 分类 prompt + 反讽规则 + 5-shot | `backend/services/sentiment_service.py:73-99` | ✅ |
| LLM 性能配置（max_tokens=1024, streaming=False, **extra_body 关 thinking**） | `sentiment_service.py:107-145` | ✅ |
| `_aggregate_labels` Python 聚合 | `sentiment_service.py:227-252` | ✅ |
| `_compute_indicators` 时序因子 | `sentiment_service.py:255-294` | ✅ |
| `_parse_labels_response` 新解析器（含 v8 截断恢复） | `sentiment_service.py` `_parse_labels_response` / `_extract_label_map` | ✅ |
| 单公司结构化日志（拉取/LLM 输入/LLM 输出/结果分段 pretty-print） | `sentiment_service.py` `_log_section` | ✅ |
| 写 sentiment_post_labels / sentiment_indicators | `sentiment_service.py:531-572` | ✅ |
| 错误响应精细化（503 vs 500 + reason） | `backend/api/routes/sentiment.py:135-179` | ✅ |
| 新表 schema（含 4 张表迁移） | `backend/core/database.py:149-225` | ✅ |
| `sentiment_indicators_service.py` 全市场重算 | `backend/services/sentiment_indicators_service.py` | ✅ |
| `top_picks_service.py` 热门股池 | `backend/services/top_picks_service.py` | ✅ |
| Scheduler hooks（16:05 / 16:35） | `backend/services/scheduler.py` | ✅ |
| 前端：极端情绪徽章 + 看板 + 热门股面板 | `frontend/src/views/SentimentView.vue` | ✅ |
| 前端 API | `frontend/src/api/index.js:166-177` | ✅ |

**未做**（明确划出范围）：
- 评估集 / A/B 测试（待数据量积累后另开 PR）
- VIX + 舆情合成指标（与 §11 VIX 联动）
- 实时刷新（当前 16:35 调度 + 手动刷新）

### 14.12 手动验证清单

```bash
# 1. 看 v3 算法跑出来的 score 分布
sqlite3 stocks.db "SELECT stock_code, date, score, bullish_n, bearish_n, neutral_n, noise_n, signals_json FROM sentiment_scores ORDER BY date DESC LIMIT 5;"

# 2. 看今日触发了哪些极端情绪
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/extreme_signals
# 预期：今天有 panic/euphoria 的股票列表

# 3. 看热门股池
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/top_picks
# 预期：东财 top 100（按成交额降序）

# 4. 手动重算 indicators
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/indicators/recompute

# 5. 看时序趋势图数据
curl -H "Authorization: Bearer $TOKEN" "http://localhost:5000/api/sentiment/indicators?code=000001&days=30"
```

**前端表现**：在舆情列表展开某只股票 → 点任意帖子标题 → 弹窗显示标题/作者/时间/正文。即使 guba 完全宕机，用户也能看完整条缓存帖子。无正文时点「重新抓取」一键再试。

---

## 15. 全市场舆情观测台（v4, 2026-06-06）

### 15.1 设计动机

当前 `SentimentView` 只看用户自己加的 watchlist + 极端信号 + top 100 成交额热门股，没有「全市场情绪」视角。用户每次开盘前/收盘后想看「今天全市场怎么看」时，必须 N 个股票一个个翻，**信息没有收敛**。

把 **沪深 300、上证 50、中证 1000、中证 2000、创业板、科创 50** 共 6 个指数（约 3700 只去重股票）的舆情分析**每天定时全量跑一遍**，存到 DB 形成时序数据。配合「市场情绪仪表盘」，让用户一眼看到今天全市场在涨情绪还是跌情绪、哪些指数/板块在恐慌、哪些在狂热。

### 15.2 6 指数 schema（指数表 + seed 数据）

`backend/services/universe_service.py` 的 `SEED_INDICES`：

| code | name | akshare_symbol | akshare_method | akshare_filter | priority |
|------|------|----------------|----------------|----------------|----------|
| csi300 | 沪深300 | 000300 | csindex | — | 1 |
| sse50 | 上证50 | 000016 | csindex | — | 2 |
| star50 | 科创50 | 000688 | csindex | — | 3 |
| csi1000 | 中证1000 | 000852 | csindex | — | 4 |
| chinext | 创业板 | NULL | spot_em_filter | `30` (code 前缀) | 5 |
| csi2000 | 中证2000 | 932004 | csindex | — | 6 |

`akshare_method` 三种：
- `csindex` — 调 `ak.index_stock_cons_weight_csindex(symbol=...)`，能拿到 5 个中证系指数
- `spot_em_filter` — 调 `ak.stock_zh_a_spot_em()`，按 code 前缀过滤（创业板 30/301、科创 688）；当前仅做兜底，主路径失败时启用
- 内部 3 次重试 + 退避；全部失败时记日志但不让单指数失败阻塞其他指数

模块加载时自动 `seed_indices()`，幂等 UPSERT。

### 15.3 数据采集

三个流程：

1. **成分股刷新**（`refresh_constituents`）
   - 输入：可选 `index_code`，默认全部 enabled
   - 调对应 akshare 接口，提取 (stock_code, stock_name, weight)
   - 写 `sentiment_universe_constituents`（PK: index_code + stock_code + snapshot_date）
   - 当日无 snapshot 时回退到 `MAX(snapshot_date) <= ?`

2. **全量爬取**（`run_universe_crawl`）
   - 输入：可选 `index_code`（None=全市场），`max_workers=8`
   - 步骤：
     1. `_prewarm_guba()` — 触发 guba cookie jar warmup
     2. `get_universe_for_date()` — 取今日去重 universe + 每只股票所属 index_codes
     3. `ThreadPoolExecutor(max_workers=N)` 调 `analyze_sentiment(code)`（复用 §10/§11/§12/§13/§14 全部能力）
     4. 每只完成后按 (index_code, stock_code, date) 拆成 N 行写 `sentiment_universe_scores`
     5. 同步更新 `sentiment_universe_jobs` 状态 (running → completed/partial/failed)

3. **指数级聚合**（`compute_universe_aggregates`）
   - 遍历当日每个 index_code
   - 计算 avg/median/std/bullish_count/bearish_count/panic_count/euphoria_count/distribution_json
   - UPSERT 到 `sentiment_universe_aggregates`（PK: index_code + date）

### 15.4 调度任务

| 任务 ID | cron | 函数 | 说明 |
|---------|------|------|------|
| `universe_constituents_weekly` | 周日 17:00 | `weekly_universe_constituents_task` | 6 指数成分股刷新（指数再平衡是季度级，无需日更） |
| `universe_crawl_daily` | 工作日 18:00 | `daily_universe_crawl_task` | 全市场爬取（避开 16:35 indicators_recompute，给 90min buffer） |
| `universe_aggregate_daily` | 工作日 19:30 | `daily_universe_aggregate_task` | crawl 完 1.5h 后算指数级聚合 |

每个任务都有 `_lock` 保护，避免重叠。手动触发走 `POST /universe/run/<code|all>` 端点。

### 15.5 数据库 schema

5 张新表，全部用 SQLite 语法（与现有 14 张表保持一致），MySQL 8.0+ 等价 DDL 见 `scripts/migrate_universe_to_mysql.sql`。

#### 15.5.1 `sentiment_universe_indices`（指数定义，~10 行）

```sql
CREATE TABLE IF NOT EXISTS sentiment_universe_indices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  akshare_symbol TEXT,
  akshare_method TEXT NOT NULL DEFAULT 'csindex',
  akshare_filter TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL DEFAULT 100,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 15.5.2 `sentiment_universe_constituents`（每日成分股快照，可能 3700 行/天）

```sql
CREATE TABLE IF NOT EXISTS sentiment_universe_constituents (
  index_code TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  weight REAL,
  snapshot_date TEXT NOT NULL,
  PRIMARY KEY (index_code, stock_code, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_unc_code_date
  ON sentiment_universe_constituents(stock_code, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_unc_index_date
  ON sentiment_universe_constituents(index_code, snapshot_date);
```

#### 15.5.3 `sentiment_universe_jobs`（每日任务进度，6 行/天）

```sql
CREATE TABLE IF NOT EXISTS sentiment_universe_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  index_code TEXT NOT NULL,
  scheduled_date TEXT NOT NULL,
  total_stocks INTEGER NOT NULL DEFAULT 0,
  completed_stocks INTEGER NOT NULL DEFAULT 0,
  failed_stocks INTEGER NOT NULL DEFAULT 0,
  skipped_stocks INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(index_code, scheduled_date)
);
CREATE INDEX IF NOT EXISTS idx_uj_date
  ON sentiment_universe_jobs(scheduled_date, status);
```

#### 15.5.4 `sentiment_universe_scores`（每只股票在每个指数下的情绪快照，~3700 行/天）

```sql
CREATE TABLE IF NOT EXISTS sentiment_universe_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  index_code TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  forum_type TEXT NOT NULL DEFAULT 'eastmoney',
  date TEXT NOT NULL,
  score REAL,
  sentiment TEXT,
  bullish_n INTEGER DEFAULT 0,
  bearish_n INTEGER DEFAULT 0,
  neutral_n INTEGER DEFAULT 0,
  noise_n INTEGER DEFAULT 0,
  panic_signal INTEGER DEFAULT 0,
  euphoria_signal INTEGER DEFAULT 0,
  momentum_cross INTEGER DEFAULT 0,
  ema3 REAL,
  ema5 REAL,
  source TEXT NOT NULL DEFAULT 'universe_crawl',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(index_code, stock_code, date)
);
CREATE INDEX IF NOT EXISTS idx_uus_code_date
  ON sentiment_universe_scores(stock_code, date);
CREATE INDEX IF NOT EXISTS idx_uus_index_date
  ON sentiment_universe_scores(index_code, date);
```

**为什么 1 行/(index, stock, date) 而不是合并 `index_codes TEXT[]`**：
- 现有 UNIQUE + INSERT OR REPLACE 模式直接复用
- 跨 index 聚合查询更简单（`WHERE index_code=? AND date=?`）
- 每天多 1500 行表大小可忽略（DB 增量 ~500KB/天）

#### 15.5.5 `sentiment_universe_aggregates`（每日指数级聚合，6 行/天，看板主表）

```sql
CREATE TABLE IF NOT EXISTS sentiment_universe_aggregates (
  index_code TEXT NOT NULL,
  date TEXT NOT NULL,
  total_stocks INTEGER NOT NULL,
  analyzed_stocks INTEGER NOT NULL DEFAULT 0,
  failed_stocks INTEGER DEFAULT 0,
  avg_score REAL,
  median_score REAL,
  std_score REAL,
  bullish_count INTEGER DEFAULT 0,
  neutral_count INTEGER DEFAULT 0,
  bearish_count INTEGER DEFAULT 0,
  panic_count INTEGER DEFAULT 0,
  euphoria_count INTEGER DEFAULT 0,
  momentum_cross_count INTEGER DEFAULT 0,
  avg_ema3 REAL,
  avg_ema5 REAL,
  distribution_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (index_code, date)
);
```

### 15.6 API 端点表

| Method | Path | 用途 | 权限 |
|--------|------|------|------|
| GET | `/api/sentiment/universe/indices` | 列出所有 enabled 指数 | `@login_required` |
| GET | `/api/sentiment/universe/summary?date=` | 6 指数今日汇总（看板主数据） | `@login_required` |
| GET | `/api/sentiment/universe/history/<code>?days=60` | 单指数时序 | `@login_required` |
| GET | `/api/sentiment/universe/constituents/<code>?date=&limit=&offset=` | 某指数成分股当日情绪 | `@login_required` |
| GET | `/api/sentiment/universe/jobs?date=` | 任务进度（前端轮询） | `@login_required` |
| POST | `/api/sentiment/universe/refresh_constituents` | 手动刷成分股（异步） | `@login_required` |
| POST | `/api/sentiment/universe/run/<code\|all>` | 手动爬取（异步） | `@login_required` |

所有写入操作走 `threading.Thread(daemon=True).start()`，立即返回 200。

### 15.7 前端组件

#### 15.7.1 `IndexDashboard.vue`（新增）

6 卡片 grid（`grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))`），每张卡片：
- 顶部：指数名（粗）+ 总股票数（小灰字）
- 中部：`avg_score` 大数字（颜色：`>=60` 绿，`<=40` 红，40-60 灰）+ 与昨日的 `vs_yesterday_score` 箭头
- 底部：3 个小徽章：乐观 N（绿）/ 悲观 N（红）/ 恐慌 N（红 + 强警示，>0 时加红边）

`Props: { date: string }` 默认今天。`Mounted`: `getUniverseSummary(date)`。

#### 15.7.2 `SentimentView.vue` 改造

1. 顶部插入 `<IndexDashboard :date="dashboardDate" />`（在 `</PageHeader>` 后）
2. 「最新情绪」卡片 `#extra` slot 加 `<el-radio-group>` 筛选器：
   - 默认「我的关注」
   - 6 个指数 radio-button
   - 切换时调 `getUniverseConstituents(code, {date, limit, offset})`，结果映射到现有渲染路径

### 15.8 云迁移说明（MySQL 8.0+）

为方便未来迁移到云数据库：

1. **SQL 方言适配**：`backend/core/db_compat.py` 检测 `pymysql` 是否可用，导出 `BACKEND = "mysql"|"sqlite"`，提供 `placeholder()` 和 `upsert_sql()` 两个 helper。**所有新代码（5 张表 + 5 upsert 函数）都走这两个 helper**。未来切 MySQL 只需在 `database.py:get_connection()` 加 DATABASE_URL 检测。
2. **5 张新表的 MySQL 8.0+ 等价 DDL**：`scripts/migrate_universe_to_mysql.sql`（独立文件，一键导入）
3. **数据搬运工具**：`scripts/migrate_universe_data.py`（SQLite → CSV → MySQL `LOAD DATA`）
4. **UPSERT 语法差异**：SQLite 用 `INSERT OR REPLACE INTO`；MySQL 用 `INSERT ... ON DUPLICATE KEY UPDATE`，由 `db_compat.upsert_sql()` 抽象

**注意**：现有 14 张表中也有 `INSERT OR REPLACE`（如 `upsert_top_picks`），本次只对 5 张新表做兼容；老表未来迁 MySQL 时单独处理（不在本任务范围）。

### 15.9 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 6 指数全量每日爬取 | 用户明确要求「每日全量」 |
| 2 | 1 行/(index, stock, date) | UNIQUE 复用、聚合查询简单；多 1500 行/天可忽略 |
| 3 | 成分股每周日 17:00 刷新 | 指数再平衡按季度，daily 太浪费 |
| 4 | crawl 用 8 workers | DeepSeek rate limit 容忍上限；端到端 ~45min |
| 5 | aggregate 19:30 跑 | crawl 1.5h buffer 防超时 |
| 6 | 共用 `GubaCircuitBreaker` | 已有全局单例；不重复造轮子 |
| 7 | `time.sleep(0.5)` 在 submit 之间 | 平滑 QPS 到 ~16/s |
| 8 | DB DDL 用 SQLite 语法 | 与现有 14 张表一致；MySQL 模板单独 sql 文件 |
| 9 | `db_compat.upsert_sql()` 抽象 UPSERT | 未来切 MySQL 只改 1 个函数 |
| 10 | 1h 缓存复用 | `analyze_sentiment` 已有的 1h 缓存减少重跑 |
| 11 | **不改 `analyze_sentiment`** | 现有分析逻辑稳定，只加 1 个 `run_universe_crawl` 调用它 |

### 15.10 实现状态表

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | 5 张表 DDL + db_compat + 1 endpoint + IndexDashboard 占位 | ✅ |
| 2 | 6 指数全接入 + 7 endpoint + SentimentView radio 筛选 + 3 cron + SPEC §15 | ✅ |
| 3 | MySQL 8.0+ 迁移工具（DDL + 数据搬运） | ⏳ |

### 15.11 手动验证清单

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/login -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 1. seed 6 指数
python -c "from backend.services.universe_service import seed_indices; print(seed_indices())"
# 预期：6

# 2. 列指数
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/sentiment/universe/indices
# 预期：6 行

# 3. 拉 csi300 成分股
python -c "from backend.services.universe_service import refresh_constituents; print(refresh_constituents('csi300'))"

# 4. 跑一次 crawl（先用 1 个指数 + 5 workers 验证）
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/sentiment/universe/run/csi300

# 5. 跑聚合（crawl 完后）
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5000/api/sentiment/universe/summary?date=$(date +%F)"

# 6. 看时序
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5000/api/sentiment/universe/history/csi300?days=7"

# 7. 看成分股当日情绪
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5000/api/sentiment/universe/constituents/csi300?date=$(date +%F)&limit=10"
```

**前端表现**：登录 → 打开 /sentiment → 顶部看到 6 张指数卡片（哪怕暂无数据也展示空状态）。「最新情绪」卡片顶部有「我的关注 / 沪深300 / 上证50 / 科创50 / 中证1000 / 创业板 / 中证2000」7 个 radio 按钮。切换到「沪深300」→ 下方「最新情绪」列表变成 csi300 成分股。

### 15.12 关键文件清单

| 状态 | 文件 | 说明 |
|------|------|------|
| 新建 | `backend/core/db_compat.py` | SQL 方言适配（~50 行） |
| 新建 | `backend/services/universe_service.py` | 核心 service（~600 行） |
| 新建 | `frontend/src/api/universe.js` | 7 个 API 包装（~40 行） |
| 新建 | `frontend/src/components/IndexDashboard.vue` | 6 卡片 grid（~180 行） |
| 新建 | `scripts/migrate_universe_to_mysql.sql` | MySQL 8.0+ DDL 模板 |
| 新建 | `scripts/migrate_universe_data.py` | SQLite → MySQL 数据搬运 |
| 修改 | `backend/core/database.py` | +5 CREATE TABLE + 5 upsert + 6 read 函数 |
| 修改 | `backend/services/scheduler.py` | +3 task function + 3 job 注册 |
| 修改 | `backend/api/routes/sentiment.py` | +7 endpoint |
| 修改 | `backend/config.py` | +10 env var |
| 修改 | `frontend/src/views/SentimentView.vue` | 插入 IndexDashboard + radio-group 筛选 |
| 修改 | `frontend/src/api/index.js` | 导出 default api 实例供 universe.js 复用 |
| 修改 | `docs/SPEC.md` | 新增 §15（本节） |

## 16. 任务调度看板（v5, 2026-06-06）

### 16.1 设计动机

**问题**：项目里目前有 10 个 APScheduler 定时任务（5 个核心 cron + 3 个全市场舆情 cron + 2 个 interval），执行时间全部硬编码在 `backend/config.py` 的 env var 里。用户改时间要：
1. SSH 到服务器
2. 改 `.env` 文件
3. 重启 Flask 进程（任务会中断，gunicorn 多 worker 还会出现重复触发）

随项目任务越来越多（这次全市场舆情看板一下加了 3 个 universe_* 任务），「改 env + 重启」的流程成为日常运营瓶颈。

**目标**：做一个**任务调度看板**（前端 `/tasks` 页面），把 10 个任务列成卡片。每张卡片显示：任务名/描述/当前 cron or interval/启停状态/下次执行时间 + 编辑控件（小时/分钟/星期 OR 间隔小时 + 启用开关）。**保存后立即生效**，不重启 Flask，不丢 in-flight 任务。

**用户决策（已采纳）**：
- **颗粒度**：每任务一行卡片（不做"每指数独立配"那种细粒度，先做通用版）
- **生效方式**：保存后立即 reschedule（不依赖重启）
- **云迁移就绪**：新表用 `db_compat.py` 抽象（与 §15 universe 表同套机制）

### 16.2 任务清单（10 个）

| job_id | display_name | trigger_type | 备注 |
|--------|--------------|--------------|------|
| `daily_update` | 每日红利指数扫描 | cron | 工作日 15:30（默认，可改） |
| `daily_sentiment` | 每日舆情批量分析 | cron | 工作日 16:00 |
| `daily_vix` | VIX 恐慌指数 | cron | 工作日 16:30 |
| `daily_top_picks` | 热门股池刷新 | cron | 工作日 16:05 |
| `daily_indicators_recompute` | 时序因子重算 | cron | 工作日 16:35 |
| `zhihu_check` | 知乎大V 监控 | interval | 默认 2h（env: `ZHIHU_CHECK_INTERVAL_HOURS`） |
| `forum_prefetch` | 股吧帖子预拉 | interval | 默认 2h（env: `GUBA_PREFETCH_INTERVAL_HOURS`） |
| `universe_constituents_weekly` | 全市场成分股周更 | cron | 每周日 17:00 |
| `universe_crawl_daily` | 全市场舆情爬取 | cron | 工作日 18:00 |
| `universe_aggregate_daily` | 全市场指数聚合 | cron | 工作日 19:30 |

### 16.3 DB Schema（1 张表）

加在 `backend/core/database.py` 的 `init_db()` 末尾。SQLite 语法；MySQL 8.0+ 等价 DDL 模板并入 `scripts/migrate_universe_to_mysql.sql`。

```sql
CREATE TABLE IF NOT EXISTS scheduler_task_config (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id          TEXT    UNIQUE NOT NULL,
  display_name    TEXT    NOT NULL,
  description     TEXT,
  trigger_type    TEXT    NOT NULL CHECK(trigger_type IN ('cron','interval')),
  -- cron 字段（trigger_type='interval' 时为 NULL）
  hour            INTEGER,                           -- 0-23
  minute          INTEGER,                           -- 0-59
  day_of_week     TEXT,                              -- 'mon-fri', 'sun', 'mon,wed,fri', '*'
  -- interval 字段（trigger_type='cron' 时为 NULL）
  interval_hours  INTEGER,                           -- >=1
  -- 生命周期
  enabled         INTEGER NOT NULL DEFAULT 1,
  next_run_time   TIMESTAMP,
  updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_by      TEXT                               -- 来自 JWT 的 username
);
```

**设计要点**：
- `job_id` 是 PK 之外的 UNIQUE，与 APScheduler 的 `add_job(id=...)` 一一对应
- `trigger_type` 显式标注 cron/interval，UI 据此切控件
- 不存函数引用（`function_name` 仅在 GET 时由后端 join，**不落 DB**）

**5 个 helper**（加在 `database.py`）：
- `get_all_scheduler_configs() -> list[dict]`
- `get_scheduler_config(job_id) -> dict | None`
- `seed_scheduler_config_if_absent(row) -> bool`（INSERT OR IGNORE）
- `update_scheduler_config(job_id, **fields) -> int`
- `update_scheduler_next_run(job_id, next_run_iso) -> None`

### 16.4 启动流程

```
init_scheduler() at app boot:
  1. seed_from_env()   # 把 10 行 INSERT OR IGNORE 写进 DB（已存在跳过）
  2. for row in get_all_scheduler_configs():
       trigger = build_trigger(row)         # CronTrigger | IntervalTrigger
       add_job(func, trigger, id=job_id)
       if not row.enabled: pause()
  3. sched.start()
  4. for row: get_job().next_run_time → 同步到 DB
```

`JOB_REGISTRY` 10 项元数据存在 `backend/services/scheduler_config_service.py`，`env_fields` lambda 把 env var 包成 DB row 字段。`build_trigger()` 根据 `trigger_type` 选 CronTrigger/IntervalTrigger。`forum_prefetch` 启动后立刻跑一次（`next_run_time=now()`），其余（含 `zhihu_check`）走正常调度（v4 2026-06-30：zhihu_check 不再启动即跑，避免反爬 403 刷屏）。

### 16.5 立即生效机制

| 操作 | 后端动作 | 是否需要重启 |
|------|----------|--------------|
| 改 cron 时间（hour/minute/dow） | `update_scheduler_config()` → `sched.reschedule_job(job_id, trigger=new)` | 否 |
| 改 interval_hours | 同上 | 否 |
| 切换 enabled 开→关 | `update_scheduler_config(enabled=False)` + `sched.pause_job()` | 否 |
| 切换 enabled 关→开 | `update_scheduler_config(enabled=True)` + `sched.resume_job()` | 否 |

**APScheduler 行为保证**：
- `reschedule_job` 不打断当前执行中的任务实例，只改下一次触发时间
- `pause_job` / `resume_job` 改的是 live 状态；DB `enabled` 字段同步翻转，UI 永远反映"期望状态"
- 重启 Flask → init 阶段按 `enabled=0` 的 row 自动 pause，保持一致

### 16.6 API 端点表（3 个）

| Method | Path | Body | 响应 |
|--------|------|------|------|
| GET | `/api/scheduler/configs` | — | 10 行 list，注入 `function_name`，兜底 `next_run_time` |
| PATCH | `/api/scheduler/configs/<job_id>` | `{hour?, minute?, day_of_week?, interval_hours?}` | `{ok, job_id, next_run_time}` |
| POST | `/api/scheduler/configs/<job_id>/<action>` | — | `{ok, paused?, next_run_time?}` |

**action** ∈ `{pause, resume}`。

**验证规则**（PATCH 入口）：

| 字段 | 规则 | 错误响应 |
|------|------|----------|
| `hour` | 0 ≤ h ≤ 23 | 400 `hour out of range` |
| `minute` | 0 ≤ m ≤ 59 | 400 `minute out of range` |
| `day_of_week` | 正则 `^(\*|((mon\|tue\|wed\|thu\|fri\|sat\|sun)([,-](mon\|tue\|wed\|thu\|fri\|sat\|sun))*$)` | 400 `invalid day_of_week` |
| `interval_hours` | 1 ≤ h ≤ 168 | 400 `interval_hours out of range (1..168)` |
| `trigger_type` mismatch | 给 cron 任务传 `interval_hours` | 400 `field not applicable to trigger_type=cron` |
| unknown job_id | — | 404 `job_id not found: <id>` |

`updated_by` 从 JWT 中间件注入的 `g.current_user` 取；无登录态时为 None。

### 16.7 前端组件

**`/tasks` 页面结构**：
- `PageHeader`：title "任务调度" + subtitle "可视化配置 10 个 APScheduler 任务的执行时间与启停状态；保存后立即生效" + 刷新按钮
- 3 张 `StatCard`：总任务 / 已启用 / 已暂停
- 响应式 grid（auto-fill, minmax(360px, 1fr)）渲染 `SchedulerTaskCard`

**`SchedulerTaskCard.vue`（~290 行）**：
- Props：`task` 包含 job_id, display_name, description, trigger_type, hour, minute, day_of_week, interval_hours, enabled, next_run_time, function_name
- 内部 `form = cloneForm(task)` 维护本地副本；`dirty` computed 对比 timing 字段
- **cron 分支**：`el-input-number` (hour 0-23) + `el-input-number` (minute 0-59) + `el-select` (day_of_week：每日/工作日/周末/单日/自定义)
- **interval 分支**：`el-input-number` (hours 1-168)
- **el-switch** 切换 enabled：调 pause/resume endpoint，**立即生效**，不需 save
- **保存按钮**：`:disabled="!dirty || saving"`，触发 PATCH endpoint
- 底部「下次执行：M/D HH:MM:SS」时间戳
- Emits：`@saved`（完整 task） / `@toggle`（job_id, enabled, next_run_time）

**`/api/scheduler.js`（~13 行）**：4 个 axios 包装 — `getSchedulerConfigs / updateSchedulerConfig / pauseSchedulerJob / resumeSchedulerJob`。

**LayoutView 新增第 4 个 nav group**：
```js
{
  label: '系统',
  items: [{ path: '/tasks', label: '任务调度', icon: Timer }],
}
```

### 16.8 实现状态表

| 状态 | 模块 | 说明 |
|------|------|------|
| ✅ | DB schema + 5 helpers | 兼容 SQLite；MySQL 模板已加 |
| ✅ | scheduler_config_service.py | JOB_REGISTRY + seed/build/apply/validate |
| ✅ | scheduler.py 改造 | 模块级 `_scheduler` 单例 + DB 启动 + next_run_time 同步 |
| ✅ | 3 个 API endpoint | GET / PATCH / pause / resume |
| ✅ | 前端页面 + 组件 | TaskSchedulerView + SchedulerTaskCard |
| ✅ | 前端路由 + nav | `/tasks` + 系统 group |
| ⏳ Phase 3 | run_now endpoint | 立即手动触发一次（POST /api/scheduler/configs/<id>/run_now） |
| ⏳ Phase 3 | scheduler_task_audit 表 | 改动审计（谁/何时/什么字段） |
| ⏳ Phase 3 | 多 worker 分布式锁 | gunicorn 部署时确保单 scheduler 进程 |

### 16.9 手动验证清单

#### 单元验证（curl）

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r .token)

# 1. 启动后 GET 10 个任务
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/scheduler/configs | jq 'length'
# 预期: 10

# 2. PATCH cron 任务
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"hour":17,"minute":15}' http://localhost:5000/api/scheduler/configs/daily_vix
# 预期: {"job_id":"daily_vix","next_run_time":"...17:15:00","ok":true}

# 3. PATCH interval 任务
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"interval_hours":3}' http://localhost:5000/api/scheduler/configs/zhihu_check
# 预期: next_run_time 反映新间隔

# 4. 验证：hour=25
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"hour":25}' http://localhost:5000/api/scheduler/configs/daily_vix
# 预期: HTTP 400 {"error":"hour out of range","field":"hour"}

# 5. 验证：day_of_week='funday'
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"day_of_week":"funday"}' http://localhost:5000/api/scheduler/configs/daily_vix
# 预期: HTTP 400 {"error":"invalid day_of_week","field":"day_of_week"}

# 6. 验证：404 unknown job_id
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"hour":17}' http://localhost:5000/api/scheduler/configs/does_not_exist
# 预期: HTTP 404 {"error":"job_id not found: does_not_exist"}

# 7. pause / resume
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/scheduler/configs/zhihu_check/pause
# 预期: 200 {"paused":true}; DB enabled=0
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/scheduler/configs/zhihu_check/resume
# 预期: 200 {"paused":false,"next_run_time":...}; DB enabled=1
```

#### 端到端验证（UI）

1. 登录 → 打开 `/tasks` → 看到 3 张 StatCard（10/10/0）+ 10 张任务卡片
2. 修改 `daily_update` 分钟 30→46 → 保存按钮启用 → 点击 → ElMessage.success + 卡片底部时间跳到 15:46
3. 硬刷新页面 → 46 还在（DB 持久化）
4. 切换 `forum_prefetch` switch 关闭 → 立即看到「已暂停」+ DB enabled=0
5. 再切回启用 → 「下次执行」时间恢复 + DB enabled=1
6. `daily_vix` hour 改成 25 → 输入框变红、保存按钮禁用

#### 现有任务不回归

```bash
# 8. 重启 Flask 后, 所有任务按 DB 新配置触发
# 9. scheduler 启动日志: "Scheduler initialized (10 jobs from DB)"
# 10. 关键时点 17:15 daily_vix 应触发（等待验证）
```

### 16.10 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 模块级 `_scheduler` 单例 | scheduler 是进程级单例，不属于 request scope；与现有 `manual_trigger` import 模式一致 |
| 2 | `seed_from_env()` 用 `INSERT OR IGNORE` | 首次启动走 env，之后启动走 DB；已存在行不被覆盖，保护用户改动 |
| 3 | `get_scheduler()` 必须非 None 才返回 | 避免 NPE；route handler 拿到 None 时返 503 |
| 4 | PATCH 同时支持 timing + enabled | 减少 endpoint 数量；UI 用一个 save 按钮完成所有 timing 改动 |
| 5 | pause/resume 走独立 POST + 同步 enabled flag | UI 切换立即生效；DB 与 live 状态保持一致，刷新页面状态不漂移 |
| 6 | 不存 `function_name` 在 DB | 函数引用是 Python 概念，DB 只存配置元数据；GET 时后端 join 出来 |
| 7 | 每卡片独立 save | 10 个独立任务，错误聚合一团糟；per-card 才能给精准 feedback |
| 8 | 新增"系统"nav group | 调度是基础设施，不属于交易/分析/量化；放第 4 组留扩展空间（审计/系统设置） |
| 9 | 不做"创建新任务" / "删除任务" | 用户只要求配置现有任务；v2 再加 |
| 10 | `next_run_time` 兜底用 `trigger.get_next_fire_time(None, now)` | APScheduler 的 `get_job().next_run_time` 在 start() 后立即取可能为 None（lazy 计算）；直接用 trigger 算稳定可靠 |
| 11 | 兜底 datetime 用 `datetime.now(timezone.utc)` | IntervalTrigger 的 start_date 是 timezone-aware；用 naive datetime 会抛 `can't compare offset-naive and offset-aware datetimes` |
| 12 | 不做 history（每次改的时间戳） | DB 写一行只反映**当前**配置；如需审计再加 audit 表（Phase 3） |

### 16.11 关键文件清单

| 状态 | 文件 | 说明 |
|------|------|------|
| 新建 | `backend/services/scheduler_config_service.py` | JOB_REGISTRY + seed/build/apply/validate（~250 行） |
| 新建 | `backend/api/routes/scheduler.py` | 3 个 endpoint + _serialize_row（~90 行） |
| 新建 | `frontend/src/api/scheduler.js` | 4 个 axios 包装（~13 行） |
| 新建 | `frontend/src/components/SchedulerTaskCard.vue` | cron/interval 自适应卡片（~290 行） |
| 新建 | `frontend/src/views/TaskSchedulerView.vue` | `/tasks` 页面（~115 行） |
| 修改 | `backend/core/database.py` | +1 CREATE TABLE + 5 helper 函数 |
| 修改 | `backend/services/scheduler.py` | 改用 DB 启动 + 模块级单例 + next_run_time 同步 |
| 修改 | `backend/api/app.py` | 注册 `scheduler_bp` |
| 修改 | `frontend/src/router/index.js` | 加 `/tasks` 路由 |
| 修改 | `frontend/src/views/LayoutView.vue` | 加 "系统" nav group |
| 修改 | `docs/SPEC.md` | 新增 §16（本节） |

### 16.12 运行历史手风琴（v5.1, 2026-06-07）

**动机**：v5 上线后用户反馈"不知道任务今天是否跑过 / 成功没"——光看「下次执行」反映的是未来，无法回答"上次跑成没"的问题。本节加一个手风琴下拉，每张卡片可展开看最近 10 条触发历史。

#### 16.12.1 新表 `scheduler_task_run`

```sql
CREATE TABLE IF NOT EXISTS scheduler_task_run (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        TEXT    NOT NULL,
  started_at    TIMESTAMP NOT NULL,
  finished_at   TIMESTAMP,
  status        TEXT    NOT NULL CHECK(status IN ('running','success','failed','skipped')),
  message       TEXT,
  duration_ms   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_run_job_started
  ON scheduler_task_run(job_id, started_at DESC);
```

**4 个 helper**（加在 `database.py`）：
- `record_run_start(job_id, started_iso) -> int` — 插入一条 status='running' 的行，返回 run_id
- `record_run_finish(run_id, finished_iso, status, message) -> int` — 更新 finished_at / status / message，duration_ms 用 `julianday` 差 × 86400000 算 ms
- `get_recent_runs(job_id, limit=20) -> list[dict]` — 按 started_at DESC 取最近 N 条
- `get_latest_run(job_id) -> dict | None` — 取最近一条（无论 status）

#### 16.12.2 追踪装饰器 `@track_run(job_id)`

加在 `backend/services/scheduler.py`，10 个 task 函数全部加上：

```python
def track_run(job_id: str):
    """装饰器：记录每次任务触发的 start/finish/success/failed/skipped 到 DB。"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = datetime.now().isoformat(timespec="seconds")
            run_id = record_run_start(job_id, started)
            try:
                result = func(*args, **kwargs)
                status = "skipped" if result == "skipped" else "success"
                record_run_finish(run_id, finished, status, None)
                return result
            except Exception as e:
                record_run_finish(run_id, finished, "failed", str(e)[:500])
                raise
        return wrapper
    return decorator
```

**status 分类规则**：
- 抛异常 → `failed`，message = `str(e)[:500]`
- 函数返回 `'skipped'` → `skipped`（lock 冲突早退场景）
- 其他返回值（`None` / `'success'`） → `success`

10 个 task 函数里，6 个有 lock 冲突早退分支（`daily_update / zhihu_check / forum_prefetch / universe_constituents_weekly / universe_crawl_daily / universe_aggregate_daily`），它们的早退分支 `return` 改为 `return "skipped"`。`daily_sentiment_task` / `daily_vix_task` / `daily_top_picks_task` / `daily_indicators_recompute_task` 无 skipped 分支，正常返回 None → success。

#### 16.12.3 API 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/scheduler/configs/<job_id>/runs?limit=20` | 返回最近 N 条（1 ≤ N ≤ 100） |

**响应**：`list[{id, job_id, started_at, finished_at, status, message, duration_ms}]`，按 started_at DESC 排序。

**错误**：
- unknown job_id → 404 `{"error":"job_id not found: <id>"}`
- limit 越界 / 非数字 → 取默认 20

#### 16.12.4 前端手风琴（SchedulerTaskCard.vue）

卡片底部新增"运行历史"行：
- 默认折叠；点击展开 / 收起
- 右侧显示"最近：成功 · 6/7 22:25:42"摘要（无记录时显示"无记录"灰字）
- 展开后渲染最近 10 条运行记录，每条：
  - 左侧 3px 彩色边（绿=success / 红=failed / 橙=running / 灰=skipped）
  - status 标签（`<el-tag type="success/danger/warning/info">`）
  - 启动时间（`M/D HH:MM:SS`）
  - 右侧耗时（`2.0s` / `1.2m` / `850ms`）
  - 失败时下方显示 message（截断 120 字 + tooltip）

**懒加载**：仅在第一次展开时调 `/runs?limit=10`；后续切换折叠不重新加载。父组件刷新任务列表（enabled 变化等）时不主动重新加载历史——除非该卡片当前是展开状态。

**API 包装**（`/api/scheduler.js`）：
```js
export const getSchedulerJobRuns = (jobId, limit = 20) =>
  api.get(`${base}/${jobId}/runs`, { params: { limit } })
```

#### 16.12.5 验证清单

#### 单元验证（curl）
```bash
TOKEN=...

# 1. 启动后 zhihu_check 跑一次（interval 启动即跑），查记录
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/scheduler/configs/zhihu_check/runs | jq '.[0]'
# 预期: {status: "running" | "success" | "failed", duration_ms: ..., ...}

# 2. 404 unknown job_id
curl -H "Authorization: Bearer $TOKEN" -w "%{http_code}\n" \
  http://localhost:5000/api/scheduler/configs/foo/runs -o /dev/null
# 预期: 404

# 3. limit 边界
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5000/api/scheduler/configs/zhihu_check/runs?limit=1" | jq 'length'
# 预期: 1
```

#### 端到端验证（UI）
1. 打开 `/tasks` → 每张卡片底部有"运行历史"行
2. 间隔任务的卡片（zhihu_check / forum_prefetch）摘要显示"最近：成功/失败 · 时间"
3. 点击 cron 任务（如 daily_update）→ 展开 → 显示"暂无运行记录"（cron 任务当天还没到 15:30）
4. 注入一条 failed 记录（直接 INSERT DB 或调失败的 task）→ 展开后看到红色"失败"标签 + 错误消息

#### 持久化
- DB 文件保留所有历史行；不自动清理（v1 不做 TTL 策略）
- 重启 Flask 不丢历史

#### 16.12.6 设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 新表 `scheduler_task_run` 而非复用 `task_logs` | task_logs 是内存 list，重启就丢；新表是 DB 持久化的审计源 |
| 2 | 装饰器模式 | 10 个 task 函数零侵入；统一处理 start/finish/status 分类 |
| 3 | 函数返回 `'skipped'` 显式标注 | 比"根据运行时长判断"更精准；早退分支 vs 异常路径一目了然 |
| 4 | 失败时 message 截断 500 字 | 防止 LLM 完整错误堆栈把 DB 行撑爆 |
| 5 | duration_ms 用 `julianday` 差 × 86400000 | SQLite 跨方言不踩 timezone 坑（datetime 算术） |
| 6 | 前端懒加载 | 10 张卡片 × 10 条 = 100 行；默认折叠避免首屏卡顿 |
| 7 | 不主动清理 / 归档 | 90 天 * 10 任务 * ~5 次/天 = 4500 行；SQLite 轻松应对。v2 再加 TTL |
| 8 | status 4 类（running/success/failed/skipped） | 涵盖所有可能；'skipped' 区分"成功跑过"和"根本没跑" |

#### 16.12.7 关键文件清单（v5.1 增量）

| 状态 | 文件 | 说明 |
|------|------|------|
| 修改 | `backend/core/database.py` | +1 CREATE TABLE + 4 helper 函数 |
| 修改 | `backend/services/scheduler.py` | +`@track_run` 装饰器 + 10 个 task 函数加装饰器 + 6 个 skipped 早退 |
| 修改 | `backend/api/routes/scheduler.py` | +1 endpoint（`/<job_id>/runs`） |
| 修改 | `frontend/src/api/scheduler.js` | +1 axios 包装 |
| 修改 | `frontend/src/components/SchedulerTaskCard.vue` | +手风琴历史 UI（~120 行） |
| 修改 | `docs/SPEC.md` | +§16.12 子节 |

## 17. 异步任务与日志治理（Phase A, 2026-06-10）

### 17.1 目标

统一所有异步任务（API 触发 / 定时触发 / 后台线程）的进度追踪、日志记录、取消机制，用 **task_runs 表 + TaskRunner 上下文管理器** 替代现有的"三套状态存储并存"架构。

### 17.2 数据模型

```sql
CREATE TABLE task_runs (
  id              TEXT PRIMARY KEY,           -- UUID v4 (32 位 hex)
  kind            TEXT NOT NULL,              -- 见 task_kinds.py
  title           TEXT,
  status          TEXT NOT NULL,              -- pending|running|success|failed|cancelled
  total           INTEGER DEFAULT 0,
  done            INTEGER DEFAULT 0,
  current_step    TEXT,
  payload_json    TEXT,
  result_json     TEXT,
  error_message   TEXT,
  error_traceback TEXT,
  triggered_by    TEXT NOT NULL,              -- user|scheduler|system
  user_id         INTEGER,
  scheduler_job   TEXT,
  cancel_requested INTEGER DEFAULT 0,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at      TIMESTAMP,
  finished_at     TIMESTAMP,
  duration_ms     INTEGER
);

CREATE TABLE task_run_logs (
  id            INTEGER PRIMARY KEY,
  task_run_id   TEXT NOT NULL,
  level         TEXT NOT NULL,    -- milestone|info|warning|error
  message       TEXT NOT NULL,
  context_json  TEXT,
  step_index    INTEGER,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 17.3 TaskRunner 核心 API

| 方法 | 说明 |
|------|------|
| `TaskRunner(kind, title, ...)` | 上下文管理器，`__enter__` 写 running，`__exit__` 自动 finalize |
| `set_total(n)` | 设置总步数 |
| `set_current(step)` | 设置当前步骤描述 |
| `progress(done)` | 更新已完成数（节流：每 5 次写一次 DB） |
| `milestone(msg)` | 关键节点日志 |
| `info(msg)` / `warn(msg)` / `error(msg)` | 一般日志 |
| `complete(result)` | 标记成功 |
| `fail(error, traceback)` | 标记失败 |
| `check_cancelled()` | 协作式取消检查点（首次 + 每 20 次查 DB） |
| `task(kind, **kw)` | 便捷工厂函数 |

### 17.4 kind 枚举注册表

18 种任务类型，见 `backend/core/task_kinds.py`：
scan_index / scan_full / backtest / sentiment_batch / sentiment_single / sentiment_universe / sentiment_audit_rerun / vix_recompute / vix_backfill / top_picks_refresh / indicators_recompute / universe_constituents_refresh / universe_aggregate / zhihu_user_refresh / zhihu_user_reanalyze / zhihu_post_reanalyze / zhihu_check_all / forum_prefetch

### 17.5 HTTP API 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/tasks` | 任务列表（?kind=&status=&triggered_by=&limit=） |
| GET | `/api/tasks/active` | 当前运行中的任务 |
| GET | `/api/tasks/recent?limit=20` | 最近完成的任务 |
| GET | `/api/tasks/<id>` | 任务详情（含 progress_pct / elapsed_seconds / latest_milestone） |
| GET | `/api/tasks/<id>/logs?since_id=N&level=` | 增量日志 |
| POST | `/api/tasks/<id>/cancel` | 请求取消（协作式） |

**兼容层**：`/api/tasks/<id>` 自动识别旧的 scan_tasks UUID，返回兼容格式。

### 17.6 日志规范

- **RotatingFileHandler**：10MB × 5 保留
- **噪声压制**：akshare / httpx / httpcore / matplotlib 等第三方设 WARNING
- **task_id 注入**：`TaskAwareFormatter` 通过 contextvars 自动注入 `[task=xxxxxxxx]` 到每行日志
- **异常处理**：全项目统一用 `logger.exception(msg)` 替代 `logger.error(msg, exc_info=True)`

### 17.7 实现状态

| 模块 | 文件 | 状态 |
|------|------|------|
| task_runs / task_run_logs 表 | `backend/core/database.py` | ✅ |
| TaskRunner | `backend/core/task_runner.py` | ✅ |
| kind 注册表 | `backend/core/task_kinds.py` | ✅ |
| 日志改造 | `backend/core/logging_config.py` | ✅ |
| tasks API（6 端点） | `backend/api/routes/tasks.py` | ✅ |
| blueprint 注册 | `backend/api/app.py` | ✅ |
| 单元测试（22 个） | `tests/test_task_runner.py` | ✅ |
| 旧 ops 路由迁移 | `backend/api/routes/ops.py` | ✅ |
| CLAUDE.md 规范更新 | `CLAUDE.md` | ✅ |

**待做（Phase B/C/D）**：
- 29 处异步任务（11 API + 8 后台 + 10 定时）接入 TaskRunner
- 前端 UnifiedProgressBar + TaskCenter
- 删除 `_BATCH_STATE` / `_backfill_state` / `_recompute_status` 等内存状态

### 17.8 Phase B 改造（2026-06-10）

#### 17.8.1 P0（最痛，优先改） — 7 个黑盒任务

| 任务 | 旧状态 | 新状态 |
|------|------|------|
| `vix_service.backfill_vix_history` | `_backfill_state` / `_backfill_lock` 内存 | 接受 `task_runner` 参数 |
| `/api/vix/backfill` | 返回无 task_id | 返回 `task_id` |
| `/api/vix/recompute` | `_recompute_status` 内存 | 返回 `task_id` |
| `/api/zhihu/users/<id>/refresh` | `_REFRESH_TASKS` 内存 | 返回 `task_id` |
| `/api/zhihu/users/<id>/analyze_recent` | `_ANALYZE_TASKS` 内存 | 返回 `task_id` |
| `/api/sentiment/audit/rerun` | 纯 daemon 线程 | 返回 `task_id` |
| `/api/sentiment/indicators/recompute` | 纯 daemon 线程 | 返回 `task_id` |
| `/api/sentiment/top_picks/refresh` | 纯 daemon 线程 | 返回 `task_id` |
| `/api/sentiment/universe/refresh_constituents` | 纯 daemon 线程 | 返回 `task_id` |

#### 17.8.2 P1（已有进度但需要统一） — 4 个并发密集任务

| 任务 | 改造方式 |
|------|------|
| `batch_analyze` (ThreadPoolExecutor) | 接受 `task_runner`；保留 `_BATCH_STATE` 写作为兼容层 |
| `run_universe_crawl` (ThreadPoolExecutor) | 接受 `task_runner`；保留 `_UNIVERSE_BATCH_STATE` 写作为兼容层 |
| `scan_dividend_index` / `scan_all_a_shares` | 接受 `task_runner`；scan_tasks 旧路径保留 |

#### 17.8.3 P2 — APScheduler 9 个定时任务

通过 `track_run` 装饰器升级到 v6：每次 tick 同时写 `scheduler_task_run` 和 `task_runs` 两张表。
任务列表：`daily_update` / `daily_sentiment` / `zhihu_check` / `daily_vix` / `daily_top_picks` / `daily_indicators_recompute` / `forum_prefetch` / `universe_constituents_weekly` / `universe_crawl_daily` / `universe_aggregate_daily`。

#### 17.8.4 新增端点

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/vix/recompute` | 返回 `task_id` |
| POST | `/api/vix/backfill` | 返回 `task_id` |
| POST | `/api/zhihu/users/<id>/refresh` | 返回 `task_id` |
| POST | `/api/zhihu/users/<id>/analyze_recent` | 返回 `task_id` |
| POST | `/api/sentiment/audit/rerun` | 返回 `task_id` |
| POST | `/api/sentiment/indicators/recompute` | 返回 `task_id` |
| POST | `/api/sentiment/top_picks/refresh` | 返回 `task_id` |
| POST | `/api/sentiment/universe/refresh_constituents` | 返回 `task_id` |
| POST | `/api/sentiment/batch_analyze` | 返回 `task_id` |
| POST | `/api/sentiment/universe/run/<idx>` | 返回 `task_id` |
| POST | `/api/index_scan` | 返回 `task_id` |
| POST | `/api/full_refresh` | 返回 `task_id` |

#### 17.8.5 弃用端点

| Method | Path | 替代 |
|--------|------|------|
| GET | `/api/vix/recompute_status` | 410 Gone → 改用 `/api/tasks/<id>` |
| GET | `/api/vix/backfill_status` | 410 Gone → 改用 `/api/tasks/<id>` |
| GET | `/api/zhihu/refresh_status/<id>` | 410 Gone → 改用 `/api/tasks/<id>` |
| GET | `/api/zhihu/analyze_status/<id>` | 410 Gone → 改用 `/api/tasks/<id>` |

兼容层（`/api/zhihu/refresh_status/<id>` / `/api/zhihu/analyze_status/<id>`）仍查询 task_runs 表并返回结果，但带 `deprecated: true` 标记。

#### 17.8.6 测试覆盖

| 测试文件 | 数量 |
|------|------|
| `tests/test_task_runner.py` | 22 |
| `tests/test_phase_b_endpoints.py` | 12 |
| `tests/test_scheduler_track_run.py` | 3 |
| **合计** | **37** |

### 17.9 已知限制

- **contextvars 不传递到 ThreadPoolExecutor 子线程**：TaskRunner 内创建的线程池 worker 日志行 `[task=--------]`，需显式透传 run_id
- **SQLite 写入瓶颈**：全市场扫描 5800 条 info 需节流；progress 已做每 5 次节流，info 无节流（建议仅用于重要节点）
- **取消延迟**：协作式取消取决于 `check_cancelled()` 调用频率，不承诺即时停止

## 18. 公司增强看板组件化（v6, 2026-06-15）

### 18.1 背景

财报解析看板（`/financial-report`）沉淀了一套"以公司为中心"的展示单元：
公司头部（东财跳转 + 价格 + 情绪）、估值条（市值/PE/百分位）、TTM KPI、股价走势、季度表、PE 历史。
同一份能力在舆情页展开详情里也应该可用——用户从情绪列表点开某只股票后，
想知道"这只票到底什么估值、近期走势如何、过去几次情绪分对应股价什么位置"。

之前两份实现是各自堆 v-if + 重复代码，这次抽出来变成可复用组件。

### 18.2 组件分层

```
frontend/src/components/stock/
├── format.js                ─ 共享格式化工具（formatPrice/formatCurrency/formatCap/eastmoneyUrl/sentiment*）
├── StockHeaderCard.vue      ─ 公司头部：东财跳转链接 + 代码 + 情绪标签 + 价格
├── ValuationBar.vue         ─ 估值条：总市值/流通市值/TTM PE/百分位
├── TtmKpiGrid.vue           ─ TTM 三件套：营收/净利润/毛利润
├── QuarterlyTable.vue       ─ 季度财务指标表
└── StockDashboard.vue       ─ 组合：include 开关控制子模块
```

- **format.js** 抽出来避免每个组件再写一遍格式化函数；也方便 SentimentView 直接 `import { sentimentTagType }` 复用。
- **StockDashboard** 是组合层，用 `include: string[]` prop 控制渲染哪些子模块：
  - `header` / `valuation` / `kpi` / `price` / `quarterly` / `pe` 任意组合
  - `inline` prop 关掉内边距/边框/阴影（用于嵌入 SentimentView 已有卡片）
- 子模块都判断 `v-if="hasAny"` 自动隐藏空数据，避免上层要写一堆条件。

### 18.3 后端聚合端点

新增 `GET /api/stock/<symbol>/dashboard`（`backend/api/routes/stock_dashboard.py`），
一次性返回三段数据：

| 字段 | 来源 | 缓存 |
|------|------|------|
| `metrics` | `stock_service.get_stock_metrics` | DB 行情缓存 |
| `financial` | `financial_service.get_financial_data` | 6h SQLite 缓存（`financial_reports_cache`） |
| `sentiment` | `sentiment_service.get_sentiment_history(days=60)` | DB 查 `sentiment_scores` |

参数：`?days=60&sentiment=0` 可关掉情绪段（SentimentView 嵌 dashboard 时不需要再拉一次，置 0 避免重复）。
所有字段都加 `try/except` 隔离，单段失败不影响其他段，前端按 `dashboardOf(code)?.financial ?? {}` 兜底。

### 18.4 PriceTrendChart 扩展

加 `markers: [{date, value, label, kind, color}]` prop，支持两种 marker：
- `kind='extreme'` → echarts `markPoint`（大点 ✱，画在收盘价线上，PANIC/EUPHORIA/动量穿叉）
- `kind='normal'` → echarts `scatter`（小点，画在副 y 轴 `[0,100]`，按 sentiment 着色）

副 y 轴有名字（"情绪分数"）和独立的轴线颜色，避免和价格轴混淆。
extreme + normal 共享同一 `markers` 数组，但渲染时分流——前端不存两套数组。

### 18.5 SentimentView 集成

`SentimentView.vue` 展开详情新增 StockDashboard 嵌入：
- `dashboardByCode` ref 按 code 缓存，避免重复请求
- `toggleExpand` 同时 `Promise.all([loadHistory, loadDashboard])`
- `sentimentMarkers(code)` 把 `historyByCode` 翻译成 markers：极端信号走 markPoint，普通日走 scatter
- 用 `inline` 模式（无边框/阴影），放在 detail-grid 上方

**复用价值**：用户在情绪列表点开 600519，左上角"看多/看空"情绪分数边上立刻看到：
- 公司估值（PE 18.5, 百分位 1%，便宜）
- 股价走势 1Y + 情绪分数叠加（哪些日是恐慌爆发点、对应当日股价位置）
- TTM 营收/净利润/毛利润
- 最近 4 季度财务

整套能力从"看情绪"扩展到"情绪 × 估值 × 行情"三维交叉，无需多页面切换。

### 18.6 FinancialReportView 改造

原来 608 行的 v-if 大杂烩 → 现在 195 行 + 复用 StockDashboard。
报告解析后只做两件事：
1. 调 `/api/financial/analyze` 拿 LLM 识别出的公司列表
2. `v-for` 渲染 `StockDashboard`，把 LLM 返回的字段透传过去

后端 `POST /api/financial/analyze` 仍按原路返回全量字段（ttm_*/quarters/price_history/...），
路由层做字段 passthrough，StockDashboard 的 props 命名与之对齐（`ttmNetProfit` ← `ttm_net_profit` 等）。

### 18.7 设计权衡

- **不抽 emotion histogram 组件**：舆情分数极端/普通分流是 markPoint + scatter 二选一，已经够清晰。
  再加维度（比如分数均值线）会让 K 线变拥挤，暂不引入。
- **不缓存前端 dashboard 数据**：每只股票展开都走 API。
  财务段 6h 缓存已经在后端命中（akshare 不会被反复调），情绪段从 DB 读很轻，前端再做 cache 没收益。
- **format.js 工具函数放组件目录而非 utils/**：这些函数强绑定"公司增强看板"语义，
  跟 stock/ 放一起更内聚；纯工具（比如日期格式化）才放 utils/。

---

## 99. 安全修复记录（2026-06-30）

全项目审查发现的鉴权漏洞集中修复，均已在 `backend/api/` 落地并经 test_client 验证（无 token / `Bearer fake-token` → 401；合法 JWT → 200）。

### 99.1 nav.py 假鉴权修复（净值模块已整体移除）

> 注：净值管理（nav）模块因未接入实盘已整体删除，本条仅作历史安全记录保留。

**问题**：`backend/api/routes/nav.py` 原本地重写了 `login_required` 装饰器，仅检查 `Authorization` 头是否以 `"Bearer "` 开头，**不校验 JWT 签名/过期**。`Bearer anything` 即可放行，净值模块全部写端点（转账/持仓/出金确认/参与方初始化）形同裸奔。

**修复**：删除本地 `login_required` 与 `functools.wraps` import，改 `from backend.api.middleware import login_required`，复用真鉴权（`middleware.py:44`，含 `jwt.decode` 校验 + `g.current_user` 注入）。

### 99.2 vix / vix2 端点补鉴权

**问题**：`backend/api/routes/vix.py`（8 路由）、`vix2.py`（5 路由）**全部零鉴权**，含 `POST /api/vix/recompute`、`POST /api/vix/backfill`、`POST /api/vix2/train`、`POST /api/vix2/backfill` 等触发型写操作。未认证可反复触发 ML 训练 / 回填耗尽 CPU + 海量 DB 写入；GET 端点泄露模型因子权重。

**修复**：两个蓝图所有路由补 `@login_required`（从 middleware import）。`app.py` 的 `before_request` 仅做日志、无全局鉴权兜底，故必须逐路由加装饰器。

### 99.3 JWT_SECRET 弱默认值收紧

**问题**：`backend/config.py` 原 `JWT_SECRET = _env("JWT_SECRET", "change-me-in-production-256bit")`，未配环境变量时回退到该公开字符串，可被攻击者伪造任意 JWT（与 99.1/99.2 叠加放大）。

**修复**：移除公开默认值。未显式配置时用 `secrets.token_urlsafe(48)` 生成进程内随机密钥并打 WARNING —— 本地开发可用，但重启后 token 失效、多 worker 间不互通，倒逼生产/多 worker 部署显式设置。`.env.example` 同步改为留空 + 生成命令注释。

### 99.4 已知未修（建议另起一轮）

- `_UNIVERSE_BATCH_STATE` 内存 dict（`universe_service.py:47`）违反 Phase B、多 worker 跨进程失效。
- APScheduler 多 worker 重复执行（`scheduler.py` + `gunicorn_config.py`）。
- `_BATCH_LOCK` 多 worker 不防重入（`sentiment_service.py:862`）。
- 触发型端点缺 `@rate_limit`（ops/sentiment/backtest）。
- CORS 默认 `*`（docker-compose 覆盖）。
- N+1 查询（`nav.py:86,240`、`forum_service.py:738`）。

---

## 19. 十倍股/财报异动扫描器（feature/tenbag-scanner, 2026-07-01）

### 19.1 目标与定位

合并实现两个相关 idea：
1. **十倍股早期信号扫描器** — 不预测涨十倍，多信号筛选「可能具备大牛股胚子」的公司，输出**分层观察池**（一级=基本面明显变化 / 二级=逻辑性感业绩未兑现 / 三级=概念强财务弱 / 排除=纯炒作）。
2. **财报异动扫描器（基本面雷达）** — 全市场扫财报找异动信号，输出 公司/行业/核心变化/可能解释/风险/结论。

异动扫描器 = 信号提取层，其产出喂给十倍股分层器。两者共享 DB 表 / task kinds / 数据抓取基础设施。**口径约束：输出是观察池/基本面雷达，不是买卖信号**（同 §11 VIX 约束，前端与 API 文案严禁「买入/卖出」措辞）。

### 19.2 模块边界

| 模块 | 职责 | 类型 | 状态 |
|------|------|------|------|
| M2 股价趋势分析器 | 月线趋势确认 | 纯量化 | ✅ Step 1 |
| 异动定量信号 | 营收/利润高增、毛利率改善、存货下降、合同负债上升、在建工程转固、应收风险、现金流跟上 | 定量（akshare 结构化财报） | ✅ Step 2 |
| 分层器 | 规则分层 → 一/二/三级 + 排除池 | 确定性规则 | 待 Step 3 |
| M1 财报 PDF 解析器 | 新产品/产能/增持/机构覆盖 | LLM（MiniMax M3） | 待 Step 6 |
| M3 高景气行业 | 高景气赛道 + 产业链卡位 | 数据驱动 | 待 Step 7 |

### 19.3 数据库 schema（新增 3 表）

```sql
CREATE TABLE tenbag_anomaly_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, report_date TEXT,
  signals_json TEXT, score REAL,
  core_changes_json TEXT, risks_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(symbol, report_date)
);
CREATE TABLE tenbag_trend_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, date TEXT NOT NULL,
  signals_json TEXT, regime TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(symbol, date)
);
CREATE TABLE tenbag_pools (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_date TEXT NOT NULL, symbol TEXT NOT NULL,
  pool_tier TEXT NOT NULL, reasons_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(snapshot_date, symbol)
);
CREATE INDEX idx_tenbag_pools_date_tier ON tenbag_pools(snapshot_date, pool_tier);
```

### 19.4 模块二 股价趋势分析器（`backend/services/tenbag_trend_service.py`）

`compute_trend_signals(daily_bars, benchmark_bars=None)` 纯函数，输入日 K 列表（复用 `financial_service._fetch_tencent_kline`）→ 输出 `{monthly_bars, ma12_monthly, ma24_monthly, ma60_daily, ma120_daily, drawdown_from_high, new_high_ratio, volume_ratio, relative_strength, regime}`。

regime 判定（主锚点日线 MA60，回退月线 MA12）：
- `stage2_breakout`：站上趋势 MA + 距 52 周高点回撤 > -15% + 新高比例 ≥ 0.3
- `advancing`：站上趋势 MA 但未满足 stage2 全部条件
- `downtrend`：跌破趋势 MA
- `consolidation`：其他

### 19.5 财报异动定量信号（`backend/services/tenbag_anomaly_service.py`）

`derive_anomaly_signals(financials)` 纯函数，输入近 4 期结构化财报 → 输出 `{signals, core_changes, possible_explanations, risks, score, conclusion}`。信号阈值集中可调（营收/利润高增 ≥30% YoY、毛利率改善 ≥5pct、合同负债升 ≥30%、存货降 ≥10%、应收风险=应收增速/营收增速>1.2、现金流滞后=经营现金流/净利润<0.5）。

akshare 抓取（EM 接口，2026-07-01 demo 实测）：`fetch_balance_sheet_em` / `fetch_cash_flow_em` / `fetch_financials_em`。字段归一化映射：`INVENTORY`→存货、`CONTRACT_LIAB`→合同负债、`CIP`→在建工程、`ACCOUNTS_RECE`→应收账款、`FIXED_ASSET`→固定资产、`NETCASH_OPERATE`→经营现金流净额。

### 19.5.1 分层器（`backend/services/tenbag_pool_service.py`）

`classify_pool(trend_signals, anomaly_signals, industry_signals=None) -> {tier, reasons}` 纯函数，确定性规则分层：一级（≥3 正向异动+无风险+趋势确认）、二级（趋势确认+1-2 萌芽异动，或 ≥3 异动+横盘）、三级（概念强+财务弱）、排除（破位+无异动，或全无信号）。industry_signals 为 M3 预留（高景气加成）。

### 19.5.2 扫描编排（`backend/services/tenbag_scan_service.py`）

`run_scan(task_runner, top_n=50, snapshot_date)` 编排：取候选池（`get_latest_top_picks`）→ 逐只 `_scan_single`（趋势→异动→分层→落库 `tenbag_trend_signals`/`tenbag_anomaly_signals`/`tenbag_pools`）→ 返回 `{scanned, failed, tiers}`。TaskRunner 提供进度/取消；单只失败隔离不中断。`_latest_report_date` 兼容升序/降序输入取最近报告期。

### 19.5.3 API 端点（`backend/api/routes/tenbag.py`，蓝图 `tenbag_bp`）

| Method | Path | 说明 | 认证 |
|--------|------|------|------|
| POST | `/api/tenbag/scan` | 触发扫描（异步 TaskRunner，body `{top_n}`，返回 task_id）；防重（tenbag_scan 已运行则 409） | 是 |
| GET | `/api/tenbag/pools?tier=&date=` | 分层结果列表（默认最新快照） | 是 |
| GET | `/api/tenbag/signals/<symbol>` | 单股趋势+异动信号详情 | 是 |
| GET | `/api/tenbag/health` | 生产线健康（最近快照/各 tier 数量/最近任务） | 是 |

### 19.5.4 调度任务

`scheduler.py` 新增 `daily_tenbag_scan_task`（`@track_run("daily_tenbag_scan")` + 函数级锁防自重叠），工作日 17:00 跑 `run_scan()`（候选 top50，长任务~2h）。注册于 `_TASK_FUNCS` + `scheduler_config_service.JOB_REGISTRY`（cron 17:00 mon-fri，`seed_from_env` 幂等写入）。调度路径 kind=`daily_tenbag_scan`（手动路径 kind=`tenbag_scan`，与 vix `daily_vix`/`vix_recompute` 双 kind 惯例一致）。

### 19.6 数据拉取接口「demo 实测先行」闸门

每个新建数据/PDF/LLM 拉取接口，集成前必须先写 `scripts/demo_tenbag_*.py` 实测交用户 review。已通过：腾讯日 K、EM 资产负债表、EM 现金流。待测：巨潮资讯 cninfo 年报 PDF、MiniMax M3 结构化提取（Step 6）。

### 19.7 候选池与性能约束

EM 财报接口逐期抓取，单只 2-3 分钟，全市场不可行。MVP：候选池 = 热门股池 top 50（复用 `top_picks_service`），财报仅取近 4 期，DB 缓存。

### 19.8 实施进度

| Step | 内容 | 状态 |
|------|------|------|
| 0 | 分支 + 设计书 + task_kinds + DB schema TDD | ✅ |
| 1 | 模块二趋势分析器 TDD + demo | ✅ |
| 2 | 异动定量信号 TDD + demo | ✅ |
| 3 | 分层器 TDD | ✅ |
| 4 | API + 异步任务 + 调度 | ✅ |
| 5 | 前端页面 | 待 |
| 6 | M1 PDF 解析器（demo 实测 cninfo+MiniMax） | 待 |
| 7 | M3 行业景气 | 待 |
