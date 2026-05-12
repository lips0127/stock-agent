"""
事件类型定义 — 量化交易系统中的所有事件类型。

事件按层级组织：
  MarketEvent  ── BarEvent, TickEvent
  SignalEvent
  OrderEvent, FillEvent, CancelEvent
  PositionEvent, PortfolioEvent
  TimerEvent, StartEvent, StopEvent

事件是纯数据载体（dataclass），通过 EventBus 分发。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ═══════════════════════════════════════════════════════════
# 市场数据事件
# ═══════════════════════════════════════════════════════════

@dataclass
class MarketEvent:
    """市场数据事件基类。"""
    symbol: str
    timestamp: datetime


@dataclass
class BarEvent(MarketEvent):
    """K线完成事件（日线/小时线/分钟线等）。"""
    timeframe: str = "1d"       # "1d", "1h", "15min", "5min", "1min"
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0         # 成交额


@dataclass
class TickEvent(MarketEvent):
    """Tick 行情事件（逐笔/快照）。"""
    price: float = 0.0
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0


# ═══════════════════════════════════════════════════════════
# 信号事件
# ═══════════════════════════════════════════════════════════

@dataclass
class SignalEvent:
    """策略生成的交易信号。"""
    strategy_id: str
    symbol: str
    direction: str             # "BUY" / "SELL"
    strength: float = 1.0      # 信号强度 0.0-1.0
    reason: str = ""
    bar_time: str = ""         # 触发信号的K线时间
    timestamp: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 订单事件
# ═══════════════════════════════════════════════════════════

@dataclass
class OrderEvent:
    """订单提交事件。"""
    order_id: str
    strategy_id: str
    symbol: str
    side: str                  # "BUY" / "SELL"
    quantity: float
    price: float | None = None # None = 市价单
    order_type: str = "MARKET" # "MARKET" / "LIMIT" / "STOP"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FillEvent:
    """成交回报事件。"""
    order_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: float            # 成交数量
    price: float               # 成交价格
    commission: float = 0.0    # 手续费
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CancelEvent:
    """撤单确认事件。"""
    order_id: str
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 组合事件
# ═══════════════════════════════════════════════════════════

@dataclass
class PositionEvent:
    """持仓变化事件。"""
    symbol: str
    strategy_id: str
    quantity: float
    avg_cost: float
    realized_pnl: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PortfolioEvent:
    """组合快照事件。"""
    total_value: float
    cash: float
    positions_value: float
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════
# 系统事件
# ═══════════════════════════════════════════════════════════

@dataclass
class TimerEvent:
    """定时触发事件（开盘/收盘/定时检查）。"""
    event_type: str            # "market_open", "market_close", "periodic_check"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StartEvent:
    """系统启动事件。"""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StopEvent:
    """系统停止事件。"""
    timestamp: datetime = field(default_factory=datetime.now)
