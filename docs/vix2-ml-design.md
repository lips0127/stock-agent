# VIX 2.0 — 机器学习因子权重设计书（2026-06-29）

## 0. 一句话目标

现有 v6.1 VIX 是**手工定权重**的「恐惧贪婪合成指数」：各分量打分后按拍脑袋的权重
（VIX 30% / 涨跌停 20% / …）加权。问题是它衡量的是「当前波动/情绪强度」，
**不衡量「这个位置作为底/顶有多好」**。实证：

| 日期 | 市场事实 | 合成 VIX | composite_pct |
|------|----------|----------|---------------|
| 2025-04-07 | 关税冲击大底 | 41.65 | 3.3% |
| 2026-03-23 | 另一次大底 | 51.34 | 1.2% |

两个都是底，但 4-07 的恐慌读数反而比 3-23 低 —— 因为原始 IV 只反映「预期波动」，
没有「相对市场环境/前瞻收益」的校准。

**VIX 2.0 = 用机器学习从历史数据中学到「哪些因子、以多大权重组合，最能提前识别
底部/顶部」**，产出一个与**前瞻市场结果**对齐的 0-100 分数。

**关键约束：v6.1 不动。** VIX 2.0 作为**并行的第二套指标**上线，新增表 / 新增 API /
前端新增一张卡片或切换开关。两套指标可同屏对比，便于评估 ML 是否真的更好。

---

## 1. 方法选型（已与用户确认）

| 维度 | 选择 | 理由 |
|------|------|------|
| **标签** | 三隘栏法 (Triple-Barrier, López de Prado) | 金融 ML 标准做法；用止盈/止损/时间三条 barrier 给每天打「未来是涨是跌」标签，比固定 N 日收益更稳健，天然对齐「底/顶」 |
| **模型** | 正则化线性模型 (Logistic + L2/ElasticNet) | 可解释——直接产出每个因子的学习权重，正好对应「用 ML 找因子权重」的诉求；样本不算多时比树/DL 稳健、不易过拟合 |
| **数据** | 扩充历史 + 降维因子集 | 50ETF QVIX 回溯到 2015-02（~2755 行），上证综指回溯到 1990；用「长历史可得」的因子做训练集，多 ETF/PCR 等近年因子作为可选增强 |

### 1.1 为什么不是 DL

当前 vix_history 仅 ~357 行（多 ETF 时代）。即便扩充到 2015 起的 ~2700 个交易日，
对 LSTM/MLP 仍偏少，极易过拟合。DL 列为后续阶段（需先把训练集做厚、做特征工程）。
线性模型此刻是「可解释 + 稳健 + 直接给权重」的最优解。

---

## 2. 数据层：长历史因子集

### 2.1 因子分两档

**核心因子（长历史，2015-02 起，~2700 样本）—— 训练主力：**

| 因子 | 来源 | 已有函数 | 含义 |
|------|------|----------|------|
| `qvix_50` | 50ETF QVIX | `fetch_50etf_qvix` | 隐含波动率水平 |
| `qvix_50_z` | 同上滚动 252 日 Z-Score | 派生 | 相对自身历史的极端度 |
| `qvix_50_chg5` | QVIX 5 日变化率 | 派生 | 波动率动能 |
| `rv_hs300` | 沪深300 Garman-Klass | `garman_klass_rv` | 已实现波动率 |
| `rv_qvix_spread` | RV − QVIX（方差风险溢价代理） | 派生 | 期权贵/便宜 |
| `ma60_dev` | 上证综指偏离 60 日线 | `compute_spot_signals_from_df` | 价格位置 |
| `mom_20d` | 20 日动量 | 同上 | 中期趋势 |
| `mom_60d` | 60 日动量 | 派生 | 中长期趋势 |
| `new_high_ratio` | 20 日新高比例 | 同上 | 趋势强度 |
| `drawdown_252` | 距 252 日高点回撤 | 派生 | 距顶距离 |
| `dist_low_252` | 距 252 日低点涨幅 | 派生 | 距底距离 |

