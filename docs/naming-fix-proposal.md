# 函数命名不一致修复方案

## 一、问题汇总

### 1. `full_market_scan` 双重语义冲突（最严重）

**文件**: `market_scan.py:77`

| 调用位置 | 调用函数 | 实际行为 |
|----------|----------|----------|
| `__main__` 直接执行 | `full_market_scan()` | 扫红利指数成分股 ~100 只 |
| `scheduler.py:41` | `full_market_scan()` | 扫红利指数成分股 ~100 只 |
| `ops.py` / API | `full_market_scan_all()` | 扫全部 A 股 ~5800 只 |

**问题**: `full_market_scan` 这个名字字面意思是"全市场扫描"，但实际只扫红利指数成分股。另一个真正扫全市场的函数叫 `full_market_scan_all`，反而用了 `_all` 后缀来区分。两者命名层级不对称，极易混淆。

---

### 2. `process_single_stock` 注释与实现语言不一致

**文件**: `market_scan.py:26`

函数体内使用中文 key（`"code"`, `"name"`, `"price"`），注释却写英文 "translating to English keys for DB"，自相矛盾。

---

### 3. `get_high_dividend_stocks_by_concept` 函数名失真

**文件**: `scanner_service.py:62`

函数名暗示"从概念板块获取高股息股票"，实际只是从红利指数成分股里取 TOP N，和"概念"毫无关系。

---

### 4. `stock_service.py:get_stock_metrics` 文档不完整

**文件**: `stock_service.py:119`

注释仅列举了 `名称、最新价、股息率` 三个返回字段，实际还返回 `每股分红` 和 `分红备注`。

---

### 5. `scheduler.py:daily_update_task` 任务命名失准

**文件**: `scheduler.py:29`

注释和函数名暗示"每日更新"，但调用的是红利指数扫描，远非"每日全市场更新"。

---

### 6. `/api/refresh` 与前端"刷新数据"按钮语义不匹配

**文件**: `ops.py:13` + 前端 `DashboardView.vue` / `LayoutView.vue`

| 端点 | 前端按钮文字 | 实际行为 |
|------|-------------|----------|
| `POST /api/refresh` | "刷新数据" | 调用 `manual_trigger()` → `daily_update_task` → `full_market_scan` → **红利指数成分股扫描 ~100 只** |
| `POST /api/full_refresh` | "全市场扫描" | 调用 `full_market_scan_all` → **全 A 股扫描 ~5800 只** |

**前端按钮命名是准确的**（"全市场扫描"对应 `/api/full_refresh`），但"刷新数据"按钮调用的 `/api/refresh` 实际行为是**红利指数扫描**，远非"刷新全部数据"。用户点击"刷新数据"时，心理预期是刷新大盘指数 + 全量扫描结果，实际只刷新了 100 只红利指数成分股。

---

### 7. `/api/top_stocks` 数据 scope 不一致

**文件**: `market.py:26` + 前端 `DashboardView.vue`

`GET /api/top_stocks` 从 `stock_daily_metrics` 表读取股息率最高的 N 条记录。前端 `DashboardView.vue` 显示这些为"高股息股票"。

**问题**：这里的"高股息"取决于最后一次扫描的 scope：
- 如果上次执行的是 `/api/full_refresh`（全 A 股），则 TOP 20 是全市场高股息
- 如果上次执行的是 `/api/refresh`（红利指数），则 TOP 20 仅来自 ~100 只红利指数成分股

`stock_daily_metrics` 表混合了两种扫描的数据，无法区分。

---

### 8. `/api/indices` 数据新鲜度问题

**文件**: `market.py:10` + `IndexCards.vue`

`GET /api/indices` 查询 DB 中 `MAX(date)` 的记录。这个 API 返回的是"最后一次扫描时写入 DB 的大盘指数"，但大盘指数实际上只有当扫描任务运行时才会写入 DB。页面上显示的"大盘指数"可能严重滞后（上次扫描是昨天，指数已变），用户无法感知数据是否实时。

---

### 9. `/api/logs` 日志范围误导

**文件**: `ops.py:107` + `TaskLogs.vue`

