"""
K线数据结构 — 支持多周期的 OHLCV Bar。
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Bar:
    """单根K线数据。"""
    symbol: str
    timeframe: str             # "1d", "1h", "15min", "5min", "1min"
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0        # 成交额

    @property
    def typical_price(self) -> float:
        """典型价格 (H+L+C)/3。"""
        return (self.high + self.low + self.close) / 3

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bar_time": self.bar_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
        }
