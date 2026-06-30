"""
历史数据提供者 — 通过 akshare 获取日线数据，SQLite 缓存。

支持：
  - 日线数据（akshare stock_zh_a_daily）
  - 分钟级数据（预留接口，后续实现）
  - 自动缓存到 DB，避免重复请求
"""

from __future__ import annotations
import logging
import os
import time
import random
from datetime import datetime, date, timedelta

from backend.data.provider import DataProvider
from backend.data.bar import Bar
from backend.core.database import get_connection

logger = logging.getLogger(__name__)

# 网络请求重试配置
_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_MAX_DELAY = 15.0
_REQUEST_TIMEOUT = 15


class HistoricalDataProvider(DataProvider):
    """历史K线数据提供者 — akshare + DB 缓存。"""

    def __init__(self):
        self._cache: dict[str, list[Bar]] = {}

    # ── 公开接口 ──────────────────────────────────────────

    def get_bars(
        self, symbol: str, timeframe: str,
        start: datetime | str, end: datetime | str,
    ) -> list[Bar]:
        """获取历史K线数据（优先从 DB 缓存读取）。"""
        symbol = str(symbol).strip().zfill(6)
        start_str = _to_date_str(start)
        end_str = _to_date_str(end)

        if timeframe != "1d":
            logger.warning(f"暂不支持的K线周期: {timeframe}，回退到日线")
            timeframe = "1d"

        # 1. 从 DB 查询缓存
        bars = self._load_from_db(symbol, timeframe, start_str, end_str)

        # 2. 如果数据不足，从 akshare 拉取并缓存
        if not bars or len(bars) < _estimate_trading_days(start_str, end_str) * 0.8:
            logger.info(f"DB 缓存不足，从 akshare 获取: {symbol} {start_str}~{end_str}")
            fetched = self._fetch_from_akshare(symbol, start_str, end_str)
            if fetched:
                self._save_to_db(fetched)
                # 重新加载以包含新数据
                bars = self._load_from_db(symbol, timeframe, start_str, end_str)

        return bars

    def get_latest_bar(self, symbol: str, timeframe: str = "1d") -> Bar | None:
        """获取最新一根K线。"""
        symbol = str(symbol).strip().zfill(6)
        bars = self._load_from_db(symbol, timeframe, None, None, limit=1)
        return bars[0] if bars else None

    # ── DB 操作 ───────────────────────────────────────────

    def _load_from_db(
        self, symbol: str, timeframe: str,
        start: str | None, end: str | None, limit: int = 0,
    ) -> list[Bar]:
        """从 SQLite 加载K线数据。"""
        sql = """SELECT symbol, timeframe, bar_time, open, high, low, close, volume, amount
                 FROM historical_bars WHERE symbol=? AND timeframe=?"""
        params: list = [symbol, timeframe]

        if start:
            sql += " AND bar_time >= ?"
            params.append(start)
        if end:
            sql += " AND bar_time <= ?"
            params.append(end)

        sql += " ORDER BY bar_time ASC"
        if limit:
            sql += f" LIMIT {limit}"

        try:
            with get_connection() as conn:
                rows = conn.cursor().execute(sql, params).fetchall()
            return [_row_to_bar(row) for row in rows]
        except Exception as e:
            logger.error(f"加载历史数据失败: {symbol}: {e}")
            return []

    def _save_to_db(self, bars: list[Bar]):
        """保存K线到 DB（INSERT OR IGNORE 去重）。"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.executemany(
                    """INSERT OR IGNORE INTO historical_bars
                       (symbol, timeframe, bar_time, open, high, low, close, volume, amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(b.symbol, b.timeframe, b.bar_time.isoformat(),
                      b.open, b.high, b.low, b.close, b.volume, b.amount)
                     for b in bars],
                )
            logger.info(f"缓存 {len(bars)} 条K线到 DB: {bars[0].symbol}")
        except Exception as e:
            logger.error(f"保存K线数据失败: {e}")

    # ── akshare 数据获取 ──────────────────────────────────

    def _try_fetch_chunk_sina(
        self, symbol: str, chunk_start: str, chunk_end: str,
    ) -> list[Bar]:
        """通过 akshare (新浪源) 拉取日线 — 主数据源。"""
        try:
            import akshare as ak
            from backend.services.stock_service import _no_proxy

            sina_symbol = f"sh{symbol}" if symbol.startswith(("6", "9")) else f"sz{symbol}"
            with _no_proxy():
                df = ak.stock_zh_a_daily(
                    symbol=sina_symbol,
                    start_date=chunk_start.replace("-", ""),
                    end_date=chunk_end.replace("-", ""),
                    adjust="qfq",
                )

            if df is not None and not df.empty:
                return self._parse_sina_df(symbol, df, chunk_start, chunk_end)

        except Exception as e:
            logger.debug(f"Sina 获取失败: {symbol}: {e}")

        return []

    def _try_fetch_chunk_sina_backup(
        self, symbol: str, chunk_start: str, chunk_end: str,
    ) -> list[Bar]:
        """备选数据源（v2, 2026-06-16）：原东财 ``ak.stock_zh_a_hist``（push2
        域）RST 频繁，改用同接口的 sina 源别名 ``ak.stock_zh_a_daily``。

        之所以保留这层兜底：sina 主源偶尔也 502，两层都用 sina 接口
        + 不同 prefix（主源 ``sina_symbol = sh/sz + code``，备选带
        ``0000001.`` 前缀走另一组 sina 端点），可提高整体成功率。
        """
        import akshare as ak
        from backend.services.stock_service import _no_proxy

        try:
            with _no_proxy():
                df = ak.stock_zh_a_daily(
                    symbol=symbol,
                    start_date=chunk_start.replace("-", ""),
                    end_date=chunk_end.replace("-", ""),
                    adjust="qfq",
                    timeout=_REQUEST_TIMEOUT,
                )

            if df is not None and not df.empty:
                return self._parse_sina_df(symbol, df, chunk_start, chunk_end)

        except Exception as e:
            logger.debug(f"备选源获取失败: {symbol}: {e}")

        return []


    def _parse_sina_df(
        self, symbol: str, df, chunk_start: str, chunk_end: str,
    ) -> list[Bar]:
        """解析新浪返回的 DataFrame（英文列名：open/high/low/close/volume/amount/date）。"""
        bars = []
        for _, row in df.iterrows():
            try:
                bar_time = row["date"]
                if hasattr(bar_time, "to_pydatetime"):
                    bar_time = bar_time.to_pydatetime()
                elif isinstance(bar_time, str):
                    bar_time = datetime.fromisoformat(bar_time)
                bars.append(Bar(
                    symbol=symbol,
                    timeframe="1d",
                    bar_time=bar_time,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=float(row.get("amount", 0)),
                ))
            except (ValueError, KeyError) as e:
                logger.debug(f"解析新浪K线行失败: {e}")
                continue

        logger.info(f"Sina 获取 {len(bars)} 条K线: {symbol} {chunk_start}~{chunk_end}")
        return bars

    def _fetch_single_chunk(
        self, symbol: str, chunk_start: str, chunk_end: str,
    ) -> list[Bar]:
        """拉取单个时间段的日线数据，带重试和双层新浪源（主源 + 备选）兜底。"""
        for attempt in range(1, _MAX_RETRIES + 1):
            # 主源：新浪（sh/sz 前缀 + 完整日期）
            bars = self._try_fetch_chunk_sina(symbol, chunk_start, chunk_end)
            if bars:
                return bars

            # 备选源（新浪源不同 prefix，与主源互为兜底）
            bars = self._try_fetch_chunk_sina_backup(symbol, chunk_start, chunk_end)
            if bars:
                return bars

            if attempt < _MAX_RETRIES:
                delay = min(_BASE_DELAY ** attempt + random.uniform(0, 1), _MAX_DELAY)
                logger.warning(
                    f"数据获取失败 (第{attempt}/{_MAX_RETRIES}次): {symbol}，"
                    f"{delay:.1f}s 后重试..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"数据获取失败(已重试{_MAX_RETRIES}次，双层新浪源均不可用): {symbol}"
                )

        return []

    def _fetch_from_akshare(
        self, symbol: str, start: str, end: str,
    ) -> list[Bar]:
        """拉取日线数据，大区间自动分段。"""
        chunks = self._split_date_range(start, end)
        all_bars = []

        for i, (cs, ce) in enumerate(chunks):
            if i > 0:
                time.sleep(random.uniform(0.5, 1.5))

            bars = self._fetch_single_chunk(symbol, cs, ce)
            all_bars.extend(bars)

        return all_bars

    @staticmethod
    def _split_date_range(start: str, end: str, max_days: int = 365) -> list[tuple[str, str]]:
        """将日期范围拆分为不超过 max_days 的连续段。"""
        try:
            sd = datetime.strptime(start, "%Y-%m-%d")
            ed = datetime.strptime(end, "%Y-%m-%d")
            chunks = []
            cursor = sd
            while cursor < ed:
                chunk_end = min(cursor + timedelta(days=max_days), ed)
                chunks.append((
                    cursor.strftime("%Y-%m-%d"),
                    chunk_end.strftime("%Y-%m-%d"),
                ))
                cursor = chunk_end + timedelta(days=1)
            return chunks or [(start, end)]
        except Exception:
            return [(start, end)]


# ── 辅助函数 ──────────────────────────────────────────────

def _row_to_bar(row) -> Bar:
    """将 DB 行转为 Bar 对象。"""
    bar_time = row["bar_time"]
    if isinstance(bar_time, str):
        bar_time = datetime.fromisoformat(bar_time)
    return Bar(
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        bar_time=bar_time,
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        amount=row["amount"] or 0.0,
    )


def _to_date_str(d: datetime | str) -> str:
    """统一转为 'YYYY-MM-DD' 字符串。"""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def _estimate_trading_days(start_str: str, end_str: str) -> int:
    """估算交易日天数（约自然日的 70%）。"""
    try:
        s = datetime.strptime(start_str, "%Y-%m-%d")
        e = datetime.strptime(end_str, "%Y-%m-%d")
        return max(1, int((e - s).days * 0.7))
    except Exception:
        return 252

