# 异步任务与日志治理 — 设计书 v1 (Draft)

**文档元信息**

| 项 | 值 |
|---|---|
| 创建日期 | 2026-06-09 |
| 状态 | Draft — 待 review |
| 作者 | Claude (基于全项目代码调研自动生成) |
| 适用代码版本 | stock-agent main 分支 |
| 关联文档 | `docs/SPEC.md` §3 / §8 / §10 / §11 |
| 实施后归档位置 | `docs/async-task-and-logging.md` (建议) |

---

## 1. 背景与动机

### 1.1 用户原始诉求

> "我对项目所有异步任务的进度显示以及日志管控都很不满意,我要求彻底分析项目里所有的异步接口以及定时任务,全部给我优化日志打印、引入进度条以及关键节点机制。"

关键词:**彻底**、**全部**、**所有**、**关键节点机制**。

### 1.2 调研结论 — 三大结构性问题

1. **任务状态存储三套并存**:
   - 持久化 DB 表(`scan_tasks`、`backtest_runs`、`sentiment_universe_jobs`、`scheduler_task_run`)
   - 内存 dict(`_BATCH_STATE`、`_UNIVERSE_BATCH_STATE`、`_backfill_state`、`_recompute_status`、`task_logs[]`)
   - 文件缓存(`market_dividends_cache.json` 等)
   
   **后果**:任务体验割裂,前端要为每类任务写一套轮询逻辑;**内存状态进程重启 / 页面刷新即丢失**。

2. **task_id 不统一**:
   - 扫描类返回持久化 task_id (UUID)
   - 回测返回 run_id (8 位 UUID)
   - **舆情批量 / 知乎刷新 / VIX 回填 / top_picks 刷新 / indicators 重算 / audit/rerun 等 7+ 个 API 完全不返回 task_id**,前端只能"凭感觉"轮询某个固定状态端点
   - 用户提交多个任务无法区分

3. **关键节点(milestone)概念缺失**:
   - 当前只有 `info / warn / error` 三级日志
   - 没有"重要里程碑"概念(任务启动 / 阶段切换 / 任务完成)
   - 前端无法显示"现在做到第几步",只能显示数字进度

### 1.3 现有局部痛点(精选 8 项)

| # | 痛点 | 来源 |
|---|---|---|
| 1 | `app.log` 无轮转,生产环境磁盘撑满风险 | `core/logging_config.py:48-52` |
| 2 | akshare 噪声未压制,大量 DEBUG 刷屏 | `core/logging_config.py:55-59` |
| 3 | `task_id / run_id 不进日志行`,无法关联日志与任务记录 | 全项目 |
| 4 | `scheduler.py` 用内存 `task_logs[]` 存日志,进程重启即丢失 | `services/scheduler.py:41-48` |
| 5 | `logger.error(..., exc_info=True)` 与 `logger.exception()` 混用 | `services/scheduler.py` 多处 |
| 6 | LLM 调用耗时只 logger.info,不入库,无法做性能分析 | `services/sentiment_service.py:498` |
| 7 | 知乎 AI 分析:前端 500ms 轮询 240 次(2 分钟),只显示 spinner 不显示进度 | `views/ZhihuMonitorView.vue` |
| 8 | VIX 回填:用户提交后无任何进度反馈,后台静默跑 3-5 分钟 | `views/VixView.vue` |

---

## 2. 全景调研(基于 3 个 Explore agent 报告)

### 2.1 APScheduler 定时任务清单(10 个)

| 任务 | Cron | 入口 | 当前进度机制 | 前端可见 |
|---|---|---|---|---|
| 红利指数日扫 | 工作日 15:30 | `daily_update_task` | scan_tasks 表 | ✅ |
| 舆情批量分析 | 工作日 16:00 | `daily_sentiment_task` | _BATCH_STATE 内存 | ⚠️ 只在 SentimentView |
| 热门股池刷新 | 工作日 16:05 | `daily_top_picks_task` | 无 | ❌ |
| VIX 恐慌指数 | 工作日 16:30 | `daily_vix_task` | _recompute_status 内存 | ⚠️ 只在 Dashboard |
| 时序因子重算 | 工作日 16:35 | `daily_indicators_recompute_task` | 无 | ❌ |
| 全市场舆情爬取 | 工作日 18:00 | `daily_universe_crawl_task` | _UNIVERSE_BATCH_STATE + DB | ⚠️ 只在 SentimentView |
| 全市场指数聚合 | 工作日 19:30 | `daily_universe_aggregate_task` | 无 | ❌ |
| 知乎大V监控 | 每 N 小时 | `zhihu_check_task` | 无(只有 scheduler_task_run) | ❌ |
| 股吧帖子预拉 | 每 N 小时 | `forum_prefetch_task` | 无 | ❌ |
| 全市场成分股周更 | 每周日 17:00 | `weekly_universe_constituents_task` | 无 | ❌ |

### 2.2 后台线程任务清单(8 类)

| 任务 | 入口 | 并发 | 进度机制 |
|---|---|---|---|
| 红利指数扫描 | `scan_dividend_index` | ThreadPool(20) | scan_tasks 表 |
| 全市场扫描 | `scan_all_a_shares` | ThreadPool(20) | scan_tasks 表 |
| 舆情批量分析 | `batch_analyze` | ThreadPool(5) | _BATCH_STATE 内存 |
| 全市场舆情爬取 | `run_universe_crawl` | ThreadPool(8) | _UNIVERSE_BATCH_STATE + DB |
| VIX 历史回填 | `backfill_vix_history` | 串行 | _backfill_state 内存 |
| 单股舆情分析 | `analyze_sentiment` | 由调用方控制 | 无 |
| 知乎 LLM 分析 | `analyze_new_posts` | 串行 | on_progress 回调 |
| 股票名称缓存刷新 | `_refresh_stock_cache` | daemon Thread | 无 |

### 2.3 异步 HTTP API 清单(11 个)

