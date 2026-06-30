"""净值管理 API 路由"""

from flask import Blueprint, jsonify, request, g
from backend.core.database import get_connection
from backend.api.middleware import login_required

nav_bp = Blueprint("nav", __name__, url_prefix="/api/nav")


def _get_total_shares() -> float:
    """计算当前总份额 = 各参与方初始份额 + 所有转账的份额变化"""
    with get_connection() as conn:
        cur = conn.cursor()
        # 初始份额总和
        cur.execute("SELECT COALESCE(SUM(initial_shares), 0) FROM nav_parties")
        initial = cur.fetchone()[0] or 0
        # 转账份额变化总和
        cur.execute("SELECT COALESCE(SUM(shares_delta), 0) FROM nav_transfers")
        transfers = cur.fetchone()[0] or 0
    return initial + transfers


def _get_current_nav(total_asset: float = None) -> dict:
    """获取当前净值信息"""
    total_shares = _get_total_shares()
    if total_shares == 0:
        return {"nav": 1.0, "total_asset": 0, "total_shares": 0}

    if total_asset is None:
        # 获取最新的总资产
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT total_asset FROM nav_records ORDER BY record_date DESC LIMIT 1")
            row = cur.fetchone()
            total_asset = row["total_asset"] if row else 0

    nav = total_asset / total_shares if total_shares > 0 else 1.0
    return {
        "nav": round(nav, 4),
        "total_asset": round(total_asset, 2),
        "total_shares": round(total_shares, 2)
    }


def _get_party_shares(party_code: str) -> float:
    """获取指定参与方的当前份额"""
    with get_connection() as conn:
        cur = conn.cursor()
        # 初始份额
        cur.execute("SELECT COALESCE(initial_shares, 0) FROM nav_parties WHERE code = ?", (party_code,))
        row = cur.fetchone()
        initial = row[0] if row else 0
        # 转账份额变化
        cur.execute(
            "SELECT COALESCE(SUM(shares_delta), 0) FROM nav_transfers WHERE party_code = ?",
            (party_code,)
        )
        transfers = cur.fetchone()[0] or 0
    return initial + transfers


# ── 参与方管理 ────────────────────────────────────────────

@nav_bp.route("/parties", methods=["GET"])
@login_required
def list_parties():
    """获取所有参与方列表"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM nav_parties ORDER BY code")
        parties = [dict(r) for r in cur.fetchall()]

    # 计算当前权益
    nav_info = _get_current_nav()
    result = []
    for p in parties:
        shares = _get_party_shares(p["code"])
        equity = shares * nav_info["nav"]
        result.append({
            **p,
            "current_shares": round(shares, 2),
            "nav": nav_info["nav"],
            "equity": round(equity, 2),
            "profit": round(equity - (p["initial_shares"] or 0), 2)
        })
    return jsonify(result)


@nav_bp.route("/parties/init", methods=["POST"])
@login_required
def init_parties():
    """初始化参与方（设置初始份额）"""
    data = request.json
    parties = data.get("parties", [])

    with get_connection() as conn:
        cur = conn.cursor()
        for p in parties:
            cur.execute("""
                INSERT OR REPLACE INTO nav_parties (code, name, description, initial_shares)
                VALUES (?, ?, ?, ?)
            """, (p["code"], p["name"], p.get("description", ""), p.get("initial_shares", 0)))

    return jsonify({"success": True, "parties_count": len(parties)})


# ── 资金转账 ──────────────────────────────────────────────

@nav_bp.route("/transfers", methods=["GET"])
@login_required
def list_transfers():
    """获取转账记录列表"""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)
    party = request.args.get("party")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    offset = (page - 1) * page_size

    with get_connection() as conn:
        cur = conn.cursor()

        # 构建查询条件
        where_clauses = []
        params = []
        if party:
            where_clauses.append("party_code = ?")
            params.append(party)
        if start_date:
            where_clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("date <= ?")
            params.append(end_date)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # 总数
        cur.execute(f"SELECT COUNT(*) FROM nav_transfers WHERE {where_sql}", params)
        total = cur.fetchone()[0]

        # 分页数据
        cur.execute(f"""
            SELECT t.*, p.name as party_name
            FROM nav_transfers t
            LEFT JOIN nav_parties p ON t.party_code = p.code
            WHERE {where_sql}
            ORDER BY t.date DESC, t.id DESC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])

        transfers = [dict(r) for r in cur.fetchall()]

    return jsonify({
        "transfers": transfers,
        "total": total,
        "page": page,
        "page_size": page_size
    })


