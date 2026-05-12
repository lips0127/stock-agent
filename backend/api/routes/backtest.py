"""回测 API — 运行回测、查看历史结果。"""

import json
import uuid
import threading
import logging
from datetime import date

from flask import Blueprint, request, jsonify

from backend.core.database import get_connection
from backend.api.middleware import login_required
from backend.strategy.registry import get as get_strategy_cls
from backend.backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)

backtest_bp = Blueprint("backtest", __name__)


@backtest_bp.route("/api/backtest/run", methods=["POST"])
@login_required
def run_backtest():
    """运行回测（异步），返回 run_id 供轮询。"""
    body = request.get_json(silent=True) or {}
    strategy_name = body.get("strategy_name")
    symbols = body.get("symbols", [])
    start = body.get("start", "2024-01-01")
    end = body.get("end", "2024-12-31")
    initial_capital = body.get("initial_capital", 100_000)
    strategy_params = body.get("params", {})
    commission_rate = body.get("commission_rate", 0.00025)
    slippage = body.get("slippage", 0.0)
    timeframe = body.get("timeframe", "1d")

    if not strategy_name:
        return jsonify({"error": "请指定 strategy_name"}), 400
    if not symbols:
        return jsonify({"error": "请指定 symbols（至少一只股票）"}), 400

    strategy_cls = get_strategy_cls(strategy_name)
    if strategy_cls is None:
        return jsonify({"error": f"策略 '{strategy_name}' 未注册"}), 404

    run_id = str(uuid.uuid4())[:8]
    params_json = json.dumps(strategy_params, ensure_ascii=False)

    # 先在 DB 中创建一条 running 状态的记录
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO backtest_runs
               (id, strategy_name, start_date, end_date, initial_capital,
                params_json, status)
               VALUES (?, ?, ?, ?, ?, ?, 'running')""",
            (run_id, strategy_name, start, end, initial_capital, params_json),
        )

    def _run():
        try:
            engine = BacktestEngine(
                strategy_class=strategy_cls,
                symbols=symbols,
                start=start,
                end=end,
                initial_capital=initial_capital,
                strategy_params=strategy_params,
                commission_rate=commission_rate,
                slippage=slippage,
                timeframe=timeframe,
            )
            report = engine.run()

            if not report or "error" in report:
                error_msg = report.get("error", "回测数据为空") if report else "回测数据为空"
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE backtest_runs SET status='failed', error_message=? WHERE id=?",
                        (error_msg, run_id),
                    )
                return

            # 更新 backtest_runs
            with get_connection() as conn:
                conn.execute(
                    """UPDATE backtest_runs SET
                       status='completed',
                       final_value=?,
                       total_return=?,
                       annual_return=?,
                       sharpe_ratio=?,
                       max_drawdown=?,
                       win_rate=?,
                       total_trades=?
                       WHERE id=?""",
                    (
                        report.get("final_value"),
                        report.get("total_return"),
                        report.get("annual_return"),
                        report.get("sharpe_ratio"),
                        report.get("max_drawdown_pct"),
                        report.get("win_rate"),
                        report.get("total_trades"),
                        run_id,
                    ),
                )

                # 保存交易明细
                for t in report.get("trades", []):
                    conn.execute(
                        """INSERT INTO backtest_trades
                           (backtest_id, symbol, side, entry_time, entry_price,
                            quantity, pnl, pnl_pct)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            t.get("symbol"),
                            t.get("side"),
                            t.get("time"),
                            t.get("price"),
                            t.get("quantity"),
                            t.get("pnl"),
                            t.get("pnl", 0) / (abs(t.get("price", 1)) * t.get("quantity", 1))
                            if t.get("price") and t.get("quantity") else 0,
                        ),
                    )

            logger.info(f"回测完成: run_id={run_id}")

        except Exception as e:
            logger.error(f"回测异常 (run_id={run_id}): {e}", exc_info=True)
            with get_connection() as conn:
                conn.execute(
                    "UPDATE backtest_runs SET status='failed', error_message=? WHERE id=?",
                    (str(e), run_id),
                )

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "回测已启动", "run_id": run_id}), 202


@backtest_bp.route("/api/backtest/runs", methods=["GET"])
@login_required
def list_runs():
    """列出历史回测记录。"""
    limit = request.args.get("limit", 20, type=int)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            (min(limit, 100),),
        )
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@backtest_bp.route("/api/backtest/runs/<run_id>", methods=["GET"])
@login_required
def get_run(run_id):
    """获取单次回测详情（含交易明细）。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "回测记录不存在"}), 404
        run = dict(row)

        cur.execute(
            "SELECT * FROM backtest_trades WHERE backtest_id = ? ORDER BY id",
            (run_id,),
        )
        trades = [dict(r) for r in cur.fetchall()]

    run["trades"] = trades
    run["params"] = json.loads(run.get("params_json", "{}")) if run.get("params_json") else {}
    return jsonify(run)
