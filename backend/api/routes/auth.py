from flask import Blueprint, request, jsonify
from backend.core.database import authenticate_user
from backend.api.middleware import generate_token

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "")
    password = data.get("password", "")
    if authenticate_user(username, password):
        token = generate_token(username)
        return jsonify({"success": True, "token": token}), 200
    return jsonify({"success": False, "message": "Invalid credentials"}), 401
