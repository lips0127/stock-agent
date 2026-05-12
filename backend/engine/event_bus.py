"""
事件总线 — 内存 pub/sub 实现，预留 Redis 升级接口。

特性：
  - 基于事件类型层级匹配（isinstance），订阅父类可收到所有子类事件
  - 优先级队列（数字越小越先执行）
  - 线程安全
  - 同步/异步两种分发模式
  - 事件日志记录（可选）
"""

from __future__ import annotations
import threading
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any

from backend.engine.events import StartEvent, StopEvent

logger = logging.getLogger(__name__)

Handler = Callable[[Any], None]


class IEventBus(ABC):
    """事件总线抽象接口 — 为后续升级到 Redis/RabbitMQ 提供契约。"""

    @abstractmethod
    def subscribe(self, event_type: type, handler: Handler, priority: int = 0) -> None:
        """订阅事件类型。priority 越小越先执行。"""
        ...

    @abstractmethod
    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        """取消订阅。"""
        ...

    @abstractmethod
    def publish(self, event: Any) -> None:
        """同步分发事件给所有匹配的 handler。"""
        ...

    @abstractmethod
    def publish_async(self, event: Any) -> None:
        """异步分发事件（使用线程池）。"""
        ...


class EventBus(IEventBus):
    """基于内存的事件总线实现。

    使用 isinstance 匹配事件类型层级：
      - 订阅 MarketEvent → 收到 BarEvent 和 TickEvent
      - 订阅 BarEvent → 只收到 BarEvent

    线程安全：所有操作在同一个锁下执行。
    """

    def __init__(self, max_workers: int = 4, log_events: bool = False):
        self._subscribers: dict[type, list[tuple[int, Handler]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="evt")
        self._running = False
        self._log_events = log_events

    # ── 订阅管理 ──────────────────────────────────────────

    def subscribe(self, event_type: type, handler: Handler, priority: int = 0) -> None:
        with self._lock:
            self._subscribers[event_type].append((priority, handler))
            self._subscribers[event_type].sort(key=lambda x: x[0])
        logger.debug(f"订阅事件: {event_type.__name__} priority={priority}")

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        with self._lock:
            self._subscribers[event_type] = [
                (p, h) for p, h in self._subscribers[event_type] if h is not handler
            ]
            if not self._subscribers[event_type]:
                del self._subscribers[event_type]

    # ── 事件分发 ──────────────────────────────────────────

    def publish(self, event: Any) -> None:
        """同步分发：逐个调用匹配的 handler。"""
        if self._log_events:
            logger.debug(f"EVENT: {type(event).__name__} {event}")
        with self._lock:
            subscribers = dict(self._subscribers)  # 快照
        for event_type, handlers in subscribers.items():
            if isinstance(event, event_type):
                for priority, handler in handlers:
                    try:
                        handler(event)
                    except Exception:
                        logger.error(f"事件处理异常: {type(event).__name__}", exc_info=True)

    def publish_async(self, event: Any) -> None:
        """异步分发：在线程池中并发执行 handler。"""
        if self._log_events:
            logger.debug(f"ASYNC EVENT: {type(event).__name__} {event}")
        with self._lock:
            subscribers = dict(self._subscribers)
        for event_type, handlers in subscribers.items():
            if isinstance(event, event_type):
                for _, handler in handlers:
                    self._executor.submit(self._safe_call, handler, event)

    @staticmethod
    def _safe_call(handler: Handler, event: Any):
        try:
            handler(event)
        except Exception:
            logger.error(f"异步事件处理异常: {type(event).__name__}", exc_info=True)

    # ── 生命周期 ──────────────────────────────────────────

    def start(self):
        """启动事件总线。"""
        self._running = True
        logger.info("EventBus 已启动")
        self.publish(StartEvent())

    def stop(self):
        """停止事件总线，等待线程池关闭。"""
        self.publish(StopEvent())
        self._running = False
        self._executor.shutdown(wait=True)
        logger.info("EventBus 已停止")

    @property
    def is_running(self) -> bool:
        return self._running
