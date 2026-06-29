# -*- coding: utf-8 -*-
"""
A 股股息率监测 - 数据逻辑层
使用 akshare 获取股票名称、最新价、股息率。
"""

import time
import pandas as pd
from contextlib import contextmanager
import requests
import akshare as ak
import logging

from backend.config import (
    SINA_HQ_URL, SINA_REFERER, SINA_TIMEOUT, SINA_INDEX_TIMEOUT,
    TENCENT_HQ_URL, TENCENT_TIMEOUT,
    BROWSER_USER_AGENT,
    HQ_SOURCE_RETRIES, HQ_SOURCE_RETRY_BACKOFF,
)

logger = logging.getLogger(__name__)


def _retry(do, retries: int = None, backoff: float = None):
    """对瞬时网络错误（连接重置/超时/5xx）做指数退避重试。

    数据格式错误（4xx、空响应）不重试，直接抛。
    """
    if retries is None:
        retries = HQ_SOURCE_RETRIES
    if backoff is None:
        backoff = HQ_SOURCE_RETRY_BACKOFF

    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = do()
            # 5xx 视为服务端瞬时错误
            if r.status_code >= 500 and attempt < retries:
                last_exc = ValueError(f"HTTP {r.status_code}")
                time.sleep(backoff * (2 ** attempt))
                continue
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise
    if last_exc:
        raise last_exc


def is_risk_stock(name: str) -> bool:
    """判定是否为 ST / *ST / 退市股票（按名称）。

    这类股票价格已严重脱离基本面（退市整理期股价常跌至 1 元以下），但
    历史分红仍按往年正常水平计算，会得到 100%+ 的异常股息率，污染高股息
    排名；且其本身存在退市/摘牌风险，不应进入选股池，故在扫描与展示两层
    一并排除。
    """
    if not name:
        return False
    upper = name.upper()
    return "ST" in upper or "退" in name


def _full_symbol(symbol: str) -> str:
    """根据 6 位股票代码返回带市场前缀的代码（sh/sz/bj）。"""
    if symbol.startswith("6"):
        return f"sh{symbol}"
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    if symbol.startswith(("4", "8", "9")):
        return f"bj{symbol}"
    return f"sh{symbol}"


# ── 代理相关环境变量 ──
# 注意（2026-06-15）：代理强制直连的 monkey-patch 已迁移到
# ``backend.core.proxy_bypass``，在 ``backend.api.app`` 启动时执行。
# 这里的 ``_no_proxy()`` 改为 no-op，向后兼容 ``with _no_proxy():`` 语法。
# 实际保护由全局 patch 提供（覆盖 requests / akshare / urllib3 所有出口）。
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


@contextmanager
def _no_proxy():
    """no-op 上下文管理器（v3，2026-06-15）。

    历史背景：v1/v2 是临时 patch Session.request 的实现，但要求所有
    外网调用点都被 ``with _no_proxy():`` 包裹，否则仍会走代理。
    修复后全局 patch 在 ``backend.api.app`` 启动时一次生效，调用点
    仍然可以写 ``with _no_proxy():`` 用来**显式标注**「这里不应走
    代理」的设计意图，但不再依赖它来实际保护。
    """
    yield



def _get_sina_hq(symbol: str) -> dict:
    """从新浪财经获取名称和最新价。"""
    full_symbol = _full_symbol(symbol)
    url = f"{SINA_HQ_URL}{full_symbol}"
    headers = {"Referer": SINA_REFERER, "User-Agent": BROWSER_USER_AGENT}

    def _do():
        with _no_proxy():
            return requests.get(url, headers=headers, timeout=SINA_TIMEOUT)

    r = _retry(_do)

    if r.status_code != 200 or len(r.text) < 50:
        raise ValueError(f"无法从新浪获取股票 {symbol} 的行情")

    try:
        content = r.text.split('"')[1]
        parts = content.split(',')
        if len(parts) < 4:
            raise ValueError
        name = parts[0]
        latest_price = float(parts[3])
        return {"name": name, "price": latest_price}
    except Exception:
        raise ValueError(f"解析新浪行情失败: {symbol}")