| 路由 | 返回 task_id? | 状态端点 | 前端轮询频率 |
|---|---|---|---|
| `POST /api/index_scan` | ✅ DB task_id | `/api/tasks/<id>` | 3s |
| `POST /api/full_refresh` | ✅ DB task_id | `/api/tasks/<id>` | 3s |
| `POST /api/backtest/run` | ✅ run_id | `/api/backtest/runs/<id>` | 2s × 120 次 |
| `POST /api/sentiment/batch_analyze` | ❌ | `/api/sentiment/batch_analyze_status` | 1.5s |
| `POST /api/sentiment/universe/run/<idx>` | ❌ | `/api/sentiment/universe/progress` | 1.5s |
| `POST /api/vix/recompute` | ❌ | `/api/vix/recompute_status` | 2s |
| `POST /api/vix/backfill` | ❌ | `/api/vix/backfill_status` | 无 |
| `POST /api/sentiment/top_picks/refresh` | ❌ | **无** | 无 |
| `POST /api/sentiment/universe/refresh_constituents` | ❌ | **无** | 无 |
| `POST /api/sentiment/indicators/recompute` | ❌ | **无** | 无 |
| `POST /api/sentiment/audit/rerun` | ❌ | **无** | 无 |

### 2.4 日志现状关键代码引用

```python
# core/logging_config.py:48-52 — 无轮转
file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8", delay=True)

# core/logging_config.py:55-59 — akshare 未压制
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# 缺少: logging.getLogger("akshare").setLevel(logging.WARNING)

# services/scheduler.py:41-48 — 内存日志,进程重启即丢
task_logs = []
def log_message(msg: str) -> None:
    with _task_logs_lock:
        task_logs.append({"time": datetime.now().isoformat(), "message": msg})
        if len(task_logs) > 1000:
            task_logs.pop(0)
```

### 2.5 前端进度组件碎片化

| 组件/页面 | 轮询端点 | 频率 | 显示内容 |
|---|---|---|---|
| ScanProgressBar | `/api/tasks/<id>` | 3s | 全局底部进度条 |
| ScanProgressView | `/api/tasks/<id>/progress` | 5s | 详情页 + 已扫描股票 |
| SentimentView (批量) | `/api/sentiment/batch_analyze_status` | 1.5s | 内嵌进度条 |
| SentimentView (universe) | `/api/sentiment/universe/progress` | 1.5s | 内嵌进度条 |
| BacktestView | `/api/backtest/runs/<id>` | 2s × 120 | 内嵌进度提示 |
| ZhihuMonitorView (刷新) | `/api/zhihu/refresh_status/<id>` | 0.5s × 60 | 用户不可见 |
| ZhihuMonitorView (AI 分析) | `/api/zhihu/analyze_status/<id>` | 0.5s × 240 | 内嵌 hint |
| Dashboard (VIX 重算) | `/api/vix/recompute_status` | 2s | 角标 badge |
| VixView (回填) | **无轮询** | — | **完全没反馈** |

---

## 3. 设计目标

### 3.1 必达目标(Must)

1. **唯一 task_id**:所有异步任务返回标准 UUID,持久化到 DB
2. **统一进度模型**:`{done, total, current_step, status, milestones[]}`
3. **统一日志读取**:`GET /api/tasks/<id>/logs?since_id=N` 增量拉取任意任务的执行日志
4. **关键节点机制**:`milestone` API 标记任务的重要里程碑(启动 / 阶段切换 / 完成)
5. **日志治理**:日志轮转、压制噪声、注入 task_id、统一异常处理
6. **任务可见性**:每一个异步任务前端都能看到进度,不能存在"黑盒任务"

### 3.2 应达目标(Should)

7. **全局任务中心**:右上角 badge + 抽屉,集中查看所有运行中/最近完成任务
8. **统一进度条组件**:`UnifiedProgressBar(taskRunId)`,所有现有进度条接入
9. **scheduler 任务前端可见**:`SchedulerTaskCard` 展示当前是否在跑 + 子步骤
10. **任务可取消**:长任务支持 `POST /api/tasks/<id>/cancel`(尽力而为)

### 3.3 不做的事(Won't, v1)

- ❌ **不引入 SSE/WebSocket**:Flask + 同步 worker 模型上 SSE 实施成本高(需要 gevent/eventlet),v1 仍用统一轮询;**预留升级口**
- ❌ **不引入 Celery/Redis 等任务队列**:当前 ThreadPoolExecutor + APScheduler 足够,引入新基础设施超出 scope
- ❌ **不做日志全文搜索**:v1 只做增量拉取与按 task_id 过滤,ELK/Loki 接入留 v2
- ❌ **不动现有 scan_tasks 表**:作为只读历史归档保留,新任务全部走 task_runs(零迁移风险)

---

## 4. 设计原则

| # | 原则 | 解释 |
|---|---|---|
| P1 | **一个任务,一个 ID,一处真相** | task_runs 表是任务状态的唯一权威源,内存状态全部废弃 |
| P2 | **后端用上下文管理器,前端用组件** | 后端 `with TaskRunner(...) as t:` 自动管理生命周期;前端 `<UnifiedProgressBar :task-run-id="id" />` 自动轮询 |
| P3 | **日志写两份:文本 + DB** | logger 仍写文件(开发调试),关键节点同时写 task_run_logs 表(用户可见) |
| P4 | **向后兼容,零迁移** | scan_tasks / backtest_runs 等旧表保留,API 兼容层适配 |
| P5 | **可观测性优先** | 每个任务都有 started_at / finished_at / duration_ms,前端可以做"哪些任务最慢"等分析 |
| P6 | **失败安全** | TaskRunner 异常自动 fail + 写堆栈,绝不漏标 |

---

## 5. 架构总览

