"""
财报文本解析器 — 使用 LLM 从自由文本中提取 A 股公司，做结构化输出。
复用 sentiment_service._get_llm() 的 LLM 客户端。
"""

import re
import json
import hashlib
import time
import logging
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from backend.core.database import insert_report_parse
from backend.config import CACHE_DIR

logger = logging.getLogger(__name__)

try:
    from backend.services.sentiment_service import _get_llm
except Exception:
    _get_llm = None

MAX_TEXT_CHARS = 12000

PARSE_PROMPT = PromptTemplate.from_template("""\
你是一位资深 A 股研究员。请分析下面这篇财经报告/新闻/会议纪要，提取其中明确提及的 A 股上市公司。

【任务】
1. 找到文中明确提到的所有 A 股上市公司（按名称或代码识别）
2. 对每家公司，提取：公司简称、6 位股票代码（如能识别）、文中相关片段、对该公司的情感倾向

【输出规则】
- 只提取明确提到的公司，不要凭空猜测
- 股票代码必须是 6 位数字，无法确定则留空字符串
- 情感倾向：bullish（正面/看多）、bearish（负面/看空）、neutral（中性/客观陈述）
- 用 80 字以内总结整篇报告的核心主题
- JSON 字符串值内的双引号必须转义为 \\"，严禁输出未转义的双引号

【输出 JSON 格式（不要解释、不要 markdown 代码块）】
{{
  "companies": [
    {{"name": "贵州茅台", "code": "600519", "context": "营收增长15%，超出市场预期", "sentiment": "bullish"}},
    {{"name": "宁德时代", "code": "300750", "context": "电池业务毛利率下滑", "sentiment": "bearish"}}
  ],
  "summary": "80字以内的报告主题总结"
}}

【原文】
{text}
""")


def _strip_think(text: str) -> str:
    """剥离模型思考块，返回实际响应。"""
    if not text:
        return ""
    patterns = [
        r" thinking.*? response",
        r"<reasoning>.*?</reasoning>",
        r"<reflection>.*?</reflection>",
        r"<\|reasoning\|>.*?<\|/reasoning\|>",
        r"<\|begin▁of▁thinking\|>.*?<\|end▁of▁thinking\|>",
    ]
    for p in patterns:
        m = re.search(p, text, re.DOTALL)
        if m:
            after = text[m.end():].strip()
            return after if after else ""
    return text


