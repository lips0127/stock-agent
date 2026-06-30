"""
情感分析服务 — 使用 LangChain + LLM 分析股票社区情绪。
支持 DeepSeek / MiniMax / 火山云，通过环境变量配置。

v3 算法（2026-06-06）：
- 4 分类标签：1 (看多) / 0 (中性) / -1 (看空) / 99 (噪声)
- math 外移：LLM 只打标，score / sentiment 全部 Python 算
- 结构化输出：json_object 模式
- 反讽规则 + 5-shot 案例
- 关 thinking（max_tokens=512, streaming=False）
- 写 sentiment_post_labels（每条帖子一个标签，供时序回填）
- 计算 panic / euphoria 信号，写 sentiment_indicators
"""

import os
import re
import json
import time
import sys
import logging
import threading
import requests
from datetime import date, datetime
from statistics import mean, pstdev

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from backend.core.database import (
    get_connection,
    upsert_post_labels, upsert_indicators,
)
from backend.services.forum_service import (
    fetch_forum_posts, get_recent_posts, audit_posts, CircuitOpenError,
)

logger = logging.getLogger(__name__)


# ── 结构化日志辅助 ──────────────────────────────────────────────────────
# 多行 JSON / 结构化数据缩进打印，让单只股票的「抓取→审计→LLM 输入/输出→结果」
# 全程日志可读、可诊断。批量跑 1000+ 只时仍保持每只一段、统一前缀 [code]。

# LLM 单次标签任务默认/上限 token。1024 够 30~50 条；超活跃股（100+ 条）偶发
# 截断时按 2x/4x 自适应重试，上限 4096，仍不够则交由解析器截断恢复兜底。
LLM_DEFAULT_MAX_TOKENS = 1024
LLM_MAX_TOKENS_CAP = 4096


def _looks_truncated(s: str) -> bool:
    """判断 LLM 输出是否被 max_tokens 截断（剥离尾部 markdown 围栏后无闭合 ]）。"""
    stripped = (s or "").rstrip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
    return not stripped.endswith("]")


def _log_section(code: str, title: str, *fields: tuple[str, object]) -> None:
    """打印单只股票分析的一个阶段块。

    Args:
        code: 股票代码
        title: 阶段标题（如「拉取帖子」「LLM 输入」「LLM 输出」）
        *fields: (键, 值) 元组列表，标量值内联，dict/list 走 json.dumps 缩进
    """
    parts = [f"[{code}] ── {title}"]
    for k, v in fields:
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            # 标量扁平列表（如标签序列）内联打印，避免每元素一行刷屏
            if (isinstance(v, list)
                    and all(not isinstance(x, (dict, list)) for x in v)):
                rendered = "[" + ", ".join(str(x) for x in v) + "]"
            else:
                try:
                    rendered = json.dumps(v, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    rendered = str(v)
            parts.append(f"  {k}:\n{rendered}")
        else:
            parts.append(f"  {k}: {v}")
    logger.info("\n".join(parts))


# ── LLM 配置 ──

# 标签常量
LABEL_BULLISH = 1
LABEL_NEUTRAL = 0
LABEL_BEARISH = -1
LABEL_NOISE = 99
VALID_LABELS = {LABEL_BULLISH, LABEL_NEUTRAL, LABEL_BEARISH, LABEL_NOISE}

# 情绪分档阈值（与 v2 保持一致）
SCORE_BULL_THRESHOLD = 60
SCORE_BEAR_THRESHOLD = 40

# LLM 配置，按优先级：DEEPSEEK > MINIMAX > VOLCANO
LLM_CONFIG = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "minimax": {
        "api_key_env": "MINIMAX_API_KEY",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-M3",
    },
    "volcano": {
        "api_key_env": "VOLCANO_API_KEY",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
    },
}

# v3 提示词（2026-06-06）：
# - 4 分类（1/0/-1/99）
# - 反讽识别规则
# - 5-shot 案例
# - 严格 JSON 输出
# - 算术外移：LLM 不再算 score，只返回 labels 数组
SENTIMENT_PROMPT = PromptTemplate.from_template("""\
你是一位深谙 A 股股民心理和股吧黑话的资深量化研究员。
对下面 {code} 的帖子逐条打标，每条帖子输出一个 JSON 对象，label ∈ {{1, 0, -1, 99}}。

【标签含义】
- 1 (看多)：明确看多 / 持有盈利者的亢奋 / 喊"加仓" / 看好后市
- 0 (中性)：客观陈述 / 询问交流 / 无明显情绪偏向
- -1 (看空)：割肉 / 绝望 / 极度恐慌 / 骂主力 / 持续看跌
- 99 (噪声)：广告 / 推广 / 抽奖 / 无意义玩梗 / 与该股无关的跨板块水帖

【反讽识别（关键）】
1. 股票大跌或遭遇利空时，"感谢主力送温暖"、"再来三个跌停老子刚好补仓"、
   "主力全家身体健康"、"感恩主力" 等是极度绝望的反讽 → -1
2. 套牢盘骂主力、骂管理层、诅咒式发言 → -1
3. 问句（如"明天开盘怎么看？"、"周一怎么办？"）若无明确倾向 → 0
4. 严格区分"反讽"与"真心夸奖"：结合股票近期走势判断
5. 严格控制 99：拿不准的情绪帖归 0，不归 99；只把明显的广告/水帖归 99

【典型案例（5-shot）】
[1] "明天涨5个点" → 1（明确看多）
[2] "今天又跌了，主力真 tm 恶心" → -1（看空+骂主力）
[3] "感谢主力送温暖，让我的成本又降低了" → -1（反讽：实际亏了）
[4] "明天开盘怎么看？有没有大哥说说" → 0（中性问句）
[5] "加微信送牛股，888 立即领取" → 99（广告）

【帖子列表】
{posts_text}

【输出格式（严格遵守）】
只输出 JSON 数组，不要任何解释、注释或 markdown 标记。
格式：[{{"id": 1, "label": 1}}, {{"id": 2, "label": -1}}, ...]
id 必须与帖子编号 [N] 中的 N 一致；数量必须等于帖子数量。
label 必须是 1 / 0 / -1 / 99 之一。
""")


