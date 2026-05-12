"""
回测引擎 — 基于事件驱动的历史数据回放。

核心流程：
  1. 加载历史数据（按时间排序）
  2. 初始化策略 → 通过 EventBus 连接所有组件
  3. 按时间顺序重放 Bar → 策略触发 → 订单 → 模拟成交 → 更新持仓
  4. 计算绩效指标 → 输出回测报告

回测和实盘使用完全相同的策略代码（仅 DataProvider 和 Clock 不同）。
"""

from __future__ import annotations
import uuid
import logging
import time as time_module
from datetime import datetime
from collections import defaultdict

from backend.engine.event_bus import EventBus
from backend.engine.clock import ReplayClock
from backend.engine.events import BarEvent, TickEvent, StartEvent, StopEvent, FillEvent
from backend.data.historical import HistoricalDataProvider
from backend.execution.paper_broker import PaperBroker
from backend.portfolio.manager import PortfolioManager
from backend.strategy.base import BaseStrategy
from backend.strategy.context import StrategyContext
from backend.backtest.metrics import calculate_metrics

logger = logging.getLogger(__name__)


class BacktestEngine:
    """事件驱动的回测引擎。

    用法:
        from backend.strategy.examples.ma_cross import MACrossStrategy

        engine = BacktestEngine(
            strategy_class=MACrossStrategy,
            symbols=["000001"],
            start="2024-01-01",
            end="2024-12-31",
            initial_capital=100000,
            strategy_params={"fast": 5, "slow": 20},
        )
        report = engine.run()
        print(f"收益率: {report['total_return']:.2%}")
        print(f"夏普: {report['sharpe_ratio']:.2f}")
        print(f"最大回撤: {report['max_drawdown']:.2%}")
    """

    def __init__(
        self,
        strategy_class: type[BaseStrategy],
        symbols: list[str],
        start: str | datetime,
        end: str | datetime,
        initial_capital: float = 100_000.0,
        strategy_params: dict | None = None,
        commission_rate: float = 0.00025,
        slippage: float = 0.0,
        timeframe: str = "1d",
    ):
        self.strategy_class = strategy_class
        self.symbols = symbols
        self.start = _to_datetime(start)
        self.end = _to_datetime(end)
        self.initial_capital = initial_capital
        self.strategy_params = strategy_params or {}
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.timeframe = timeframe

        # 运行时组件
        self._event_bus: EventBus | None = None
        self._clock: ReplayClock | None = None
        self._data: HistoricalDataProvider | None = None
        self._broker: PaperBroker | None = None
        self._portfolio: PortfolioManager | None = None
        self._strategy: BaseStrategy | None = None

        # 回测记录
        self._daily_values: list[float] = []
        self._trades: list[dict] = []
        self._signals: list[dict] = []

    # ── 运行回测 ──────────────────────────────────────────

    def run(self) -> dict:
        """执行回测，返回绩效报告。"""
        t0 = time_module.time()

        self._setup()
        bars_by_symbol = self._load_data()

        if not bars_by_symbol:
            logger.error("回测数据为空，无法运行")
            return {}

        # 按时间顺序合并所有股票的K线
        all_bars = self._merge_and_sort_bars(bars_by_symbol)

        logger.info(f"回测开始: {self.strategy_class.__name__} "
                    f"{self.symbols} {len(all_bars)} 根K线")

        self._event_bus.publish(StartEvent())
        self._strategy.on_start()

        # 记录初始净值
        self._record_snapshot(self._clock.now(), force=True)

        # 逐根K线回放
        last_record_date = None
        for bar in all_bars:
            self._clock.advance(bar.bar_time)
            self._broker.update_price(bar.symbol, bar.close)
            self._portfolio.update_price(bar.symbol, bar.close)

            self._event_bus.publish(BarEvent(
                symbol=bar.symbol,
                timestamp=bar.bar_time,
                timeframe=bar.timeframe,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                amount=bar.amount,
            ))

            # 每日记录一次组合净值（用第一个 symbol 的 bar 作为标记）
            bar_date = bar.bar_time.date()
            if bar_date != last_record_date:
                self._record_snapshot(bar.bar_time)
                last_record_date = bar_date

        # 最终快照
        self._record_snapshot(self._clock.now(), force=True)

        self._strategy.on_stop()
        self._event_bus.publish(StopEvent())

        elapsed = time_module.time() - t0
        logger.info(f"回测完成: 耗时 {elapsed:.1f}s")

        return self._generate_report()

    # ── 内部方法 ──────────────────────────────────────────

    def _setup(self):
        """初始化所有组件并组装事件流。"""
        self._event_bus = EventBus(max_workers=1, log_events=False)
        self._clock = ReplayClock(start=self.start)

        self._data = HistoricalDataProvider()
        self._portfolio = PortfolioManager(self._event_bus, self.initial_capital)
        self._broker = PaperBroker(
            self._event_bus,
            initial_capital=self.initial_capital,
            commission_rate=self.commission_rate,
            slippage=self.slippage,
        )

        # 创建策略
        self._strategy = self.strategy_class(
            params=self.strategy_params,
            symbols=self.symbols,
            timeframes=[self.timeframe],
        )

        strategy_id = f"{self.strategy_class.__name__}_{uuid.uuid4().hex[:6]}"
        context = StrategyContext(
            strategy_id=strategy_id,
            event_bus=self._event_bus,
            clock=self._clock,
            data_provider=self._data,
            portfolio_manager=self._portfolio,
        )
        self._strategy.set_context(context)
        self._strategy.on_init()

        # 将策略的方法注册到事件总线
        self._event_bus.subscribe(BarEvent, self._strategy.on_bar, priority=50)
        self._event_bus.subscribe(TickEvent, self._strategy.on_tick, priority=50)

        # 监听成交事件，记录交易
        self._event_bus.subscribe(FillEvent, self._on_fill, priority=50)

    def _load_data(self) -> dict[str, list]:
        """加载所有股票的历史数据。"""
        bars_by_symbol = {}
        for symbol in self.symbols:
            bars = self._data.get_bars(symbol, self.timeframe, self.start, self.end)
            if bars:
                bars_by_symbol[symbol] = bars
                logger.info(f"加载 {symbol}: {len(bars)} 根 {self.timeframe} K线")
            else:
                logger.warning(f"无历史数据: {symbol}")
        return bars_by_symbol

    @staticmethod
    def _merge_and_sort_bars(bars_by_symbol: dict[str, list]) -> list:
        """将多只股票的K线按时间合并排序。"""
        all_bars = []
        for bars in bars_by_symbol.values():
            all_bars.extend(bars)
        all_bars.sort(key=lambda b: b.bar_time)
        return all_bars

    def _on_fill(self, fill: FillEvent):
        """记录成交（用于回测统计）。"""
        self._trades.append({
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "quantity": fill.quantity,
            "price": fill.price,
            "commission": fill.commission,
            "time": fill.timestamp.isoformat(),
            "pnl": 0.0,  # 后续在平仓时计算
        })

    def _record_snapshot(self, ts: datetime, force: bool = False):
        """记录组合净值快照。"""
        if self._portfolio is None:
            return
        value = self._portfolio.get_total_value()
        if not self._daily_values or force or value != (self._daily_values[-1] if self._daily_values else None):
            self._daily_values.append(value)

    def _generate_report(self) -> dict:
        """生成回测报告。"""
        if not self._daily_values:
            return {"error": "无回测数据"}

        trading_days = len(self._daily_values)

        # 尝试为每笔交易计算盈亏（简化：买入后下一次卖出配对）
        pnl = 0.0
        pending_buy: dict[str, list[dict]] = defaultdict(list)  # symbol → buy trades
        for trade in self._trades:
            if trade["side"] == "BUY":
                pending_buy[trade["symbol"]].append(trade)
            else:
                if pending_buy.get(trade["symbol"]):
                    buy = pending_buy[trade["symbol"]].pop(0)
                    pnl = (trade["price"] - buy["price"]) * trade["quantity"] \
                          - buy["commission"] - trade["commission"]
                    trade["pnl"] = pnl

        metrics = calculate_metrics(
            self._daily_values,
            self._trades,
            self.initial_capital,
            trading_days,
        )

        return {
            "strategy": self.strategy_class.__name__,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "start": self.start.strftime("%Y-%m-%d"),
            "end": self.end.strftime("%Y-%m-%d"),
            **metrics,
            "trades": self._trades,
            "equity_curve": self._daily_values,
        }


def _to_datetime(d: str | datetime) -> datetime:
    if isinstance(d, datetime):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d")