def _get_tencent_hq(symbol: str) -> dict:
    """从腾讯财经获取名称和最新价（首选数据源，HTTPS 最稳定）。"""
    full_symbol = _full_symbol(symbol)
    url = f"{TENCENT_HQ_URL}{full_symbol}"
    headers = {"User-Agent": BROWSER_USER_AGENT}

    def _do():
        with _no_proxy():
            return requests.get(url, headers=headers, timeout=TENCENT_TIMEOUT)

    r = _retry(_do)

    if r.status_code != 200:
        raise ValueError(f"腾讯返回非 200: {r.status_code} ({symbol})")

    # 响应格式: v_sz001210="51~名称~代码~当前价~昨收~开盘~...";
    # 退市/未上市的代码可能返回 v_xxxx=""; ，整段 payload 为空
    payload = r.text.split('"', 2)
    if len(payload) < 2 or not payload[1].strip():
        raise ValueError(f"腾讯返回空数据: {symbol}")

    try:
        parts = payload[1].split('~')
        # 字段约定: [0]=市场标记 [1]=名称 [3]=当前价
        if len(parts) < 4:
            raise ValueError
        name = parts[1]
        latest_price = float(parts[3])
        if latest_price <= 0:
            raise ValueError(f"腾讯无有效价格: {symbol}")
        return {"name": name, "price": latest_price}
    except ValueError:
        raise
    except Exception:
        raise ValueError(f"解析腾讯行情失败: {symbol}")


def _get_eastmoney_hq(symbol: str) -> dict:
    """从东方财富 secid 接口获取名称和最新价（push2 域，2026-06-16 标记为不可用）。

    状态：用户本地网络对 push2.eastmoney.com 域持续 RST（裸 socket/curl
    同样失败，非代理问题）。保留函数定义以便其他文件 ``import`` 不破，
    但调用永远会抛 ConnectionError — ``get_stock_metrics`` 的兜底链已
    移除本函数（见 v3 改动）。任何新代码**不要**调用本函数。
    """
    raise ConnectionError(
        "eastmoney push2.eastmoney.com 域在当前网络下不可用（2026-06-16），"
        "请改用 sina/tencent 数据源"
    )


def get_sina_index_spot(symbol: str) -> dict:
    """从新浪财经获取大盘指数。"""
    url = f"{SINA_HQ_URL}{symbol}"
    headers = {"Referer": SINA_REFERER}

    try:
        with _no_proxy():
            r = requests.get(url, headers=headers, timeout=SINA_INDEX_TIMEOUT)

        if r.status_code == 200:
            content = r.text.split('"')[1]
            parts = content.split(',')
            return {
                "name": parts[0],
                "current": float(parts[1]),
                "change_amount": float(parts[2]),
                "change_pct": float(parts[3]),
                "volume": float(parts[4]),
                "amount": float(parts[5])
            }
    except Exception as e:
        logger.error(f"Error fetching index {symbol}: {e}", exc_info=True)
        return None


def get_eastmoney_url(symbol: str) -> str:
    """生成 East Money 股票详情页 URL。"""
    symbol = str(symbol).strip()

    if symbol.startswith("6"):
        market = "sh"
    elif symbol.startswith(("0", "3")):
        market = "sz"
    elif symbol.startswith(("4", "8", "9")):
        market = "bj"
    else:
        market = "sh"

    return f"http://quote.eastmoney.com/{market}{symbol}.html"