def _get_llm() -> ChatOpenAI | None:
    """根据环境变量自动选择可用的 LLM 提供商。

    v3 性能配置（2026-06-06）：
    - max_tokens=1024：每条标签约 ~10 token（含格式化换行），30+ 条需 ~400 token，
      留 2x buffer 防截断。512 在 minimax 输出换行/markdown 时会截断尾 ] → 解析失败。
    - streaming=False：批量场景非流式更省网络往返
    - 关闭 thinking：M3 thinking 模式输出 13K 字/110s，纯成本零收益
    v4 关闭 thinking（2026-06-08）：
    - extra_body 顶层传 {"thinking": {"type": "disabled"}}（langchain 原生字段）
    - 兼容 model_kwargs 注入，冗余兜底
    """
    for provider, cfg in LLM_CONFIG.items():
        api_key = os.environ.get(cfg["api_key_env"], "").strip()
        if api_key:
            logger.info(f"使用 LLM 提供商: {provider} (model={cfg['model']})")
            kwargs = dict(
                api_key=api_key,
                base_url=cfg["base_url"],
                model=cfg["model"],
                temperature=0.1,    # 降低随机性，让标签更稳定
                max_tokens=LLM_DEFAULT_MAX_TOKENS,    # v8: 默认 1024；截断时由 analyze_sentiment 按 2x/4x 重试
                streaming=False,    # v3: 批量场景关流式
                timeout=60,
            )
            # 关闭 MiniMax-M3 thinking 模式
            if provider == "minimax":
                # langchain ChatOpenAI 原生 extra_body 字段，OpenAI SDK 会原样 merge 到请求体
                # （model_kwargs 会被 openai 客户端拒绝 unknown kwarg，所以只能用 extra_body）
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                logger.info("MiniMax-M3 thinking 模式已禁用（extra_body 顶层）")
            # v5 2026-06-08：timeout 60 → 30s。thinking 关闭后单次标签任务应在 5-10s 内完成；
            # 卡 30s 说明 LLM 服务端异常或网络堵塞，标记为失败比让批量卡死更合理。
            kwargs["timeout"] = int(os.environ.get("SENTIMENT_LLM_TIMEOUT", "30"))
            return ChatOpenAI(**kwargs)
    logger.error("未配置任何 LLM API Key，请设置 DEEPSEEK_API_KEY / MINIMAX_API_KEY / VOLCANO_API_KEY")
    return None


def _get_current_model_name() -> str:
    """返回当前激活的 LLM 模型名（写入 post_labels.model 字段用）。"""
    for provider, cfg in LLM_CONFIG.items():
        if os.environ.get(cfg["api_key_env"], "").strip():
            return f"{provider}/{cfg['model']}"
    return "unknown"


def _build_posts_text(posts: list[dict], max_chars: int = 1800) -> tuple[str, list[dict]]:
    """将帖子列表拼接为 prompt 可用的文本，并做 LLM 层过滤。

    v3 2026-06-06：
    - max_chars 3000 → 1800：减少 prompt 体积，间接压缩 thinking 输出
    - 返回 (text, kept_posts)：kept_posts 与编号 [N] 一一对应，
      供后续 LLM 返回的 [{id, label}] 反向解析回 post_id

    v1 2026-06-04：标题审计集成。优先级：
    1. 如果帖子有 actual_title 且 title_match=0（不一致）→ 用 actual_title
    2. 否则用原 title
    """
    lines = []
    total_chars = 0
    kept = []   # 与 [N] 编号一一对应

    # LLM 层过滤关键词（与 DB 白名单保持一致）
    _LLM_FILTER_KEYWORDS = ["转发", "阅读", "收藏", "发表于"]

    for p in posts:
        # 标题审计：mismatch 时用 actual_title 替代
        stored = p.get("title", "")
        actual = p.get("actual_title")
        if (actual and actual.strip()
                and p.get("title_match") == 0
                and p.get("audit_status") not in ("broken", "manual_rejected")):
            title = actual
        else:
            title = stored

        content = (p.get("content") or "").strip()

        # LLM 层过滤：跳过含白名单关键词的帖子
        if any(kw in title for kw in _LLM_FILTER_KEYWORDS):
            continue

        # LLM 层过滤：跳过标题过短（<5字）的帖子
        if len(title.strip()) < 5:
            continue

        if not title or title in ("转发", "。"):
            title = content[:30] if content else ""
        if title in ("转发", "", "。"):
            continue

        idx = len(kept) + 1
        text = f"[{idx}] {title[:80]}"
        if content and len(content) > 10:
            text += f"\n    {content[:80]}"
        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 60:
                lines.append(text[:remaining])
                kept.append(p)
            break
        lines.append(text)
        kept.append(p)
        total_chars += len(text)
    return "\n\n".join(lines), kept


# ── 评分聚合（v3, 2026-06-06）：math 外移到 Python ──