**增强因子（近年，多 ETF 时代才有）—— 可选，默认关闭以保样本量：**
`vix_synthetic`（5 ETF 加权）、`growth_premium`、`pcr_volume`、`limit_ratio`、`margin_chg`。

> 训练时若开启增强因子，样本截断到这些因子的最早可得日期，样本量骤减；
> 因此 v2.0 首版只用核心因子，增强因子放在 `feature_set='enhanced'` 选项里供实验。

### 2.2 标签生成（三隘栏）

对上证综指（或沪深300）每个交易日 t：

```
entry = close[t]
upper = entry * (1 + pt)        # 止盈 barrier，pt 默认 0.05（依波动率缩放）
lower = entry * (1 - sl)        # 止损 barrier，sl 默认 0.05
vertical = t + H 个交易日        # 时间 barrier，H 默认 20

在 (t, t+H] 内，看 close 先触哪条：
  先触 upper        → label = +1（此处买入未来会涨 → 当前是「底」侧）
  先触 lower        → label = -1（此处买入未来会跌 → 当前是「顶」侧）
  都没触，到 vertical → label = sign(close[vertical] - entry)（按到期方向）
```

- barrier 宽度按近 20 日 RV 动态缩放（高波动期放宽，低波动期收窄），避免高波动期全部秒触发。
- 训练目标：`P(label=+1)` = 「当前是底部、未来上涨」的概率。
- **VIX 2.0 分数 = (1 − P_up) × 100**，即「恐慌/底部分」：P_up 高（强烈看涨底部）→ 分数低（极度恐慌/机会）；
  与现有口径一致（低分=恐慌=机会，高分=贪婪=风险）。

### 2.3 防泄漏

- 特征只用 t 日**收盘后已知**的信息。
- 标签用 t 之后 H 日的未来价格 —— 训练/回测时严格按时间切分，绝不让未来信息进特征。
- 时间序列 CV：`TimeSplit`（前段训练→后段验证，滚动前移），**禁止**随机 KFold。
- 评估最近一段（如最后 252 日）必须是纯样本外。

---

## 3. 模型层

### 3.1 Pipeline

```
StandardScaler → LogisticRegression(penalty='l2'|'elasticnet',
                                     class_weight='balanced',
                                     C=网格搜索)
```

- 标准化必做（线性模型对量纲敏感）。
- `class_weight='balanced'`：底/顶天数远少于震荡天数。
- 超参 `C`（正则强度）用 `TimeSeriesSplit` 网格搜索，按 ROC-AUC 选。

### 3.2 产出物（可解释权重）

训练完成后落盘：

```json
{
  "model_version": "vix2-l2-2026-06-29",
  "feature_set": "core",
  "trained_at": "...",
  "train_range": ["2015-02-09", "2025-06-26"],
  "n_samples": 2480,
  "label_params": {"pt": 0.05, "sl": 0.05, "H": 20, "rv_scale": true},
  "cv_auc": 0.63,
  "oos_auc": 0.60,
  "weights": {            // 标准化空间的系数，可直接读「哪个因子最重要、方向如何」
    "qvix_50_z": -0.82,
    "ma60_dev": 0.55,
    "drawdown_252": -0.71,
    ...
  },
  "scaler": {"mean": [...], "scale": [...]}
}
```

`weights` 就是「ML 找到的因子权重」—— 前端可直接展示成条形图，回答用户最初的诉求。

### 3.3 推断

每日盘后（接在现有 16:30 VIX 任务后）：取当日核心因子 → scaler 变换 →
`predict_proba` → `P_up` → 分数 `(1−P_up)×100` → 百分位/regime（沿用 v6.1 的分级口径）。

---

## 4. 工程落地

### 4.1 新增文件

