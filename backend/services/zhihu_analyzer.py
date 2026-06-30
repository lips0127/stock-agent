"""
知乎动态 LLM 分析器。
复用 sentiment_service 中的 LLM 客户端（DeepSeek / MiniMax / 火山云）。
对单篇知乎文章/回答做结构化分析：
  - 整体立场（看多/看空/中性/混合）
  - 涉及的资产（A股/港股/美股/黄金/汇率/债券/加密等）+ 各自立场
  - 行业/板块
  - 60字总结 + 60字行动建议
  - 关键观点 3-5 条
  - 置信度 0-100
"""
import re
import json
import time
import logging
from datetime import datetime
from typing import Any

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.callbacks import BaseCallbackHandler

from backend.core.database import (
    get_zhihu_post_by_id,
    upsert_zhihu_analysis,
)

logger = logging.getLogger(__name__)


# ── LLM 客户端（从 sentiment_service 复用） ──────────────────────
try:
    from backend.services.sentiment_service import _get_llm, _StreamLogHandler
except Exception:
    _get_llm = None
    _StreamLogHandler = None

ANALYSIS_PROMPT = PromptTemplate.from_template("""\
你是一名严谨的卖方研究分析师。请分析下面这篇知乎文章/回答，输出结构化 JSON。

【任务】
1. 判断作者对各资产的立场：bullish（看多）/ bearish（看空）/ neutral（中性）
2. 提取涉及的【具体资产】，按"个股 > ETF/指数 > 板块 > 大类"的优先级：
   - 优先：具体股票代码或名称（"腾讯 00700"、"茅台 600519"、"英伟达 NVDA"、"中际旭创 300308"）
   - 次之：指数/ETF（"沪深300"、"纳指"、"黄金ETF"）
   - 再次：板块（"半导体"、"白酒"、"新能源"）
   - 最后：大类（"A股"、"港股"、"美股"、"黄金"）—— 仅在以上都不适用时使用
3. 总结作者的核心观点（3 条以内）
4. 给出 60 字以内的可执行建议（具体到「加仓 X / 减仓 Y / 关注 Z」的动作，不要"咨询专业人士"这种废话）
5. 置信度 0-100：你对作者立场的解读把握

【资产字段规范（每条 stance_assets 必须填齐）】
  asset    : 资产名称（必填，最长 30 字；个股用简称如"腾讯"、"中际旭创"，不写全称）
  code     : 代码（可选，能识别就填：A 股 6 位数字 / 港股 5 位数字 / 美股 1-5 位大写字母）
  category : 类别（必填，枚举值见下）
  stance   : bullish / bearish / neutral
  reason   : 20 字内的判断依据

【category 枚举】
  cn_stock  : A 股个股
  hk_stock  : 港股
  us_stock  : 美股
  index     : 指数（沪深300、纳指、恒生等）
  etf       : ETF（黄金ETF、纳指ETF 等）
  commodity : 大宗商品（黄金、原油、铜等）
  fx        : 外汇（美元、人民币、日元等）
  crypto    : 加密货币（BTC、ETH 等）
  bond      : 债券（国债、可转债等）
  sector    : 行业板块（半导体、白酒、新能源、医药等）

【立场一致性】
- 整体 stance 与 stance_assets 不矛盾：若对不同资产持相反立场，stance 必须为 mixed
- 同一资产只能出现一次 stance（去重）；若文中对同一资产前后表态相反，按"最新 + 最具体"原则取一个
- 任何对市场、个股、行业的具体看多/看空都必须有对应的 stance_assets 条目，**不能把多个股票合并到"A股"一类**

【忽略】
- 与投资无关的寒暄、专栏介绍
- 免责声明（如"不构成投资建议"）
- 推广、引流内容

【输出 JSON（不要解释、不要 markdown 代码块）】
{{
  "stance": "bullish | bearish | neutral | mixed",
  "stance_assets": [
    {{"asset": "中际旭创", "code": "300308", "category": "cn_stock", "stance": "bullish", "reason": "AI 光模块龙头"}},
    {{"asset": "沪深300", "category": "index", "stance": "neutral", "reason": "指数横盘"}},
    {{"asset": "黄金", "category": "commodity", "stance": "bearish", "reason": "避险情绪回落"}}
  ],
  "sectors": ["科技", "金融"],
  "summary": "60字内总结",
  "action_suggestion": "60字内具体建议",
  "key_points": ["要点1", "要点2", "要点3"],
  "confidence": 70
}}

【原文】
标题：{title}
作者：{author}
发布时间：{created_at}
正文：
{content}
""")


