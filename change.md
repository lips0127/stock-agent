# Change Log

## 2026-08-31

### 修复调度器 cron 任务「出生即暂停、永不触发」（生产事故，服务器部署验证）

用户在服务器 `/tasks` 页质疑定时任务有效性，排查发现：**10 个调度任务中只有 forum_prefetch 在真实执行**（每 2h，11 次全成功），其余 8 个 cron 任务（daily_update/sentiment/vix/tenbag_scan/top_picks/indicators_recompute、universe 三个）部署 20 小时无一触发，DB `next_run_time` 全为 NULL。

**根因（两层）**：
1. `scheduler.init_scheduler` 以 `add_job(..., next_run_time=None)` 注册任务——APScheduler 3.x 中该参数为 None 的语义是「以暂停态添加」，不是「按 trigger 计算」。仅 forum_prefetch 显式传了 now 得以幸免。容器内 3.11.2 同款复现实锤。
2. 禁用任务的 `pause()` 原写在调度器 `start()` 之前，对 pending 任务不生效（start 时按 trigger 重算 next_run_time 覆盖暂停态）。修复前该分支从未被执行过（所有任务已被 next_run_time=None 提前暂停），故未暴露。

**连带发现**：容器时区为 UTC，cron 时刻按北京时间语义设计（如 daily_vix=16:30 收盘后），实际会在凌晨触发且 mon-fri 错位为北京周二至周六。

**修复**：
- `init_scheduler`：启用任务注册时省略 `next_run_time`；禁用任务在 `start()` 之后统一 `pause()`。
- `backend/Dockerfile`：运行时层装 `tzdata` 并固定 `TZ=Asia/Shanghai`（/etc/localtime + ENV 双保险）。
- 回归测试 `tests/test_scheduler_init.py`：① 启用 cron 任务注册后 next_run_time 必须非 None；② 禁用任务必须 paused（先红后绿）。
- SPEC §10 增补 cron 时区语义与注册契约。

**验证**：pytest 调度测试 5 用例通过；`server_ops.py deploy` 后服务器 DB `next_run_time` 全部落为北京时间具体时刻、容器日志时间戳 +08。

## 2026-08-30

### 产品收敛日：能力下线、新功能、安全部署与口径修复（main）

一次性收敛多线工作，`docs/SPEC.md` 同步重写为当前产品唯一事实源（能力分层 Core/Beta/Experimental/Removed 与各域契约）。

**知乎监控下线（Removed）**：
- 删除 `backend/api/routes/zhihu.py`、`backend/services/zhihu_{analyzer,service}.py`、`backend/services/email_service.py`、前端 `ZhihuMonitorView`/`ZhihuTimelineView` 及路由、`task_kinds.py` 知乎任务、调度与相关测试。原因：知乎反爬对作者动态接口确定性 403，免 cookie 通道不可行，维护成本与价值不成比例（SPEC §5）。

**自选股观察池（Core）**：
- 新增 `backend/api/routes/watchlist.py`、`backend/services/watchlist_service.py`、`frontend/src/views/WatchlistView.vue`；`/api/watchlist` CRUD + 带可信元数据的报价聚合，单独校验 JWT 边界（`tests/test_market_auth.py` 等）。

**VIX 大小盘拆分轨道（Beta）**：
- 新增 `backend/services/fear_greed_tracks.py`：上证50/沪深300/中证500/创业板/科创50 五条轨道，各轨道 IV 锚与价格同源；regime 一律按 trailing 252 日滚动百分位划分（point-in-time），落库 `vix_track_history`。

**安全与部署加固**：
- 新增 `backend/security_check.py`（生产就绪审计 CLI，entrypoint 强制执行）、安全响应头（CSP/HSTS）、登录限流；`.env.production.example` + `docs/DEPLOY.md` + 单容器三阶段构建（`backend/Dockerfile`，镜像内编译前端）；删除旧 `deploy/` 三件套；新增 GitHub Actions 质量门禁（`.github/workflows/quality.yml`）与 `requirements-dev.txt`、`scripts/verify.ps1`。

**前端视觉系统重构（2026-08-30）**：
- `frontend/src/styles/design-system.css` token 为唯一事实源：单一强调色、zinc 中性灰、等宽数字、克制动效；全部视图/组件迁移到新 token，新增 `ErrorState.vue`，删除 `GradientBlob.vue`。不改路由、接口与数据语义。

