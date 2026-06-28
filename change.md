# Change Log

## 2026-06-28

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