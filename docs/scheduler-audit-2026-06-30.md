# 任务调度看板审计报告（2026-06-30）

## 1. 调度器是否真的在跑

- `init_scheduler()` 在 `backend/api/app.py:create_app()` 中被调用（启动顺序：日志→DB→CORS→scheduler），随 Flask 进程启动。
- `BackgroundScheduler` 单例，10 个 job 全部 `enabled=1`（DB `scheduler_task_config` 实测全部启用）。
- **结论**：只要后端进程在跑，调度器就在跑。

## 2. 10 个任务的实际配置（DB 实测，可能与代码默认值不同）

| job_id | 触发 | DB 实测时间 | 代码默认 | 说明 |
|---|---|---|---|---|
| daily_update | cron | 工作日 15:30 | 15:30 | 红利指数扫描 |
| daily_sentiment | cron | 工作日 16:00 | 16:00 | 舆情批量分析 |
| daily_top_picks | cron | 工作日 16:05 | 16:05 | 热门股池 |
| daily_vix | cron | 工作日 **17:15** | 16:30 | VIX+VIX2 ⚠️ DB 覆盖了代码默认 |
| daily_indicators_recompute | cron | 工作日 16:35 | 16:35 | 因子重算 |
| zhihu_check | interval | 每 **3h** | ZHIHU_CHECK_INTERVAL_HOURS | 知乎（反爬失败中） |
| forum_prefetch | interval | 每 2h | GUBA_PREFETCH_INTERVAL_HOURS | 股吧预拉（cookie 过期中） |
| universe_constituents_weekly | cron | 周日 17:00 | 17:00 | 成分股周更 |
| universe_crawl_daily | cron | 工作日 18:00 | 18:00 | 全市场爬取 |
| universe_aggregate_daily | cron | 工作日 19:30 | 19:30 | 指数聚合 |

> 注：DB 配置优先级高于代码默认（`seed_from_env` 用 `INSERT OR IGNORE`，首次 seed 后改 DB 不回退）。`daily_vix` 17:15 / `zhihu_check` 3h 是用户经前端 PATCH 改过的。

## 3. 实际运行情况（DB `scheduler_task_run` 实测）

- **只有 interval 任务有运行记录**：`forum_prefetch`（每 2h）、`zhihu_check`（每 3h）有近期 tick 记录。
- **cron 任务（daily_update / daily_sentiment / daily_vix / daily_top_picks / daily_indicators_recompute / universe_*）在 `scheduler_task_run` 中无近期记录**。
  - 原因推断：本次审计时点（21:47）已过所有 cron 触发时间，且 DB 中这些 job 的 `next_run_time` 多为 `None`（只在进程启动时同步一次，进程重启后会重新计算）。这说明**后端进程在 cron 触发时段没在跑**，或刚重启不久。
  - **风险**：如果后端不是常驻进程（本地开发手动起停），cron 任务大概率错过触发窗口。生产部署需保证进程常驻。

## 4. ⚠️ 核心问题：失败静默（已修复）

**审计前**：多数定时任务在顶层 `except` 吞掉异常，`track_run` 装饰器判定 `success`，前端看板显示「最近：成功」，即便任务实际失败：
- `zhihu_check`：全员反爬 403 / 熔断 → 记 success
- `daily_vix`：数据源全挂 → 记 success
- `universe_*`：抓取崩溃 → 记 success
- `daily_update`：所有重试失败 → 记 success

**已修复**（commit 53fa6ee，仅改 except 是否 re-raise，不改业务逻辑）：
- `daily_update_task`：所有重试失败后 `raise last_err`
- `zhihu_check_task`：顶层异常 `raise`（per-user 循环仍吞，保留部分容错）
- `daily_vix_task`：VIX 计算失败 `raise`（VIX2 失败非致命，仍吞）
- `weekly_universe_constituents` / `daily_universe_crawl` / `daily_universe_aggregate`：`raise`

`track_run` 装饰器在 except 中 `t.fail()` + `raise`，APScheduler 记录任务异常但不崩进程。前端 `SchedulerTaskCard` 已展示 `last_run_status` + 运行历史 + 状态标签，修复后能正确看到 failed。

## 5. 依赖时序

```
15:30 daily_update（红利扫描）
16:00 daily_sentiment（舆情，依赖扫描结果）
16:05 daily_top_picks（热门股池）
16:30/17:15 daily_vix（VIX+VIX2）
16:35 daily_indicators_recompute（因子重算，依赖 sentiment_scores）
18:00 universe_crawl_daily（全市场爬取，依赖 16:35 indicators + forum_prefetch 缓存）
19:30 universe_aggregate_daily（聚合，依赖 18:00 crawl）
```

- 时序设计合理，每环给下一环留 buffer。
- **风险**：前置失败（如 16:00 sentiment 失败）不会阻塞后续任务（各自独立），但后续任务会拿到不完整数据。修复 4 后，前置失败现在能从看板看到 failed，便于排查。

## 6. 高风险项（只建议，未改）

1. **zhihu_check / forum_prefetch 在反爬未修复前是否应 disable**：目前每 2-3h 跑一次全员 403，刷日志且无产出。建议在反爬重设计落地前，前端 PATCH 暂停这两个 job（`apply_pause`），避免无谓请求。**留用户决定**。
2. **cron 任务非常驻进程则形同虚设**：本地开发手动起停会错过 cron 窗口。生产需常驻 + 进程守护。
3. **`daily_vix` DB=17:15 vs 代码=16:30 不一致**：DB 覆盖生效，但文档/代码默认值未同步，易混淆。建议统一（改代码默认为 17:15 或改 DB 回 16:30）。
4. **多 worker 部署 APScheduler 重复执行**：`scheduler.py` + `gunicorn_config.py` 多 worker 会重复 tick（SPEC §99.4 已记录），需锁或单 worker 跑调度。
5. **`_UNIVERSE_BATCH_STATE` 内存 dict** 违反 Phase B 约束（多 worker 跨进程失效），SPEC §99.4 已记录。

## 7. 验证手段

```bash
# 看 10 个 job 配置 + enabled + next_run_time
sqlite3 stocks.db "select job_id,enabled,hour,minute,day_of_week,interval_hours,next_run_time from scheduler_task_config order by job_id"

# 看最近运行（修复后失败任务会显示 failed）
sqlite3 stocks.db "select job_id,status,started_at,finished_at from scheduler_task_run order by started_at desc limit 20"

# 前端 /tasks 页面核对 last_run_status
```