| 文件 | 职责 |
|------|------|
| `backend/services/vix2_features.py` | 长历史因子构建（核心/增强两档），全部 point-in-time |
| `backend/services/vix2_labels.py` | 三隘栏标签生成 |
| `backend/services/vix2_model.py` | 训练（pipeline + CV + 落盘）、加载、单日推断 |
| `backend/api/routes/vix2.py` | `/api/vix2/*` 端点 |
| `scripts/train_vix2.py` | 离线训练入口（CLI，可手动重训） |
| `data/models/vix2_*.json` + `.joblib` | 落盘的模型 + 元数据 |

### 4.2 新增表 `vix2_history`

```sql
CREATE TABLE IF NOT EXISTS vix2_history (
    date TEXT PRIMARY KEY,
    p_up REAL,                 -- 模型输出的上涨/底部概率
    score REAL,                -- (1-p_up)*100
    percentile REAL,           -- 近 252 日滚动百分位
    regime TEXT,               -- 沿用 classify_by_percentile
    model_version TEXT,
    features_json TEXT          -- 当日因子快照（审计用）
);
```

> 不污染 vix_history。两套指标各自独立表，前端可叠加对比。

### 4.3 新增 API

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/vix2` | 最新 VIX 2.0 快照（score/p_up/regime/percentile/model_version） |
| GET | `/api/vix2/history?days=365` | 历史序列（叠加到趋势图） |
| GET | `/api/vix2/model` | 当前模型元数据 + 因子权重（前端画权重条形图） |
| POST | `/api/vix2/train` | 触发离线重训（TaskRunner 包裹，返回 task_id） |
| POST | `/api/vix2/backfill` | 用当前模型回填历史 score（TaskRunner，返回 task_id） |

所有异步端点走 `TaskRunner`，返回 32-hex `task_id`，前端 `GET /api/tasks/<id>` 轮询
（遵守 CLAUDE.md Phase A/B 约束）。

### 4.4 前端

`VixView.vue` 新增一张 ModernCard「VIX 2.0（机器学习）」：
- 大数字 = VIX 2.0 score + regime tag
- 因子权重条形图（读 `/api/vix2/model` 的 `weights`）
- 趋势图叠加 VIX 2.0 score 线（与 v6.1 composite 同图对比）
- 模型信息行：version / oos_auc / 训练样本数 / 训练时间

---

## 5. 实施步骤

1. **特征层** `vix2_features.py` + 单元自检（长历史因子能拉到 2015、无 NaN 泄漏）
2. **标签层** `vix2_labels.py` + 自检（三隘栏在合成数据上行为正确）
3. **模型层** `vix2_model.py`：训练/CV/落盘/加载/推断
4. **训练脚本** `scripts/train_vix2.py`，跑出首版模型 + 元数据
5. **DB** `vix2_history` 表 + upsert/query 函数
6. **API** `vix2.py` 五端点 + 注册 blueprint
7. **调度** 接到现有盘后任务链（VIX 算完→VIX2 推断）
8. **前端** VixView 新增卡片 + 趋势叠加
9. **SPEC** 新增 §11F；本设计书归档

## 6. 验收标准

- OOS（最近 252 日纯样本外）ROC-AUC > 0.55（显著优于 0.5 随机）
- 在 2025-04-07 / 2026-03-23 两个已知大底，VIX 2.0 score 应同处极端恐慌档，
  且**相对排序更合理**（不再出现「更深的底反而读数更低」的矛盾）
- v6.1 指标行为完全不变（回归对比 vix_history 不被触碰）
- 训练可复现：固定随机种子，`scripts/train_vix2.py` 重跑得到一致权重

## 7. 已知风险

- A 股可预测性弱，AUC 可能仅略高于 0.5 —— 届时如实呈现，不粉饰；线性权重本身仍有解释价值。
- barrier 参数（pt/sl/H）对标签影响大，首版用 RV 缩放的对称 barrier，留作可调超参。
- 样本仍偏少（~2700）：严格正则 + 时间序列 CV + 纯样本外评估三重防过拟合。