def _aggregate_labels(labels: list[int]) -> dict:
    """根据四分类标签列表算出 score / sentiment / 分布。

    Args:
        labels: 每条帖子的标签，∈ {1, 0, -1, 99}

    Returns:
        {
          "bullish": int, "bearish": int, "neutral": int, "noise": int,
          "total_analyzed": int,  # 剔除 99 后的有效标签数
          "score": float,         # 0-100，看多占有效多空的比例
          "sentiment": "乐观|中性|悲观",
        }
    """
    bullish = sum(1 for x in labels if x == LABEL_BULLISH)
    bearish = sum(1 for x in labels if x == LABEL_BEARISH)
    neutral = sum(1 for x in labels if x == LABEL_NEUTRAL)
    noise = sum(1 for x in labels if x == LABEL_NOISE)

    valid = bullish + bearish
    if valid > 0:
        score = round(bullish / valid * 100, 1)
    else:
        score = 50.0  # 没有明确多空 → 中性

    if score >= SCORE_BULL_THRESHOLD:
        sentiment = "乐观"
    elif score <= SCORE_BEAR_THRESHOLD:
        sentiment = "悲观"
    else:
        sentiment = "中性"

    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "noise": noise,
        "total_analyzed": bullish + bearish + neutral,  # noise 排除
        "score": score,
        "sentiment": sentiment,
    }


def _compute_indicators(stock_code: str, agg: dict,
                        history_scores: list[float],
                        history_bullish: list[int],
                        history_bearish: list[int]) -> dict:
    """计算 panic / euphoria / EMA 等时序因子。

    Args:
        stock_code: 6 位股票代码
        agg: 今日聚合结果（含 score / bullish / bearish）
        history_scores: 最近 30 日 score 序列（不含今日），按时间升序
        history_bullish: 最近 30 日 bullish_n 序列（不含今日）
        history_bearish: 最近 30 日 bearish_n 序列（不含今日）

    Returns:
        {
          "ema3": float | None, "ema5": float | None,
          "panic_signal": int, "euphoria_signal": int,
          "momentum_cross": int,
        }
    """
    today_score = agg["score"]
    today_bullish = agg["bullish"]
    today_bearish = agg["bearish"]

    # EMA3 / EMA5（含今日）
    ema3 = _ema(history_scores + [today_score], 3) if history_scores else None
    ema5 = _ema(history_scores + [today_score], 5) if history_scores else None

    # 30 日 bullish / bearish 的均值 + std
    bullish_series = history_bullish + [today_bullish]
    bearish_series = history_bearish + [today_bearish]
    bull_ma, bull_std = _mean_std(bullish_series)
    bear_ma, bear_std = _mean_std(bearish_series)

    # Panic: 当日 bearish > mean + 2*std
    panic = 1 if (bear_std is not None and bear_ma is not None
                  and today_bearish > bear_ma + 2 * bear_std) else 0
    # Euphoria: 当日 bullish > mean + 2*std
    euphoria = 1 if (bull_std is not None and bull_ma is not None
                     and today_bullish > bull_ma + 2 * bull_std) else 0

    # Momentum cross: EMA3 上穿 EMA5（用今日 vs 昨日的 EMA 对比）
    momentum = 0
    if len(history_scores) >= 2:
        prev_ema3 = _ema(history_scores[:-1] + [history_scores[-1]], 3)
        prev_ema5 = _ema(history_scores[:-1] + [history_scores[-1]], 5)
        if (prev_ema3 is not None and prev_ema5 is not None
                and ema3 is not None and ema5 is not None):
            momentum = 1 if (prev_ema3 <= prev_ema5 and ema3 > ema5) else 0

    return {
        "ema3": ema3,
        "ema5": ema5,
        "bullish_ma30": bull_ma,
        "bullish_std30": bull_std,
        "bearish_ma30": bear_ma,
        "bearish_std30": bear_std,
        "panic_signal": panic,
        "euphoria_signal": euphoria,
        "momentum_cross": momentum,
    }


def _ema(values: list[float], period: int) -> float | None:
    """指数移动平均（标准实现：alpha = 2/(period+1)）。"""
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema_val = sum(values[:period]) / period  # 种子用 SMA
    for v in values[period:]:
        ema_val = alpha * v + (1 - alpha) * ema_val
    return round(ema_val, 2)


def _mean_std(values: list[int]) -> tuple[float | None, float | None]:
    """均值 + 总体标准差。返回 (mean, std)，样本 < 2 时返回 (None, None)。"""
    if len(values) < 2:
        return None, None
    m = mean(values)
    s = pstdev(values)
    return round(m, 2), round(s, 2)


def _summarize_audit_from_posts(posts: list[dict]) -> dict:
    """从帖子列表统计审计摘要（用于缓存命中场景）。"""
    total = len(posts)
    matched = 0
    mismatched = 0
    pending = 0
    broken = 0
    mismatches = []
    for p in posts:
        st = p.get("audit_status")
        if st == "broken":
            broken += 1
            continue
        if p.get("title_match") == 1 or st in ("verified", "manual_accepted"):
            matched += 1
        elif p.get("title_match") == 0 or st == "mismatch":
            mismatched += 1
            mismatches.append({
                "post_id": p.get("post_id"),
                "stored": p.get("title"),
                "actual": p.get("actual_title"),
                "url": p.get("url"),
            })
        else:
            pending += 1
    return {
        "audited": matched + mismatched,
        "matched": matched,
        "mismatched": mismatched,
        "fetch_errors": 0,
        "skipped": broken,
        "mismatches": mismatches[:10],
        "total_posts": total,
    }


