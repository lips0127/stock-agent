# Change Log

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