@nav_bp.route("/transfers", methods=["POST"])
@login_required
def create_transfer():
    """新增转账记录"""
    data = request.json
    date = data.get("date")
    party_code = data.get("party_code")
    amount = float(data.get("amount", 0))
    direction = data.get("direction", "IN")  # IN 或 OUT
    note = data.get("note", "")

    if not date or not party_code or amount <= 0:
        return jsonify({"error": "Invalid parameters"}), 400

    # 获取当前净值（用于计算份额）
    nav_info = _get_current_nav()

    # 计算份额变化：入金 = amount / nav，出金 = -amount / nav
    if direction == "IN":
        shares_delta = amount / nav_info["nav"]
    else:
        shares_delta = -amount / nav_info["nav"]

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO nav_transfers (date, party_code, amount, direction, nav_at_time, shares_delta, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date, party_code, amount, direction, nav_info["nav"], shares_delta, note))

        transfer_id = cur.lastrowid

    return jsonify({
        "success": True,
        "transfer_id": transfer_id,
        "nav_at_time": nav_info["nav"],
        "shares_delta": round(shares_delta, 2)
    })


@nav_bp.route("/transfers/<int:transfer_id>", methods=["DELETE"])
@login_required
def delete_transfer(transfer_id):
    """删除转账记录"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM nav_transfers WHERE id = ?", (transfer_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "Transfer not found"}), 404

    return jsonify({"success": True})


# ── 净值计算 ──────────────────────────────────────────────

@nav_bp.route("/current", methods=["GET"])
@login_required
def get_current_nav():
    """获取当前净值及各方权益"""
    nav_info = _get_current_nav()

    # 各方权益
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM nav_parties ORDER BY code")
        parties = [dict(r) for r in cur.fetchall()]

    party_equities = []
    for p in parties:
        shares = _get_party_shares(p["code"])
        equity = shares * nav_info["nav"]
        party_equities.append({
            "code": p["code"],
            "name": p["name"],
            "initial_shares": p["initial_shares"],
            "current_shares": round(shares, 2),
            "equity": round(equity, 2),
            "profit": round(equity - (p["initial_shares"] or 0), 2)
        })

    return jsonify({
        **nav_info,
        "parties": party_equities
    })


@nav_bp.route("/calculate", methods=["POST"])
@login_required
def calculate_nav():
    """手动输入总资产，计算并记录净值"""
    data = request.json
    total_asset = float(data.get("total_asset", 0))
    record_date = data.get("record_date")
    note = data.get("note", "")

    if total_asset <= 0:
        return jsonify({"error": "Invalid total_asset"}), 400

    total_shares = _get_total_shares()
    nav = total_asset / total_shares if total_shares > 0 else 1.0

    # 保存净值记录
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO nav_records (record_date, total_asset, total_shares, nav, note)
            VALUES (?, ?, ?, ?, ?)
        """, (record_date, total_asset, total_shares, nav, note))

    return jsonify({
        "success": True,
        "record_date": record_date,
        "total_asset": round(total_asset, 2),
        "total_shares": round(total_shares, 2),
        "nav": round(nav, 4)
    })