**股息率口径修复（fix）**：
- `stock_service.get_stock_metrics` 新增 400 天分红时效闸门：停发分红公司（振东制药 2021 年 10 派 27、万科 A FY2022 后停发等）的远古分红不得除以现价冒充当前股息率，修复仪表盘高股息榜 20%-60%+ 假股息率；口径与时点规则写入 SPEC §3.5；回归脚本 `scripts/test_dividend_sources.py`。实测：异常股归零，茅台 4.01%/神华 4.22%/双汇 5.83% 正常。

**现场治理**：
- 删除根目录 QA 截图（`*.png`）、`vr-test.js`、`scripts/debug_zhihu_pins.py`、旧日志与 ACL 损坏的 `.pytest_cache/`（已加入 `.gitignore`）。

**远程部署工具（补充）**：
- 新增 `scripts/server_ops.py`：腾讯云单容器一键部署与运维（status/deploy/logs/health/backup/exec）。连接信息读 `server.local.json`（gitignore），仓库只进占位符模板 `server.local.example.json`，真实 IP 与私钥路径绝不入库。代码传输走 `git archive`（服务器无需 GitHub 凭证）；构建改为服务器端 nohup 后台执行 + 轮询 `deploy.log`。
- `backend/Dockerfile` 三个构建阶段接入腾讯云镜像源（apt/pip/npm）——国内服务器直连官方源曾导致构建 30 分钟无法完成。

## 2026-07-01

### 十倍股/财报异动扫描器 — Step 0~2（feature/tenbag-scanner）

新增特性分支 `feature/tenbag-scanner`，合并开发「十倍股早期信号扫描器」+「财报异动扫描器（基本面雷达）」。本期完成基础设施 + 模块二 + 异动定量信号（MVP 三件套的前两件）。

**Step 0 — 基础设施**：
- 新设计书 `docs/tenbag-scanner-design.md`（模块边界/信号定义/分层规则/DB schema/task kinds/API/口径约束）。
- `task_kinds.py` 注册 `tenbag_scan` / `tenbag_report_analyze` / `industry_prosperity_refresh`。
- `database.py` 新增 3 表：`tenbag_anomaly_signals` / `tenbag_trend_signals` / `tenbag_pools` + 5 个 CRUD helper（`upsert_tenbag_anomaly` / `get_tenbag_anomaly` / `upsert_tenbag_trend` / `get_tenbag_trend` / `upsert_tenbag_pool` / `list_tenbag_pools`）。
- TDD：`tests/test_tenbag_db.py`（5 用例，先红后绿）。

**Step 1 — 模块二 股价趋势分析器**（`backend/services/tenbag_trend_service.py`，纯量化零依赖）：
- `compute_trend_signals(daily_bars, benchmark_bars=None)`：月线重采样、月线 MA12/MA24、日线 MA60/MA120、距 52 周高点回撤、月度创新高占比、月度放量量比、相对大盘强度 RS、regime 判定（`stage2_breakout` / `advancing` / `consolidation` / `downtrend`）。
- regime 主锚点用日线 MA60（短历史也可用），月线 MA12/24 作信息项。
- TDD：`tests/test_tenbag_trend.py`（9 用例）。实测 600519 真实数据 → downtrend / 回撤 -22.36%，符合预期。

**Step 2 — 财报异动定量信号**（`backend/services/tenbag_anomaly_service.py`）：
- `derive_anomaly_signals(financials)` 纯函数：营收/利润高增、毛利率改善、存货下降、合同负债上升、在建工程转固、应收风险、现金流滞后 → 输出 `{signals, core_changes, possible_explanations, risks, score, conclusion}`，对齐用户异动扫描器模板。按 report_date 排序兼容任意输入顺序。
- `fetch_balance_sheet_em` / `fetch_cash_flow_em` / `fetch_financials_em`：akshare EM 接口抓取，英文代号列归一化（`INVENTORY`→存货 等，2026-07-01 demo 实测确认）。复用 `financial_service` 损益摘要 + `_no_proxy` + `_full_symbol`。
- TDD：`tests/test_tenbag_anomaly.py`（9 用例，akshare 全 mock 不联网）。

**demo 实测先行闸门（用户强制要求）**：
- `scripts/demo_tenbag_kline.py`：腾讯日 K 实测通过（600519，366 根，字段完整）。
- `scripts/demo_tenbag_balance_sheet.py`：EM 资产负债表实测通过，确认列名为英文代号（`INVENTORY`/`CONTRACT_LIAB`/`CIP`/`ACCOUNTS_RECE`/`FIXED_ASSET`），自带 `_YOY` 同比列。
- `scripts/demo_tenbag_cash_flow.py`：EM 现金流实测通过，`NETCASH_OPERATE` 命中（茅台 2025 年报 ~615 亿）。
- ⚠️ EM 接口逐期抓取，单只 2-3 分钟，全市场不可行 → 候选池限定热门股池 top 50、财报仅取近 4 期（用户确认）。

