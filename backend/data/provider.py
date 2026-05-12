"""
数据提供者抽象 — 定义行情数据访问的统一接口。

实现：
  HistoricalDataProvider — 通过 akshare + DB 缓存获取历史K线
  LiveDataProvider — 复用 stock_service 获取实时行情（后续实现）
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime

from backend.data.bar import Bar


class DataProvider(ABC):
    """行情数据提供者抽象接口。"""

    @abstractmethod
    def get_bars(
        self, symbol: str, timeframe: str,
        start: datetime | str, end: datetime | str,
    ) -> list[Bar]:
        """获取历史K线数据。

        Args:
            symbol: 6位股票代码
            timeframe: K线周期 ("1d", "1h", "15min", "5min")
            start: 起始日期
            end: 结束日期

        Returns:
            Bar 列表，按时间升序排列
        """
        ...

    @abstractmethod
    def get_latest_bar(self, symbol: str, timeframe: str = "1d") -> Bar | None:
        """获取最新一根K线。"""
        ...

    def has_data(self, symbol: str, timeframe: str = "1d") -> bool:
        """检查是否有该股票的历史数据。"""
        try:
            bars = self.get_bars(symbol, timeframe, "2000-01-01", "2099-12-31")
            return len(bars) > 0
        except Exception:
            return False
