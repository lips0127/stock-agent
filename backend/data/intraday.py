"""
30分钟粒度K线数据获取。
- A股指数：新浪财经 getKLineData API（实时）
- 港股/美股：日线兜底
"""
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import requests

from backend.services.stock_service import _no_proxy

logger = logging.getLogger(__name__)

# ── 指数定义 ──────────────────────────────────────────

INDEX_MAP = {
    "sh000001": {"name": "上证指数", "market": "A"},
    "sz399001": {"name": "深证成指", "market": "A"},
    "sz399006": {"name": "创业板指", "market": "A"},
    "sh000688": {"name": "科创50", "market": "A"},
    "sh000300": {"name": "沪深300", "market": "A"},
    "int:hsi": {"name": "恒生指数", "market": "HK"},
    "int:spx": {"name": "标普500", "market": "US"},
}

SINA_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)

SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
}


def _fetch_sina_intraday(symbol: str, scale: int = 30,
                         datalen: int = 400) -> list[dict] | None:
    """从新浪获取A股指数的分钟K线。

    返回 ``[{day, open, high, low, close, volume}, ...]``，按时间升序。
    """
    params = {"symbol": symbol, "scale": scale, "ma": "no", "datalen": datalen}
    try:
        with _no_proxy():
            resp = requests.get(
                SINA_KLINE_URL, params=params, headers=SINA_HEADERS, timeout=15,
            )
        if resp.status_code != 200:
            logger.warning(f"新浪K线 HTTP {resp.status_code}: {symbol}")
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) == 0:
            logger.warning(f"新浪K线返回空: {symbol}")
            return None
        return data
    except Exception as e:
        logger.warning(f"新浪K线请求失败 {symbol}: {e}")
        return None


def _normalize_sina_bar(bar: dict) -> dict:
    """将新浪的 {day, open, high, low, close, volume} 转为统一格式。"""
    t = bar.get("day", "")
    if len(t) == 10:  # "2026-05-28"
        t += " 00:00:00"
    return {
        "time": t,
        "open": float(bar.get("open", 0) or 0),
        "high": float(bar.get("high", 0) or 0),
        "low": float(bar.get("low", 0) or 0),
        "close": float(bar.get("close", 0) or 0),
        "volume": float(bar.get("volume", 0) or 0),
    }


def _fetch_yfinance_intraday(ticker: str, period: str = "7d",
                             interval: str = "30m") -> list[dict] | None:
    """通过 yfinance 获取港股/美股分钟K线。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，无法获取港股/美股数据")
        return None
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval)
        if df.empty:
            return None
        bars = []
        for idx, row in df.iterrows():
            bars.append({
                "time": idx.strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return bars
    except Exception as e:
        logger.warning(f"yfinance 获取失败 {ticker}: {e}")
        return None


def _fetch_akshare_daily(symbol: str, days: int = 7) -> list[dict] | None:
    """通过 akshare 获取A股指数日线作为兜底。"""
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        with _no_proxy():
            df = ak.stock_zh_index_daily(symbol=f"sh{symbol[2:]}" if symbol.startswith("sh") else f"sz{symbol[2:]}")
        if df is None or df.empty:
            return None
        df = df.tail(days)
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "time": str(row.get("date", "")),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
            })
        return bars
    except Exception as e:
        logger.warning(f"akshare 日线获取失败 {symbol}: {e}")
        return None


def get_intraday_bars(symbol: str, interval: str = "30min",
                      days: int = 7) -> dict[str, Any]:
    """获取指数K线数据。主入口。

    Returns:
        {symbol, name, interval, source, bars: [{time, open, high, low, close, volume}]}
    """
    info = INDEX_MAP.get(symbol, {"name": symbol, "market": "unknown"})
    name = info["name"]
    market = info["market"]
    scale = int(interval.replace("min", "")) if "min" in interval else 30

    bars = None
    source = "unknown"

    if market == "A":
        # 1. 尝试新浪分钟K线
        bars = _fetch_sina_intraday(symbol, scale=scale,
                                    datalen=days * 16 + 40)
        if bars:
            source = "sina_intraday"
        else:
            # 2. 兜底：akshare 日线
            bars = _fetch_akshare_daily(symbol, days=days)
            if bars:
                source = "akshare_daily"
                interval = "1d"

    elif market in ("HK", "US"):
        ticker_map = {"int:hsi": "^HSI", "int:spx": "^GSPC"}
        ticker = ticker_map.get(symbol, "")
        # 尝试 yfinance 分钟线
        bars = _fetch_yfinance_intraday(ticker, period=f"{days}d",
                                        interval=f"{scale}m")
        if bars:
            source = "yfinance_intraday"
        else:
            # 日线兜底
            bars = _fetch_yfinance_intraday(ticker, period=f"{days}d",
                                            interval="1d")
            if bars:
                source = "yfinance_daily"
                interval = "1d"

    if not bars:
        return {
            "symbol": symbol, "name": name, "interval": interval,
            "source": "none", "error": "数据源不可用", "bars": [],
        }

    # 统一格式化 & 按时间过滤
    normalized = []
    cutoff = None
    if days > 0:
        cutoff = time.time() - days * 86400
    for b in bars:
        nb = _normalize_sina_bar(b) if isinstance(b, dict) and "day" in b else b
        if cutoff:
            try:
                t = datetime.fromisoformat(nb["time"])
                if t.timestamp() < cutoff:
                    continue
            except (ValueError, OSError):
                pass
        normalized.append(nb)

    result = {
        "symbol": symbol, "name": name, "interval": interval,
        "source": source, "bars": normalized,
    }
    if source.endswith("_daily") or source == "akshare_daily":
        result["warning"] = "30分钟线数据暂不可用，展示日线数据"
    return result
