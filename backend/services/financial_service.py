"""
财报数据服务 — 通过 akshare 获取季度业绩 + 利润表，通过腾讯获取行情 + K 线，SQLite 缓存。
"""

import json
import logging
import re
import time
from datetime import datetime

import akshare as ak
import requests

from backend.core.database import (
    upsert_financials_cache,
    get_financials_cache,
)
from backend.services.stock_service import _no_proxy, get_stock_metrics
from backend.config import (
    TENCENT_HQ_URL, TENCENT_TIMEOUT, BROWSER_USER_AGENT,
)

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 6

# 腾讯 K 线缓存（同一进程 1 分钟内不重复抓）
_kline_cache: dict = {"data": None, "symbol": None, "ts": 0}


# ── 公开入口 ──────────────────────────────────────────────

def get_financial_data(symbol: str) -> dict | None:
    """获取单只股票的 TTM 财务 + 行情 + K 线 + PE 历史数据。

    返回:
        {symbol, name, report_date, ttm_revenue, ttm_net_profit, ttm_gross_profit,
         ttm_eps, ttm_pe, price, total_market_cap, float_market_cap,
         total_shares, float_shares,
         pe_history: [{date, pe}, ...],  # 近 1 年日频 PE
         price_history: [{date, close, volume}, ...],  # 近 1 年 K 线
         quarters: [{quarter, revenue, net_profit, gross_profit, gross_margin}, ...],
         eastmoney_url, cached}
    """
    symbol = str(symbol).strip().zfill(6)

    cached = _load_cache(symbol)
    if cached:
        return cached

    try:
        data = _fetch_all(symbol)
    except Exception as e:
        logger.warning(f"财务数据获取失败 {symbol}: {e}")
        return None

    if data is None:
        return None

    _save_cache(data)
    data["cached"] = False
    return data


# ── 缓存读写 ──────────────────────────────────────────────

def _load_cache(symbol: str) -> dict | None:
    row = get_financials_cache(symbol)
    if not row or not row.get("fetched_at"):
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if (datetime.now() - fetched).total_seconds() > CACHE_TTL_HOURS * 3600:
        return None
    return _row_to_result(row, cached=True)


def _save_cache(data: dict) -> None:
    try:
        upsert_financials_cache(
            symbol=data["symbol"],
            report_date=data.get("report_date"),
            ttm_revenue=data.get("ttm_revenue"),
            ttm_net_profit=data.get("ttm_net_profit"),
            ttm_gross_profit=data.get("ttm_gross_profit"),
            ttm_eps=data.get("ttm_eps"),
            quarterly_data=json.dumps(data.get("quarters", []), ensure_ascii=False),
            price=data.get("price"),
            total_market_cap=data.get("total_market_cap"),
            float_market_cap=data.get("float_market_cap"),
            total_shares=data.get("total_shares"),
            float_shares=data.get("float_shares"),
            ttm_pe=data.get("ttm_pe"),
            pe_history=json.dumps(data.get("pe_history", []), ensure_ascii=False),
            price_history=json.dumps(data.get("price_history", []), ensure_ascii=False),
            ttm_pe_percentile=data.get("ttm_pe_percentile"),
            ttm_pe_percentile_basis=data.get("ttm_pe_percentile_basis"),
        )
    except Exception as e:
        logger.warning(f"财务数据缓存写入失败: {e}")


def _row_to_result(row: dict, cached: bool) -> dict:
    quarters = _try_json(row.get("quarterly_data"))
    pe_history = _try_json(row.get("pe_history"))
    price_history = _try_json(row.get("price_history"))
    symbol = row["symbol"]
    return {
        "symbol": symbol,
        "name": row.get("name"),
        "report_date": row.get("report_date"),
        "ttm_revenue": row.get("ttm_revenue"),
        "ttm_net_profit": row.get("ttm_net_profit"),
        "ttm_gross_profit": row.get("ttm_gross_profit"),
        "ttm_eps": row.get("ttm_eps"),
        "ttm_pe": row.get("ttm_pe"),
        "ttm_pe_percentile": row.get("ttm_pe_percentile"),
        "ttm_pe_percentile_basis": row.get("ttm_pe_percentile_basis"),
        "price": row.get("price"),
        "total_market_cap": row.get("total_market_cap"),
        "float_market_cap": row.get("float_market_cap"),
        "total_shares": row.get("total_shares"),
        "float_shares": row.get("float_shares"),
        "quarters": quarters,
        "pe_history": pe_history,
        "price_history": price_history,
        "eastmoney_url": _eastmoney_url(symbol),
        "cached": cached,
    }


