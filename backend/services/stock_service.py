# -*- coding: utf-8 -*-
"""
A 股股息率监测 - 数据逻辑层
使用 akshare 获取股票名称、最新价、股息率。
"""

import os
import time
import pandas as pd
from contextlib import contextmanager
import requests
import akshare as ak
import logging

from backend.config import SINA_HQ_URL, SINA_REFERER, SINA_TIMEOUT, SINA_INDEX_TIMEOUT

logger = logging.getLogger(__name__)

# 代理相关环境变量
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


@contextmanager
def _no_proxy():
    """临时取消代理，退出时恢复。

    同时处理环境变量代理和 Windows 系统代理（requests 可能通过
    system proxy settings 走代理，即使环境变量为空），
    因此还需要 monkey-patch requests.Session 强制禁用代理。
    """
    backup = {k: os.environ.pop(k, None) for k in _PROXY_KEYS}
    _orig_request = requests.Session.request
    def _patched_request(self, method, url, **kwargs):
        kwargs.setdefault('proxies', {'http': None, 'https': None})
        return _orig_request(self, method, url, **kwargs)
    requests.Session.request = _patched_request
    try:
        yield
    finally:
        requests.Session.request = _orig_request
        for k, v in backup.items():
            if v is not None:
                os.environ[k] = v


def _get_sina_hq(symbol: str) -> dict:
    """从新浪财经获取名称和最新价。"""
    if symbol.startswith("6"):
        full_symbol = f"sh{symbol}"
    elif symbol.startswith(("0", "3")):
        full_symbol = f"sz{symbol}"
    elif symbol.startswith(("4", "8", "9")):
        full_symbol = f"bj{symbol}"
    else:
        full_symbol = f"sh{symbol}"

    url = f"{SINA_HQ_URL}{full_symbol}"
    headers = {"Referer": SINA_REFERER}

    with _no_proxy():
        r = requests.get(url, headers=headers, timeout=SINA_TIMEOUT)

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


def _get_eastmoney_hq(symbol: str) -> dict:
    """从东方财富获取名称和最新价（备用数据源）。"""
    # 东方财富 secid 格式: market.code
    # SH=1, SZ=0, BJ=0
    if symbol.startswith(("6", "68")):
        secid = f"1.{symbol}"
    elif symbol.startswith(("0", "3", "4", "8", "9")):
        secid = f"0.{symbol}"
    else:
        secid = f"1.{symbol}"

    url = "http://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f57,f58,f43",
        "ut": "fa5fd1943c7b386f172d6893dbfccf91",
    }

    with _no_proxy():
        r = requests.get(url, params=params, timeout=SINA_TIMEOUT)

    data = r.json()
    item = data.get("data")
    if not item:
        raise ValueError(f"东方财富返回空数据: {symbol}")

    name = item.get("f58", "")
    price = item.get("f43")
    if price is None or price == "-" or float(price) <= 0:
        raise ValueError(f"东方财富无有效价格: {symbol}")

    return {"name": name, "price": float(price)}


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

    # 多数据源获取名称和最新价：新浪 → 东方财富
    hq = None
    sources = [("新浪", _get_sina_hq), ("东方财富", _get_eastmoney_hq)]
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
                df_hist = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
                if df_hist is not None and not df_hist.empty:
                    latest_price = float(df_hist.iloc[-1]["收盘"])
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