def analyze_sentiment(code: str, forum_type: str = "eastmoney") -> dict | None:
    """分析某只股票的社区情绪。

    v3 2026-06-06：
    - 失败时返回带 `_error=True, _reason=...` 的 dict（而非 None），
      路由层据此选择 503/500 + 准确文案
    - 成功时返回的 dict 包含 signals / indicators / 4 分类分布

    Args:
        code: 6位股票代码
        forum_type: 论坛类型

    Returns:
        成功：完整 dict
        失败：{"_error": True, "_reason": "circuit_open"|"no_posts"|"no_llm"|"parse_error"|"internal", "_message": "..."}
    """
    code = str(code).strip().zfill(6)
    today = date.today().isoformat()
    cache_hours = 1  # 1小时内不重复分析

    def _err(reason: str, message: str) -> dict:
        return {"_error": True, "_reason": reason, "_message": message}

    # 检查缓存（N小时内有效）
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT sentiment, score, summary, bullish_n, bearish_n,
                      neutral_n, noise_n, signals_json
               FROM sentiment_scores
               WHERE stock_code=? AND forum_type=?
               AND datetime(created_at) >= datetime('now', ?)
               ORDER BY created_at DESC LIMIT 1""",
            (code, forum_type, f"-{cache_hours} hours"),
        )
        cached = cur.fetchone()
    if cached:
        logger.info(f"情绪分析命中缓存: {code} {forum_type} (past {cache_hours}h)")
        # 从DB读取关联帖子
        cached_posts = get_recent_posts(code, forum_type, limit=15)
        audit_summary = _summarize_audit_from_posts(cached_posts)
        signals = json.loads(cached["signals_json"]) if cached["signals_json"] else {}
        return {"sentiment": cached["sentiment"], "score": cached["score"],
                "summary": cached["summary"], "cached": True,
                "audit": audit_summary,
                "bullish": cached["bullish_n"], "bearish": cached["bearish_n"],
                "neutral": cached["neutral_n"], "noise": cached["noise_n"],
                "signals": signals,
                "posts": [{"title": p["title"], "url": p["url"],
                           "post_id": p.get("post_id"),
                           "title_match": p.get("title_match"),
                           "audit_status": p.get("audit_status"),
                           "actual_title": p.get("actual_title")}
                          for p in cached_posts]}

    # 爬取帖子（含审计，v2 2026-06-04：网络韧性 - 熔断降级）
    try:
        posts, audit_summary = fetch_forum_posts(
            code, forum_type, days=3, fetch_content=True, audit=True
        )
    except CircuitOpenError as e:
        # 熔断中：降级 DB 缓存；DB 也空 → 明确告诉前端「熔断中 + 无缓存」
        logger.warning(f"guba 熔断中（{code}）: {e}，降级 DB 缓存")
        posts = get_recent_posts(code, forum_type, limit=30)
        audit_summary = {"audited": 0, "matched": 0, "mismatched": 0,
                         "fetch_errors": 0, "skipped": 0,
                         "circuit_open": True}
        if not posts:
            return _err("circuit_open", "guba 暂时不可达（熔断中），且无本地缓存")
    except requests.RequestException as e:
        logger.warning(f"抓取帖子网络异常（{code}）: {e}，降级 DB 缓存")
        posts = get_recent_posts(code, forum_type, limit=30)
        audit_summary = {"audited": 0, "matched": 0, "mismatched": 0,
                         "fetch_errors": 1, "skipped": 0}
        if not posts:
            return _err("network_error", f"网络异常且无缓存: {e}")

    if not posts:
        logger.warning(f"[{code}] 无可用帖子进行情绪分析")
        return _err("no_posts", "无可用帖子（guba 不可达 + DB 也没缓存）")

    # 结构化打印拉取结果：帖子数 + 审计摘要（fetch_forum_posts 已跑审计）
    _log_section(
        code, "拉取帖子",
        ("抓取帖子数", len(posts)),
        ("审计摘要", audit_summary),
    )

    # 标题真实性审计：fetch_forum_posts 默认已跑（audit=True）
    # 仅在 audit_summary 为 None 时补跑（兼容旧调用方）
    if audit_summary is None and posts:
        try:
            audit_summary = audit_posts(
                [{"post_id": p.get("post_id"), "title": p.get("title"),
                  "code": code, "url": p.get("url")}
                 for p in posts if p.get("post_id")],
                forum_type=forum_type,
            )
        except CircuitOpenError:
            audit_summary = {"audited": 0, "matched": 0, "mismatched": 0,
                             "fetch_errors": 0, "skipped": 0,
                             "circuit_open": True}

    # LLM 分析
    llm = _get_llm()
    if not llm:
        return _err("no_llm", "未配置 LLM API Key（DEEPSEEK_API_KEY / MINIMAX_API_KEY / VOLCANO_API_KEY）")

    posts_text, kept_posts = _build_posts_text(posts)
    if not kept_posts:
        logger.warning(f"过滤后无有效帖子: {code}")
        return _err("no_posts", "帖子全部被过滤规则剔除，无可分析内容")

    # 结构化打印 LLM 输入：帖子数 + 拼接后的 prompt 文本（截断到 600 字防刷屏）
    _log_section(
        code, "LLM 输入",
        ("forum_type", forum_type),
        ("输入帖子数", len(kept_posts)),
        ("prompt 帖子文本", posts_text[:600] + ("…" if len(posts_text) > 600 else "")),
    )

    chain = SENTIMENT_PROMPT | llm | StrOutputParser()

    try:
        t0 = time.time()
        result_str = chain.invoke({"code": code, "posts_text": posts_text})
        elapsed = time.time() - t0
        result_str = (result_str or "").strip()

        if not result_str:
            logger.error(f"[{code}] LLM 返回空响应")
            return _err("parse_error", "LLM 返回空响应")

        # 截断自适应重试：max_tokens 不够时输出在数组中间被切断、丢尾 ]。
        # 按 2x/4x 递增 max_tokens 重试，拿回完整标签集；到上限仍截断则交由
        # 解析器截断恢复兜底（丢尾部少数标签，不致整只失败）。
        retry_log = []
        cur_max_tokens = LLM_DEFAULT_MAX_TOKENS
        while _looks_truncated(result_str) and cur_max_tokens < LLM_MAX_TOKENS_CAP:
            cur_max_tokens = min(cur_max_tokens * 2, LLM_MAX_TOKENS_CAP)
            logger.warning(
                f"[{code}] LLM 输出截断（{len(result_str)} 字无闭合 ]），"
                f"以 max_tokens={cur_max_tokens} 重试"
            )
            t_retry = time.time()
            retry_chain = (
                SENTIMENT_PROMPT | llm.bind(max_tokens=cur_max_tokens) | StrOutputParser()
            )
            new_str = (retry_chain.invoke({"code": code, "posts_text": posts_text}) or "").strip()
            elapsed += time.time() - t_retry
            if new_str:
                result_str = new_str
                retry_log.append(cur_max_tokens)
            if not _looks_truncated(result_str):
                break

        truncated = _looks_truncated(result_str)
        # 结构化打印 LLM 原始输出：耗时 + 字数 + 是否截断 + 重试档位 + 内容
        _log_section(
            code, "LLM 输出",
            ("耗时", f"{elapsed:.1f}s"),
            ("返回字数", len(result_str)),
            ("是否截断(无闭合])", "是 ⚠️" if truncated else "否"),
            ("max_tokens", cur_max_tokens),
            ("截断重试档位", retry_log or "无"),
            ("原始响应", result_str[:1500] + ("…" if len(result_str) > 1500 else "")),
        )

        # ── 解析 v3 格式：[{id, label}, ...] ──
        labels_by_id, raw_parsed = _parse_labels_response(result_str)
        if labels_by_id is None:
            logger.error(
                f"[{code}] LLM 返回解析失败\n  raw(尾部 200 字): "
                f"{result_str[-200:]!r}"
            )
            return _err("parse_error", f"LLM 返回解析失败: {raw_parsed}")

        # 把 id 映射回 post_id + 收集标签
        per_post_labels = []
        int_labels = []
        for idx, p in enumerate(kept_posts, 1):
            label = labels_by_id.get(idx, LABEL_NEUTRAL)  # 缺失默认中性
            int_labels.append(label)
            pid = p.get("post_id")
            if pid is not None:
                per_post_labels.append({
                    "post_id": int(pid),
                    "label": int(label),
                    "raw_response": raw_parsed if idx == 1 else None,  # 只在第一条存 raw
                })

        # 写帖子级标签到 sentiment_post_labels
        if per_post_labels:
            try:
                upsert_post_labels(code, per_post_labels, forum_type,
                                   model=_get_current_model_name())
            except Exception as e:
                logger.warning(f"写 post_labels 失败 ({code}): {e}")

        # ── Python 算 score / sentiment / 分布 ──
        agg = _aggregate_labels(int_labels)
        summary = _build_summary(agg, kept_posts)  # 15 字以内

        # ── 算 panic / euphoria 等时序因子 ──
        history = _load_history_for_indicators(code, forum_type, days=30)
        indicators = _compute_indicators(
            code, agg,
            history_scores=history["scores"],
            history_bullish=history["bullish_n"],
            history_bearish=history["bearish_n"],
        )

        # ── 写 sentiment_scores（含 4 分类 + signals_json） ──
        signals_payload = {
            "panic": indicators["panic_signal"],
            "euphoria": indicators["euphoria_signal"],
            "momentum_cross": indicators["momentum_cross"],
        }
        with get_connection() as conn:
            conn.cursor().execute(
                """INSERT OR REPLACE INTO sentiment_scores
                   (stock_code, forum_type, date, sentiment, score, post_count,
                    summary, bullish_n, bearish_n, neutral_n, noise_n, signals_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, forum_type, today, agg["sentiment"], agg["score"],
                 len(kept_posts), summary,
                 agg["bullish"], agg["bearish"], agg["neutral"], agg["noise"],
                 json.dumps(signals_payload, ensure_ascii=False)),
            )

        # ── 写 sentiment_indicators（时序因子） ──
        try:
            upsert_indicators(
                code, today, agg["score"],
                indicators["ema3"], indicators["ema5"],
                indicators["bullish_ma30"], indicators["bullish_std30"],
                indicators["bearish_ma30"], indicators["bearish_std30"],
                indicators["panic_signal"], indicators["euphoria_signal"],
                indicators["momentum_cross"],
            )
        except Exception as e:
            logger.warning(f"写 indicators 失败 ({code}): {e}")

        # 结构化打印分析结果：聚合分布 + 标签序列 + signals
        labels_seq = [labels_by_id.get(i, LABEL_NEUTRAL)
                      for i in range(1, len(kept_posts) + 1)]
        _log_section(
            code, "情绪分析完成",
            ("sentiment", agg["sentiment"]),
            ("score", agg["score"]),
            ("分布", {k: agg[k] for k in ("bullish", "bearish", "neutral", "noise")}),
            ("有效分析数", agg["total_analyzed"]),
            ("标签序列(1=多/0=中/-1=空/99=噪)", labels_seq),
            ("signals", signals_payload),
            ("indicators", {k: v for k, v in indicators.items()
                            if k in ("ema3", "ema5", "panic_signal",
                                    "euphoria_signal", "momentum_cross")}),
            ("summary", summary),
        )

        return {
            "sentiment": agg["sentiment"], "score": agg["score"],
            "summary": summary, "post_count": len(kept_posts),
            "bullish": agg["bullish"], "bearish": agg["bearish"],
            "neutral": agg["neutral"], "noise": agg["noise"],
            "cached": False,
            "audit": audit_summary,
            "signals": signals_payload,
            "indicators": {k: v for k, v in indicators.items()
                            if k in ("ema3", "ema5", "panic_signal",
                                    "euphoria_signal", "momentum_cross")},
            "posts": [{"title": p["title"], "url": p["url"],
                       "post_id": p.get("post_id"),
                       "label": labels_by_id.get(i + 1, LABEL_NEUTRAL),
                       "title_match": p.get("title_match"),
                       "audit_status": p.get("audit_status"),
                       "actual_title": p.get("actual_title")}
                      for i, p in enumerate(kept_posts[:15])],
        }
    except Exception as e:
        logger.error(f"情绪分析失败: {code}: {e}", exc_info=True)
        return _err("internal", f"分析过程异常: {e}")


