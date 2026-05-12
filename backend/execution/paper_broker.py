"""
模拟交易券商 — 用于回测和策略验证。

市价单：下一根K线以开盘价成交
限价单：价格触及后成交
包含模拟手续费（默认万2.5，最低5元）
"""

from __future__ import annotations
import uuid
import logging
from datetime import datetime
from collections import defaultdict

from backend.execution.broker import AbstractBroker
from backend.execution.order import Order, OrderStatus, OrderSide, OrderType
from backend.portfolio.position import Position
from backend.engine.events import OrderEvent, FillEvent, CancelEvent
from backend.engine.event_bus import EventBus

logger = logging.getLogger(__name__)


class PaperBroker(AbstractBroker):
    """模拟券商 — 在回测/模拟环境中模拟成交。

    作为 EventBus 上的中间件：
      - 订阅 OrderEvent → 模拟成交流程 → 发布 FillEvent
      - 订阅 CancelEvent → 更新订单状态
    """

    def __init__(self, event_bus: EventBus, initial_capital: float = 100_000.0,
                 commission_rate: float = 0.00025, min_commission: float = 5.0,
                 slippage: float = 0.0):
        self._event_bus = event_bus
        self._capital = initial_capital
        self._available = initial_capital
        self._commission_rate = commission_rate
        self._min_commission = min_commission
        self._slippage = slippage
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._latest_prices: dict[str, float] = {}  # symbol → 最新价

        # 注册到事件总线
        event_bus.subscribe(OrderEvent, self._on_order, priority=20)
        event_bus.subscribe(CancelEvent, self._on_cancel, priority=20)

    # ── AbstractBroker 接口实现 ────────────────────────────

    def submit_order(self, order: Order) -> str:
        """提交订单到模拟环境。"""
        if not order.order_id:
            order.order_id = str(uuid.uuid4())[:8]
        self._orders[order.order_id] = order
        logger.info(f"[Paper] 收到订单: {order.symbol} {order.side.value} "
                    f"{order.quantity}股 @ {order.price or '市价'}")
        return order.order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.transition(OrderStatus.CANCELLED):
                logger.info(f"[Paper] 订单已撤销: {order_id}")
                return True
        return False

    def get_orders(self, **filters) -> list[Order]:
        orders = list(self._orders.values())
        for key, value in filters.items():
            orders = [o for o in orders if getattr(o, key, None) == value]
        return orders

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity != 0]

    def get_account(self) -> dict:
        positions_value = sum(p.market_value for p in self._positions.values())
        return {
            "capital": self._capital,
            "available": self._available,
            "positions_value": positions_value,
            "total_value": self._available + positions_value,
            "commission_rate": self._commission_rate,
        }

    def connect(self, **credentials) -> bool:
        logger.info("[Paper] 模拟券商已就绪（无需真实连接）")
        return True

    def disconnect(self) -> None:
        logger.info("[Paper] 模拟券商已断开")

    # ── 事件处理 ──────────────────────────────────────────

    def _on_order(self, event: OrderEvent):
        """处理订单事件 — 模拟成交。"""
        order_id = self.submit_order(Order(
            order_id=event.order_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type=event.order_type,
            price=event.price,
            strategy_id=event.strategy_id,
        ))

        order = self._orders[order_id]
        order.transition(OrderStatus.SUBMITTED)

        # 获取当前价格
        current_price = self._latest_prices.get(event.symbol)
        if current_price is None:
            order.transition(OrderStatus.REJECTED)
            order.error_message = "无可用行情"
            logger.warning(f"[Paper] 订单被拒绝: {order_id} 无行情")
            return

        # 模拟成交
        fill_price = current_price
        if order.order_type == OrderType.LIMIT and order.price is not None:
            # 限价单：检查是否触及
            if (order.side == OrderSide.BUY and current_price > order.price) or \
               (order.side == OrderSide.SELL and current_price < order.price):
                return  # 未触及限价，等待后续K线
            fill_price = order.price

        # 滑点
        if self._slippage > 0:
            slippage_amount = fill_price * self._slippage
            if order.side == OrderSide.BUY:
                fill_price += slippage_amount
            else:
                fill_price -= slippage_amount

        # 手续费
        trade_amount = fill_price * order.quantity
        commission = max(trade_amount * self._commission_rate, self._min_commission)

        # 检查资金
        if order.side == OrderSide.BUY:
            required = trade_amount + commission
            if required > self._available:
                # 部分成交
                max_qty = int(self._available / (fill_price * (1 + self._commission_rate)) / 100) * 100
                if max_qty <= 0:
                    order.transition(OrderStatus.REJECTED)
                    order.error_message = "资金不足"
                    return
                order.filled_qty = float(max_qty)
                order.quantity = float(max_qty)
                trade_amount = fill_price * order.quantity
                commission = max(trade_amount * self._commission_rate, self._min_commission)

        order.filled_qty = order.quantity
        order.filled_price = fill_price
        order.commission = commission
        order.transition(OrderStatus.FILLED)

        # 更新资金
        if order.side == OrderSide.BUY:
            self._available -= (trade_amount + commission)
        else:
            self._available += (trade_amount - commission)

        logger.info(f"[Paper] 成交: {order.symbol} {order.side.value} "
                    f"{order.quantity}股 @ {fill_price:.2f} 手续费 {commission:.2f}")

        # 发布成交事件
        self._event_bus.publish(FillEvent(
            order_id=order.order_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.filled_qty,
            price=fill_price,
            commission=commission,
        ))

    def _on_cancel(self, event: CancelEvent):
        self.cancel_order(event.order_id)

    # ── 内部方法 ──────────────────────────────────────────

    def update_price(self, symbol: str, price: float):
        """更新最新价格（由数据源/回测引擎调用）。"""
        self._latest_prices[symbol] = price
        # 同步更新持仓的当前价格
        if symbol in self._positions:
            self._positions[symbol].update_price(price)

    def get_price(self, symbol: str) -> float:
        return self._latest_prices.get(symbol, 0.0)