def get_stock_metrics(symbol: str) -> dict:
    """根据 6 位股票代码获取名称、最新价、股息率、每股分红和分红备注。"""
    symbol = str(symbol).strip().zfill(6)

    # 多数据源获取名称和最新价：腾讯（HTTPS 最稳） → 新浪
    # 注（v3, 2026-06-16）：东方财富 push2 域对当前网络持续 RST，已从
    # 兜底链移除，保留 _get_eastmoney_hq 仅作占位（永远抛 ConnectionError）。
    hq = None
    sources = [
        ("腾讯", _get_tencent_hq),
        ("新浪", _get_sina_hq),
    ]
    errors = []

    for src_name, fetch_fn in sources:
        try:
            hq = fetch_fn(symbol)
            if hq and hq.get("price", 0) > 0:
                break
        except Exception as e:
            errors.append(f"{src_name}: {e}")

    if hq is None:
        logger.error(f"无法从任何数据源获取 {symbol} 行情: {'; '.join(errors)}")
        return None

    name = hq["name"]
    latest_price = hq["price"]

    if latest_price <= 0:
        try:
            with _no_proxy():
                df_hist = ak.stock_zh_a_daily(
                    symbol=f"sh{symbol}" if symbol.startswith(("6", "9")) else f"sz{symbol}",
                    adjust="qfq",
                )
                if df_hist is not None and not df_hist.empty:
                    latest_price = float(df_hist.iloc[-1]["close"])
        except Exception as e:
            logger.warning(f"获取 {symbol} 历史价格失败，将使用当前价 0: {e}", exc_info=True)

    dividend_yield_pct = 0.0
    dividend_per_share = 0.0
    dividend_note = ""
    try:
        with _no_proxy():
            df_div = ak.stock_fhps_detail_em(symbol=symbol)

        if df_div is not None and not df_div.empty:
            df_div['股权登记日'] = pd.to_datetime(df_div['股权登记日'], errors='coerce')
            df_div['现金分红-现金分红比例'] = pd.to_numeric(df_div['现金分红-现金分红比例'], errors='coerce')

            # 包含已实施和董事会决议通过（后者也是确定的分红承诺）
            _confirmed_status = {'实施分配', '董事会决议通过'}
            df_confirmed = df_div[df_div['方案进度'].isin(_confirmed_status)].copy()

            if not df_confirmed.empty:
                df_confirmed['_报告期'] = pd.to_datetime(df_confirmed['报告期'], errors='coerce')
                df_confirmed['_财年'] = df_confirmed['_报告期'].dt.year
                df_confirmed['_is_annual'] = df_confirmed['_报告期'].dt.month == 12

                # 找最近一个有年报分红的完整财年
                annual_years = sorted(
                    df_confirmed[df_confirmed['_is_annual'] & df_confirmed['现金分红-现金分红比例'].notna()]['_财年'].unique(),
                    reverse=True
                )

                if annual_years:
                    target_year = annual_years[0]
                    year_divs = df_confirmed[
                        (df_confirmed['_财年'] == target_year) &
                        df_confirmed['现金分红-现金分红比例'].notna()
                    ]
                    total_cash_per_10 = float(year_divs['现金分红-现金分红比例'].sum())
                    dividend_note = f"FY{target_year}"
                else:
                    # 无完整财年年报，取最近一次半年报分红
                    interim = df_confirmed[
                        ~df_confirmed['_is_annual'] & df_confirmed['现金分红-现金分红比例'].notna()
                    ].sort_values('股权登记日', ascending=False)
                    if not interim.empty:
                        total_cash_per_10 = float(interim.iloc[0]['现金分红-现金分红比例'])
                        dividend_note = "仅半年报"
                    else:
                        total_cash_per_10 = 0.0

                if total_cash_per_10 > 0 and latest_price > 0:
                    dividend_per_share = total_cash_per_10 / 10.0
                    dividend_yield_pct = (dividend_per_share / latest_price) * 100
    except Exception as e:
        logger.warning(f"获取 {symbol} 分红数据失败，股息率将返回 0: {e}", exc_info=True)

    return {
        "名称": name,
        "最新价": float(latest_price),
        "股息率": float(round(dividend_yield_pct, 2)),
        "每股分红": float(round(dividend_per_share, 4)),
        "分红备注": dividend_note,
    }