`GET /api/logs` 返回 `scheduler.py` 中模块级 `task_logs` 列表，仅记录定时任务和手动触发任务的日志。但前端 `TaskLogs` 组件显示在 Dashboard 页面下方，位置紧邻股票表格，容易让用户误以为这是"全站操作日志"。

---

## 二、后端修复方案

### 方案 A（推荐）：重命名 + 调整职责边界

#### Step 1 — `market_scan.py` 函数重命名

| 原函数名 | 新函数名 | 说明 |
|----------|----------|------|
| `full_market_scan` | `scan_dividend_index` | 明确只扫红利指数成分股 |
| `full_market_scan_all` | `scan_all_a_shares` | 明确全量 A 股扫描 |

#### Step 2 — `scheduler.py` 调整

`scheduler.py:41` 调用的函数名同步改为 `scan_dividend_index`。`daily_update_task` 的注释改为"每日红利指数扫描任务"。

#### Step 3 — `process_single_stock` 注释修正

删除错误英文注释，或改为准确的中文注释。

#### Step 4 — `scanner_service.py` 函数重命名

| 原函数名 | 新函数名 | 说明 |
|----------|----------|------|
| `get_high_dividend_stocks_by_concept` | `get_top_dividend_stocks` | 去掉误导性的 "by_concept" |

#### Step 5 — `stock_service.py:get_stock_metrics` 注释补全

补充完整的返回字段列表（名称、最新价、股息率、每股分红、分红备注）。

---

### 方案 B（保守）：仅修复注释，不动函数名

- 修正所有函数的 docstring，准确描述实际行为
- 在 `full_market_scan` 函数开头加注释，明确说明"当前仅扫描红利指数成分股"

---

## 三、前后端语义对齐修复

### 3.1 `/api/refresh` 端点重命名

**问题**: 前端"刷新数据"调用 `/api/refresh` 实际只扫 ~100 只红利指数成分股。

**建议**: 将 `/api/refresh` 重命名为 `/api/index_scan`（红利指数扫描），前端 `api/index.js` 中的 `refreshData` 改名为 `refreshIndexStocks`，LayoutView 中的按钮文字改为"刷新红利指数"。

### 3.2 `/api/top_stocks` 增加 scan_type 过滤

**问题**: `stock_daily_metrics` 表混合了两种扫描的数据。

**建议**: 在 `stock_daily_metrics` 表增加 `scan_type` 字段（`'full'` 或 `'index'`），写入时区分来源。查询 TOP 20 时可按 `scan_type = 'full'` 过滤，保证全市场 TOP 20 语义一致。

### 3.3 `/api/indices` 大盘指数实时抓取

**问题**: 大盘指数从 DB 读取，可能是陈旧数据。

**建议**: 新增 `/api/indices/live` 端点，实时从新浪抓取大盘指数。`IndexCards.vue` 在 `onMounted` 时调用此端点而非从 DB 读取。

### 3.4 日志范围说明

**建议**: 在前端 `TaskLogs.vue` 组件的 header 处增加说明文字："仅显示扫描任务日志"，避免用户误以为这是全站日志。

---

## 四、影响范围评估

| 文件 | 改动方式 | 影响范围 |
|------|----------|----------|
| `market_scan.py` | 重命名两个函数 + 修正注释 | 仅本文件内部 |
| `scheduler.py` | 更新调用函数名 | 间接：定时任务自动扫描 |
| `ops.py` | 更新 API 路由注释 | API 层，路由路径不变 |
| `scanner_service.py` | 重命名 + 修正注释 | 本文件 + `market_scan.py` 调用处 |
| `stock_service.py` | 仅修正 docstring | 无影响，仅文档 |
| `frontend/src/api/index.js` | 重命名 `refreshData` | 前端 API 封装，调用方同步 |
| `frontend/src/views/LayoutView.vue` | 更新按钮文字 | 前端 UI |

---

## 五、推荐路径

1. **Step 1**: 修复后端命名问题（`market_scan.py`、`scheduler.py`、`scanner_service.py` 函数重命名）
2. **Step 2**: 修正 `stock_service.py` docstring
3. **Step 3**: 前后端语义对齐（`/api/refresh` 重命名、`stock_daily_metrics` 增加 `scan_type` 字段、大盘指数实时抓取）
4. **Step 4**: 更新 `docs/SPEC.md` 中受影响的函数名和 API 描述
