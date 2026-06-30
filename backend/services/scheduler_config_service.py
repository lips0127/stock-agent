"""任务调度配置 service（v5, 2026-06-06）。

- 启动时把 10 个 APScheduler 任务的配置从 env seed 到 DB
- 启动后从 DB 读配置构建 CronTrigger / IntervalTrigger
- 用户 PATCH 时：写 DB → 调 scheduler.reschedule_job 立即生效
- 用户 pause / resume 时：调 scheduler.pause_job / resume_job 立即生效
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import (
    SCHEDULER_HOUR, SCHEDULER_MINUTE,
    ZHIHU_CHECK_INTERVAL_HOURS, GUBA_PREFETCH_INTERVAL_HOURS,
    UNIVERSE_CONSTITUENT_REFRESH_DOW,
    UNIVERSE_CONSTITUENT_REFRESH_HOUR, UNIVERSE_CONSTITUENT_REFRESH_MINUTE,
    UNIVERSE_CRAWL_HOUR, UNIVERSE_CRAWL_MINUTE,
    UNIVERSE_AGG_HOUR, UNIVERSE_AGG_MINUTE,
)
from backend.core.database import (
    get_all_scheduler_configs, get_scheduler_config, seed_scheduler_config_if_absent,
    update_scheduler_config, update_scheduler_next_run,
)

logger = logging.getLogger("scheduler_config")

# ── 注册表（v5, 2026-06-06）：10 个任务的 seed 元数据 ──
#   job_id, display_name, description, trigger_type, func_obj, env_field_mapping
JOB_REGISTRY: list[dict[str, Any]] = [
    {
        "job_id": "daily_update",
        "display_name": "每日红利指数扫描",
        "description": "工作日收盘后扫全市场红利股（默认 15:30）",
        "trigger_type": "cron",
        "func_name": "daily_update_task",
        "env_fields": lambda: dict(
            hour=SCHEDULER_HOUR, minute=SCHEDULER_MINUTE, day_of_week="mon-fri",
        ),
    },
    {
        "job_id": "daily_sentiment",
        "display_name": "每日舆情批量分析",
        "description": "工作日 16:00 跑用户关注股票的情绪分析",
        "trigger_type": "cron",
        "func_name": "daily_sentiment_task",
        "env_fields": lambda: dict(
            hour=(SCHEDULER_HOUR + 1) if SCHEDULER_HOUR < 23 else 16,
            minute=0, day_of_week="mon-fri",
        ),
    },
    {
        "job_id": "daily_vix",
        "display_name": "VIX 恐慌指数",
        "description": "工作日 16:30 算 VIX + 恐惧贪婪综合指数",
        "trigger_type": "cron",
        "func_name": "daily_vix_task",
        "env_fields": lambda: dict(hour=16, minute=30, day_of_week="mon-fri"),
    },
    {
        "job_id": "daily_top_picks",
        "display_name": "热门股池刷新",
        "description": "工作日 16:05 拉东方财富 top 100 成交额",
        "trigger_type": "cron",
        "func_name": "daily_top_picks_task",
        "env_fields": lambda: dict(hour=16, minute=5, day_of_week="mon-fri"),
    },
    {
        "job_id": "daily_indicators_recompute",
        "display_name": "时序因子重算",
        "description": "工作日 16:35 算 EMA/panic/euphoria/momentum",
        "trigger_type": "cron",
        "func_name": "daily_indicators_recompute_task",
        "env_fields": lambda: dict(hour=16, minute=35, day_of_week="mon-fri"),
    },
    {
        "job_id": "zhihu_check",
        "display_name": "知乎大V 监控",
        "description": "每 N 小时检查 KOL 动态 + LLM 分析 + 邮件通知",
        "trigger_type": "interval",
        "func_name": "zhihu_check_task",
        "env_fields": lambda: dict(interval_hours=ZHIHU_CHECK_INTERVAL_HOURS),
    },
    {
        "job_id": "forum_prefetch",
        "display_name": "股吧帖子预拉",
        "description": "每 N 小时拉一次股吧列表（不调 LLM，guba 熔断保护）",
        "trigger_type": "interval",
        "func_name": "forum_prefetch_task",
        "env_fields": lambda: dict(interval_hours=GUBA_PREFETCH_INTERVAL_HOURS),
    },
    {
        "job_id": "universe_constituents_weekly",
        "display_name": "全市场成分股周更",
        "description": "每周日 17:00 拉 6 指数的成分股",
        "trigger_type": "cron",
        "func_name": "weekly_universe_constituents_task",
        "env_fields": lambda: dict(
            hour=UNIVERSE_CONSTITUENT_REFRESH_HOUR,
            minute=UNIVERSE_CONSTITUENT_REFRESH_MINUTE,
            day_of_week=UNIVERSE_CONSTITUENT_REFRESH_DOW,
        ),
    },
    {
        "job_id": "universe_crawl_daily",
        "display_name": "全市场舆情爬取",
        "description": "工作日 18:00 跑全市场 (~1500 股) 情绪分析",
        "trigger_type": "cron",
        "func_name": "daily_universe_crawl_task",
        "env_fields": lambda: dict(
            hour=UNIVERSE_CRAWL_HOUR, minute=UNIVERSE_CRAWL_MINUTE, day_of_week="mon-fri",
        ),
    },
    {
        "job_id": "universe_aggregate_daily",
        "display_name": "全市场指数聚合",
        "description": "工作日 19:30 算指数级 avg/median/distribution",
        "trigger_type": "cron",
        "func_name": "daily_universe_aggregate_task",
        "env_fields": lambda: dict(
            hour=UNIVERSE_AGG_HOUR, minute=UNIVERSE_AGG_MINUTE, day_of_week="mon-fri",
        ),
    },
]

JOB_REGISTRY_BY_ID = {j["job_id"]: j for j in JOB_REGISTRY}


# ── seed / build ──

def seed_from_env() -> int:
    """启动时调一次：把 10 行 INSERT OR IGNORE 写进 DB（已有行不覆盖）。"""
    n = 0
    for job in JOB_REGISTRY:
        fields = job["env_fields"]()
        row = {
            "job_id": job["job_id"],
            "display_name": job["display_name"],
            "description": job["description"],
            "trigger_type": job["trigger_type"],
            **fields,
            "enabled": 1,
        }
        if seed_scheduler_config_if_absent(row):
            n += 1
            logger.info(f"seed scheduler_task_config: {job['job_id']}")
    if n:
        logger.info(f"scheduler_task_config: 新增 {n} 行（其余 {len(JOB_REGISTRY) - n} 行已存在）")
    return n


def build_trigger(row: dict) -> CronTrigger | IntervalTrigger:
    """把 DB row 转成 APScheduler trigger 对象。"""
    if row["trigger_type"] == "cron":
        return CronTrigger(
            hour=row["hour"] if row["hour"] is not None else "*",
            minute=row["minute"] if row["minute"] is not None else "*",
            day_of_week=row["day_of_week"] or "*",
        )
    return IntervalTrigger(hours=row["interval_hours"])


def compute_next_run_time(row: dict) -> str | None:
    """从 trigger 算出下次执行时间（ISO 格式）。

    用 trigger.get_next_fire_time(None, now) 直接计算，避开 APScheduler
    内部 lazy 计算 next_run_time 的坑（cron trigger 在 start() 后
    get_job().next_run_time 立即取可能为 None）。
    """
    trigger = build_trigger(row)
    # 用 timezone-aware now（IntervalTrigger 内部 start_date 是 aware 的，
    # 不能跟 datetime.now() 的 naive 值比）
    nrt = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
    return nrt.isoformat() if nrt else None


# ── 立即生效 apply_* ──

def _get_sched():
    """惰性 import 避免循环引用（scheduler.py 调本 service）。"""
    from backend.services.scheduler import get_scheduler
    return get_scheduler()


def apply_reschedule(job_id: str, new_fields: dict, updated_by: str | None = None) -> dict:
    """PATCH 调这个：写 DB → reschedule_job → 返回新 next_run_time。"""
    row = get_scheduler_config(job_id)
    if not row:
        raise KeyError(f"unknown job_id: {job_id}")
    if row["trigger_type"] == "cron" and "interval_hours" in new_fields:
        raise ValueError("field not applicable to trigger_type=cron")
    if row["trigger_type"] == "interval" and any(k in new_fields for k in ("hour", "minute", "day_of_week")):
        raise ValueError("field not applicable to trigger_type=interval")
    update_scheduler_config(job_id, updated_by=updated_by, **new_fields)
    new_row = get_scheduler_config(job_id)
    trigger = build_trigger(new_row)
    sched = _get_sched()
    sched.reschedule_job(job_id, trigger=trigger)
    job = sched.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    update_scheduler_next_run(job_id, next_run)
    return {"ok": True, "job_id": job_id, "next_run_time": next_run}


def apply_pause(job_id: str) -> dict:
    sched = _get_sched()
    sched.pause_job(job_id)
    update_scheduler_config(job_id, enabled=False, updated_by=None)
    update_scheduler_next_run(job_id, None)
    return {"ok": True, "paused": True, "job_id": job_id}


def apply_resume(job_id: str) -> dict:
    sched = _get_sched()
    sched.resume_job(job_id)
    job = sched.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    update_scheduler_config(job_id, enabled=True, updated_by=None)
    update_scheduler_next_run(job_id, next_run)
    return {"ok": True, "paused": False, "job_id": job_id, "next_run_time": next_run}


# ── 验证 ──

_DOW_PATTERN = re.compile(
    r"^(\*|((mon|tue|wed|thu|fri|sat|sun)([,-](mon|tue|wed|thu|fri|sat|sun))*))$"
)


def validate_field(trigger_type: str, key: str, value) -> str | None:
    """返回 None 表示通过；返回 str 表示错误消息。"""
    if key in ("hour", "minute") and trigger_type == "cron":
        try:
            v = int(value)
        except (TypeError, ValueError):
            return f"{key} must be int"
        if key == "hour" and not (0 <= v <= 23):
            return "hour out of range"
        if key == "minute" and not (0 <= v <= 59):
            return "minute out of range"
    elif key == "day_of_week" and trigger_type == "cron":
        if not isinstance(value, str) or not _DOW_PATTERN.match(value.strip().lower()):
            return "invalid day_of_week"
    elif key == "interval_hours" and trigger_type == "interval":
        try:
            v = int(value)
        except (TypeError, ValueError):
            return "interval_hours must be int"
        if not (1 <= v <= 168):
            return "interval_hours out of range (1..168)"
    elif key == "enabled":
        if not isinstance(value, bool):
            return "enabled must be bool"
    else:
        return f"field '{key}' not applicable to trigger_type={trigger_type}"
    return None