```
                          ┌─────────────────────────────────────┐
                          │  Frontend                           │
                          │  ┌──────────────────────────────┐   │
                          │  │ TaskCenter (右上角全局抽屉) │   │
                          │  └──────────────────────────────┘   │
                          │  ┌──────────────────────────────┐   │
                          │  │ UnifiedProgressBar           │   │
                          │  │  - props: taskRunId          │   │
                          │  │  - 自动轮询 /api/tasks/<id>  │   │
                          │  └──────────────────────────────┘   │
                          └─────────────┬───────────────────────┘
                                        │ HTTP(轮询)
                          ┌─────────────▼───────────────────────┐
                          │  Backend HTTP API                   │
                          │  GET /api/tasks                     │
                          │  GET /api/tasks/<id>                │
                          │  GET /api/tasks/<id>/logs?since=N   │
                          │  POST /api/tasks/<id>/cancel        │
                          └─────────────┬───────────────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
   ┌──────────▼──────────┐  ┌──────────▼──────────┐  ┌──────────▼──────────┐
   │ APScheduler 定时     │  │ Async HTTP 任务      │  │ 后台线程任务         │
   │ (10 个 job)          │  │ (11 个 POST)         │  │ (8 类)               │
   └──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘
              │                         │                         │
              └─────────────────────────┼─────────────────────────┘
                                        │ 使用
                          ┌─────────────▼───────────────────────┐
                          │  core/task_runner.py                │
                          │  ┌──────────────────────────────┐   │
                          │  │ TaskRunner (上下文管理器)    │   │
                          │  │  - __enter__ / __exit__      │   │
                          │  │  - set_total / progress      │   │
                          │  │  - milestone / info / warn   │   │
                          │  │  - complete / fail / cancel  │   │
                          │  └──────────────────────────────┘   │
                          │  ┌──────────────────────────────┐   │
                          │  │ TaskLogAdapter (logger 桥)  │   │
                          │  │  - contextvars 注入 run_id  │   │
                          │  └──────────────────────────────┘   │
                          └─────────────┬───────────────────────┘
                                        │ 读写
                          ┌─────────────▼───────────────────────┐
                          │  SQLite                             │
                          │  ┌──────────────────────────────┐   │
                          │  │ task_runs (新表)            │   │
                          │  │ task_run_logs (新表)        │   │
                          │  └──────────────────────────────┘   │
                          │  ┌──────────────────────────────┐   │
                          │  │ scan_tasks / backtest_runs   │   │
                          │  │ (保留为只读历史归档)         │   │
                          │  └──────────────────────────────┘   │
                          └─────────────────────────────────────┘
```

---

## 6. 后端方案

### 6.1 数据模型

#### 6.1.1 `task_runs` 表(新建)

```sql
CREATE TABLE task_runs (
  id              TEXT PRIMARY KEY,           -- UUID v4 (32 位 hex)
  kind            TEXT NOT NULL,              -- 枚举:见 §6.1.3
  title           TEXT,                       -- 用户可读的任务名("全市场扫描")
  status          TEXT NOT NULL,              -- pending|running|success|failed|cancelled
  total           INTEGER DEFAULT 0,
  done            INTEGER DEFAULT 0,
  current_step    TEXT,                       -- "正在分析 600519"
  payload_json    TEXT,                       -- 任务入参
  result_json     TEXT,                       -- 成功时的结果摘要
  error_message   TEXT,
  error_traceback TEXT,                       -- 失败时的完整堆栈
  triggered_by    TEXT NOT NULL,              -- user|scheduler|system
  user_id         INTEGER,                    -- 触发用户(可空)
  scheduler_job   TEXT,                       -- 调度任务 job_id(scheduler 触发时)
  cancel_requested INTEGER DEFAULT 0,         -- 0|1,任务自行轮询
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at      TIMESTAMP,
  finished_at     TIMESTAMP,
  duration_ms     INTEGER
);
CREATE INDEX idx_task_runs_kind_status ON task_runs(kind, status, created_at DESC);
CREATE INDEX idx_task_runs_status_started ON task_runs(status, started_at DESC);
```

#### 6.1.2 `task_run_logs` 表(新建)

```sql
CREATE TABLE task_run_logs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  task_run_id   TEXT NOT NULL,
  level         TEXT NOT NULL,    -- milestone|info|warning|error
  message       TEXT NOT NULL,
  context_json  TEXT,             -- 可选结构化上下文
  step_index    INTEGER,          -- 当前步骤序号(可选,用于"第 5 步")
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_trl_run_id ON task_run_logs(task_run_id, id);
CREATE INDEX idx_trl_milestone ON task_run_logs(task_run_id, level) WHERE level = 'milestone';
```

**level 语义**:
- `milestone`: 关键节点("开始抓取股吧"、"开始 LLM 分析"、"写入数据库完成")
- `info`: 一般进度("分析 600519 完成")
- `warning`: 可恢复异常("代理失败,切换备用源")
- `error`: 不可恢复异常("任务终止")

#### 6.1.3 `kind` 枚举(预定义 18 类)

| kind | 触发源 | 说明 |
|---|---|---|
| `scan_index` | 用户 / scheduler 15:30 | 红利指数扫描 |
| `scan_full` | 用户 | 全市场扫描 |
| `backtest` | 用户 | 策略回测 |
| `sentiment_batch` | 用户 / scheduler 16:00 | 舆情批量分析 |
| `sentiment_single` | 用户 | 单股舆情分析 |
| `sentiment_universe` | 用户 / scheduler 18:00 | 全市场舆情爬取 |
| `sentiment_audit_rerun` | 用户 | 标题真实性重审 |
| `vix_recompute` | 用户 / scheduler 16:30 | VIX 重算 |
| `vix_backfill` | 用户 | VIX 历史回填 |
| `top_picks_refresh` | 用户 / scheduler 16:05 | 热门股池刷新 |
| `indicators_recompute` | 用户 / scheduler 16:35 | 时序因子重算 |
| `universe_constituents_refresh` | 用户 / scheduler 周日 17:00 | 全市场成分股周更 |
| `universe_aggregate` | scheduler 19:30 | 全市场指数聚合 |
| `zhihu_user_refresh` | 用户 | 知乎单用户抓取 |
| `zhihu_user_reanalyze` | 用户 | 知乎用户重分析 |
| `zhihu_post_reanalyze` | 用户 | 单帖重分析 |
| `zhihu_check_all` | scheduler 每 N 小时 | 全部大V抓取 + 邮件 |
| `forum_prefetch` | scheduler 每 N 小时 | 股吧帖子预拉 |

新增 kind 时,统一在 `core/task_kinds.py` 中央注册。

#### 6.1.4 旧表迁移策略

| 旧表 | 处理方式 |
|---|---|
| `scan_tasks` | **保留只读**,新建的扫描任务双写 task_runs + scan_tasks(兼容期);v2 删除 |
| `backtest_runs` | **保留**,作为 backtest 的业务结果表(非任务状态表);task_runs 只存调度状态,backtest_runs 存绩效指标 + 交易明细 |
| `scheduler_task_run` | **保留**,作为 scheduler-only 视图;新代码读写 task_runs;v2 可考虑合并 |
| `sentiment_universe_jobs` | **保留**,作为 universe 批处理的业务表(每个指数一行);task_runs 存整体调度状态 |
| `_BATCH_STATE / _backfill_state / _recompute_status` 等内存 dict | **删除**,改读 task_runs |

**关键决策**:不一次性迁移,采用"双写过渡 + 渐进切换"。新表里的 task_runs 是真相之源,旧表保留是为了:① 旧 API 兼容期内能用;② 提供历史数据兜底。

### 6.2 核心组件 `core/task_runner.py`(新建)