@nav_bp.route("/history", methods=["GET"])
@login_required
def get_nav_history():
    """获取净值历史记录"""
    days = request.args.get("days", 90, type=int)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM nav_records
            ORDER BY record_date DESC
            LIMIT ?
        """, (days,))

        records = [dict(r) for r in cur.fetchall()]

    return jsonify(records)


# ── 持仓快照 ──────────────────────────────────────────────

@nav_bp.route("/positions", methods=["GET"])
@login_required
def list_positions():
    """获取持仓快照列表"""
    date = request.args.get("date")  # 可选，默认为最新

    with get_connection() as conn:
        cur = conn.cursor()

        if date:
            cur.execute("""
                SELECT * FROM nav_positions WHERE snapshot_date = ?
                ORDER BY symbol
            """, (date,))
        else:
            # 获取最新日期
            cur.execute("SELECT snapshot_date FROM nav_positions ORDER BY snapshot_date DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return jsonify([])

            cur.execute("""
                SELECT * FROM nav_positions WHERE snapshot_date = ?
                ORDER BY symbol
            """, (row["snapshot_date"],))

        positions = [dict(r) for r in cur.fetchall()]

    return jsonify(positions)


@nav_bp.route("/positions", methods=["POST"])
@login_required
def create_position():
    """新增持仓记录"""
    data = request.json
    snapshot_date = data.get("snapshot_date")
    positions = data.get("positions", [])

    if not snapshot_date or not positions:
        return jsonify({"error": "Invalid parameters"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        for p in positions:
            cur.execute("""
                INSERT OR REPLACE INTO nav_positions
                (snapshot_date, symbol, name, quantity, avg_cost, current_price, market_value, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_date,
                p.get("symbol", ""),
                p.get("name", ""),
                p.get("quantity", 0),
                p.get("avg_cost", 0),
                p.get("current_price", 0),
                p.get("market_value", 0),
                p.get("source", "manual")
            ))

    return jsonify({"success": True, "positions_count": len(positions)})


@nav_bp.route("/positions/dates", methods=["GET"])
@login_required
def list_position_dates():
    """获取所有持仓快照的日期列表"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT snapshot_date FROM nav_positions
            ORDER BY snapshot_date DESC
        """)
        dates = [r["snapshot_date"] for r in cur.fetchall()]

    return jsonify(dates)


# ── 提取计算 ──────────────────────────────────────────────

@nav_bp.route("/withdraw/preview", methods=["POST"])
@login_required
def preview_withdraw():
    """预览提取金额"""
    data = request.json
    party_code = data.get("party_code")
    target_amount = data.get("target_amount")  # 想要提取的金额
    target_shares = data.get("target_shares")  # 或者指定份额

    if not party_code:
        return jsonify({"error": "party_code is required"}), 400

    nav_info = _get_current_nav()
    party_shares = _get_party_shares(party_code)
    party_equity = party_shares * nav_info["nav"]

    result = {
        "party_code": party_code,
        "nav": nav_info["nav"],
        "party_total_shares": round(party_shares, 2),
        "party_total_equity": round(party_equity, 2)
    }

    if target_amount is not None:
        shares_needed = float(target_amount) / nav_info["nav"]
        result["target_amount"] = target_amount
        result["shares_to_redeem"] = round(shares_needed, 2)
        result["can_withdraw"] = shares_needed <= party_shares
    elif target_shares is not None:
        amount_to_receive = float(target_shares) * nav_info["nav"]
        result["target_shares"] = target_shares
        result["amount_to_receive"] = round(amount_to_receive, 2)
        result["can_withdraw"] = float(target_shares) <= party_shares

    return jsonify(result)


@nav_bp.route("/withdraw/confirm", methods=["POST"])
@login_required
def confirm_withdraw():
    """确认提取，生成出金记录"""
    data = request.json
    party_code = data.get("party_code")
    target_amount = data.get("target_amount")
    target_shares = data.get("target_shares")
    date = data.get("date")
    note = data.get("note", "")

    if not party_code or not date:
        return jsonify({"error": "party_code and date are required"}), 400

    if target_amount is None and target_shares is None:
        return jsonify({"error": "target_amount or target_shares is required"}), 400

    nav_info = _get_current_nav()

    if target_amount is not None:
        shares_delta = -float(target_amount) / nav_info["nav"]
    else:
        shares_delta = -float(target_shares)
        target_amount = abs(shares_delta * nav_info["nav"])

    with get_connection() as conn:
        cur = conn.cursor()
        # 生成出金记录
        cur.execute("""
            INSERT INTO nav_transfers (date, party_code, amount, direction, nav_at_time, shares_delta, note)
            VALUES (?, ?, ?, 'OUT', ?, ?, ?)
        """, (date, party_code, target_amount, nav_info["nav"], shares_delta, note))

        transfer_id = cur.lastrowid

    return jsonify({
        "success": True,
        "transfer_id": transfer_id,
        "target_amount": round(target_amount, 2),
        "shares_redeemed": round(abs(shares_delta), 2)
    })