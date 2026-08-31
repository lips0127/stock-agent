# 个人 A 股研究与风险辅助看板：当前产品规格

> **文档状态：当前事实源（canonical）**
> **更新时间：2026-08-30**
> **适用分支：当前工作区实现**

## 1. 文档权威性与维护规则

本文件定义当前已发布、在测和已移除能力的边界，是产品、接口、页面与运维行为的唯一当前事实源。

设计历史、已废弃方案和阶段性实验记录不构成当前产品承诺；索引见第 16 节。

任何功能开发、接口改动、数据口径变化、调度行为变化或页面发布前，必须先核对本文件。

若实现与本文件不一致，提交者必须在同一次变更中更新本文件，或明确把实现标为实验且不接入发布页面。

“已存在代码”不自动等于“已发布能力”。能力状态以第 5 节为准。

## 2. 产品定位

### 2.1 目标

本产品是供个人使用的 **A 股研究与风险辅助看板**。

它帮助用户查看数据证据、市场与个股风险状态、研究候选池，以及异步任务的运行状况。

产品优先级是：数据可追溯、口径诚实、失败可见、页面可操作、运维可诊断。

### 2.2 目标用户

- 有自主判断能力、需要集中查看 A 股研究材料的个人用户。

- 愿意区分原始数据、加工指标、实验结果和主观决策的用户。

- 需要在收盘后运行扫描、查看任务和复核数据质量的维护者。

### 2.3 非目标

以下均不属于本产品的当前或隐含能力：

- 券商接入、资金划转、委托下单、自动执行或跟单。

- 自动交易器、组合执行器、仓位管理器或风控执行器。

- 个性化投资建议、收益承诺、确定性预测或“必买/必卖”结论。

- 将未经严格样本外验证的指标、模型或候选池描述为交易信号。

用户的投资判断、交易决策和风险承担始终在产品之外。

## 3. 数据可信原则

### 3.1 每一项可见数据都应回答六个问题

| 维度 | 必须可追溯的含义 |
| --- | --- |
| source | 数据来自哪个外部源、缓存或计算过程。 |
| as-of | 数据所代表的市场时点、报告期或快照日期。 |
| freshness | 拉取、缓存或计算的时间，以及相对新鲜度。 |
| coverage | 覆盖范围、成功/失败/跳过数量和缺失条件。 |
| degraded | 是否使用缓存、降级源、部分数据或过期数据。 |
| error | 失败原因、影响范围和可重试性；不得伪装成正常结果。 |

新增 API 或页面必须优先补齐这些元数据；无法提供时要明确标记“未知”，不能用空白暗示正常。

### 3.2 时点一致性

研究、回填和模型评估必须遵守 point-in-time 原则：在任一历史时点，只能使用当时已经可获得的数据。

公司行动、财报发布日期、指数成分调整、行情修订和缓存回填都可能改变可得性，不能以最终版本覆盖当时可得版本而不留说明。

任何历史曲线都必须区分：真实历史快照、事后重算、in-sample 回放和 walk-forward 样本外结果。

### 3.3 失败与降级

外部源不可用、反爬、解析失败、数据不足或模型未训练时，接口和页面必须返回可见的失败、降级或不可用状态。

异步任务不得把部分失败、异常吞掉或“空结果”写成成功；至少要记录状态、失败原因、影响数量和可继续操作。

缓存可用于提升可用性，但页面必须显示缓存时点，且不得把缓存数据标为实时。

东方财富股吧（guba）详情页存在速率型反爬（2026-08-31 实测定性）：持续高速抓取后返回约 2.8KB 的「身份核实」引导壳（静默 JS 挑战页），列表页与详情页同受影响。自然冷却需数小时；真实浏览器访问一次即自动通过挑战并种下「已验证」访客 cookie，脚本携带该新鲜 cookie 可立即恢复（`tools/guba_cookie_harvest.py` 采集到 `$CACHE_DIR/guba_cookies.json`，服务侧 mtime 热加载，约 1 分钟生效，无需重启；cookie 属反爬凭证，禁止提交 Git 或写入日志）。抓取层的对应约束为详情页全局节流、引导壳退避重试与周期探测自愈；正文补抓限时间窗口和单轮数量上限，避免积压全量补抓把源打挂。正文缺失属 degraded 而非故障关闭，帖子列表/标题在列表页未被墙时不受影响。

