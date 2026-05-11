"""
情感分析服务 — 使用 LangChain + LLM 分析股票社区情绪。
支持 DeepSeek / MiniMax / 火山云，通过环境变量配置。
"""

import os
import re
import json
import time
import sys
import logging
from datetime import date

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from backend.core.database import get_connection
from backend.services.forum_service import fetch_forum_posts, get_recent_posts

logger = logging.getLogger(__name__)


class _StreamLogHandler(BaseCallbackHandler):
    """流式回调：实时打印 LLM 进度。"""

    def __init__(self, code: str):
        self.code = code
        self.chars = 0
        self.t0 = None

    def on_llm_start(self, *args, **kwargs):
        self.t0 = time.time()

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        if self.chars == 0:
            logger.info(f"[{self.code}] MiniMax 分析中...")
        self.chars += len(token)

    def on_llm_end(self, *args, **kwargs):
        elapsed = time.time() - self.t0 if self.t0 else 0
        logger.info(f"[{self.code}] MiniMax 返回 {self.chars} 字, 耗时 {elapsed:.1f}s")


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
        "model": "MiniMax-M2.7",
    },
    "volcano": {
        "api_key_env": "VOLCANO_API_KEY",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
    },
}

SENTIMENT_PROMPT = PromptTemplate.from_template("""\
给{code}的帖子逐条打标"看多/看空/中性"，统计后算分输出JSON。

帖子：
{posts_text}

输出JSON：
{{"sentiment":"乐观|中性|悲观","score":50,"summary":"15字总结","bullish":N,"bearish":N,"neutral":N}}
score=看多÷(看多+看空)×100。>60乐观<40悲观。不要解释。
""")


def _get_llm() -> ChatOpenAI | None:
    """根据环境变量自动选择可用的 LLM 提供商。"""
    for provider, cfg in LLM_CONFIG.items():
        api_key = os.environ.get(cfg["api_key_env"], "").strip()
        if api_key:
            logger.info(f"使用 LLM 提供商: {provider} (model={cfg['model']})")
            return ChatOpenAI(
                api_key=api_key,
                base_url=cfg["base_url"],
                model=cfg["model"],
                temperature=0.3,
                max_tokens=16384,
            )
    logger.error("未配置任何 LLM API Key，请设置 DEEPSEEK_API_KEY / MINIMAX_API_KEY / VOLCANO_API_KEY")
    return None