**口径**：输出是观察池/基本面雷达，不是买卖信号（同 VIX 约束）。

**回归**：45 个测试全绿（tenbag_db 5 + tenbag_trend 9 + tenbag_anomaly 9 + task_runner 22）。

**待续**：Step 3 分层器、Step 4 API+调度、Step 5 前端、Step 6 PDF 解析器（需 demo 实测 cninfo+MiniMax）、Step 7 行业景气。

---

### Step 3 分层器（feature/tenbag-scanner）

`backend/services/tenbag_pool_service.py` `classify_pool(trend_signals, anomaly_signals, industry_signals=None) -> {tier, reasons}` 纯函数，确定性规则分层：
- 一级：≥3 正向异动 + 无风险 + 趋势确认（stage2/advancing）
- 二级：趋势确认 + 1-2 萌芽异动；或 ≥3 异动但横盘（业绩待市场验证）
- 三级：概念/趋势强（stage2 或 新高≥0.4 或 量比≥1.5）+ ≤1 异动
- 排除：趋势破位 + 无异动；或 无异动且趋势未确认

industry_signals 为 M3 预留（高景气加成仅影响 reasons）。TDD：`tests/test_tenbag_pool.py`（9 用例）。E2E 实测 600519（downtrend + 无异动 → 排除池）符合预期。54 测试全绿。

### Step 4 API + 异步任务 + 调度（feature/tenbag-scanner）

- `backend/services/tenbag_scan_service.py` `run_scan(task_runner, top_n=50, snapshot_date)`：编排候选池（`get_latest_top_picks` top50）→ 逐只 `_scan_single`（趋势→异动→分层→落库 3 表）→ 返回 `{scanned, failed, tiers}`。单只失败隔离；`_latest_report_date` 兼容升降序。TDD `tests/test_tenbag_scan.py`（4 用例，fetch 全 mock）。
- `backend/api/routes/tenbag.py`（蓝图 `tenbag_bp`，注册于 `app.py`）：`POST /api/tenbag/scan`（异步 TaskRunner 返回 task_id，防重 409，body `{top_n}`）、`GET /api/tenbag/pools`、`GET /api/tenbag/signals/<symbol>`、`GET /api/tenbag/health`。TDD `tests/test_tenbag_routes.py`（8 用例，含鉴权/scan 启动）。
- `scheduler.py` `daily_tenbag_scan_task`（`@track_run("daily_tenbag_scan")` + 函数级锁，工作日 17:00，长任务~2h）+ `_TASK_FUNCS` + `scheduler_config_service.JOB_REGISTRY`（cron 17:00 mon-fri）。
- 调度 kind=`daily_tenbag_scan`、手动 kind=`tenbag_scan`（双 kind 惯例同 vix）。
- SPEC §19.5.2/3/4 + design + change.md 同步。66 测试全绿（含 scheduler 回归）。

**待续**：Step 5 前端页面、Step 6 PDF 解析器（需 demo 实测 cninfo+MiniMax）、Step 7 行业景气。

---

## 2026-06-28

### VIX 算法 v6 / v6.1 — 多 ETF 合成生效 + 评审采纳调整

**症状**:
1. **多 ETF 合成从未生效（P0）**: `fetch_multi_etf_qvix` 判断 `"iv_close" in df.columns`，但 akshare 的 `index_option_300etf_qvix()` 等返回列名是 `close`（仅 50ETF 单独 rename 成 `iv_close`）。5 个 ETF 全被跳过，VIX 主体一直回退到单一 50ETF。
2. **平稳日不敏感**: VIX 主体是波动最低的宽基 50ETF，且 composite 里 VIX 实际贡献仅约 14%，微动被现货位置淹没。
3. **回填性能**: 每个交易日重拉腾讯全量历史（~50s/天），356 天回填 ~4h。
4. **回填污染**: 多 ETF 失败时仍写入降级数据，污染 Z-Score/百分位基线。

**修复（v6）**:
- 修列名 bug（`close`），5 ETF 真正合成；返回按日对齐的 synthetic 序列（prev/prev2/high/low）。
- 新增两个快信号：`_vix_change_to_score`（日变化率）、`_vix_swing_to_score`（日内振幅）。
- 腾讯历史进程级 TTL 缓存（→1800s）+ margin 缓存，回填 ~2s/天。

