"""
订单模型 — 订单数据结构 + 状态机。

状态流转：
  CREATED → SUBMITTED → PARTIALLY_FILLED → FILLED
                     ↘ → REJECTED
                     ↘ → CANCELLED
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


# 合法的状态转换
_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                             OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                                    OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


@dataclass
class Order:
    """订单数据模型。"""
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None     # None for MARKET orders
    strategy_id: str = ""
    status: OrderStatus = OrderStatus.CREATED
    filled_qty: float = 0.0
    filled_price: float | None = None
    commission: float = 0.0
    error_message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def transition(self, new_status: OrderStatus) -> bool:
        """尝试状态转换，返回是否合法。"""
        if new_status in _VALID_TRANSITIONS.get(self.status, set()):
            self.status = new_status
            self.updated_at = datetime.now()
            return True
        return False

    @property
    def is_done(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED,
                               OrderStatus.REJECTED)

    @property
    def remaining(self) -> float:
        return self.quantity - self.filled_qty