def _build_posts_text(posts: list[dict], max_chars: int = 3000) -> str:
    """将帖子列表拼接为 prompt 可用的文本。"""
    lines = []
    total_chars = 0
    for i, p in enumerate(posts, 1):
        title = p.get("title", "")
        content = (p.get("content") or "").strip()
        # 过滤掉纯"转发"的无意义帖
        if not title or title in ("转发", "。"):
            title = content[:30] if content else ""
        if title in ("转发", "", "。"):
            continue
        text = f"[{i}] {title[:80]}"
        # 只带前80字正文
        if content and len(content) > 10:
            text += f"\n    {content[:80]}"
        if total_chars + len(text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 60:
                lines.append(text[:remaining])
            break
        lines.append(text)
        total_chars += len(text)
    return "\n\n".join(lines)


def analyze_sentiment(code: str, forum_type: str = "eastmoney") -> dict | None:
    """分析某只股票的社区情绪。

    优先使用 DB 缓存（同一天不重复分析），否则爬取帖子 → LLM 分析 → 缓存结果。

    Args:
        code: 6位股票代码
        forum_type: 论坛类型

    Returns:
        {"sentiment": "...", "score": N, "summary": "..."} 或 None
    """
    code = str(code).strip().zfill(6)
    today = date.today().isoformat()
    cache_hours = 1  # 1小时内不重复分析

    # 检查缓存（N小时内有效）
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT sentiment, score, summary FROM sentiment_scores
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
        return {"sentiment": cached["sentiment"], "score": cached["score"],
                "summary": cached["summary"], "cached": True,
                "posts": [{"title": p["title"], "url": p["url"]} for p in cached_posts]}

    # 爬取帖子
    posts = fetch_forum_posts(code, forum_type, days=3, fetch_content=True)
    if not posts:
        # 尝试从 DB 取缓存帖子
        posts = get_recent_posts(code, forum_type, limit=30)

    if not posts:
        logger.warning(f"无可用帖子进行情绪分析: {code}")
        return None

    # LLM 分析
    llm = _get_llm()
    if not llm:
        return None

    posts_text = _build_posts_text(posts)
    chain = SENTIMENT_PROMPT | llm | StrOutputParser()

    try:
        result_str = chain.invoke(
            {"code": code, "posts_text": posts_text},
            config={"callbacks": [_StreamLogHandler(code)]},
        )
        original = result_str.strip()

        if not original:
            logger.error(f"LLM 返回空响应: {code}")
            return None

        logger.debug(f"LLM raw response ({len(original)} chars): {original[:300]}")

        # 去除 <think>...</think> 推理块（MiniMax M2.7 等模型会输出）
        think_match = re.search(r"<think>.*?</think>", original, re.DOTALL)
        if think_match:
            result_str = original[think_match.end():].strip()
            # 如果剥离 think 后为空，尝试从 think 块外面找内容
            if not result_str:
                result_str = original
        else:
            result_str = original

        # 提取 JSON（LLM 可能在前后加文字、markdown代码块）
        # 先处理 ```json ... ``` 代码块
        if "```" in result_str:
            parts = result_str.split("```")
            for p in parts:
                p = p.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    result_str = p
                    break

        # 找到第一个 { 到最后一个 } 之间的 JSON，忽略尾部多余文字
        start = result_str.find("{")
        end = result_str.rfind("}")
        if start >= 0 and end > start:
            result_str = result_str[start:end + 1]

        # 尝试解析，如果有多余数据则截断到最后一个有效JSON对象
        try:
            result = json.loads(result_str)
        except json.JSONDecodeError:
            # 可能有多余文字在JSON后面，逐个缩短尝试
            for i in range(len(result_str), start + 2, -1):
                try:
                    result = json.loads(result_str[:i])
                    result_str = result_str[:i]
                    break
                except json.JSONDecodeError:
                    continue
            else:
                raise

        sentiment = result.get("sentiment", "中性")
        score = int(result.get("score", 50))
        summary = result.get("summary", "")[:100]
        post_count = len(posts)

        # 写入 DB 缓存
        with get_connection() as conn:
            conn.cursor().execute(
                """INSERT OR REPLACE INTO sentiment_scores
                   (stock_code, forum_type, date, sentiment, score, post_count, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (code, forum_type, today, sentiment, score, post_count, summary),
            )

        logger.info(f"情绪分析完成: {code} sentiment={sentiment} score={score}")
        return {"sentiment": sentiment, "score": score, "summary": summary,
                "post_count": post_count, "cached": False,
                "posts": [{"title": p["title"], "url": p["url"]} for p in posts[:15]]}
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"LLM 返回解析失败: {e}, raw={result_str[:200]}")
        return None
    except Exception as e:
        logger.error(f"情绪分析失败: {code}: {e}", exc_info=True)
        return None


def batch_analyze(codes: list[str] = None, forum_type: str = "eastmoney",
                  max_workers: int = 3) -> list[dict]:
    """批量分析所有启用监控的（或指定）股票，并发执行。"""
    if codes is None:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT stock_code FROM sentiment_config
                   WHERE enabled=1 AND forum_type=?""",
                (forum_type,),
            )
            codes = [r["stock_code"] for r in cur.fetchall()]

    if not codes:
        logger.info("没有需要分析的股票")
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info(f"开始并发分析 {len(codes)} 只股票 (workers={max_workers})")
    results = []

    def _analyze_one(code):
        result = analyze_sentiment(code, forum_type)
        if result:
            result["code"] = code
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyze_one, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    logger.info(f"批量进度: {len(results)}/{len(codes)} - {code} 完成")
            except Exception as e:
                logger.error(f"批量分析 {code} 异常: {e}", exc_info=True)

    logger.info(f"批量舆情分析完成: {len(results)}/{len(codes)} 只股票")
    return results


def get_sentiment_history(code: str, forum_type: str = "eastmoney",
                          days: int = 30) -> list[dict]:
    """获取某只股票的历史情绪数据。"""
    code = str(code).strip().zfill(6)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT date, sentiment, score, post_count, summary FROM sentiment_scores
               WHERE stock_code=? AND forum_type=?
               ORDER BY date DESC LIMIT ?""",
            (code, forum_type, days),
        )
        return [dict(r) for r in cur.fetchall()]