**结构性调整（v6.1，采纳 GPT/Gemini 双评审）**:
1. ETF 等权 → 代表性加权 50/300/500/创业板/科创 = 20/30/20/15/15%（按当日可用列归一化）。
2. 新增宽基/成长拆分 `vix_broad`/`vix_growth`/`vix_growth_premium`（区分系统性风险 vs 风格杀估值）。
3. composite = FG×60% + 现货×40%（提高前瞻话语权）。
4. 快信号 20%→15% 且变化率做 2 日平滑，回补给 VIX 水平（→30%）。
5. 日内振幅改「单 ETF 振幅% → 加权」（避免拼接非同时点极值造出虚假全天恐慌）。

**收尾**:
- `compute_today_snapshot(require_multi=True)`: 多 ETF 失败则跳过、保留旧值（不写降级数据）。
- `recompute_percentiles(window=252)`: 回填后按 point-in-time（往前 252 交易日）统一重算百分位/regime。
- 前端 `VixTrendChart` 仅信任 `vix_source=='multi_etf'` 行，`connectNulls:false`（无数据断线不画假直线）；回填按钮加确认弹窗。
- 数据边界拓展至 2025-01-01（356 交易日）；前端轮询改用 `getTask(taskId)`（旧 `*_status` 端点已 410）。

**为什么**: 这是「A股恐惧贪婪/风险偏好指数」而非严格 CBOE VIX 复制品。ML 自动定权重留待后续作为独立预测叠加层，不替换可解释的温度计主输出。详见 SPEC.md §11D/§11E。

---

### 修复 ST/*ST/退市股污染高股息排名

**症状**: 全量扫描把 ST、*ST、退市股纳入排名，得到 277%、128% 等异常股息率（股价崩塌但分红按往年正常水平计算）。

**修复（两层排除）**:

1. **判定函数** `stock_service.is_risk_stock(name)`: 名称含 `ST` 或 `退` 即判定为风险股。
2. **扫描层（根因）**: `get_all_a_share_codes` 按名称直接剔除 ST/退市，不再写入 DB。两个数据源（`stock_zh_a_spot`、`stock_info_a_code_name`）都覆盖。
3. **展示层（兜底）**: `/api/top_stocks`、`/api/all_stocks` 加 `name NOT LIKE '%ST%' AND name NOT LIKE '%退%'`，立即隐藏 DB 里已存在的历史脏行。
4. SPEC.md §8.2 + 开发注意事项同步更新。

**为什么不动算法**: ST/退市本身有退市风险，本就不该进选股池——加股息率上限是治标，会掩盖真问题。

---

### 新增「红利指数」轻量扫描导航与页面

**症状**: 红利指数扫描（`scan_type='index'`）仍能跑，但结果在 UI 上"消失"——一旦当日存在全市场扫描（`full`），`/api/all_stocks` 与 `/api/top_stocks` 优先返回 `full`，index 结果被掩盖无处可看。

**修复**:

1. **`/api/all_stocks` 新增 `scan_type` 参数**: `index|full` 时按该类型**自身最近一次**扫描日期取数（不再被当天 full 掩盖）；不传保持旧行为。
2. **新增 `DividendIndexView` 页面**（`/dividend-index`）: 表格复用全量扫描样式，header 含「运行红利指数扫描」按钮，提交 `/api/index_scan` 并接入底部进度条。
3. **侧边栏导航**: 辅助交易组、全量扫描下方加「红利指数」项（Coin 图标）。
4. **顺带修复 `ScanProgressBar` 标签 bug**: 原来只读 `task.type`，但 `/api/tasks/<id>` 返回 `kind`，导致**全市场扫描在轮询后被错标成"红利指数扫描"**。现在 `type` 与 `kind` 双兜。
5. SPEC.md §8.1 + 开发注意事项同步更新。

---

### 顺带修复 `frontend/src/components/stock/format.js` 缺函数头

**症状**: `dist/` 自 Jun 15 以来一直未更新——`npm run build` 早已失败（`StockHeaderCard.vue` 导入了 `sentimentTagType`，但该函数定义前一行 `changeClass` 闭合后剩 4 行孤立语句，缺 `export function ... {` 头）。

**修复**: 补回 `sentimentTagType` 函数头。`dist/` 重建后含 `DividendIndexView` chunk，可直接由 Flask 静态托管。