def _parse_labels_response(result_str: str) -> tuple[dict[int, int] | None, str | None]:
    """解析 LLM 返回的 `[{id, label}, ...]` 数组。

    容错策略：
    1. 剥离 <think>...</think>
    2. 剥 markdown ```json``` 包裹
    3. 找到第一个 [ 到最后一个 ]，尝试 parse
    4. 截断恢复：max_tokens 不够时 LLM 输出在数组中间被切断，没有闭合 ]。
       找最后一个完整对象的右大括号 } 截断后补 ] 重试
    5. 逐个缩短尾部字符重试（应对尾部多余文字）
    6. 提取 {id, label} 字段，校验 label ∈ {1, 0, -1, 99}
    """
    s = result_str
    # 1. 剥离 think
    think_match = re.search(r"<think>.*?</think>", s, re.DOTALL)
    if think_match:
        s = s[think_match.end():].strip()
    if not s:
        s = result_str

    # 2. markdown code block
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("["):
                s = p
                break

    # 3. 找 [ 到 ]
    start = s.find("[")
    if start < 0:
        return None, None
    end = s.rfind("]")

    # 4. 截断恢复：没有闭合 ]（输出被 max_tokens 切断）→
    #    找最后一个完整对象的 }，截断后补 ] 再 parse
    if end <= start:
        last_obj_end = s.rfind("}")
        if last_obj_end > start:
            s_trunc = s[start:last_obj_end + 1] + "]"
            try:
                parsed = json.loads(s_trunc)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                logger.warning(
                    f"LLM 输出被截断（无闭合 ]），截断恢复成功: "
                    f"已解析 {len(parsed)} 条标签"
                )
                return _extract_label_map(parsed, result_str)
        return None, None

    s = s[start:end + 1]

    # 5. parse + 逐个缩短重试
    parsed = None
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        for i in range(len(s) - 1, start + 1, -1):
            try:
                parsed = json.loads(s[:i] + "]")
                break
            except json.JSONDecodeError:
                continue
    if parsed is None or not isinstance(parsed, list):
        return None, None

    return _extract_label_map(parsed, result_str)