```python
import contextvars
import logging
import threading
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from .database import (
    insert_task_run, update_task_run, append_task_run_log,
    get_task_run, mark_task_cancelled
)

# contextvars 用于把 run_id 注入到当前线程的 logger 上下文
current_task_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_task_run_id", default=None
)


class TaskCancelled(Exception):
    """任务被用户取消时抛出"""
    pass


class TaskRunner:
    """统一任务执行器(上下文管理器)。
    
    用法:
        with TaskRunner(kind='scan_full', title='全市场扫描', triggered_by='user') as t:
            t.milestone('开始拉取股票列表')
            stocks = get_all_a_share_codes()
            t.set_total(len(stocks))
            t.milestone(f'开始扫描 {len(stocks)} 只股票')
            for i, code in enumerate(stocks):
                t.check_cancelled()  # 检查是否被取消
                t.set_current(f'扫描 {code}')
                process_single_stock(code)
                t.progress(i + 1)
            t.milestone('扫描完成,开始写库')
            write_to_db(...)
            t.complete(result={'count': len(stocks)})
    """
    
    def __init__(
        self,
        kind: str,
        title: str | None = None,
        triggered_by: str = 'user',
        user_id: int | None = None,
        scheduler_job: str | None = None,
        payload: dict | None = None,
    ):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.title = title or kind
        self.triggered_by = triggered_by
        self.user_id = user_id
        self.scheduler_job = scheduler_job
        self.payload = payload or {}
        self._status = 'pending'
        self._total = 0
        self._done = 0
        self._current_step = None
        self._token = None  # contextvar token,用于 reset
        self._logger = logging.getLogger(f"task.{kind}")
        self._last_progress_write = 0  # 节流:每 N 次 progress 才落库一次
    
    def __enter__(self):
        insert_task_run(
            id=self.id, kind=self.kind, title=self.title, status='running',
            triggered_by=self.triggered_by, user_id=self.user_id,
            scheduler_job=self.scheduler_job, payload_json=json.dumps(self.payload),
            started_at=datetime.now().isoformat(),
        )
        self._status = 'running'
        self._token = current_task_run_id.set(self.id)
        self._logger.info(f"[task={self.id[:8]} kind={self.kind}] started: {self.title}")
        self.milestone(f"任务启动:{self.title}", silent_log=True)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is TaskCancelled:
                self._finalize('cancelled', error_message='用户取消')
                self._logger.info(f"[task={self.id[:8]}] cancelled")
                return True  # 吃掉异常
            elif exc_type is not None:
                tb_text = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
                self._finalize('failed', error_message=str(exc_val), error_traceback=tb_text)
                self._logger.exception(f"[task={self.id[:8]}] failed")
                return False  # 异常继续上抛
            elif self._status == 'running':
                # 用户没有显式 complete(),按成功处理
                self._finalize('success')
        finally:
            if self._token:
                current_task_run_id.reset(self._token)
    
    # ----- 进度 API -----
    def set_total(self, total: int):
        self._total = total
        update_task_run(self.id, total=total)
    
    def set_current(self, step: str):
        self._current_step = step
        update_task_run(self.id, current_step=step)
    
    def progress(self, done: int, throttle_every: int = 5):
        """更新已完成数,默认每 5 次写一次 DB(避免高频写)。"""
        self._done = done
        self._last_progress_write += 1
        if self._last_progress_write >= throttle_every or done == self._total:
            update_task_run(self.id, done=done)
            self._last_progress_write = 0
    
    # ----- 日志 API -----
    def milestone(self, msg: str, context: dict | None = None, silent_log: bool = False):
        """关键节点,前端会突出显示。"""
        append_task_run_log(self.id, level='milestone', message=msg, context_json=context)
        if not silent_log:
            self._logger.info(f"[milestone] {msg}")
    
    def info(self, msg: str, context: dict | None = None):
        append_task_run_log(self.id, level='info', message=msg, context_json=context)
        self._logger.info(msg)
    
    def warn(self, msg: str, context: dict | None = None):
        append_task_run_log(self.id, level='warning', message=msg, context_json=context)
        self._logger.warning(msg)
    
    def error(self, msg: str, exc_info: bool = False, context: dict | None = None):
        append_task_run_log(self.id, level='error', message=msg, context_json=context)
        if exc_info:
            self._logger.exception(msg)
        else:
            self._logger.error(msg)
    
    # ----- 完成 / 失败 / 取消 -----
    def complete(self, result: dict | None = None):
        self._finalize('success', result_json=json.dumps(result) if result else None)
        self.milestone("任务完成", silent_log=True)
    
    def fail(self, error: str, traceback_text: str | None = None):
        self._finalize('failed', error_message=error, error_traceback=traceback_text)
    
    def check_cancelled(self):
        """轮询点:任务自己调用,检测是否被前端取消。"""
        row = get_task_run(self.id)
        if row and row.get('cancel_requested'):
            raise TaskCancelled()
    
    def _finalize(self, status: str, **kwargs):
        if self._status == status:
            return
        self._status = status
        finished = datetime.now().isoformat()
        update_task_run(
            self.id, status=status, finished_at=finished,
            done=self._done, current_step=None, **kwargs
        )


@contextmanager
def task(kind: str, **kwargs):
    """便捷工厂:`with task('scan_full', title='全市场扫描') as t: ...`"""
    with TaskRunner(kind, **kwargs) as t:
        yield t
```

### 6.3 异步任务改造清单(11 个 API + 8 类后台 + 10 个定时)

**改造模式**(以 `scan_all_a_shares` 为例):

```python
# 改造前 (backend/tasks/market_scan.py)
def scan_all_a_shares(task_id, max_workers=None):
    codes = get_all_a_share_codes()
    update_scan_task(task_id, status='running', total=len(codes))
    # ... 略

# 改造后
def scan_all_a_shares(max_workers=None, triggered_by='user', user_id=None):
    with TaskRunner('scan_full', title='全市场扫描', triggered_by=triggered_by,
                    user_id=user_id) as t:
        t.milestone('获取 A 股代码列表')
        codes = get_all_a_share_codes()
        t.set_total(len(codes))
        t.milestone(f'开始扫描 {len(codes)} 只股票')
        for i, code in enumerate(codes):
            t.check_cancelled()
            t.set_current(f'扫描 {code}')
            process_single_stock(code)
            t.progress(i + 1)
        t.milestone('扫描完成')
        t.complete(result={'count': len(codes)})
    return t.id  # 返回给 HTTP API
```