### 3.4 页面数据状态

每个 Core 或 Beta 数据区域必须有明确且互斥的呈现状态，而不是用空表格或默认数值掩盖问题。

- **loading**：请求尚未完成；不得展示上一次结果为本次实时结果。

- **ready**：数据可用；同时显示 source、as-of 与 freshness。

- **stale**：仅有过期缓存；显示缓存时点、更新失败原因和刷新入口（如适用）。

- **partial**：覆盖不完整；显示预期范围、成功数、失败数和被排除范围。

- **degraded**：已切换数据源或计算降级；显示原始失败与实际使用来源。

- **unavailable**：没有可安全呈现的数据；显示可理解的错误与后续操作，不伪造零值。

前端不得依据“数组非空”推断数据可靠，也不得因单个子域失败而把整个聚合响应误标为成功。

服务端对聚合结果应尽量让每个子域独立携带状态，以便页面保留可用证据并如实暴露缺失。

### 3.5 市场扫描指标口径（2026-08-30 修订）

`stock_daily_metrics` 是扫描时点快照（source=腾讯/新浪行情 + 东方财富分红明细），页面必须显示扫描日期，不得表述为实时。

- **股息率** = 最近一个有年报分红的完整财年（含同财年中期分红）每股现金分红 ÷ 最新价；无完整财年年报时回退最近一次半年报分红。

- **分红时效闸门**：最近一次分红证据（已实施的股权登记日，未实施方案的最新公告日）距今超过 400 天即视为「当前不分红」，股息率记 0，个股接口以 `dividend_note` 标注最后分红日期。停发分红公司（多为基本面恶化、股价已大幅下跌）的远古分红记录不得除以现价冒充当前股息率，也不得进入高股息排名——否则 2021 年 10 派 27 的振东制药、FY2022 后停发的万科 A 这类公司会以 20%-60%+ 的假股息率占据榜单前排（2026-08-30 修复的实际案例）。

- **ST/\*ST/退市股**：扫描层按名称剔除（`is_risk_stock`），展示层 SQL 按名称兜底过滤；其崩塌股价叠加历史分红会产生极端假股息率。


## 4. 当前架构

### 4.1 运行结构

```text
开发：浏览器 ──> Vite :5173 ── /api/* ──> Flask :5000 ──> SQLite / 外部数据源
                         ^                     |
                         |                     +── TaskRunner / APScheduler（同一进程）
                         |
                Flask 可自动启动并 302 到 Vite

生产：浏览器 ──> 单容器（Docker）Flask / Gunicorn :5000 ──> SQLite / 外部数据源
                     └──> 容器内 frontend/dist 静态文件（构建阶段编译）
```

后端为 Python Flask；前端为 Vue 3、Vue Router、Pinia、Element Plus 和 ECharts；持久化为 SQLite。

主要外部数据与内容源包括 AkShare、Sina、Tencent、EastMoney、东方财富股吧及可选 LLM 服务。

这些来源均可能有延迟、限流、口径差异或不可用情况，因此不构成市场真值保证。

### 4.2 代码责任边界

| 区域 | 当前责任 |
| --- | --- |
| `backend/api/app.py` | Flask 工厂、蓝图注册、开发期 Vite 代理与静态回退。 |
| `backend/api/routes/` | HTTP 契约、鉴权和参数校验；不应承载复杂数据计算。 |
| `backend/services/` | 数据获取、缓存、扫描、研究计算、解析和调度任务业务。 |
| `backend/core/database.py` | SQLite 初始化、迁移兼容和持久化访问。 |
| `backend/core/task_runner.py` | 异步任务的生命周期、进度、日志与协作式取消。 |
| `backend/services/scheduler.py` | 当前进程内 APScheduler 的注册和任务函数。 |
| `frontend/src/` | 受登录保护的 Vue 页面、状态管理和 API 调用。 |