def _try_json(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return []


# ── 抓取主流程 ────────────────────────────────────────────

def _fetch_all(symbol: str) -> dict | None:
    # 1) 财务摘要（可能失败，不阻塞行情/K线）
    fin = None
    try:
        fin = _fetch_financial_abstract(symbol)
    except Exception as e:
        logger.warning(f"财务摘要获取异常 {symbol}: {e}")

    # 2) 腾讯 HQ：行情 + 市值 + 股本
    hq = _fetch_tencent_hq_full(symbol)
    if not hq:
        return None

    # 3) 腾讯 K 线：近 1 年日 K
    kline = _fetch_tencent_kline(symbol, days=365)

    # 4) TTM EPS = TTM 净利润 / 总股本
    ttm_eps = None
    ttm_np = fin.get("ttm_net_profit") if fin else None
    total_shares = hq.get("total_shares")
    if ttm_np is not None and total_shares and total_shares > 0:
        ttm_eps = round(ttm_np / total_shares, 4)

    # 5) TTM PE
    price = hq.get("price")
    ttm_pe = None
    if price and ttm_eps and ttm_eps > 0:
        ttm_pe = round(price / ttm_eps, 2)

    # 6) PE 历史
    pe_history = []
    if kline and ttm_eps and ttm_eps > 0:
        for row in kline:
            pe_history.append({
                "date": row["date"],
                "pe": round(row["close"] / ttm_eps, 2),
            })

    # 7) 百分位
    pe_pct = None
    pe_pct_basis = None
    if ttm_eps and ttm_eps > 0 and pe_history and ttm_pe is not None:
        pe_pct = _percentile([p["pe"] for p in pe_history], ttm_pe)
        pe_pct_basis = "pe"
    elif kline and price:
        closes = [r["close"] for r in kline]
        pe_pct = _percentile(closes, price)
        pe_pct_basis = "price"

    return {
        "symbol": symbol,
        "name": hq.get("name"),
        "report_date": fin.get("report_date") if fin else None,
        "ttm_revenue": fin.get("ttm_revenue") if fin else None,
        "ttm_net_profit": fin.get("ttm_net_profit") if fin else None,
        "ttm_gross_profit": fin.get("ttm_gross_profit") if fin else None,
        "ttm_eps": ttm_eps,
        "ttm_pe": ttm_pe,
        "ttm_pe_percentile": pe_pct,
        "ttm_pe_percentile_basis": pe_pct_basis,
        "price": price,
        "total_market_cap": hq.get("total_market_cap"),
        "float_market_cap": hq.get("float_market_cap"),
        "total_shares": total_shares,
        "float_shares": hq.get("float_shares"),
        "quarters": fin.get("quarters", []) if fin else [],
        "pe_history": pe_history,
        "price_history": kline,
        "eastmoney_url": _eastmoney_url(symbol),
    }


def _diff_val(a, b) -> float | None:
    """a - b, returning None if either is None."""
    return (a - b) if (a is not None and b is not None) else None


def _quarter_label(date_str: str) -> str | None:
    """'2026-03-31' or '20260331' -> '2026Q1'."""
    s = str(date_str).replace("-", "").strip()
    m = re.match(r"(\d{4})(\d{2})\d{2}", s)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if mo < 1 or mo > 12:
        return None
    q = (mo - 1) // 3 + 1
    return f"{y}Q{q}"


def _same_quarter_prev_year(label: str, all_labels: set) -> str | None:
    """Given '2026Q1', return '2025Q1' if present in all_labels."""
    m = re.match(r"(\d{4})Q([1-4])", label)
    if not m:
        return None
    target = f"{int(m.group(1)) - 1}Q{m.group(2)}"
    return target if target in all_labels else None


def _prev_quarter(label: str, all_labels: set) -> str | None:
    """Given '2026Q1', return '2025Q4' if present."""
    m = re.match(r"(\d{4})Q([1-4])", label)
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    if q == 1:
        target = f"{y - 1}Q4"
    else:
        target = f"{y}Q{q - 1}"
    return target if target in all_labels else None


def _pct_change(current, base) -> float | None:
    """Percentage change from base to current. None if either is missing or base <= 0."""
    if current is None or base is None:
        return None
    if base == 0:
        return None
    return round((current - base) / abs(base) * 100, 1)


# ── 财务摘要（akshare） ───────────────────────────────────

def _fetch_financial_abstract(symbol: str) -> dict | None:
    try:
        with _no_proxy():
            df = ak.stock_financial_abstract(symbol=symbol)
    except Exception as e:
        logger.warning(f"财务摘要获取异常 {symbol}: {e}")
        return None
    if df is None or df.empty:
        return None

    indicator_map = {}
    for i, row in df.iterrows():
        indicator_map[str(row["指标"]).strip()] = i

    def _get_row(*keys):
        for k in keys:
            if k in indicator_map:
                return df.iloc[indicator_map[k]]
        return None

    revenue_row = _get_row("营业总收入", "营业收入")
    net_row = _get_row("净利润", "归属母公司净利润")
    gross_margin_row = _get_row("毛利率")

    if revenue_row is None:
        return None

    # 动态解析日期列 — 匹配 yyyy-MM-dd 或 yyyyMMdd 等变体
    date_cols = [c for c in df.columns[2:] if re.match(r"^\d{4}-\d{2}-\d{2}$", str(c)) or re.match(r"^\d{8}$", str(c))]
    if len(date_cols) < 4:
        return None

    # 构建 累计值 lookup：{label: {revenue, net_profit, gross_margin}}
    cumulative: dict[str, dict] = {}
    for dc in date_cols:
        label = _quarter_label(dc)
        if not label:
            continue
        rev_cum = _safe_float(revenue_row[dc])
        net_cum = _safe_float(net_row[dc]) if net_row is not None else None
        gm_cum = _safe_float(gross_margin_row[dc]) if gross_margin_row is not None else None
        cumulative[label] = {"revenue_cum": rev_cum, "net_profit_cum": net_cum, "gross_margin_cum": gm_cum}

    # 按时间排序标签
    sorted_labels = sorted(cumulative.keys())
    all_labels = set(cumulative.keys())

    # 推导单季度值：Q1 = Q1累计, Q2 = Q2累计 - Q1累计, ...
    single_quarters: dict[str, dict] = {}
    prev_label = None
    for label in sorted_labels:
        cur = cumulative[label]
        if label.endswith("Q1") or prev_label is None:
            q_revenue = cur["revenue_cum"]
            q_net = cur["net_profit_cum"]
            q_margin_cum = cur["gross_margin_cum"]
            # Q1: 单季度毛利率 = 累计毛利率（就是 Q1 的毛利率）
            q_gross = (q_revenue * q_margin_cum / 100) if (q_revenue is not None and q_margin_cum is not None) else None
        else:
            prev = cumulative[prev_label]
            q_revenue = _diff_val(cur["revenue_cum"], prev["revenue_cum"])
            q_net = _diff_val(cur["net_profit_cum"], prev["net_profit_cum"])

            # 单季度毛利润 = 累计毛利润差
            q_gross = None
            rev_cur = cur["revenue_cum"] or 0
            rev_prev = prev["revenue_cum"] or 0
            gm_cur = cur["gross_margin_cum"]
            gm_prev = prev["gross_margin_cum"]
            if gm_cur is not None and gm_prev is not None and rev_cur and rev_prev:
                cum_gross_cur = rev_cur * gm_cur / 100
                cum_gross_prev = rev_prev * gm_prev / 100
                q_gross = cum_gross_cur - cum_gross_prev

        q_margin_pct = round(q_gross / q_revenue * 100, 2) if (q_gross is not None and q_revenue) else None

        single_quarters[label] = {
            "revenue": q_revenue,
            "net_profit": q_net,
            "gross_profit": q_gross,
            "gross_margin": q_margin_pct,
        }
        prev_label = label

    # 为每个季度计算 YoY / QoQ
    for label, sq in single_quarters.items():
        # 同比
        yoy_label = _same_quarter_prev_year(label, all_labels)
        if yoy_label and yoy_label in single_quarters:
            base = single_quarters[yoy_label]
            sq["revenue_yoy"] = _pct_change(sq["revenue"], base["revenue"])
            sq["net_profit_yoy"] = _pct_change(sq["net_profit"], base["net_profit"])
            # 毛利率已是百分比，同比用百分点差而非百分比变化
            sq["gross_margin_yoy"] = _diff_val(sq["gross_margin"], base["gross_margin"])
        else:
            sq["revenue_yoy"] = None
            sq["net_profit_yoy"] = None
            sq["gross_margin_yoy"] = None

        # 环比
        qoq_label = _prev_quarter(label, all_labels)
        if qoq_label and qoq_label in single_quarters:
            base = single_quarters[qoq_label]
            sq["revenue_qoq"] = _pct_change(sq["revenue"], base["revenue"])
            sq["net_profit_qoq"] = _pct_change(sq["net_profit"], base["net_profit"])
            # 毛利率已是百分比，环比用百分点差
            sq["gross_margin_qoq"] = _diff_val(sq["gross_margin"], base["gross_margin"])
        else:
            sq["revenue_qoq"] = None
            sq["net_profit_qoq"] = None
            sq["gross_margin_qoq"] = None

    # 取最近 4 个季度（按时间倒序）
    recent_labels = sorted_labels[-4:]
    quarters = []
    ttm_revenue = 0.0
    ttm_net_profit = 0.0
    ttm_gross_profit = 0.0

    for label in reversed(recent_labels):
        sq = single_quarters[label]
        entry = {
            "quarter": label,
            "revenue": sq["revenue"],
            "net_profit": sq["net_profit"],
            "gross_profit": sq["gross_profit"],
            "gross_margin": sq["gross_margin"],
            "revenue_yoy": sq["revenue_yoy"],
            "net_profit_yoy": sq["net_profit_yoy"],
            "gross_margin_yoy": sq["gross_margin_yoy"],
            "revenue_qoq": sq["revenue_qoq"],
            "net_profit_qoq": sq["net_profit_qoq"],
            "gross_margin_qoq": sq["gross_margin_qoq"],
        }
        quarters.append(entry)
        ttm_revenue += sq["revenue"] or 0
        ttm_net_profit += sq["net_profit"] or 0
        ttm_gross_profit += sq["gross_profit"] or 0

    return {
        "report_date": str(date_cols[0]),
        "ttm_revenue": ttm_revenue,
        "ttm_net_profit": ttm_net_profit,
        "ttm_gross_profit": ttm_gross_profit,
        "quarters": quarters,
    }


# ── 腾讯 HQ 完整字段 ──────────────────────────────────────

def _full_symbol(symbol: str) -> str:
    if symbol.startswith(("4", "8")):
        return f"bj{symbol}"
    if symbol.startswith(("5", "6", "9")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def _fetch_tencent_hq_full(symbol: str) -> dict | None:
    """从腾讯 qt.gtimg.cn 拉取完整行情。

    注意：Tencent 返回的「总市值」字段在 long long 量级不可靠（疑似万元/亿元混淆），
    我们用 total_shares × price 自计算（更可靠）。
    """
    url = f"{TENCENT_HQ_URL}{_full_symbol(symbol)}"
    try:
        with _no_proxy():
            r = requests.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=TENCENT_TIMEOUT)
    except Exception as e:
        logger.warning(f"腾讯 HQ 异常 {symbol}: {e}")
        return None
    if r.status_code != 200:
        return None
    try:
        parts = r.text.split('"', 2)[1].split("~")
        if len(parts) < 78:
            return None
        name = parts[1]
        price = _safe_float(parts[3]) or 0
        # 72=流通股, 73=总股本（单位：股）
        total_shares = _safe_float(parts[73])
        float_shares = _safe_float(parts[72])
        # 自计算市值（亿元）
        total_market_cap = (total_shares * price / 1e8) if total_shares else None
        float_market_cap = (float_shares * price / 1e8) if float_shares else None
        return {
            "name": name,
            "price": price,
            "float_market_cap": float_market_cap,
            "total_market_cap": total_market_cap,
            "total_shares": total_shares,
            "float_shares": float_shares,
        }
    except Exception as e:
        logger.warning(f"解析腾讯 HQ 失败 {symbol}: {e}")
        return None


# ── 腾讯 K 线 ─────────────────────────────────────────────

def _fetch_tencent_kline(symbol: str, days: int = 365) -> list[dict]:
    """腾讯 K 线：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"""
    now = time.time()
    if _kline_cache.get("symbol") == symbol and (now - _kline_cache["ts"]) < 60:
        return _kline_cache["data"] or []

    full = _full_symbol(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,{days},qfq"
    try:
        with _no_proxy():
            r = requests.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=10)
        data = r.json()
    except Exception as e:
        logger.warning(f"腾讯 K 线异常 {symbol}: {e}")
        _kline_cache.update({"data": [], "symbol": symbol, "ts": now})
        return []

    rows = data.get("data", {}).get(full, {}).get("qfqday") or []
    result = []
    for row in rows:
        # 格式: [date, open, close, high, low, volume]
        if len(row) < 6:
            continue
        try:
            result.append({
                "date": str(row[0]),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
            })
        except (ValueError, TypeError):
            continue

    _kline_cache.update({"data": result, "symbol": symbol, "ts": now})
    return result


# ── 工具 ─────────────────────────────────────────────────

def _percentile(values: list[float], target: float) -> float | None:
    """计算 target 在 values 中的百分位（0-100）。"""
    if not values or target is None:
        return None
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    below = sum(1 for v in valid if v <= target)
    return round(below / len(valid) * 100, 1)


def _eastmoney_url(symbol: str) -> str:
    # A 股 / 创业板 / 科创板 / 北交所：沪市 sh，深市 sz，北交所 bj
    if symbol.startswith(("4", "8")):
        market = "bj"
    elif symbol.startswith(("5", "6", "9")):
        market = "sh"
    else:
        market = "sz"
    return f"https://quote.eastmoney.com/{market}{symbol}.html"


def _safe_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