**11 个 HTTP API 改造**:全部改为返回 `{"task_run_id": "xxx"}`,内部用 TaskRunner 包裹。

**8 类后台线程任务改造**:全部用 TaskRunner 包裹,删除 `_BATCH_STATE / _backfill_state / _recompute_status` 等内存状态。

**10 个 APScheduler 定时任务改造**:全部用 TaskRunner 包裹,`triggered_by='scheduler'`,`scheduler_job=job_id`。

### 6.4 新 HTTP API 端点(`api/routes/tasks.py`,新建)

| Method | Path | 说明 | 认证 |
|---|---|---|---|
| GET | `/api/tasks` | 任务列表,支持 `?kind=&status=&triggered_by=&limit=` | 是 |
| GET | `/api/tasks/<id>` | 任务详情(含 total/done/current_step/payload/result) | 是 |
| GET | `/api/tasks/<id>/logs?since_id=N&level=` | 增量日志,level 可过滤 milestone | 是 |
| POST | `/api/tasks/<id>/cancel` | 请求取消(置 cancel_requested=1) | 是 |
| GET | `/api/tasks/active` | 当前所有 running 任务(前端 TaskCenter 用) | 是 |
| GET | `/api/tasks/recent?limit=20` | 最近 N 个任务(任意状态) | 是 |

**响应示例**(`GET /api/tasks/<id>`):

```json
{
  "id": "a1b2c3d4...",
  "kind": "scan_full",
  "title": "全市场扫描",
  "status": "running",
  "total": 5847,
  "done": 1234,
  "progress_pct": 21.1,
  "current_step": "扫描 002594",
  "payload": {},
  "result": null,
  "error_message": null,
  "triggered_by": "user",
  "user_id": 1,
  "scheduler_job": null,
  "started_at": "2026-06-09T15:30:01",
  "finished_at": null,
  "duration_ms": null,
  "elapsed_seconds": 42,
  "latest_milestone": {
    "id": 123,
    "message": "开始扫描 5847 只股票",
    "created_at": "2026-06-09T15:30:03"
  }
}
```

**响应示例**(`GET /api/tasks/<id>/logs?since_id=120`):

```json
{
  "task_run_id": "a1b2c3d4...",
  "logs": [
    {"id": 121, "level": "info", "message": "分析 600519 完成", "created_at": "..."},
    {"id": 122, "level": "warning", "message": "代理超时,切换备用源", "created_at": "..."},
    {"id": 123, "level": "milestone", "message": "开始写入数据库", "created_at": "..."}
  ],
  "next_since_id": 124,
  "has_more": false
}
```

**兼容层**:`/api/tasks/<id>` 同时识别旧的 scan_tasks UUID 和新的 task_runs UUID(优先查 task_runs,fallback 到 scan_tasks)。旧 `/api/sentiment/batch_analyze_status` 等内部转向新接口。

### 6.5 日志规范

#### 6.5.1 `core/logging_config.py` 改造

```python
from logging.handlers import RotatingFileHandler

# 1. 改 RotatingFileHandler(10MB × 5 保留)
file_handler = RotatingFileHandler(
    log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5,
    encoding="utf-8", delay=True
)

# 2. 压制 akshare + 更多第三方
for noisy in ('werkzeug', 'urllib3', 'apscheduler', 'akshare', 'httpx',
              'httpcore', 'matplotlib'):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# 3. 注入 task_run_id 到日志(通过 Formatter)
class TaskAwareFormatter(Log4jFormatter):
    def format(self, record):
        from core.task_runner import current_task_run_id
        run_id = current_task_run_id.get()
        record.task_run_id = run_id[:8] if run_id else '--------'
        return super().format(record)

# 4. 日志格式增加 [task=xxxxxxxx] 字段
FORMAT = '%(asctime)s [%(threadName)s] [task=%(task_run_id)s] %(levelname)s %(name)s - %(message)s'

# 5. 可选 JSON 输出(LOG_JSON=true 启用,默认关)
if os.getenv('LOG_JSON') == 'true':
    file_handler.setFormatter(JsonFormatter())
```

#### 6.5.2 异常处理统一规范

- **全项目改用 `logger.exception(msg)`**,禁用 `logger.error(msg, exc_info=True)` 写法
- TaskRunner 内异常自动 `logger.exception` + 写 `task_run_logs.error`,无需手动调用

#### 6.5.3 关键节点(milestone)规范

每个任务**至少**有以下 milestone:

1. **任务启动**(自动,`__enter__` 触发)
2. **关键阶段切换**(用户显式调用):如"开始 LLM 分析"、"开始写入数据库"、"开始爬取股吧"
3. **重大失败**(可选):如"网络中断,降级到备用源"
4. **任务完成**(自动,`complete()` 触发)

**示例(舆情批量分析)**:

```
[milestone] 任务启动:舆情批量分析
[milestone] 加载监控股票列表 (45 只)
[milestone] 开始爬取股吧帖子
[info]      抓取 600519 完成 (20 帖)
[warning]   抓取 002594 超时,跳过
...
[milestone] 帖子抓取完成,共 856 帖
[milestone] 开始 LLM 情绪分析
[info]      分析 600519 完成
...
[milestone] LLM 分析完成
[milestone] 写入 sentiment_scores
[milestone] 任务完成
```

---

## 7. 前端方案

### 7.1 统一进度组件 `UnifiedProgressBar.vue`(新建)