def _fix_unescaped_quotes(text: str) -> str:
    """修复 JSON 字符串值内未转义的双引号。

    LLM 经常把原文中的引号（如 "MLCC缺货替代"）直接拷贝到 JSON 字符串
    值内而不转义，导致 json.loads 失败。此函数将内容引号转为 \\"。
    只修复前后均为内容字符（中日韩文字/字母/数字）的引号，避免误伤 JSON 语法。
    """
    return re.sub(
        r'(?<=[一-鿿㐀-䶿豈-﫿A-Za-z0-9])"'
        r'(?=[一-鿿㐀-䶿豈-﫿A-Za-z0-9])',
        r'\"',
        text,
    )


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
        pass
    # 从末尾向前收缩
    for i in range(end, start + 1, -1):
        try:
            return json.loads(text[start:i + 1])
        except json.JSONDecodeError:
            continue
    # 从开头向后收缩（LLM 可能在 JSON 前加了说明文字）
    for j in range(start + 1, end):
        if text[j] == "{":
            try:
                return json.loads(text[j:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _load_stock_name_map() -> dict[str, str]:
    """从 stock_names.json 加载 {公司简称: 6位代码} 映射表。"""
    cache_file = Path(CACHE_DIR) / "stock_names.json"
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    name_to_code: dict[str, str] = {}
    for entry in data:
        name = (entry.get("name") or "").strip()
        code = (entry.get("code") or "").strip()
        if name and code and len(code) == 6 and code.isdigit():
            # 同名股取先出现的（一般是主板优先）
            if name not in name_to_code:
                name_to_code[name] = code
    return name_to_code


def _resolve_code(name: str, name_map: dict[str, str]) -> str:
    """根据公司名称匹配代码。精确匹配优先，失败则尝试模糊匹配。"""
    n = name.strip()
    if not n:
        return ""
    # 精确匹配
    if n in name_map:
        return name_map[n]
    # 去掉后缀（股份、有限公司、集团等）
    for suffix in ["股份有限公司", "有限公司", "集团", "控股", "科技"]:
        if n.endswith(suffix):
            short = n[:-len(suffix)].strip()
            if short and short in name_map:
                return name_map[short]
    # 模糊匹配：名称包含关系
    for known_name, code in name_map.items():
        if n in known_name or known_name in n:
            return code
    return ""


def parse_financial_report(text: str) -> dict:
    """解析财经报告文本，提取公司列表。

    Args:
        text: 自由文本（财经新闻、研究报告、业绩说明会纪要等）

    Returns:
        {companies: [{name, code, context, sentiment}], summary: str}
    """
    if _get_llm is None:
        return {"error": "未配置 LLM API Key", "companies": [], "summary": ""}

    if not text or not text.strip():
        return {"error": "请输入报告文本", "companies": [], "summary": ""}

    text = text.strip()[:MAX_TEXT_CHARS]
    text_hash = hashlib.sha256(text.encode()).hexdigest()

    llm = _get_llm()
    if not llm:
        return {"error": "LLM 初始化失败", "companies": [], "summary": ""}

    # 覆盖 sentiment_service 默认的 max_tokens=512 — 报告含 7+ 公司时 JSON 会被截断
    try:
        llm.max_tokens = 8192
    except Exception:
        pass

    chain = PARSE_PROMPT | llm | StrOutputParser()

    t0 = time.time()
    try:
        raw = chain.invoke({"text": text})
    except Exception as e:
        logger.error(f"财报解析 LLM 调用失败: {e}", exc_info=True)
        return {"error": f"LLM 调用失败: {e}", "companies": [], "summary": ""}

    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)
    raw_str = str(raw).strip() if raw else ""
    cleaned = _strip_think(raw_str)
    cleaned = _fix_unescaped_quotes(cleaned)
    elapsed = time.time() - t0

    if not cleaned:
        logger.error(f"财报解析 LLM 返回空 耗时 {elapsed:.1f}s")
        return {"error": "LLM 返回为空", "companies": [], "summary": ""}

    parsed = _extract_json(cleaned)
    if not parsed:
        # 截断 vs 真坏 JSON：检查 cleaned 末尾是否在 JSON 中间被打断
        if cleaned.rstrip()[-1:] in ("}", "]"):
            logger.error(
                f"财报解析 JSON 解析失败 耗时 {elapsed:.1f}s "
                f"cleaned_len={len(cleaned)} "
                f"cleaned_head={cleaned[:200]!r} "
                f"cleaned_tail={cleaned[-200:]!r}"
            )
        else:
            logger.error(
                f"财报解析 LLM 返回被截断 耗时 {elapsed:.1f}s "
                f"cleaned_len={len(cleaned)} "
                f"cleaned_tail={cleaned[-200:]!r}"
            )
        return {"error": "LLM 输出被截断或格式异常（可能公司数过多）", "companies": [], "summary": ""}

    companies = _validate_companies(parsed.get("companies", []))
    summary = str(parsed.get("summary", ""))[:200]

    # 对缺失代码的公司做名称→代码反查
    name_map = _load_stock_name_map()
    resolved_count = 0
    for c in companies:
        if not c["code"] and c["name"]:
            resolved = _resolve_code(c["name"], name_map)
            if resolved:
                c["code"] = resolved
                resolved_count += 1
    if resolved_count:
        logger.info(f"名称→代码反查成功: {resolved_count} 家")

    model_name = "unknown"
    try:
        model_name = getattr(llm, "model_name", "unknown")
    except Exception:
        pass

    # 写解析历史
    try:
        insert_report_parse(
            report_text_hash=text_hash,
            report_text_preview=text[:500],
            parsed_result=json.dumps(parsed, ensure_ascii=False),
            model_name=model_name,
            company_count=len(companies),
        )
    except Exception as e:
        logger.warning(f"解析历史写入失败: {e}")

    logger.info(f"财报解析完成: {len(companies)} 家公司 耗时 {elapsed:.1f}s")
    return {"companies": companies, "summary": summary}


def _validate_companies(raw: list) -> list[dict]:
    """校验并清理 LLM 返回的公司列表。"""
    if not isinstance(raw, list):
        return []
    out = []
    seen_codes = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:30]
        code = str(item.get("code", "")).strip()
        context = str(item.get("context", "")).strip()[:200]
        sentiment = str(item.get("sentiment", "neutral")).lower()
        if sentiment not in ("bullish", "bearish", "neutral"):
            sentiment = "neutral"
        if not name:
            continue
        # 代码校验：必须是 6 位数字
        if code and (len(code) != 6 or not code.isdigit()):
            code = ""
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        out.append({
            "name": name,
            "code": code,
            "context": context,
            "sentiment": sentiment,
        })
    return out