def _strip_think(text: str) -> str:
    """剥离模型思考块，返回实际响应。

    兼容多种格式（不同模型/不同 SDK 输出的思考标签各异）：
      - ``<think>...</think>``（MiniMax 官方 OpenAI 兼容 API）
      - ``<reasoning>...</reasoning>``（Anthropic-like）
      - ``<reflection>...</reflection>``
      - ``<|reasoning|>...<|/reasoning|>``（特殊 token）
      - ``<|begin▁of▁thinking|>...<|end▁of▁thinking|>``（Anthropic 内部）

    关键改进：原版只在 `</think>` **之后还有内容**时才截断；新版即使 think
    块占满全部内容、之后什么都没有，也视为空响应（不再误把 think 块当成答案）。
    """
    if not text:
        return ""
    # 先尝试带 closing 标签的标准格式
    patterns = [
        r"<think>.*?</think>",
        r"<reasoning>.*?</reasoning>",
        r"<reflection>.*?</reflection>",
        r"<\|reasoning\|>.*?<\|/reasoning\|>",
        r"<\|begin▁of▁thinking\|>.*?<\|end▁of▁thinking\|>",
    ]
    for p in patterns:
        m = re.search(p, text, re.DOTALL)
        if m:
            # 截掉 think 部分，返回剩余内容
            after = text[m.end():].strip()
            if after:
                return after
            # 整段都是 think 块，无后续内容 → 视为空
            return ""
    return text


def _extract_json(text: str) -> dict | None:
    if "```" in text:
        for part in text.split("```"):
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                text = p
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        for i in range(end, start + 1, -1):
            try:
                return json.loads(text[start:i + 1])
            except json.JSONDecodeError:
                continue
    return None


_ASSET_CATEGORIES = ("cn_stock", "hk_stock", "us_stock", "index", "etf",
                      "commodity", "fx", "crypto", "bond", "sector")

# 把 LLM 自由发挥的类别名规范化到枚举值上
_CATEGORY_NORMALIZE = {
    "a股": "cn_stock", "a股个股": "cn_stock", "沪深a": "cn_stock", "sh": "cn_stock", "sz": "cn_stock",
    "港股": "hk_stock", "hk": "hk_stock", "恒生": "index", "恒生指数": "index",
    "美股": "us_stock", "us": "us_stock", "纳斯达克": "index", "纳指": "index",
    "道琼斯": "index", "标普": "index", "sp500": "index", "spx": "index",
    "沪深300": "index", "上证": "index", "深证": "index", "创业板": "index", "科创50": "index",
    "btc": "crypto", "eth": "crypto", "比特币": "crypto", "以太坊": "crypto", "加密货币": "crypto",
    "usd": "fx", "美元": "fx", "人民币": "fx", "汇率": "fx",
    "原油": "commodity", "石油": "commodity", "黄金": "commodity", "白银": "commodity",
    "铜": "commodity", "商品": "commodity", "大宗商品": "commodity",
    "国债": "bond", "债券": "bond", "可转债": "bond",
    "etf": "etf", "基金": "etf",
    "板块": "sector", "行业": "sector", "半导体": "sector", "白酒": "sector",
    "新能源": "sector", "医药": "sector", "科技": "sector", "金融": "sector",
}


def _normalize_category(raw) -> str:
    """把 LLM 返回的 category 规范化到枚举值；不在表里则返回空串（前端按无分类处理）。"""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if s in _ASSET_CATEGORIES:
        return s
    return _CATEGORY_NORMALIZE.get(s, "")


def _validate_result(d: dict) -> dict:
    """规范化 LLM 输出，做容错。"""
    stance = str(d.get("stance", "neutral")).lower()
    if stance not in ("bullish", "bearish", "neutral", "mixed"):
        stance = "neutral"

    assets_in = d.get("stance_assets") or []
    if not isinstance(assets_in, list):
        assets_in = []
    assets_out = []
    for a in assets_in[:8]:
        if not isinstance(a, dict):
            continue
        asset_name = str(a.get("asset", "")).strip()[:30]
        a_stance = str(a.get("stance", "neutral")).lower()
        if a_stance not in ("bullish", "bearish", "neutral"):
            a_stance = "neutral"
        reason = str(a.get("reason", "")).strip()[:100]
        if not asset_name:
            continue
        code = str(a.get("code", "")).strip()[:12] if a.get("code") else ""
        category = _normalize_category(a.get("category"))
        assets_out.append({
            "asset": asset_name,
            "code": code,
            "category": category,
            "stance": a_stance,
            "reason": reason,
        })

    sectors = d.get("sectors") or []
    if not isinstance(sectors, list):
        sectors = []
    sectors = [str(s).strip()[:20] for s in sectors if str(s).strip()][:6]

    summary = str(d.get("summary", ""))[:100]
    action = str(d.get("action_suggestion", ""))[:100]

    kp = d.get("key_points") or []
    if not isinstance(kp, list):
        kp = []
    key_points = [str(p).strip()[:120] for p in kp if str(p).strip()][:5]

    try:
        confidence = int(d.get("confidence", 50))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    return {
        "stance": stance,
        "stance_assets": assets_out,
        "sectors": sectors,
        "summary": summary,
        "action_suggestion": action,
        "key_points": key_points,
        "confidence": confidence,
    }