```vue
<template>
  <div class="unified-progress" v-if="task">
    <div class="upb-header">
      <span class="upb-kind">{{ kindLabel(task.kind) }}</span>
      <span class="upb-status" :class="`upb-status--${task.status}`">
        {{ statusLabel(task.status) }}
      </span>
      <el-button v-if="task.status === 'running' && cancellable"
                 size="small" text @click="cancel">取消</el-button>
    </div>
    <div v-if="task.status === 'running'" class="upb-body">
      <el-progress :percentage="task.progress_pct" :stroke-width="6" />
      <div class="upb-meta">
        <span>{{ task.done }} / {{ task.total }}</span>
        <span class="upb-current">{{ task.current_step }}</span>
        <span class="upb-elapsed">{{ formatElapsed(task.elapsed_seconds) }}</span>
      </div>
      <div v-if="task.latest_milestone" class="upb-milestone">
        🚩 {{ task.latest_milestone.message }}
      </div>
    </div>
    <div v-else-if="task.status === 'failed'" class="upb-error">
      ❌ {{ task.error_message }}
    </div>
    <div v-else-if="task.status === 'success'" class="upb-success">
      ✅ 完成,耗时 {{ formatElapsed(task.duration_ms / 1000) }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getTask, cancelTask } from '@/api/tasks'

const props = defineProps({
  taskRunId: { type: String, required: true },
  cancellable: { type: Boolean, default: true },
  pollInterval: { type: Number, default: 1500 },
  showLogs: { type: Boolean, default: false }
})
const emit = defineEmits(['complete', 'fail', 'update'])

const task = ref(null)
let timer = null

async function poll() {
  task.value = await getTask(props.taskRunId)
  emit('update', task.value)
  if (task.value.status === 'success') emit('complete', task.value)
  if (task.value.status === 'failed') emit('fail', task.value)
  if (['success', 'failed', 'cancelled'].includes(task.value.status)) {
    clearInterval(timer)
  }
}
onMounted(() => {
  poll()
  timer = setInterval(poll, props.pollInterval)
})
onUnmounted(() => clearInterval(timer))
watch(() => props.taskRunId, () => poll())

async function cancel() {
  await cancelTask(props.taskRunId)
}
</script>
```

### 7.2 全局任务中心 `TaskCenter.vue`(新建,在 LayoutView 中挂载)

```vue
<template>
  <!-- 右上角入口 -->
  <el-badge :value="activeTasks.length" :hidden="activeTasks.length === 0">
    <el-button :icon="Bell" circle @click="drawer = true" />
  </el-badge>
  
  <!-- 抽屉 -->
  <el-drawer v-model="drawer" title="任务中心" size="480px">
    <el-tabs v-model="tab">
      <el-tab-pane label="运行中" name="active">
        <div v-for="t in activeTasks" :key="t.id" class="task-item">
          <UnifiedProgressBar :task-run-id="t.id" :cancellable="true"
                              :show-logs="true" />
        </div>
        <EmptyHint v-if="activeTasks.length === 0">暂无运行中任务</EmptyHint>
      </el-tab-pane>
      <el-tab-pane label="最近完成" name="recent">
        <div v-for="t in recentTasks" :key="t.id" class="task-item">
          <div class="task-summary">
            <span class="kind">{{ kindLabel(t.kind) }}</span>
            <span :class="`status status--${t.status}`">{{ t.status }}</span>
            <span class="time">{{ formatTime(t.finished_at) }}</span>
            <span class="duration">{{ formatDuration(t.duration_ms) }}</span>
          </div>
          <el-collapse>
            <el-collapse-item :title="`查看 ${t.id.slice(0,8)} 的关键节点`">
              <TaskMilestones :task-run-id="t.id" />
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<script setup>
// 单一全局轮询:每 2s 拉 /api/tasks/active + /api/tasks/recent?limit=20
// 解决目前每个页面独立轮询的问题
</script>
```

### 7.3 现有组件改造清单

| 文件 | 改造方式 |
|---|---|
| `ScanProgressBar.vue` | 内部改用 `<UnifiedProgressBar :task-run-id="taskStore.activeId" />`,保留底部 sticky 样式 |
| `ScanProgressView.vue` | 详情页保留(扫描专用的"已扫描股票表格"),进度部分换 UnifiedProgressBar |
| `SentimentView.vue` | 删除 `batchProgress` 自有逻辑,改用 `<UnifiedProgressBar :task-run-id="batchTaskId" />` |
| `BacktestView.vue` | 删除 2s × 120 次轮询逻辑,改用 UnifiedProgressBar |
| `ZhihuMonitorView.vue` | 删除 0.5s × 60/240 轮询,改用 UnifiedProgressBar(知乎刷新 + AI 分析) |
| `VixView.vue` | 回填按钮提交后挂 UnifiedProgressBar,**修复"完全无反馈"问题** |
| `DashboardView.vue` | VIX 重算 badge 改用 TaskCenter 中的 active 计数 |
| `SchedulerTaskCard.vue` | 当前定时任务运行中时,挂 UnifiedProgressBar 显示实时进度 |
| `TaskLogs.vue` | 重构为可按 task 过滤的"任务执行日志"组件,接入 `/api/tasks/<id>/logs` |

### 7.4 新增 API 客户端 `api/tasks.js`(新建)

```javascript
import client from './index'

export const getTask = (id) => client.get(`/tasks/${id}`).then(r => r.data)
export const getTaskLogs = (id, sinceId = 0, level = '') =>
  client.get(`/tasks/${id}/logs`, { params: { since_id: sinceId, level } }).then(r => r.data)
export const cancelTask = (id) => client.post(`/tasks/${id}/cancel`).then(r => r.data)
export const listActiveTasks = () => client.get('/tasks/active').then(r => r.data)
export const listRecentTasks = (limit = 20) =>
  client.get('/tasks/recent', { params: { limit } }).then(r => r.data)
export const listTasks = (params) => client.get('/tasks', { params }).then(r => r.data)
```

### 7.5 全局轮询优化

**当前问题**:每个页面独立 setInterval,首页可能同时跑 4-5 个轮询。

**优化策略**:
- TaskCenter 中全局轮询 `/api/tasks/active`(2s 一次)
- UnifiedProgressBar 接 TaskCenter store,**不再独立轮询**,而是从 store 取最新数据
- 仅当用户打开抽屉时,才轮询 `/api/tasks/recent`(降低后端压力)

---

## 8. 实施分阶段

### Phase A — 后端基础设施(2-3 天)

| 步骤 | 文件 |
|---|---|
| 1. 新建 `task_runs` / `task_run_logs` 表(DDL + 幂等迁移) | `core/database.py` |
| 2. 新建 `core/task_runner.py`(TaskRunner + contextvars) | 新文件 |
| 3. 新建 `core/task_kinds.py`(kind 枚举注册) | 新文件 |
| 4. 改造 `core/logging_config.py`(轮转 + 噪声 + task_run_id 注入) | 修改 |
| 5. 新建 `api/routes/tasks.py`(6 个端点) | 新文件 |
| 6. `api/app.py` 注册 tasks_bp | 修改 |
| 7. 单元测试:TaskRunner 上下文管理器、cancel、异常路径 | `tests/test_task_runner.py` |

**Phase A 验收**:能跑一个示例任务,数据库里能看到 task_runs + task_run_logs 记录,GET /api/tasks/<id> 能返回正确数据。

### Phase B — 后端任务改造(3-4 天,可并行)