def _extract_label_map(parsed: list, result_str: str) -> tuple[dict[int, int] | None, str | None]:
    """从已解析的 list 提取 {id: label}，校验 label 并做容错映射。"""
    out: dict[int, int] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("id"))
            lbl = int(item.get("label"))
        except (TypeError, ValueError):
            continue
        if lbl not in VALID_LABELS:
            # 容错：把异常值映射到最近的有效标签
            if lbl > 1: lbl = LABEL_BULLISH
            elif lbl < -1: lbl = LABEL_BEARISH
            else: lbl = LABEL_NEUTRAL
        out[idx] = lbl

    return (out if out else None), result_str


def _build_summary(agg: dict, kept_posts: list[dict]) -> str:
    """根据聚合结果生成 15 字以内的中文总结。

    极简规则版：直接根据分数给模板。
    """
    score = agg["score"]
    if score >= 80:
        return "极度乐观，看多主导"
    if score >= 65:
        return "偏乐观，多方占优"
    if score >= 55:
        return "略偏多，整体温和"
    if score >= 45:
        return "多空平衡，观望为主"
    if score >= 35:
        return "略偏空，谨慎情绪"
    if score >= 20:
        return "偏悲观，空方主导"
    return "极度悲观，恐慌蔓延"


def _load_history_for_indicators(code: str, forum_type: str,
                                 days: int = 30) -> dict:
    """加载历史 sentiment_scores 序列，供时序因子计算用。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT score, bullish_n, bearish_n FROM sentiment_scores
               WHERE stock_code=? AND forum_type=?
               AND date >= date('now', ?)
               ORDER BY date ASC""",
            (code, forum_type, f"-{days} day"),
        )
        rows = cur.fetchall()
    return {
        "scores": [r["score"] for r in rows],
        "bullish_n": [r["bullish_n"] for r in rows],
        "bearish_n": [r["bearish_n"] for r in rows],
    }


