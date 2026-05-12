"""
交易时钟 — 提供统一的时间源。

三种时钟模式：
  RealClock      — 使用系统实际时间（实盘交易）
  ReplayClock    — 回放历史时间（回测），时间由外部推动
  SimulationClock — 模拟时钟，可加速/减速（模拟交易）
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """时钟抽象基类。"""

    @abstractmethod
    def now(self) -> datetime:
        """返回当前时间。"""
        ...

    @abstractmethod
    def is_market_open(self) -> bool:
        """当前是否在交易时段。"""
        ...


class RealClock(Clock):
    """系统实时时钟。"""

    def now(self) -> datetime:
        return datetime.now()

    def is_market_open(self) -> bool:
        now = self.now()
        if now.weekday() >= 5:  # 周末
            return False
        t = now.hour * 60 + now.minute
        # A股交易时段: 9:30-11:30, 13:00-15:00
        return (570 <= t < 690) or (780 <= t < 900)


class ReplayClock(Clock):
    """回放时钟 — 用于回测，时间由外部推进。"""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, dt: datetime):
        """推进到指定时间（只能向前）。"""
        if dt >= self._now:
            self._now = dt

    def is_market_open(self) -> bool:
        return True  # 回测中始终认为市场开放


class SimulationClock(Clock):
    """模拟时钟 — 可控制时间流速。"""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime.now()
        self._speed = 1.0       # 时间倍速
        self._paused = False
        self._last_real = datetime.now()

    def now(self) -> datetime:
        if not self._paused:
            elapsed = (datetime.now() - self._last_real).total_seconds()
            self._now += type(self._now).__new__(
                type(self._now),
                microseconds=int(elapsed * self._speed * 1_000_000),
            )
            self._last_real = datetime.now()
        return self._now

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float):
        self._speed = max(0.0, value)

    def pause(self):
        self._paused = True

    def resume(self):
        self._last_real = datetime.now()
        self._paused = False

    def is_market_open(self) -> bool:
        now = self.now()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return (570 <= t < 690) or (780 <= t < 900)
