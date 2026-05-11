import json
import time
import logging
from pathlib import Path
from backend.config import CACHE_DIR, CACHE_EXPIRE_HOURS
from backend.services.stock_service import get_stock_metrics, _no_proxy

logger = logging.getLogger(__name__)

CACHE_FILE = Path(CACHE_DIR) / "market_dividends_cache.json"


def _is_cache_valid(cache_data: dict) -> bool:
    """检查缓存是否在有效期内。"""
    ts = cache_data.get("timestamp", 0)
    return (time.time() - ts) < (CACHE_EXPIRE_HOURS * 3600)


def _read_cache() -> dict | None:
    """读取缓存，过期则返回 None。"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if _is_cache_valid(data):
                logger.info("Using cached high-dividend data")
                return data
            else:
                logger.info("Cache expired, will refresh")
                return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cache read failed: {e}")
    return None


def _write_cache(data: list) -> None:
    """写入缓存并附加时间戳。"""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False)
    except OSError as e:
        logger.warning(f"Cache write failed: {e}")


def get_dividend_index_constituents() -> list:
    """获取中证红利指数成分股代码列表。"""
    import akshare as ak
    try:
        with _no_proxy():
            df = ak.index_stock_cons(symbol="000922")
    except Exception as e:
        logger.warning(f"获取中证红利指数(000922)成分股失败，尝试回退 000015: {e}", exc_info=True)
        try:
            with _no_proxy():
                df = ak.index_stock_cons(symbol="000015")
        except Exception as e:
            logger.error(f"获取红利指数成分股失败(000922 和 000015 均失败): {e}", exc_info=True)
            return []
    return df["品种代码"].astype(str).str.zfill(6).tolist()


def get_top_dividend_stocks(limit: int = 20) -> list:
    """从红利指数成分股中获取股息率 TOP N 股票，带缓存。"""
    cached = _read_cache()
    if cached is not None:
        return cached.get("data", [])[:limit]

    codes = get_dividend_index_constituents()
    stocks = []

    for i, code in enumerate(codes):
        try:
            metrics = get_stock_metrics(code)
            if metrics and metrics.get("股息率"):
                stocks.append({"code": code, **metrics})
        except Exception as e:
            logger.warning(f"Failed to get metrics for {code}: {e}", exc_info=True)
            continue
        if i > 0 and i % 5 == 0:
            time.sleep(1)

    stocks.sort(key=lambda x: x.get("股息率", 0), reverse=True)
    result = stocks[:limit]

    _write_cache(result)
    return result
