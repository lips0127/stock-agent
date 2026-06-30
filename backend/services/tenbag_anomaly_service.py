"""财报异动信号服务（基本面雷达）。

两部分：
1. ``derive_anomaly_signals(financials)`` — 纯函数，输入结构化近 4 期财报 ->
   输出异动信号 + 核心变化/可能解释/风险/结论/评分。可单测，不联网。
2. ``fetch_financials_em(symbol)`` — akshare 抓取（EM 资产负债表 + 现金流 +
   financial_service 损益摘要），把英文代号列归一化为统一字段。

口径：仅作基本面雷达/观察池输入，不输出买卖信号。

字段归一化映射（EM 英文代号 -> 统一字段，2026-07-01 demo 实测确认）：
  INVENTORY       -> inventory        存货
  CONTRACT_LIAB   -> contract_liab    合同负债
  CIP             -> cip              在建工程
  FIXED_ASSET     -> fixed_asset      固定资产
  ACCOUNTS_RECE   -> accounts_rece    应收账款
  NETCASH_OPERATE -> netcash_operate  经营活动现金流净额
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 阈值参数（集中可调）──
REVENUE_GROWTH_PCT = 30.0        # 营收高增 YoY%
NETPROFIT_GROWTH_PCT = 30.0      # 利润高增 YoY%
GROSS_MARGIN_IMPROVE_PCT = 5.0   # 毛利率改善 YoY 百分点
CONTRACT_LIAB_UP_PCT = 30.0      # 合同负债上升 YoY%
INVENTORY_DOWN_PCT = 10.0        # 存货下降 YoY%
RECEIVABLE_RISK_RATIO = 1.2      # 应收增速 / 营收增速 > 1.2 -> 风险
CASHFLOW_LAG_RATIO = 0.5         # 经营现金流 / 净利润 < 0.5 -> 风险

# EM 列名 -> 统一字段
EM_FIELD_MAP = {
    "INVENTORY": "inventory",
    "CONTRACT_LIAB": "contract_liab",
    "CIP": "cip",
    "FIXED_ASSET": "fixed_asset",
    "ACCOUNTS_RECE": "accounts_rece",
    "NETCASH_OPERATE": "netcash_operate",
}


# ── 纯函数：异动信号派生 ────────────────────────────────────

def derive_anomaly_signals(financials: dict) -> dict:
    """从结构化财报派生异动信号。

    Args:
        financials: {symbol, name, periods: [{report_date, revenue, net_profit,
            gross_margin, inventory, contract_liab, cip, fixed_asset,
            accounts_rece, netcash_operate}, ...]} periods 按时间升序。

    Returns:
        {signals: {bool}, core_changes: [str], possible_explanations: [str],
         risks: [str], score: float, conclusion: str}
    """
    periods = financials.get("periods") or []
    # 按 report_date 升序排序，兼容调用方任意输入顺序
    periods = sorted(
        [p for p in periods if p.get("report_date")],
        key=lambda p: str(p.get("report_date")),
    )
    result = {
        "signals": {
            "revenue_high_growth": False,
            "net_profit_high_growth": False,
            "gross_margin_improve": False,
            "inventory_down": False,
            "contract_liability_up": False,
            "cip_to_fixed_asset": False,
            "receivable_risk": False,
            "cashflow_lag": False,
        },
        "core_changes": [],
        "possible_explanations": [],
        "risks": [],
        "score": 0.0,
        "conclusion": "数据不足",
    }
    if len(periods) < 4:
        return result

    cur = periods[-1]
    yoy = periods[-4]   # 去年同期
    prev = periods[-2]  # 上一期

    def _yoy_pct(curr, base):
        if curr is None or base is None or base == 0:
            return None
        return (curr - base) / abs(base) * 100

    def _diff(curr, base):
        if curr is None or base is None:
            return None
        return curr - base

    # 营收高增
    rev_yoy = _yoy_pct(cur.get("revenue"), yoy.get("revenue"))
    if rev_yoy is not None and rev_yoy >= REVENUE_GROWTH_PCT:
        result["signals"]["revenue_high_growth"] = True
        result["core_changes"].append(f"营收 YoY +{rev_yoy:.0f}%")

    # 利润高增
    np_yoy = _yoy_pct(cur.get("net_profit"), yoy.get("net_profit"))
    if np_yoy is not None and np_yoy >= NETPROFIT_GROWTH_PCT:
        result["signals"]["net_profit_high_growth"] = True
        result["core_changes"].append(f"净利润 YoY +{np_yoy:.0f}%")

    # 毛利率改善（百分点差）
    gm_diff = _diff(cur.get("gross_margin"), yoy.get("gross_margin"))
    if gm_diff is not None and gm_diff >= GROSS_MARGIN_IMPROVE_PCT:
        result["signals"]["gross_margin_improve"] = True
        result["core_changes"].append(f"毛利率 YoY +{gm_diff:.1f}pct")

    # 合同负债上升
    cl_yoy = _yoy_pct(cur.get("contract_liab"), yoy.get("contract_liab"))
    if cl_yoy is not None and cl_yoy >= CONTRACT_LIAB_UP_PCT:
        result["signals"]["contract_liability_up"] = True
        result["core_changes"].append(f"合同负债 YoY +{cl_yoy:.0f}%")
        result["possible_explanations"].append("订单前置 / 需求改善")

    # 存货下降（去库存，需求旺盛）
    inv_yoy = _yoy_pct(cur.get("inventory"), yoy.get("inventory"))
    if inv_yoy is not None and inv_yoy <= -INVENTORY_DOWN_PCT:
        result["signals"]["inventory_down"] = True
        result["core_changes"].append(f"存货 YoY {inv_yoy:.0f}%")
        result["possible_explanations"].append("产品涨价 / 供不应求")

    # 在建工程转固（在建降 + 固定资产升）
    cip_diff = _diff(cur.get("cip"), prev.get("cip"))
    fa_diff = _diff(cur.get("fixed_asset"), prev.get("fixed_asset"))
    if cip_diff is not None and fa_diff is not None and cip_diff < 0 and fa_diff > 0:
        result["signals"]["cip_to_fixed_asset"] = True
        result["core_changes"].append("在建工程转固（产能投产）")
        result["possible_explanations"].append("产能利用率提升")

    # 应收账款风险（应收增速 > 营收增速）
    ar_yoy = _yoy_pct(cur.get("accounts_rece"), yoy.get("accounts_rece"))
    if rev_yoy is not None and ar_yoy is not None and rev_yoy != 0:
        if ar_yoy / max(abs(rev_yoy), 1e-9) >= RECEIVABLE_RISK_RATIO and ar_yoy > 0:
            result["signals"]["receivable_risk"] = True
            result["risks"].append(f"应收账款 YoY +{ar_yoy:.0f}% 超营收增速")

    # 经营现金流滞后（现金流 / 净利润 < 0.5）
    np_cur = cur.get("net_profit")
    nc_cur = cur.get("netcash_operate")
    if np_cur is not None and nc_cur is not None and np_cur > 0:
        if nc_cur / np_cur < CASHFLOW_LAG_RATIO:
            result["signals"]["cashflow_lag"] = True
            result["risks"].append("经营现金流未跟上净利润")

    # 评分：正向异动 +1，风险项 -0.5
    positive = ["revenue_high_growth", "net_profit_high_growth",
                "gross_margin_improve", "inventory_down",
                "contract_liability_up", "cip_to_fixed_asset"]
    risk_keys = ["receivable_risk", "cashflow_lag"]
    score = sum(1 for k in positive if result["signals"][k])
    score -= 0.5 * sum(1 for k in risk_keys if result["signals"][k])
    result["score"] = round(score, 2)

    # 结论
    if score >= 2:
        result["conclusion"] = "值得进入观察池（不等于直接买入）"
    elif score >= 1:
        result["conclusion"] = "出现积极信号，持续跟踪"
    elif score > 0:
        result["conclusion"] = "信号偏弱，暂观察"
    else:
        result["conclusion"] = "无明显异动或存风险"

    return result


# ── akshare 抓取（EM 资产负债表 + 现金流）────────────────────

def _em_symbol(symbol: str) -> str:
    """600519 -> SH600519（EM 接口要大写前缀）。"""
    from backend.services.financial_service import _full_symbol
    f = _full_symbol(str(symbol).zfill(6))
    return f[:2].upper() + f[2:]


def fetch_balance_sheet_em(symbol: str, periods: int = 4) -> list[dict]:
    """抓资产负债表近 N 期，归一化为统一字段。

    Returns: [{report_date, inventory, contract_liab, cip, fixed_asset,
               accounts_rece}, ...] 按时间升序。
    """
    import akshare as ak
    from backend.services.stock_service import _no_proxy
    em_sym = _em_symbol(symbol)
    try:
        with _no_proxy():
            df = ak.stock_balance_sheet_by_report_em(symbol=em_sym)
    except Exception as e:
        logger.warning(f"资产负债表抓取失败 {symbol}: {e}")
        return []
    if df is None or df.empty:
        return []

    # 取近 N 期，按报告日升序
    df = df.sort_values("REPORT_DATE", ascending=False).head(periods)
    df = df.iloc[::-1]
    out = []
    for _, row in df.iterrows():
        entry = {"report_date": _norm_report_date(row.get("REPORT_DATE"))}
        for em_col, field in EM_FIELD_MAP.items():
            if field == "netcash_operate":
                continue  # 现金流在另一张表
            entry[field] = _safe_float(row.get(em_col))
        out.append(entry)
    return out


def fetch_cash_flow_em(symbol: str, periods: int = 4) -> list[dict]:
    """抓现金流量表近 N 期，取经营活动现金流净额。

    Returns: [{report_date, netcash_operate}, ...] 按时间升序。
    """
    import akshare as ak
    from backend.services.stock_service import _no_proxy
    em_sym = _em_symbol(symbol)
    try:
        with _no_proxy():
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=em_sym)
    except Exception as e:
        logger.warning(f"现金流抓取失败 {symbol}: {e}")
        return []
    if df is None or df.empty:
        return []

    df = df.sort_values("REPORT_DATE", ascending=False).head(periods)
    df = df.iloc[::-1]
    out = []
    for _, row in df.iterrows():
        out.append({
            "report_date": _norm_report_date(row.get("REPORT_DATE")),
            "netcash_operate": _safe_float(row.get("NETCASH_OPERATE")),
        })
    return out


def fetch_financials_em(symbol: str, periods: int = 4) -> dict:
    """组装完整财报：损益（financial_service）+ 资负 + 现金流，按报告日对齐。

    Returns: {symbol, name, periods: [...]} 供 derive_anomaly_signals 消费。
    """
    from backend.services.financial_service import get_financial_data

    bs = fetch_balance_sheet_em(symbol, periods=periods)
    cf = fetch_cash_flow_em(symbol, periods=periods)

    # 损益摘要：复用 financial_service 已有的季度分解（含 revenue/net_profit/gross_margin）
    fin = get_financial_data(symbol)
    income_by_q: dict[str, dict] = {}
    name = None
    if fin:
        name = fin.get("name")
        for q in fin.get("quarters", []) or []:
            lbl = q.get("quarter")
            if lbl:
                income_by_q[lbl] = {
                    "revenue": q.get("revenue"),
                    "net_profit": q.get("net_profit"),
                    "gross_margin": q.get("gross_margin"),
                }

    # 以资产负债表报告日为主轴，按 YYYYQN 标签对齐损益 + 现金流
    cf_by_date = {c["report_date"]: c for c in cf}
    periods_out = []
    for b in bs:
        rd = b.get("report_date")
        qlabel = _report_date_to_quarter(rd)
        inc = income_by_q.get(qlabel, {}) if qlabel else {}
        merged = {
            "report_date": qlabel or rd,
            "revenue": inc.get("revenue"),
            "net_profit": inc.get("net_profit"),
            "gross_margin": inc.get("gross_margin"),
            "inventory": b.get("inventory"),
            "contract_liab": b.get("contract_liab"),
            "cip": b.get("cip"),
            "fixed_asset": b.get("fixed_asset"),
            "accounts_rece": b.get("accounts_rece"),
            "netcash_operate": cf_by_date.get(rd, {}).get("netcash_operate"),
        }
        periods_out.append(merged)

    return {"symbol": str(symbol).zfill(6), "name": name, "periods": periods_out}


# ── 工具 ─────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f if f == f else None  # NaN 检查
    except (ValueError, TypeError):
        return None


def _norm_report_date(val) -> str | None:
    """Timestamp/str -> 'YYYY-MM-DD'。"""
    if val is None:
        return None
    s = str(val).split(" ")[0]
    return s[:10] if s else None


def _report_date_to_quarter(date_str: str | None) -> str | None:
    """'2026-03-31' -> '2026Q1'。"""
    if not date_str:
        return None
    s = str(date_str).replace("-", "").strip()
    if len(s) < 6:
        return None
    y, mo = s[:4], s[4:6]
    try:
        q = (int(mo) - 1) // 3 + 1
        return f"{y}Q{q}"
    except ValueError:
        return None