## 5. 能力状态分层

| 层级 | 当前范围 | 发布与表述约束 |
| --- | --- | --- |
| Core | 登录、仪表盘、个股/股息数据浏览、红利指数扫描、自选股观察池、统一任务查看。 | 可作为日常看板基础；仍需显示数据时点和失败状态。 |
| Beta | 舆情、恐慌贪婪指数（VIX 域）、调度配置、财报解析。 | 可供试用和复核；口径、覆盖和外部源失败必须可见。 |
| Experimental | VIX2/v8.1（仅后端）、十倍股/财报异动扫描、因子研究性输出。 | 不得作为交易信号、预测承诺或默认发布页承诺。 |
| Removed | strategy、backtest、portfolio、execution、risk 框架及其页面/API；知乎监控（zhihu）及其页面/API/调度/通知链路。 | 不得在当前导航、API 文档或能力描述中恢复为现状。 |

策略、回测、组合、执行和风控框架已在 commit `17de516` 删除。

知乎监控模块（页面 `/zhihu`、`/zhihu/timeline`，API `/api/zhihu/*`，调度任务 `zhihu_check`，以及 `email_service` 邮件通知链路）已于 2026-08-30 移除：知乎反爬对作者动态列表接口返回确定性 403，登录 cookie 无法改变结果，免 cookie 抓取通道不可行，人工维护成本与模块价值不成比例。

旧资料中的 `StrategiesView`、`BacktestView`、`PortfolioView`、`/api/backtest` 与 `/api/quant` 均不是当前能力，新增工作也不得依赖它们。

## 6. 当前前端信息架构

前端真实路由以 `frontend/src/router/index.js` 为准；除 `/login` 外，以下页面均在登录布局内。

| 路由 | 页面 | 能力状态 | 用户可见目的 |
| --- | --- | --- | --- |
| `/dashboard` | Dashboard | Core | 汇总市场、候选池和任务入口。 |
| `/stocks` | Stocks | Core | 浏览全市场或扫描产出的个股数据。 |
| `/dividend-index` | DividendIndex | Core | 查看红利指数成分与扫描结果。 |
| `/watchlist` | Watchlist | Core | 个人自选股观察池：管理关注代码、备注与实时报价浏览。 |
| `/scan/:taskId` | ScanProgress | Core supporting route | 查看单次扫描进度与失败。 |
| `/sentiment` | Sentiment | Beta | 管理股吧舆情、指标、审计和候选观察。 |
| `/vix` | Vix | Beta | 查看恐慌贪婪指数（v7 构造分口径，0=极度恐慌、100=极度贪婪），可经「聚合 / 大小盘拆分」切换到五条单指数轨道（上证50/沪深300/中证500/创业板/科创50）同屏对比；实验内容不下发页面。 |
| `/tasks` | TaskScheduler | Core / Beta operations | 查看任务、日志、取消和调度配置。 |
| `/financial-report` | FinancialReport | Beta | 解析报告文本并辅助查看财务材料。 |

不存在已发布的十倍股页面或导航入口。

十倍股扫描虽已注册后端蓝图，但仅为 backend-only experimental，除非单独完成产品验收，不得把它接入发布 UI。

### 6.1 前端视觉设计系统（2026-08-30 重构）

前端视觉语言以 `frontend/src/styles/design-system.css` 的 token 为唯一事实源，本次重构只改表现层，不改变路由、接口与数据语义：

- 单一强调色 electric blue（`--color-accent: #2563eb`）；A 股红涨绿跌（rose/emerald）与 amber/red 状态色为语义专用，不与主色混用。

- 中性灰只有 zinc 一族；浅色为唯一主题（暗色模式未发布，不得在页面内自行反转主题）。

- 数字呈现统一等宽字体 + tabular-nums（`.num` 工具类）；圆角锁为控件 8 / 卡片 12 / 对话框 16。

- 动效刻度克制：仅 transform/opacity 过渡，全局遵守 `prefers-reduced-motion`。

- 数据状态呈现遵守 3.4 节；`.state-badge` 与 loading/empty/error 组件为标准呈现形态。