# ── 批量分析进度状态（v7 2026-06-29）─────────────────────────────────────────
# 历史问题：v4 起用模块级 _BATCH_STATE 内存 dict 维护进度，前端经
# get_batch_status() 轮询。多进程部署（gunicorn 多 worker）下，跑批的 worker
# 与处理轮询请求的 worker 不是同一进程，读不到对方内存 → 前端永远 running=False。
# 且违反 CLAUDE.md Phase B「禁止 *_state 内存 dict」约束。
# 现改为：进度完全落 task_runs 表（result_json 存运行中快照），get_batch_status
# 从 DB 读，跨进程可用。_BATCH_LOCK 仅作同进程内防重入兜底。
_BATCH_LOCK = threading.Lock()


def _latest_batch_task_run() -> dict | None:
    """取最近一条 kind='sentiment_batch' 的 task_run（任意状态）。"""
    from backend.core.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM task_runs WHERE kind='sentiment_batch' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_batch_status() -> dict:
    """批量分析任务进度（前端轮询用，跨进程）。

    从 task_runs 表最近一条 sentiment_batch 记录还原：
    - running / total / done / failed / current / current_name
    - failed / current / current_name 从 result_json 快照解析（运行中写入）
    """
    row = _latest_batch_task_run()
    if not row:
        return {
            "running": False, "total": 0, "done": 0, "failed": 0,
            "current": None, "current_name": None,
            "started_at": None, "finished_at": None,
        }

    snap = {}
    if row.get("result_json"):
        try:
            snap = json.loads(row["result_json"])
        except Exception:
            snap = {}

    running = row.get("status") == "running"
    done = row.get("done") or 0
    total = row.get("total") or 0
    # 完成态：result_json 形如 {analyzed, total, failed}；运行态：{done, failed, current, current_name}
    failed = snap.get("failed", 0) if isinstance(snap.get("failed", 0), int) else 0
    current = snap.get("current")
    current_name = snap.get("current_name")
    if running and snap.get("done") is not None:
        done = snap.get("done", done)

    return {
        "running": running,
        "total": total,
        "done": done,
        "failed": failed,
        "current": current,
        "current_name": current_name,
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "task_id": row.get("id"),
    }