def analyze_post(post_id: str, force: bool = False) -> dict | None:
    """对单篇知乎动态做 LLM 分析，结果写入 zhihu_analyses。

    Args:
        post_id: 知乎 post_id
        force: True 时强制重跑（覆盖已有分析）
    """
    if _get_llm is None:
        logger.error("sentiment_service 不可用，无法调用 LLM")
        return None

    post = get_zhihu_post_by_id(post_id)
    if not post:
        logger.warning(f"知乎 post 不存在: {post_id}")
        return None

    if not force and post.get("stance") is not None:
        logger.info(f"知乎分析已存在: {post_id}")
        return _serialize_analysis(post)

    llm = _get_llm()
    if not llm:
        return None

    title = post.get("title", "") or ""
    content = (post.get("content_text") or post.get("excerpt") or "")[:3000]
    author = post.get("url_token", "")
    created_at = post.get("created_at_original", "") or ""

    chain = ANALYSIS_PROMPT | llm | StrOutputParser()
    code = f"ZH-{post_id[:10]}"
    callbacks = [_StreamLogHandler(code)] if _StreamLogHandler else []

    t0 = time.time()
    try:
        raw = chain.invoke(
            {"title": title, "author": author, "created_at": created_at, "content": content},
            config={"callbacks": callbacks},
        )
    except Exception as e:
        logger.error(f"知乎 LLM 调用失败 {post_id}: {e}", exc_info=True)
        return None

    # 把 str / list 都转成 str（少数模型可能返回 content blocks）
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)
    elif raw is None:
        raw = ""
    raw_str = str(raw).strip()
    cleaned = _strip_think(raw_str)
    elapsed = time.time() - t0
    if not cleaned:
        # 之前这里吞掉空响应，看不到 raw 内容；现在打印出来方便诊断
        logger.error(
            f"知乎 LLM 返回空 {post_id} 耗时 {elapsed:.1f}s "
            f"raw_len={len(raw_str)} raw[:300]={raw_str[:300]!r}"
        )
        return None

    parsed = _extract_json(cleaned)
    if not parsed:
        # 打印 cleaned 头 200 字用于诊断（可能是截断、think 块没撕干净、JSON 嵌套等）
        logger.error(
            f"知乎 LLM 返回非 JSON {post_id} 耗时 {elapsed:.1f}s "
            f"cleaned_len={len(cleaned)} cleaned[:300]={cleaned[:300]!r}"
        )
        return None

    result = _validate_result(parsed)
    model_name = "unknown"
    try:
        model_name = getattr(llm, "model_name", "unknown")
    except Exception:
        pass

    # 找出使用的 provider 用于显示
    try:
        from backend.services.sentiment_service import LLM_CONFIG
        for prov, cfg in LLM_CONFIG.items():
            if cfg.get("model") == model_name:
                model_name = f"{prov}/{model_name}"
                break
    except Exception:
        pass

    analysis_id = upsert_zhihu_analysis(
        post_id=post_id,
        url_token=post["url_token"],
        stance=result["stance"],
        stance_assets=json.dumps(result["stance_assets"], ensure_ascii=False),
        sectors=json.dumps(result["sectors"], ensure_ascii=False),
        summary=result["summary"],
        action_suggestion=result["action_suggestion"],
        key_points=json.dumps(result["key_points"], ensure_ascii=False),
        confidence=result["confidence"],
        raw_response=cleaned[:3000],
        model_name=model_name,
    )
    logger.info(f"知乎分析完成 {post_id} 耗时 {time.time() - t0:.1f}s stance={result['stance']}")
    result["id"] = analysis_id
    result["post_id"] = post_id
    result["url_token"] = post["url_token"]
    result["model_name"] = model_name
    result["analyzed_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    return result


def analyze_new_posts(url_token: str = None, limit: int = 20,
                      on_progress=None) -> list[dict]:
    """批量分析尚未分析的动态（按时间倒序最多 limit 条）。

    Args:
        on_progress: 可选回调 ``fn(analyzed_count, total)``，每分析完一篇触发。
            用于前端实时显示进度。
    """
    from backend.core.database import get_zhihu_posts
    rows = get_zhihu_posts(url_token=url_token, limit=limit * 2)
    pending = [r for r in rows if r.get("stance") is None][:limit]
    total = len(pending)
    results = []
    for p in pending:
        r = analyze_post(p["post_id"])
        if r:
            results.append(r)
        if on_progress:
            try:
                on_progress(len(results), total)
            except Exception:
                pass
        time.sleep(0.3)
    if on_progress and total == 0:
        try:
            on_progress(0, 0)
        except Exception:
            pass
    return results


def _serialize_analysis(post: dict) -> dict:
    """从 DB 行序列化分析结果。"""
    def _load(s, default):
        if not s:
            return default
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return default
    return {
        "post_id": post.get("post_id"),
        "url_token": post.get("url_token"),
        "stance": post.get("stance"),
        "stance_assets": _load(post.get("stance_assets"), []),
        "sectors": _load(post.get("sectors"), []),
        "summary": post.get("summary") or "",
        "action_suggestion": post.get("action_suggestion") or "",
        "key_points": _load(post.get("key_points"), []),
        "confidence": post.get("confidence") or 50,
        "analyzed_at": post.get("analyzed_at"),
        "model_name": post.get("model_name"),
    }