按优先级 P0 → P1 → P2 推进:

**P0(最痛,优先改)**:
- VIX 回填(`vix_service.backfill_vix_history`)— 当前完全无反馈
- 知乎刷新(`zhihu_service.fetch_user_activities`)— 0.5s 高频轮询
- 知乎 AI 分析(`zhihu_analyzer.analyze_new_posts`)— 同上
- top_picks 刷新 / indicators 重算 / universe 成分股刷新 / audit/rerun — 4 个完全黑盒任务

**P1(已有进度但需要统一)**:
- 全市场扫描(`scan_all_a_shares`)
- 红利指数扫描(`scan_dividend_index`)
- 回测(`backtest.engine.run`)
- 舆情批量分析(`batch_analyze`)
- 舆情 universe 爬取(`run_universe_crawl`)
- VIX 重算(`vix_service.compute_and_store`)

**P2(定时任务接入 TaskRunner)**:
- 10 个 APScheduler 任务全部包裹 TaskRunner

**Phase B 验收**:每改一个任务,前端调用对应 API 都能拿到 task_run_id,/api/tasks/<id> 能看到进度,/api/tasks/<id>/logs 能看到 milestone。

### Phase C — 前端统一(2-3 天)

| 步骤 | 文件 |
|---|---|
| 1. 新建 `api/tasks.js` 客户端 | 新文件 |
| 2. 新建 `stores/tasks.js` Pinia store(全局轮询 active tasks) | 新文件 |
| 3. 新建 `components/UnifiedProgressBar.vue` | 新文件 |
| 4. 新建 `components/TaskMilestones.vue`(展示 milestone 列表) | 新文件 |
| 5. 新建 `components/TaskCenter.vue` 并在 LayoutView 中挂载 | 新文件 + 修改 |
| 6. 改造现有 9 个组件/页面接入 UnifiedProgressBar | 见 §7.3 |
| 7. SchedulerTaskCard 增强:运行中显示实时进度 | 修改 |

**Phase C 验收**:
- 任意触发一个异步任务,右上角 badge +1
- 打开任务中心,能看到运行中任务 + 进度 + 当前步骤 + 最新 milestone
- 任务完成后自动从"运行中"移到"最近完成"
- VIX 回填、知乎刷新等以前"黑盒"的任务都有进度

### Phase D — 清理与文档(1 天)

| 步骤 | 文件 |
|---|---|
| 1. 删除内存状态:`_BATCH_STATE / _backfill_state / _recompute_status / task_logs[]` | 多文件 |
| 2. 删除旧的状态端点路由(`/api/sentiment/batch_analyze_status` 等) | 兼容层透传新接口 |
| 3. 更新 `docs/SPEC.md` 新增 §12 "异步任务与日志治理 (v1)" | 修改 |
| 4. 更新 `CLAUDE.md` 增加"新增异步任务必须用 TaskRunner"约定 | 修改 |
| 5. 复制本设计书到 `docs/async-task-and-logging.md` | 新文件 |

---

## 9. 验证清单(手动 E2E)

### 9.1 后端 Smoke Test

```bash
# 1. 启动后端
python -m backend.api.app

# 2. 触发任意异步任务
curl -X POST http://localhost:5000/api/full_refresh -H "Authorization: Bearer xxx"
# → 返回 {"task_run_id": "abc..."}

# 3. 查看任务详情
curl http://localhost:5000/api/tasks/abc... -H "Authorization: Bearer xxx"
# → 应包含 total/done/current_step/latest_milestone

# 4. 查看任务日志
curl http://localhost:5000/api/tasks/abc.../logs?level=milestone

# 5. 取消任务
curl -X POST http://localhost:5000/api/tasks/abc.../cancel
# → 任务应在数秒内进入 cancelled 状态(取决于 check_cancelled 频率)

# 6. 查看运行中任务
curl http://localhost:5000/api/tasks/active

# 7. 触发定时任务的手动版本,验证 triggered_by='scheduler' 标记
```

### 9.2 前端验收清单

- [ ] 任意页面触发异步任务,右上角 badge +1
- [ ] 打开任务中心抽屉,显示运行中任务卡片
- [ ] 进度条平滑推进,current_step 文字实时更新
- [ ] milestone 用 🚩 图标显示在卡片下方
- [ ] 任务完成自动从"运行中"移到"最近完成",时长正确
- [ ] 任务失败显示错误消息
- [ ] 取消按钮可用,点击后任务在数秒内停止
- [ ] 刷新页面,运行中任务能正确恢复(因为状态在 DB)
- [ ] 同时跑多个任务(如同时触发全市场扫描 + VIX 回填),任务中心都能看到
- [ ] 9 个改造过的页面进度条都正常工作
- [ ] SchedulerTaskCard 在定时任务运行中时显示子步骤

### 9.3 日志验收

- [ ] `logs/app.log` 文件出现轮转(达到 10MB 时新建 `app.log.1`)
- [ ] akshare DEBUG 日志不再刷屏
- [ ] 日志行包含 `[task=xxxxxxxx]` 字段
- [ ] 异常堆栈完整(`logger.exception` 写入)
- [ ] LLM 调用耗时入库到 task_run_logs(以 milestone 或 info 形式)

### 9.4 回归验证

- [ ] 现有 `/api/tasks/<id>` 调用(老 scan_tasks UUID)仍返回正确数据(兼容层)
- [ ] 旧 `/api/sentiment/batch_analyze_status` 等端点仍可用(透传新接口)
- [ ] 回测页面绩效指标 / 交易明细仍正确(backtest_runs 表保留)

---

## 10. 关键决策点 — 供 review 评估