## 7. VIX 与 VIX2 实验边界

`/vix` 页面的唯一主指标是**恐慌贪婪指数**（2026-08-30 页面改造）：取 v7 构造真实情绪分的贪婪方向口径 `fear_greed_v7`（= 100 − fear_truth，0=极度恐慌、100=极度贪婪）。regime 标签与解读必须按近 252 个交易日滚动百分位划分（<10% 极度恐慌、10-30% 恐慌、30-70% 中性、70-90% 贪婪、>90% 极度贪婪），不得按绝对分数固定分档——v7 构造分的绝对水平整体偏高（历史中位数约 88），固定阈值会把多数交易日误标为贪婪。合成 VIX、ETF IV、RV、PCR、融资余额、涨跌停等仅作为底层证据披露；v6.1 FG、composite 合成、VIX2 拟合分等其余情绪读数不再下发 `/vix` 页面，页面不得并列展示多个互相竞争的情绪读数。本页是风险观察和数据展示能力，不是买卖指令。

**大小盘拆分视角**（2026-08-30 第二批改造，同日两次按用户反馈修订）：`/vix` 页面用**一个「聚合 / 大小盘拆分」切换项**组织：聚合态只显示单一恐慌贪婪指数（`fear_greed_v7`）；拆分态**同屏**显示五条单指数轨道——上证50、沪深300、中证500、创业板、科创50（`vix_track_history`，date+track 主键），各轨道读数与走势并列对比。轨道复用 v7 构造真实情绪分的**同一构造与权重**，且**每条轨道的 IV 锚与价格同源、一一对应**：上证50→50ETF 期权 QVIX + 上证50 指数、沪深300→300ETF、中证500→500ETF、创业板→创业板ETF、科创50→科创50ETF，不存在跨品种代替口径。regime 一律按各自 trailing 252 日滚动百分位划分（point-in-time），不得用固定阈值。v7 构造的分量明细（价格回撤/跌停广度/IV 飙升/IV 水平）只落库并随 API 下发，**不再在页面展示**（用户判定分量原值不可读、无动作价值）。拆分轨道是同一构造在不同指数上的观察视角，不是新模型，不得表述为预测或交易信号。

**数据完整性与任务可见性约束**（2026-08-30）：VIX 快照只允许写入交易日——非交易日触发重算时必须自动落到最近一个交易日，历史数据中不得残留非交易日行。前端加载 `/vix` 时若最新快照距今超出容差或 DB 行数不足以覆盖所选窗口，必须如实提示并自动触发缺口回填（skip_existing），不得静默展示断档曲线。重算与回填是异步任务：页面必须持续展示任务进展（当前步骤、耗时、逐日进度），刷新或重开页面后必须通过 `GET /api/tasks/active` 恢复进行中任务的展示；后端对同 kind 的重复提交返回 409 并附带进行中 task_id，前端收到 409 时应接管该任务而不是报错了事。

**未来因子审计**（2026-08-30，覆盖总体 v7 与五条拆分轨道全链路）：代码层结论——所有派生量（60 日回撤、均线/动量体制门控、IV 5 日变化率、IV 252 日分位、VIX Z-Score、RV 窗口、跌停家数/PCR/融资余额）均为 trailing 窗口或当日盘后数据；回填路径对所有外部源做 `as_of` 逐日截断，Z-Score 与轨道瞬时百分位取 `date < 当日` 的严格历史；落库的滚动百分位（fg7/large/small/track/IV 分位）为 trailing **含当日自身** 的 self-inclusive 口径（属定义选择，与前视泄漏无关）。实证抽查：4 个抽样日仅用 `date ≤ 当日` 数据复算 fg7 百分位，与存储值全部一致；2026-07-15 回填行的 `iv_50etf` 与 `margin_balance` 与「截至当日可得」的复算值完全一致。已披露边界：① 数据商可能事后修订历史序列，回填值依赖当前拉取的全量序列、未保留原始时点快照（严格 PIT 数据库层面的局限，非代码泄漏）；② 回填模式下总体 v7 的跌停广度分量缺失（权重分摊），与 live 重算路径的分量构成存在跨期差异，曲线长程比较时需注意；③ PCR 等当日数据可能延迟发布，后续重算以同日数据补全，属同日补全而非未来数据。

