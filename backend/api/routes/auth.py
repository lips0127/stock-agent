from flask import Blueprint, request, jsonify
from backend.core.database import authenticate_user
from backend.api.middleware import generate_token, login_rate_limit

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/login", methods=["POST"])
@login_rate_limit
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return jsonify({"success": False, "message": "请输入用户名和密码"}), 400
    if authenticate_user(username, password):
        token = generate_token(username)
        return jsonify({"success": True, "token": token}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401