| # | 决策 | 推荐方案 | 备选 | 风险 |
|---|---|---|---|---|
| D1 | 表治理 | 新建 task_runs + 保留旧表(双写过渡) | 一次性迁移 / 扩展 scan_tasks | 推荐方案零迁移风险,但有"双表"短期复杂度 |
| D2 | 前端架构 | 全局 TaskCenter + UnifiedProgressBar 双视图 | 只做组件不做中心 | 推荐方案改动较大,但解决"看不到全局"痛点 |
| D3 | 实时推送 | v1 用统一轮询(单一全局 loop,2s) | SSE / WebSocket | 推荐方案最简,Flask 同步 worker 上 SSE 成本高 |
| D4 | scheduler_task_run 表存废 | 保留,仅作为 scheduler 视图;新代码读写 task_runs | 一次性合并到 task_runs | 推荐方案兼容现有 SchedulerTaskCard |
| D5 | backtest_runs 表存废 | 保留,作为业务结果表;task_runs 只存调度状态 | 完全废弃 | 推荐方案保留绩效指标的领域语义 |
| D6 | task_run_logs 写入开销 | 每个任务 5-20 条 milestone + 100-5000 条 info,SQLite 写入足够 | 用文件分片 / 引入 Redis | 全市场扫描 5800 条 info 写入约 10s,需要节流 |
| D7 | 日志 JSON 化 | 可选(`LOG_JSON=true`),默认仍是人类可读文本 | 强制 JSON | 推荐方案兼顾开发体验和未来 ELK 接入 |
| D8 | 任务取消 | 协作式取消(任务自己 `check_cancelled`) | 强制 kill 线程 | 推荐方案安全,但取消延迟取决于任务自检频率 |
| D9 | task_runs 历史清理 | v1 不做,任由表增长;v2 加 cron 清理 30 天前的 | 立即加清理任务 | v1 简化范围 |
| D10 | 兼容层端点存废 | 保留 `/api/sentiment/batch_analyze_status` 等老端点,内部透传 | 一次性删除 | 推荐方案避免破坏现有前端 |

**Reviewer 重点关注**:

- **D1**(表治理): 是否同意"新建 + 保留旧表"策略?如不同意,需要拍板"一次性迁移"还是"扩展旧表"
- **D2**(前端架构): 是否需要"任务中心"全局抽屉?如认为 overkill,可砍掉只保留组件
- **D3**(实时推送): 是否 v1 接受统一轮询的延迟(最多 2s)?如不接受,需要决定上 SSE
- **D6**(写入开销): 是否同意 milestone 全写、info 节流(每 5-10 条写一次)的策略
- **D8**(取消): 是否能接受协作式取消的延迟(数秒级)

---

## 11. 风险与回滚

### 11.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 高频写 task_run_logs 拖慢 SQLite | 中 | 中 | progress 节流(每 5 次写一次);milestone 全写但量小 |
| 双写期(scan_tasks + task_runs)数据不一致 | 低 | 低 | 用 try/finally 包裹两次写;不一致时优先以 task_runs 为准 |
| 任务取消时 ThreadPoolExecutor 内的子任务无法立即停 | 高 | 低 | 文档说明"取消延迟取决于任务自检频率";不承诺即时 |
| TaskRunner 异常处理覆盖不全,出现"running" 僵尸任务 | 中 | 中 | 加 cron 清理:启动时把 finished_at 为空且 started_at 超过 6h 的标 failed |
| 前端 TaskCenter 全局轮询失败后无重试 | 低 | 低 | axios 拦截器 + 退避重试 |
| 日志 task_run_id 注入不到 ThreadPoolExecutor 子线程 | 高 | 低 | contextvars 默认会传递到子线程,但需要测试验证;否则需要手动透传 |

### 11.2 回滚方案

- **后端**:git revert 改造提交;DB 中 task_runs / task_run_logs 表保留(无害);旧表数据完整
- **前端**:git revert,9 个组件/页面回到原状

**回滚成本评估**:中等。后端 TaskRunner 改造涉及 20+ 个文件,但都是机械替换;前端涉及 9 个组件,但 UnifiedProgressBar 是新组件不影响旧逻辑。

---

## 12. SPEC.md 更新计划

新增章节 **§12 异步任务与日志治理 (v1, 2026-06-09)**,内容包括:

- §12.1 目标与范围
- §12.2 数据模型(task_runs / task_run_logs schema)
- §12.3 TaskRunner 核心组件 API
- §12.4 kind 枚举注册表(18 种,见 §6.1.3)
- §12.5 HTTP API 端点(6 条,见 §6.4)
- §12.6 日志规范(轮转 / 噪声 / 注入 / 异常)
- §12.7 关键节点(milestone)规范
- §12.8 前端组件(UnifiedProgressBar / TaskCenter)
- §12.9 兼容层(旧 API / 旧表)
- §12.10 实现状态表(对应 Phase A/B/C/D 完成度)
- §12.11 已知限制(取消延迟 / SQLite 写入瓶颈)

同时更新 **CLAUDE.md** 新增"## 核心工作协议"补充条款:

> - **新增异步任务约束**:任何新增的后台任务(API 触发 / 定时触发 / 内部线程)必须使用 `core/task_runner.TaskRunner` 包裹,严禁新增内存状态 dict;严禁不返回 task_run_id 的异步 API

---

## 13. 工作量估算

| Phase | 工作量 | 关键产出 |
|---|---|---|
| Phase A 基础设施 | 2-3 天 | task_runs 表 + TaskRunner + 6 个 API |
| Phase B 后端改造(11 API + 8 后台 + 10 定时) | 3-4 天 | 所有异步任务接入 TaskRunner |
| Phase C 前端统一 | 2-3 天 | TaskCenter + UnifiedProgressBar + 9 组件改造 |
| Phase D 清理与文档 | 1 天 | 删除旧状态 + 更新 SPEC.md / CLAUDE.md |
| **合计** | **8-11 天** | 完整治理 |

如需缩减,可砍 Phase C 的 TaskCenter(只做 UnifiedProgressBar)缩减到 6-8 天。

---

## 14. 反对意见预期(reviewer 可能提出的质疑)

1. **"为什么不直接用 Celery?"** — 引入 Celery 需要 Redis/RabbitMQ broker,部署复杂度上升;当前规模(每天 ~50 次后台任务)用 SQLite + ThreadPoolExecutor 完全够用
2. **"双表(scan_tasks + task_runs)不是技术债?"** — 是,但比一次性迁移风险低;v2 可在 task_runs 稳定后删除 scan_tasks
3. **"全局轮询 2s 还是太慢"** — 如不接受,选 D3 的 SSE 方案,工作量 +2 天
4. **"为什么不用 logging.LoggerAdapter 而用 Formatter+contextvars?"** — LoggerAdapter 需要在每个 logger 调用处显式注入,侵入性大;contextvars+Formatter 是零侵入方案
5. **"milestone 写表会不会拖慢任务?"** — 单次 INSERT ~1ms,任务通常只有 5-20 条 milestone,可忽略
6. **"任务取消用线程标志位不是更直接吗?"** — DB 标志位的优势是跨进程 / 跨重启都有效;线程标志位重启后丢失

---

**END OF DESIGN DOC v1 (Draft)**