VIX2/v8.1 自 2026-07-01 起处于未提交在研实验状态；2026-08-30 页面改造后 VIX2 结果不再出现在 `/vix` 页面（`Vix2TrendChart` 组件已移除），仅保留后端接口与数据。其代码、训练和回填均不等于已发布功能。

VIX2 的主指标不得宣传或暗示预测能力、胜率、可交易性或收益提升。

任何 VIX2 结论进入 Beta 或 Core 前，必须同时满足以下验收：

- 严格按时间顺序进行 walk-forward OOS 验证，而不是只报告随机切分或全样本结果。

- 每个预测点都可审计训练 cutoff，证明未使用预测日之后的数据、标签、修订值或未来成分信息。

- 回填曲线明确标识训练窗口、预测窗口、数据可得时点和缺失/跳过日期。

- 与简单基线比较，例如常数、滞后值或朴素风险状态；不能只与自身训练集比较。

- 报告样本量、窗口、指标、置信不确定性、失效区间和复现命令。

- 未达到上述标准或结果不稳定时，结论必须标记为 **“无稳健预测力”**。

## 8. 后端蓝图与数据域

| 蓝图/域 | 路径前缀或代表接口 | 责任 | 状态 |
| --- | --- | --- |
| Auth | `POST /api/login` | 凭证校验与 JWT 签发。 | Core |
| Market / Stock | `/api/indices`、`/api/top_stocks`、`/api/stock/*` | 市场指数、股息与个股数据。 | Core |
| Watchlist | `/api/watchlist` | 自选股观察池 CRUD 与聚合报价；报价带 source/as-of/coverage/degraded。 | Core |
| Stock dashboard / intraday | `/api/stock/<symbol>/dashboard`、`/api/market/intraday` | 公司增强聚合和分时数据。 | Core / Beta |
| Ops / Tasks | `/api/index_scan`、`/api/full_refresh`、`/api/tasks/*` | 手工扫描、统一任务状态和日志。 | Core |
| Scheduler | `/api/scheduler/*` | 调度配置、启停和运行记录。 | Beta operations |
| Sentiment | `/api/sentiment/*` | 股吧抓取、LLM 分析、审计、指标与全市场观察。 | Beta |
| VIX | `/api/vix/*` | VIX、历史、风险观察及异步重算/回填。 | Beta |
| VIX2 | `/api/vix2/*` | 实验模型、训练和 walk-forward 回填。 | Experimental |
| Financial | `/api/financial/*` | 报告解析与财务资料聚合。 | Beta |
| Tenbag | `/api/tenbag/*` | 后端观察池和财报异动扫描。 | Experimental; no released UI |

## 9. 数据库边界

SQLite 数据库文件为 `stocks.db`；容器运行时由 `CACHE_DIR` 决定位置，Docker 当前使用 `/data` 卷。

当前数据库约有 25 张表，按下列业务域维护；本规格不复制逐列 schema，以 `backend/core/database.py` 为实现依据。

| 数据域 | 主要表/对象 | 用途 |
| --- | --- | --- |
| 身份 | `py_users` | 本地用户凭证。 |
| 市场与扫描 | `stock_daily_metrics`、`market_indices`、`scan_tasks` | 股票指标、指数快照和旧扫描兼容记录。 |
| 舆情 | `sentiment_config`、`forum_posts`、`sentiment_scores`、`sentiment_post_labels`、`sentiment_filters`、`sentiment_indicators`、`sentiment_top_picks` | 监控配置、原始内容、分析、审计和派生指标。 |
| 全市场舆情 | `sentiment_universe_*` | 指数、成分、作业、分数和聚合。 |
| VIX | `vix_history`、`vix_track_history`、`vix2_history` | 风险快照、大小盘拆分轨道、历史与实验性 VIX2 结果。 |
| 调度与任务 | `scheduler_task_config`、`scheduler_task_run`、`task_runs`、`task_run_logs` | 调度配置/运行和统一异步任务生命周期。 |
| 财报 | `financial_reports_cache`、`report_parse_history` | 财务资料缓存与报告解析历史。 |
| 自选股 | `watchlist` | 个人观察池：代码、名称、备注与排序；单用户产品不设用户隔离。 |
| 十倍股实验 | `tenbag_anomaly_signals`、`tenbag_trend_signals`、`tenbag_pools` | 实验性异动、趋势与观察池快照。 |

