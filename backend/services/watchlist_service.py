"""自选股观察池服务 — 个人研究关注列表的持久化与实时报价聚合。

定位（SPEC §5 Core）：纯研究浏览能力。报价来自腾讯行情，聚合响应携带
source / as_of / coverage / degraded / errors 元数据（SPEC §3.1/3.3），
部分代码获取失败时仍返回可用子集并显式标注，不把部分失败伪装成完整快照。
不产生任何买卖信号。
"""

import logging
import re
from datetime import datetime

import requests

from backend.config import TENCENT_HQ_URL, TENCENT_TIMEOUT, BROWSER_USER_AGENT
from backend.core.database import get_connection
from backend.services.stock_service import _full_symbol

logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"^\d{6}$")


def validate_code(code: str) -> str:
    """校验并规范化 6 位 A 股代码；非法输入抛 ValueError。"""
    code = str(code or "").strip()
    if not _CODE_RE.match(code):
        raise ValueError("股票代码必须是 6 位数字")
    return code


def list_watch_stocks() -> list[dict]:
    """按 sort_order（后进可调）与添加顺序返回观察池。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, code, name, note, sort_order, created_at FROM watchlist ORDER BY sort_order, id"
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def add_watch_stock(code: str, name: str = "", note: str = "") -> tuple[dict, bool]:
    """添加观察标的。已存在时幂等返回现有行（created=False）。"""
    code = validate_code(code)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, code, name, note, sort_order, created_at FROM watchlist WHERE code = ?", (code,))
        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row)), False
        cur.execute(
            "INSERT INTO watchlist (code, name, note, sort_order) VALUES (?, ?, ?, "
            "COALESCE((SELECT MAX(sort_order) FROM watchlist) + 1, 0))",
            (code, str(name or "").strip(), str(note or "").strip()),
        )
        new_id = cur.lastrowid
    return get_watch_stock(code), True


def get_watch_stock(code: str) -> dict | None:
    code = validate_code(code)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, code, name, note, sort_order, created_at FROM watchlist WHERE code = ?", (code,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))


def update_watch_stock(code: str, note: str | None = None) -> dict | None:
    """更新备注；返回更新后的行，不存在时返回 None。"""
    code = validate_code(code)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM watchlist WHERE code = ?", (code,))
        if not cur.fetchone():
            return None
        cur.execute("UPDATE watchlist SET note = ? WHERE code = ?", (str(note or "").strip(), code))
    return get_watch_stock(code)


def remove_watch_stock(code: str) -> bool:
    """移除观察标的；返回是否存在并已删除。"""
    code = validate_code(code)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM watchlist WHERE code = ?", (code,))
        return cur.rowcount > 0


def fetch_watch_quotes(stocks: list[dict]) -> dict:
    """对观察池批量取腾讯实时报价，返回带可信元数据的聚合结果。

    单次 HTTP 批量请求（qt.gtimg.cn 支持逗号分隔多代码）；单个代码解析
    失败只影响该项并进入 errors，不拖垮整次聚合。
    """
    fetched_at = datetime.now().isoformat(timespec="seconds")
    result: list[dict] = []
    errors: list[dict] = []
    if not stocks:
        return {
            "data": [],
            "source": "tencent",
            "as_of": fetched_at,
            "coverage": {"expected": 0, "ok": 0, "failed": 0},
            "degraded": False,
            "unavailable": False,
            "errors": [],
        }

    full_map = {s["code"]: _full_symbol(s["code"]) for s in stocks}
    symbols_param = ",".join(full_map.values())
    try:
        resp = requests.get(
            f"{TENCENT_HQ_URL}{symbols_param}",
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=TENCENT_TIMEOUT,
        )
        resp.raise_for_status()
        raw_blocks = resp.text
    except Exception as e:
        logger.warning(f"自选股批量报价请求失败: {type(e).__name__}", exc_info=True)
        return {
            "data": [],
            "source": "tencent",
            "as_of": fetched_at,
            "coverage": {"expected": len(stocks), "ok": 0, "failed": len(stocks)},
            "degraded": False,
            "unavailable": True,
            "errors": [{"code": s["code"], "error": type(e).__name__} for s in stocks],
        }

    # 解析 v_sh600519="51~名称~代码~现价~昨收~..."; 逐段提取
    parsed: dict[str, dict] = {}
    for block in re.findall(r'v_\w+="([^"]*)"', raw_blocks):
        parts = block.split("~")
        if len(parts) < 4:
            continue
        code = parts[2].zfill(6)
        try:
            price = float(parts[3])
            prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0.0
        except ValueError:
            continue
        if price <= 0:
            continue
        change_pct = None
        if len(parts) > 32 and parts[32]:
            try:
                change_pct = float(parts[32])
            except ValueError:
                change_pct = None
        if change_pct is None and prev_close > 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)
        parsed[code] = {
            "name": parts[1],
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
        }

    for s in stocks:
        code = s["code"]
        quote = parsed.get(code)
        if quote is None:
            errors.append({"code": code, "error": "no_quote"})
            result.append({
                "code": code,
                "name": s.get("name") or "",
                "note": s.get("note") or "",
                "price": None,
                "change_pct": None,
                "quote_error": "no_quote",
            })
            continue
        result.append({
            "code": code,
            "name": quote["name"] or s.get("name") or "",
            "note": s.get("note") or "",
            "price": quote["price"],
            "change_pct": quote["change_pct"],
            "quote_error": None,
        })

    ok = sum(1 for r in result if r["quote_error"] is None)
    return {
        "data": result,
        "source": "tencent",
        "as_of": fetched_at,
        "coverage": {"expected": len(stocks), "ok": ok, "failed": len(stocks) - ok},
        "degraded": 0 < ok < len(stocks),
        "unavailable": ok == 0,
        "errors": errors,
    }