def batch_analyze(codes: list[str] = None, forum_type: str = "eastmoney",
                  max_workers: int = 5, task_runner=None) -> list[dict]:
    """批量分析所有启用监控的（或指定）股票，并发执行。

    v3 2026-06-06：
    - max_workers 3 → 5（max_tokens 降到 512 后单只耗时降，并发可适当提）
    - 加 per-code in-flight dedup：同 code 第二次起等待第一次的结果
    - 加 5s 进度日志
    v4 2026-06-07：
    - 进度经 task_runs 表暴露给前端轮询
    v5 2026-06-08：
    - per-future deadline（PER_STOCK_DEADLINE）：单只股票超过 90s 仍不返回
      则强制标记为失败（TimeoutError），UI 解锁，整体批次继续推进。
    v6 2026-06-10：
    - 接受 task_runner (TaskRunner) 参数，进度写入 task_runs 表
    v7 2026-06-29：
    - 废弃模块级 _BATCH_STATE 内存 dict（多进程下读不到，违反 Phase B）；
      进度快照写 task_runs.result_json，get_batch_status 从 DB 读，跨进程可用。
    """
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from concurrent.futures import TimeoutError as _FutTimeout

    if not _BATCH_LOCK.acquire(blocking=False):
        logger.warning("已有批量分析任务在进行中（同进程）")
        return []
    try:
        if codes is None:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """SELECT stock_code, stock_name FROM sentiment_config
                       WHERE enabled=1 AND forum_type=?""",
                    (forum_type,),
                )
                rows = cur.fetchall()
                codes = [r["stock_code"] for r in rows]
                code_to_name = {r["stock_code"]: (r["stock_name"] or "") for r in rows}

        # 进度镜像（本地，跨进程通过 task_runs.result_json 暴露）
        prog = {
            "total": len(codes), "done": 0, "failed": 0,
            "current": None, "current_name": None,
        }
        last_persist = [0.0]  # 上次落库时间，节流

        def _persist_progress(force: bool = False):
            """把进度快照写进 task_runs.result_json（跨进程轮询用）。节流到 ~2s/次。"""
            if not task_runner:
                return
            now = time.time()
            if not force and now - last_persist[0] < 2:
                return
            last_persist[0] = now
            from backend.core.database import update_task_run
            update_task_run(
                task_runner.id,
                done=prog["done"],
                result_json={
                    "done": prog["done"], "failed": prog["failed"],
                    "current": prog["current"], "current_name": prog["current_name"],
                },
            )

        if not codes:
            logger.info("没有需要分析的股票")
            if task_runner:
                task_runner.complete(result={"analyzed": 0, "total": 0, "failed": 0})
            return []

        logger.info(f"开始并发分析 {len(codes)} 只股票 (workers={max_workers})")
        if task_runner:
            task_runner.set_total(len(codes))
            task_runner.milestone(f"开始并发分析 {len(codes)} 只股票 (workers={max_workers})")
            _persist_progress(force=True)
        results = []
        in_flight: dict[str, "concurrent.futures.Future"] = {}
        submit_at: dict[str, float] = {}  # per-future 提交时间，用于公平 deadline

        def _analyze_one(code):
            return analyze_sentiment(code, forum_type)

        last_log = [time.time()]
        # v5 2026-06-08：单只股票硬截止 90s（含 guba 抓取 + 审计 + LLM）
        per_stock_deadline = float(os.environ.get("SENTIMENT_BATCH_PER_STOCK_TIMEOUT", "90"))
        # 整个批次上限：15 只 × 90s 顺序除以 5 并发 ≈ 270s，再加 2x buffer = 600s（10 分钟）
        batch_deadline = float(os.environ.get("SENTIMENT_BATCH_TOTAL_TIMEOUT", "600"))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 启动时先 dedup（同 code 已在 in_flight 的不再 submit 第二次）
            for c in codes:
                if c not in in_flight:
                    in_flight[c] = executor.submit(_analyze_one, c)
                    submit_at[c] = time.time()
                    prog["current"] = c
                    prog["current_name"] = code_to_name.get(c, "")

            batch_start = time.time()
            # 循环驱动而不是 as_completed：以便每次循环可设置 deadline，
            # 把"卡死的 future"显式打 failed 并让 UI 推进。
            while in_flight:
                if task_runner:
                    task_runner.check_cancelled()
                # 已完成的立即收
                completed_now = [c for c, f in in_flight.items() if f.done()]
                if not completed_now:
                    # 仍有 in-flight，等一下再看（用阻塞 + 短 timeout，避免 spin）
                    wait_timeout = min(per_stock_deadline, batch_deadline - (time.time() - batch_start))
                    if wait_timeout <= 0:
                        # 整批超时
                        break
                    # 等任一 future 完成
                    done_set, _ = wait(
                        list(in_flight.values()),
                        timeout=wait_timeout,
                        return_when=FIRST_COMPLETED,
                    )
                    completed_now = [c for c, f in in_flight.items() if f.done()]
                    if not completed_now:
                        # 全部 in-flight 都卡住了，遍历找超过 per-stock deadline 的 → 标 failed
                        now = time.time()
                        stuck = [(c, f) for c, f in in_flight.items()
                                 if not f.done() and (now - submit_at.get(c, now)) > per_stock_deadline]
                        if stuck:
                            for c, f in stuck:
                                logger.warning(f"批量分析 {c} 超过 {per_stock_deadline:.0f}s 未返回，强制标记失败（future 仍在跑但 UI 不再等待）")
                                f.cancel()  # 尝试取消；若已运行则 no-op
                                prog["failed"] += 1
                                in_flight.pop(c, None)
                                submit_at.pop(c, None)
                            _persist_progress()
                        else:
                            # 没到 deadline 但 wait 返回 0 个 done，说明所有 future 都被同一未捕获的
                            # 异常拖累；做一次 sanity 检查：是否所有都已 done 但未收
                            completed_now = [c for c, f in in_flight.items() if f.done()]

                for code in completed_now:
                    future = in_flight.pop(code, None)
                    submit_at.pop(code, None)
                    if future is None:
                        continue
                    try:
                        result = future.result(timeout=0)
                        if result and not result.get("_error"):
                            result["code"] = code
                            results.append(result)
                            prog["done"] += 1
                        else:
                            prog["failed"] += 1
                    except _FutTimeout:
                        logger.warning(f"批量分析 {code} 结果等待超时")
                        prog["failed"] += 1
                    except Exception as e:
                        logger.error(f"批量分析 {code} 异常: {e}", exc_info=True)
                        prog["failed"] += 1
                    if task_runner:
                        task_runner.progress(prog["done"] + prog["failed"])
                    _persist_progress()
                # 当前正在分析：挑一个还在 inflight 的
                remaining = [c for c, f in in_flight.items() if not f.done()]
                next_code = remaining[0] if remaining else None
                prog["current"] = next_code
                prog["current_name"] = code_to_name.get(next_code, "") if next_code else ""
                # 进度日志：每 5s 打一次
                if time.time() - last_log[0] > 5:
                    logger.info(f"批量进度: {prog['done']+prog['failed']}/{len(codes)} (in_flight={len(in_flight)})")
                    last_log[0] = time.time()
                # 整批超时
                if time.time() - batch_start > batch_deadline:
                    logger.warning(f"批量舆情分析总时长超过 {batch_deadline:.0f}s，强制结束，剩余 {len(in_flight)} 只标记失败")
                    for c, f in list(in_flight.items()):
                        prog["failed"] += 1
                        f.cancel()
                        submit_at.pop(c, None)
                    in_flight.clear()
                    break

        logger.info(f"批量舆情分析完成: {len(results)}/{len(codes)} 只股票 (failed={prog['failed']})")
        if task_runner:
            task_runner.milestone(
                f"分析完成: {len(results)}/{len(codes)} 只股票 (失败 {prog['failed']})"
            )
            task_runner.complete(result={
                "analyzed": len(results),
                "total": len(codes),
                "failed": prog["failed"],
                "done": prog["done"],
            })
        return results
    finally:
        _BATCH_LOCK.release()


def get_sentiment_history(code: str, forum_type: str = "eastmoney",
                          days: int = 30) -> list[dict]:
    """获取某只股票的历史情绪数据。

    v3 2026-06-06：返回字段扩展，包含 4 分类分布 + signals_json。
    """
    code = str(code).strip().zfill(6)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date, sentiment, score, post_count, summary,
                      bullish_n, bearish_n, neutral_n, noise_n, signals_json
               FROM sentiment_scores
               WHERE stock_code=? AND forum_type=?
               ORDER BY date DESC LIMIT ?""",
            (code, forum_type, days),
        )
        rows = [dict(r) for r in cur.fetchall()]
    # 解析 signals_json
    for r in rows:
        if r.get("signals_json"):
            try:
                r["signals"] = json.loads(r["signals_json"])
            except Exception:
                r["signals"] = {}
        else:
            r["signals"] = {}
        r.pop("signals_json", None)
    return rows