数据表是内部持久化实现，不是对外 API 契约；页面和服务不得绕过数据质量标识直接把表中旧记录渲染为实时结论。

知乎监控移除后，`zhihu_*` 表不再由 `backend/core/database.py` 创建；已有数据库文件中的遗留 zhihu 表仅作历史数据留档，不接入任何当前代码路径，也不得作为恢复该模块的依据。

## 10. 异步任务与调度约束

`TaskRunner` 是新异步任务的统一生命周期入口，持久化 `task_runs` 与 `task_run_logs`，提供进度、milestone、失败信息和协作式取消。

新异步能力必须返回 `task_id`，客户端通过 `GET /api/tasks/<task_id>` 和 `GET /api/tasks/<task_id>/logs` 观察状态；不要新增私有轮询协议。

任务状态至少包括运行中、成功、失败、已请求/已完成取消；结果应保留失败数量和可诊断错误。

任务线程目前由 Web 进程内启动，进程重启不会继续执行中的工作；数据库只能保留运行记录，不能提供分布式队列语义。

APScheduler 当前也运行在 Flask 进程内，调度配置和运行记录可持久化，但调度器本身不是单例服务。

Gunicorn 多 worker 会各自初始化 APScheduler，可能导致同一任务重复执行。这是 P0 风险；修复前生产部署必须限制为单调度实例，或引入独立、带互斥保证的调度进程。

调度任务和手工任务都必须防止同类长任务重叠，并记录 skipped、failed 或 cancelled，而非静默返回成功。

调度 cron 时刻（hour/minute/day_of_week）按 **Asia/Shanghai** 语义解释：生产容器固定 `TZ=Asia/Shanghai`（tzdata），`/tasks` 页与任务历史中的时间均为北京时间。启用状态的调度任务注册后必须带 trigger 计算出的 `next_run_time`；APScheduler 3.x 中 `add_job(next_run_time=None)` 的语义是「以暂停态添加」，禁用任务须在调度器 start() 之后显式 pause（2026-08-31 修复：上述两点曾被写反，导致 8 个 cron 任务出生即暂停、永不触发，回归见 `tests/test_scheduler_init.py`）。

## 11. API 契约与鉴权

### 11.1 公共接口

只有以下 HTTP 接口可在无 JWT 时访问：

| Method | Path | 契约 |
| --- | --- | --- |
| `POST` | `/api/login` | 接收用户名和密码；认证成功后返回 JWT。此为唯一 canonical 登录接口。 |
| `GET` | `/health` | 存活检查；不得泄露配置、凭证或内部数据。 |

### 11.2 受保护业务接口

除第 11.1 节外，所有业务 API 必须要求 `Authorization: Bearer <JWT>`，包括读取市场数据、任务、调度、舆情、VIX、财报和实验接口。

鉴权失败返回 `401`；不存在资源返回 `404`；冲突的并发任务返回 `409`；参数错误返回清晰的 `4xx`，而非模糊成功响应。

### 11.3 按域的接口约束

