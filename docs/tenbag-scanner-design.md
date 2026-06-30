# 十倍股早期信号扫描器 + 财报异动扫描器 — 设计书

> 状态：Draft（2026-06-30 起，特性分支 `feature/tenbag-scanner`，TDD 小步快跑）
> 口径约束：**输出是分层观察池 / 基本面雷达，不是买卖信号**（同 VIX 约束，前端与 API 文案严禁「买入/卖出」措辞）。

## 1. 背景与目标

两个高度相关的 idea 合并实现：

1. **十倍股早期信号扫描器** — 不预测涨十倍，而是多信号筛选「可能具备大牛股胚子」的公司，输出**分层观察池**。
2. **财报异动扫描器（基本面雷达）** — 全市场扫财报找异动信号，输出 公司/行业/核心变化/可能解释/风险/结论。

**合并关系**：异动扫描器 = 信号提取层；其产出喂给十倍股分层器。两者共享 DB 表 / task kinds / 数据抓取基础设施。

## 2. 模块边界

| 模块 | 职责 | 类型 | MVP |
|------|------|------|-----|
| M2 股价趋势分析器 | 月线趋势确认（大牛股月线先走出来） | 纯量化 | ✅ 首期 |
| 异动定量信号 | 营收/利润高增、毛利率改善、存货下降、合同负债上升、在建工程转固、应收风险、现金流跟上 | 定量（akshare 结构化财报） | ✅ 首期 |
| 分层器 | 规则分层 → 一/二/三级 + 排除池 | 确定性规则 | ✅ 首期 |
| M1 财报 PDF 解析器 | 新产品/产能/增持/机构覆盖等定性信号 | LLM（MiniMax M3） | 后续迭代 |
| M3 高景气行业 | 高景气赛道 + 产业链卡位 | 数据驱动 | 后续迭代 |

## 3. 信号定义

### 3.1 趋势信号（M2，纯量化）
- 月线 MA12 / MA24
- 月度创新高占比（近 N 月创 N 月新高的月数占比）
- 距 52 周高点回撤 %
- 月度放量（量比）
- 相对大盘强度 RS
- Weinstein Stage 2 平台突破判定
- `trend_regime`: `stage2_breakout` / `advancing` / `consolidation` / `downtrend`

### 3.2 异动信号（定量）
| 信号 | 来源 | 判定 |
|------|------|------|
| 营收高增 | 损益 | YoY ≥ 阈值 |
| 利润高增 | 损益 | YoY ≥ 阈值 |
| 毛利率改善 | 损益 | YoY/QoQ 升 ≥ N pct |
| 存货下降 | 资产负债表 | YoY/QoQ 降（需求旺盛去库存） |
| 合同负债上升 | 资产负债表 | YoY 升（订单前置） |
| 在建工程转固 | 资产负债表 | 在建工程降 + 固定资产升（产能投产） |
| 应收账款上升（风险） | 资产负债表 | YoY 升 > 营收增速（回款质量差） |
| 经营现金流跟上 | 现金流量表 | 经营现金流净额 / 净利润 ≥ 阈值 |

输出对齐用户异动扫描器模板：`{公司, 行业, 核心变化[], 可能解释[], 风险[], 结论}`。

## 4. 分层规则（确定性，纯函数）

`tenbag_pool_service.classify_pool(trend_signals, anomaly_signals, industry_signals=None) -> {tier, reasons}`

| Tier | 条件 |
|------|------|
| 一级（基本面明显变化） | ≥3 正向异动 + 无风险 + 趋势确认（stage2/advancing）+（M3 后）高景气 |
| 二级（逻辑性感业绩未兑现） | 趋势确认 + 1-2 个萌芽异动；或 ≥3 异动但趋势横盘（业绩待市场验证） |
| 三级（概念强财务弱） | 概念/趋势强（stage2 或 新高≥0.4 或 量比≥1.5）+ ≤1 个异动 |
| 排除（纯炒作） | 趋势破位（downtrend）+ 无异动；或 无异动且趋势未确认 |

判定顺序：排除(破位) → 一级 → 二级(横盘强异动) → 二级(趋势+萌芽) → 三级(概念强) → 排除(全无) → 兜底三级。

阈值参数集中可调，便于回测/审计。

## 5. 数据库 schema（新增 3 表）

```sql
CREATE TABLE IF NOT EXISTS tenbag_anomaly_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  report_date TEXT,
  signals_json TEXT,           -- 异动信号 dict
  score REAL,
  core_changes_json TEXT,      -- 核心变化列表
  risks_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(symbol, report_date)
);

CREATE TABLE IF NOT EXISTS tenbag_trend_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  signals_json TEXT,           -- 趋势信号 dict
  regime TEXT,                 -- stage2_breakout/advancing/consolidation/downtrend
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS tenbag_pools (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  pool_tier TEXT NOT NULL,     -- '1'/'2'/'3'/'exclude'
  reasons_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(snapshot_date, symbol)
);
CREATE INDEX idx_tenbag_pools_date_tier ON tenbag_pools(snapshot_date, pool_tier);
```

迁移范式：`init_db()` 内 `CREATE TABLE IF NOT EXISTS`（见 `database.py` vix_history 模式）。

## 6. task kinds

`backend/core/task_kinds.py` 新增：
- `tenbag_scan` — 十倍股/异动全市场扫描
- `tenbag_report_analyze` — 单股年报 PDF 深度分析（M1）
- `industry_prosperity_refresh` — 行业景气度刷新（M3）

全部走 `TaskRunner`（CLAUDE.md Phase A/B 约束）。

## 7. API 端点（计划）

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/tenbag/scan` | 触发扫描（异步，返回 task_id） |
| GET | `/api/tenbag/pools?tier=&date=` | 分层结果列表 |
| GET | `/api/tenbag/signals/<symbol>` | 单股异动+趋势信号详情 |
| GET | `/api/tenbag/health` | 生产线健康 |

## 8. 数据拉取接口「demo 实测先行」闸门

每个新建数据/PDF/LLM 拉取接口，集成前必须先写 `scripts/demo_tenbag_*.py` 实测，交用户 review：

1. 腾讯日 K（复用，demo 复跑确认）
2. akshare 资产负债表 `stock_balance_sheet_by_report_em` + sina 兜底
3. akshare 现金流量表 `stock_cash_flow_sheet_by_report_em`
4. 巨潮资讯 cninfo 年报 PDF（M1）
5. MiniMax M3 LLM 结构化提取（M1）

## 9. 复用点

- `financial_service._fetch_tencent_kline` — 日 K 取数
- `financial_service._fetch_financial_abstract` — 损益摘要（已有 TTM/季度 YoY/QoQ）
- `report_parser._get_llm` / `_strip_think` / `_fix_unescaped_quotes` / `_extract_json` — LLM + JSON 容错
- `core/task_runner.TaskRunner` + `scheduler.track_run` — 异步任务
- `top_picks_service` — MVP 候选池（不全市场，控制成本）

## 10. 实施步骤

见计划文件 `C:\Users\weizhou\.claude\plans\linked-sauteeing-marble.md`。每步收尾同步更新本设计书 + SPEC §14 + change.md。
