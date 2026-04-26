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
    """临时取消代理，退出时恢复。"""
    backup = {k: os.environ.pop(k, None) for k in _PROXY_KEYS}
    try:
        yield
    finally:
        for k, v in backup.items():
            if v is not None:
                os.environ[k] = v

def _get_sina_hq(symbol: str) -> dict:
    """从新浪财经获取名称和最新价。"""
    # 转换代码格式
    if symbol.startswith("6"):
        full_symbol = f"sh{symbol}"
    elif symbol.startswith(("0", "3")):
        full_symbol = f"sz{symbol}"
    elif symbol.startswith(("4", "8")):
        full_symbol = f"bj{symbol}"
    else:
        full_symbol = f"sh{symbol}" # 默认 sh

    url = f"{SINA_HQ_URL}{full_symbol}"
    headers = {"Referer": SINA_REFERER}

    with _no_proxy():
        r = requests.get(url, headers=headers, timeout=SINA_TIMEOUT)
    
    if r.status_code != 200 or len(r.text) < 50:
        raise ValueError(f"无法从新浪获取股票 {symbol} 的行情")
    
    # 解析：var hq_str_sh600519="贵州茅台,1466.990,..."
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

def get_sina_index_spot(symbol: str) -> dict:
    """
    Fetch index spot data from Sina.
    s_sh000001 = 上证指数
    s_sz399001 = 深证成指
    s_sz399006 = 创业板指
    s_sh000688 = 科创50
    s_sh000012 = 国债指数
    """
    url = f"{SINA_HQ_URL}{symbol}"
    headers = {"Referer": SINA_REFERER}

    try:
        with _no_proxy():
            r = requests.get(url, headers=headers, timeout=SINA_INDEX_TIMEOUT)
        
        # var hq_str_s_sh000001="上证指数,3041.17,54.12,1.81,3662283,39634568";
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
        logger.error(f"Error fetching {symbol}: {e}")
        return None

def get_eastmoney_url(symbol: str) -> str:
    """Generate East Money detail page URL for a given stock symbol."""
    symbol = str(symbol).strip()
    # East Money uses 0.xxxxxx for SZ, 1.xxxxxx for SH, but the web URL usually uses sh/sz prefix or market ID.
    # New URL format: http://quote.eastmoney.com/sh600519.html or sz000001.html
    # BJ: bj83xxxx
    
    if symbol.startswith("6"):
        market = "sh"
    elif symbol.startswith(("0", "3")):
        market = "sz"
    elif symbol.startswith(("4", "8", "9")): # 9 for some BJ stocks? 8 for BJ.
        market = "bj"
    else:
        market = "sh" # Default fallback
        
    return f"http://quote.eastmoney.com/{market}{symbol}.html"

def get_stock_metrics(symbol: str) -> dict:

    """
    根据 6 位股票代码获取该股票的名称、最新价和股息率。
    行情用 Sina HQ；分红用 stock_fhps_detail_em。
    """
    symbol = str(symbol).strip().zfill(6)

    # 1. 获取名称和最新价
    hq = _get_sina_hq(symbol)
    name = hq["name"]
    latest_price = hq["price"]

    if latest_price <= 0:
        # 尝试从历史接口获取昨日收盘
        try:
            with _no_proxy():
                df_hist = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
                if df_hist is not None and not df_hist.empty:
                    latest_price = float(df_hist.iloc[-1]["收盘"])
        except Exception:
            pass

    # 2. 获取分红数据并计算股息率
    dividend_yield_pct = 0.0
    try:
        with _no_proxy():
            df_div = ak.stock_fhps_detail_em(symbol=symbol)
        
        if df_div is not None and not df_div.empty:
            # 统一列名和类型
            df_div['股权登记日'] = pd.to_datetime(df_div['股权登记日'], errors='coerce')
            df_div['现金分红-现金分红比例'] = pd.to_numeric(df_div['现金分红-现金分红比例'], errors='coerce')
            
            # 过滤出“实施分配”的记录
            df_impl = df_div[df_div['方案进度'] == '实施分配'].copy()
            
            if not df_impl.empty:
                # 方案 1: 近 12 个月累计分红 (TTM)
                now = pd.Timestamp.now()
                one_year_ago = now - pd.DateOffset(years=1)
                
                # 必须确保股权登记日有效
                recent_divs = df_impl[
                    (df_impl['股权登记日'] >= one_year_ago) & 
                    (df_impl['股权登记日'] <= now)
                ]
                
                if not recent_divs.empty:
                    total_cash_per_10 = recent_divs['现金分红-现金分红比例'].sum()
                else:
                    # 方案 2: 若近 12 个月无记录，取最新的一笔 (仅当最新一笔在合理范围内，比如 18 个月内)
                    df_impl = df_impl.sort_values('报告期', ascending=False)
                    latest_div = df_impl.iloc[0]
                    latest_date = latest_div['股权登记日']
                    
                    # 如果最新分红超过 1.5 年，视为无分红（避免历史高分红被误算）
                    if pd.notna(latest_date) and latest_date >= (now - pd.DateOffset(months=18)):
                        total_cash_per_10 = latest_div['现金分红-现金分红比例']
                    else:
                        total_cash_per_10 = 0.0

                
                if total_cash_per_10 > 0 and latest_price > 0:
                    div_per_share = total_cash_per_10 / 10.0
                    dividend_yield_pct = (div_per_share / latest_price) * 100
    except Exception:
        # 分红获取失败不影响基本行情显示
        pass

    return {
        "名称": name,
        "最新价": float(latest_price),
        "股息率": float(round(dividend_yield_pct, 2)),
    }