| 域 | 代表接口 | 契约要点 |
| --- | --- | --- |
| 市场 | `GET /api/indices`、`/api/indices/live`、`/api/top_stocks`、`/api/all_stocks` | 区分缓存/实时来源、快照时点和筛选范围。 |
| 个股 | `GET /api/stock/<symbol>`、`/api/stock/<symbol>/dashboard` | 组合结果中每个子域可独立失败并显式标记。 |
| 扫描与任务 | `POST /api/index_scan`、`/api/full_refresh`、`GET/POST /api/tasks/*` | 创建异步任务后使用统一 `task_id` 查询。 |
| 调度 | `GET/PATCH/POST /api/scheduler/configs/*` | 修改配置必须记录操作者和生效结果。 |
| 舆情 | `/api/sentiment/*` | 原帖、分析、审计、指标和候选结果须区分来源与生成时间。guba 详情页受速率型反爬约束：抓取层带全局节流、引导壳退避重试与周期探测自愈（2026-08-31 起）；`/api/sentiment/circuit_status` 的 `cookie_stale` 字段语义为「反爬降级中」，恢复走自然冷却或热加载采集 cookie（`tools/guba_cookie_harvest.py`），正文缺失时帖子标题仍可用。 |
| 风险观察 | `/api/vix/*`、`/api/vix2/*` | VIX2 全程标注实验和验证状态。 |
| 财报 | `POST /api/financial/parse`、`/api/financial/analyze` | 解析结果是研究辅助，保留来源文本/报告期说明。 |
| 自选股 | `GET/POST /api/watchlist`、`PATCH/DELETE /api/watchlist/<code>` | 报价聚合必须区分成功/失败子项并携带 as-of；仅研究浏览，不构成交易信号。 |
| 十倍股 | `/api/tenbag/*` | 后端实验观察池，不等同于前端发布功能或买卖信号。 |

## 12. 安全与隐私要求

以下为不可妥协的发布要求：

- 日志不得记录密码、JWT、`Authorization` header、Cookie、SMTP secret、完整敏感请求体或完整敏感响应体。

- 生产环境必须配置固定、强随机的 `JWT_SECRET`；不得依赖进程内随机密钥。

- 生产环境必须设置非默认管理员用户名和强密码；不得使用示例凭证。

- 生产环境必须限定 `CORS_ORIGINS` 到明确受控的来源，不能使用通配符。

- `.env`、浏览器 Cookie、SMTP 凭证和第三方密钥不得提交到 Git、响应或任务日志。

- 管理型写操作、触发任务和邮件测试必须走 JWT 鉴权；只读不构成公开接口例外。

安全模块（2026-08-30 落地）：

- **安全响应头**：`install_security_headers` 为所有响应附加 `X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy`；HTML 文档另加 CSP（脚本限 `self`、禁 iframe 嵌套）；`ENABLE_HSTS=true` 时下发 HSTS。

- **登录防爆破**：`/api/login` 每 IP 限流 `LOGIN_RATE_LIMIT_PER_MINUTE`（默认 10/分钟），限流器线程安全且桶数有界。

- **生产就绪审计**：`python -m backend.security_check` 校验 JWT_SECRET 强度、管理员默认值、CORS 通配符/本机来源与 DEBUG；容器 entrypoint 启动前强制执行，报告不回显任何密钥值。

- **部署契约**：compose 以 `${VAR:?}` 强制注入四个生产凭证；单容器镜像在构建阶段内编译前端产物（`backend/Dockerfile` 三阶段），部署步骤见 `docs/DEPLOY.md`。

遗留的弱配置仅允许存在于本地开发（`backend/config.py` 默认值 + 进程内随机 JWT 回退）；任何公网部署必须通过 `security_check` 审计。

## 13. 开发与生产运行

### 13.1 开发模式

```bash
# Flask 初始化数据库、调度器，并在依赖已安装时自动拉起 Vite。
python -m backend.api.app

# 仅启动后端，关闭开发代理。
FRONTEND_DEV_PROXY=false python -m backend.api.app

# 手工启动前端开发服务器。
cd frontend
npm ci
npm run dev
```

开发时通常访问 `http://localhost:5000`，Flask 在 Vite 可用时 302 到 `http://localhost:5173`；Vite 将 `/api/*` 代理回 Flask `:5000`。

### 13.2 当前生产链路

```bash
# 单容器部署：前端在镜像构建阶段内编译（干净环境可直接构建，无需宿主机 npm）
sudo docker compose up -d --build
```

Flask 在生产模式（`FRONTEND_DEV_PROXY=false`）直接服务容器内 `frontend/dist`：`/` 与 SPA 路由回退到 `index.html`，`/assets/*` 提供静态资源。SQLite、缓存和日志使用 Docker `app-data` 卷。

完整腾讯云部署步骤（Docker 安装、`.env` 凭证、安全组、备份与恢复）见 `docs/DEPLOY.md`；部署前可用 `python -m backend.security_check` 审计生产就绪度。

## 14. 质量门禁与完成定义

每个后端/前端交付至少执行与变更相关的检查，并在交付记录中给出退出状态：

```bash
python -m pytest

cd frontend
npm ci
npm run build

git diff --check
```

当前尚未建立可信的端到端 CI 门禁；未来 CI 至少应运行后端 pytest、前端 `npm ci && npm run build` 和 `git diff --check`。

涉及数据、模型或扫描的变更还必须验证时点口径、错误路径、部分覆盖和数据陈旧显示。

涉及 API 的变更还必须验证 JWT 边界、无凭证 `401`、合法凭证成功路径和不泄露敏感信息的日志。

完成定义包括：实现、测试、可见错误状态、SPEC 同步和未发布实验的清晰标注；任一缺失都不能称为完成。

### 14.1 文档变更审查

规格改动必须与代码变更一起审查，不能在发布后再补写事实源。

- 归档文件必须可校验且不得被新规格改写。

- 当前规格必须明确能力状态，而非以旧设计推断当前范围。

- 文档差异必须通过 `git diff --check`。

- 页面、蓝图、鉴权和任务路径应在交付前逐项对照。

历史材料仅用于追溯，不能作为恢复已删除模块的依据。

## 15. 当前 P0 接管清单

| P0 | 验收结果 |
| --- | --- |
| 修复敏感日志泄露风险 | 登录、JWT、Cookie、SMTP 等敏感值不会进入应用日志或错误回显。（已关闭：请求日志只记元数据并脱敏 query；错误串不回显客户端，有测试守护） |
| 生产鉴权配置 | 固定 JWT 密钥、非默认管理员凭证和受限 CORS 有部署时强制校验。（已关闭：entrypoint + `security_check` CLI 双层校验，compose `${VAR:?}` 缺失即拒启） |
| 单实例调度保障 | 多 worker 不会重复调度；责任边界和部署方式可验证。（已关闭：entrypoint 与本地 gunicorn 配置双重强制单 worker） |
| Docker 前端构建链路 | 干净环境可重复产出前端资源，失败信息清晰。（已关闭：`backend/Dockerfile` 三阶段在镜像内执行 `npm ci && npm run build`，`docker compose up --build` 即完整部署） |
| API/页面事实对齐 | 路由、接口、鉴权与本 SPEC 一致，删除的量化模块不再出现。（已对齐：watchlist 已入册；契约测试守护部署架构） |
| 数据可信展示 | Core/Beta 页面能展示 source、as-of、freshness、coverage 与 degraded/error。（live 指数、watchlist 报价已实现；其余页面渐进补齐） |
| VIX2 研究验收 | 完成可审计 walk-forward OOS 与基线比较；否则明确”无稳健预测力”。（已有 test_vix2_walkforward.py 与实验边界标注） |

## 16. 历史设计索引

以下文件仅供追溯和迁移参考，不能覆盖本规格的当前结论：

| 文件 | 性质 |
| --- | --- |
| `docs/archive/SPEC-legacy-through-2026-07-01.md` | 旧版完整规格的原样归档；包含已经失效的量化交易架构描述。 |
| `docs/async-task-and-logging-design.md` | 任务与日志的历史设计参考。 |
| `docs/scheduler-audit-2026-06-30.md` | 调度审计历史记录。 |
| `docs/tenbag-scanner-design.md` | 十倍股扫描实验设计，不代表发布 UI。 |
| `docs/vix-v5-design.md` | VIX 的历史设计。 |
| `docs/vix2-ml-design.md` | VIX2 模型研究设计；其任何预测表述须受第 7 节约束。 |
| `docs/naming-fix-proposal.md` | 历史命名整理提案。 |

历史资料与当前实现冲突时，以本文件、当前代码和被明确批准的迁移计划为准。
