"""知乎大V监控 API 路由（v2, 2026-06-10 — TaskRunner 重构）。"""

import json
import logging
import threading
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request

from backend.core.database import (
    get_zhihu_users, get_zhihu_user_by_token, add_zhihu_user,
    delete_zhihu_user, update_zhihu_user,
    get_zhihu_posts, get_zhihu_post_by_id,
    get_zhihu_subscriptions, add_zhihu_subscription,
    update_zhihu_subscription, delete_zhihu_subscription,
    get_zhihu_timeline_posts,
    get_zhihu_smtp_settings, get_zhihu_email_logs,
)
from backend.services.zhihu_service import (
    extract_url_token, refresh_user, refresh_all_enabled,
    fetch_user_profile,
)
from backend.services.zhihu_analyzer import analyze_post, analyze_new_posts
from backend.services.email_service import (
    send_email, get_active_settings, save_settings, mask_password,
    notify_new_analysis,
)
from backend.api.middleware import login_required
from backend.core.task_runner import TaskRunner

zhihu_bp = Blueprint("zhihu", __name__)
logger = logging.getLogger(__name__)


# ── 用户管理 ──────────────────────────────────────────

@zhihu_bp.route("/api/zhihu/users", methods=["GET"])
@login_required
def list_users():
    """监控用户列表 + 一些统计字段。"""
    users = get_zhihu_users()
    from backend.core.database import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        for u in users:
            cur.execute(
                """SELECT COUNT(*) AS c FROM zhihu_posts p
                   LEFT JOIN zhihu_analyses a ON a.post_id = p.post_id
                   WHERE p.url_token=? AND a.id IS NULL""",
                (u["url_token"],),
            )
            u["unanalyzed_count"] = cur.fetchone()["c"] or 0
            cur.execute(
                "SELECT COUNT(*) AS c FROM zhihu_posts WHERE url_token=?",
                (u["url_token"],),
            )
            u["post_count"] = cur.fetchone()["c"] or 0
            if u["post_count"] == 0 and not u.get("last_checked_at"):
                u["status_kind"] = "never_scanned"
            elif u.get("last_error"):
                u["status_kind"] = "error"
            elif u["post_count"] == 0:
                u["status_kind"] = "no_posts"
            else:
                u["status_kind"] = "ok"
    return jsonify(users)


@zhihu_bp.route("/api/zhihu/users", methods=["POST"])
@login_required
def add_user():
    """新增知乎用户监控。"""
    body = request.get_json(silent=True) or {}
    raw = (body.get("url") or body.get("url_token") or "").strip()
    if not raw:
        return jsonify({"error": "请提供知乎个人主页 URL 或 url_token"}), 400

    token = extract_url_token(raw)
    if not token:
        return jsonify({"error": "无法解析 url_token"}), 400

    profile = None
    fetch_failed = False
    try:
        profile = fetch_user_profile(token)
    except Exception as e:
        logger.warning(f"抓取知乎用户资料失败 {token}: {e}")
        fetch_failed = True

    user = add_zhihu_user(
        url_or_token=token,
        display_name=(profile or {}).get("display_name", ""),
        avatar_url=(profile or {}).get("avatar_url", ""),
        headline=(profile or {}).get("headline", ""),
        follower_count=(profile or {}).get("follower_count", 0),
    )
    if not user:
        return jsonify({"error": "添加失败"}), 500

    if not profile:
        user["_warning"] = (
            "无法立即拉取知乎资料（可能 IP 被限流或 url_token 不正确）。"
            "已加入监控列表，后续抓取时会自动重试。"
            if not fetch_failed
            else f"抓取异常: {fetch_failed}"
        )
    return jsonify(user), 201


@zhihu_bp.route("/api/zhihu/users/<int:user_id>", methods=["DELETE"])
@login_required
def remove_user(user_id):
    ok = delete_zhihu_user(user_id)
    if not ok:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({"message": "已移除"})


@zhihu_bp.route("/api/zhihu/users/<int:user_id>", methods=["PATCH"])
@login_required
def patch_user(user_id):
    body = request.get_json(silent=True) or {}
    allowed = {"enabled", "email_notify"}
    kwargs = {k: body[k] for k in allowed if k in body}
    if "enabled" in kwargs:
        kwargs["enabled"] = 1 if kwargs["enabled"] else 0
    if "email_notify" in kwargs:
        kwargs["email_notify"] = 1 if kwargs["email_notify"] else 0
    ok = update_zhihu_user(user_id, **kwargs)
    if not ok:
        return jsonify({"error": "更新失败或无变化"}), 400
    return jsonify({"message": "已更新"})


@zhihu_bp.route("/api/zhihu/users/<int:user_id>/refresh", methods=["POST"])
@login_required
def refresh_one(user_id):
    """立即刷新该用户。后台线程执行；返回 task_id 供前端轮询 GET /api/tasks/<id>。

    Query params:
        analyze=0  跳过 LLM 分析（仅抓取）
    """
    skip_analyze = request.args.get("analyze", "1") == "0"
    from backend.core.database import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT url_token FROM zhihu_users WHERE id=?", (user_id,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "用户不存在"}), 404
    url_token = row["url_token"]

    task_id = uuid.uuid4().hex

    def _job():
        with TaskRunner(
            kind="zhihu_user_refresh",
            title=f"刷新知乎用户 {url_token}",
            payload={"user_id": user_id, "url_token": url_token, "skip_analyze": skip_analyze},
            task_id=task_id,
        ) as t:
            result = {"new_posts": 0, "errors": [], "fetched": 0}
            try:
                t.milestone(f"开始抓取 {url_token} 的动态...")
                r = refresh_user(url_token, max_pages=2)
                result.update({k: v for k, v in r.items()
                              if k in ("new_posts", "errors", "fetched", "profile")})
                t.set_total(r.get("fetched", 0))

                if r.get("new_posts", 0) > 0 and not skip_analyze:
                    t.milestone(f"抓取到 {r['new_posts']} 条新动态，开始 LLM 分析...")
                    results = analyze_new_posts(
                        url_token=url_token, limit=10,
                        on_progress=lambda done, total: (
                            t.set_total(total), t.progress(done)
                        ),
                    )
                    if results:
                        user = get_zhihu_user_by_token(url_token)
                        display_name = (user or {}).get("display_name") or url_token
                        sent, skipped, msg = notify_new_analysis(
                            url_token, display_name, results
                        )
                        logger.info(f"邮件通知 {url_token}: sent={sent} skipped={skipped} {msg}")
                        result["analyzed"] = len(results)
                elif skip_analyze:
                    t.milestone(f"仅抓取完成（跳过分析），共 {r.get('fetched', 0)} 条")
                t.complete(result=result)
            except Exception as e:
                logger.error(f"知乎刷新后台任务失败 {url_token}: {e}", exc_info=True)
                result["errors"].append(str(e))
                from backend.services.zhihu_service import update_zhihu_user_by_token
                update_zhihu_user_by_token(url_token, last_error=f"refresh exception: {str(e)[:150]}")
                t.fail(str(e))

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"message": "已启动刷新任务", "task_id": task_id,
                    "user_id": user_id, "url_token": url_token})


@zhihu_bp.route("/api/zhihu/refresh_status/<task_id>", methods=["GET"])
@login_required
def refresh_status(task_id):
    """[deprecated] 请改用 GET /api/tasks/<task_id>。"""
    from backend.core.database import get_task_run
    row = get_task_run(task_id)
    if not row:
        return jsonify({"error": "task 不存在或已过期",
                        "hint": "请改用 GET /api/tasks/<task_id>"}), 404
    return jsonify({
        "deprecated": True,
        "task_id": task_id,
        "status": row.get("status"),
        "result": json.loads(row.get("result_json") or "{}") if row.get("result_json") else None,
        "hint": "请改用 GET /api/tasks/<task_id>",
    })


@zhihu_bp.route("/api/zhihu/analyze_status/<task_id>", methods=["GET"])
@login_required
def analyze_status(task_id):
    """[deprecated] 请改用 GET /api/tasks/<task_id>。"""
    from backend.core.database import get_task_run
    row = get_task_run(task_id)
    if not row:
        return jsonify({"error": "task 不存在或已过期",
                        "hint": "请改用 GET /api/tasks/<task_id>"}), 404
    return jsonify({
        "deprecated": True,
        "task_id": task_id,
        "status": row.get("status"),
        "result": json.loads(row.get("result_json") or "{}") if row.get("result_json") else None,
        "hint": "请改用 GET /api/tasks/<task_id>",
    })


@zhihu_bp.route("/api/zhihu/users/<int:user_id>/analyze_recent", methods=["POST"])
@login_required
def analyze_recent(user_id):
    """批量 LLM 分析该用户最近 N 条动态（含文章/回答/想法）。
    后台线程跑，task_id 供前端轮询 GET /api/tasks/<id>。
    """
    from backend.core.database import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT url_token FROM zhihu_users WHERE id=?", (user_id,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "用户不存在"}), 404
    url_token = row["url_token"]

    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 30))

    task_id = uuid.uuid4().hex

    def _job():
        with TaskRunner(
            kind="zhihu_user_reanalyze",
            title=f"分析知乎用户 {url_token} 动态",
            payload={"user_id": user_id, "url_token": url_token, "limit": limit},
            task_id=task_id,
        ) as t:
            result = {"analyzed": 0, "skipped": 0, "errors": []}

            def on_progress(analyzed, total):
                t.set_total(total)
                t.progress(analyzed)
                if analyzed == 0:
                    t.set_current(f"正在加载 LLM 模型...")
                elif analyzed < total:
                    t.set_current(f"分析第 {analyzed}/{total} 条...")
                else:
                    t.set_current("分析完成，正在保存...")

            try:
                t.milestone(f"开始分析 {url_token} 的最近 {limit} 条动态")
                analysis_results = analyze_new_posts(
                    url_token=url_token, limit=limit, on_progress=on_progress,
                )
                result["analyzed"] = len(analysis_results)
                result["skipped"] = max(0, limit - len(analysis_results))
                if result["analyzed"] == 0 and result["skipped"] > 0:
                    t.milestone("所有动态均已分析，无需重复")
                if analysis_results:
                    try:
                        user = get_zhihu_user_by_token(url_token)
                        if user and user.get("email_notify"):
                            display_name = user.get("display_name") or url_token
                            sent, _, msg = notify_new_analysis(
                                url_token, display_name, analysis_results
                            )
                            result["notified"] = sent
                    except Exception as e:
                        logger.warning(f"分析后通知失败 {url_token}: {e}")
                t.complete(result=result)
            except Exception as e:
                logger.error(f"知乎批量分析后台任务失败 {url_token}: {e}", exc_info=True)
                result["errors"].append(str(e))
                t.fail(str(e))

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"message": "分析任务已启动", "task_id": task_id,
                    "user_id": user_id, "url_token": url_token, "limit": limit})


@zhihu_bp.route("/api/zhihu/users/<int:user_id>/posts", methods=["GET"])
@login_required
def list_user_posts(user_id):
    from backend.core.database import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT url_token FROM zhihu_users WHERE id=?", (user_id,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "用户不存在"}), 404
    limit = request.args.get("limit", 30, type=int)
    posts = get_zhihu_posts(url_token=row["url_token"], limit=limit)
    for p in posts:
        for f in ("stance_assets", "sectors", "key_points"):
            if p.get(f):
                try:
                    p[f] = json.loads(p[f])
                except (json.JSONDecodeError, TypeError):
                    p[f] = []
            else:
                p[f] = []
    return jsonify(posts)


# ── 时间线报表 ─────────────────────────────────────

@zhihu_bp.route("/api/zhihu/timeline", methods=["GET"])
@login_required
def get_timeline():
    """获取最近 N 天所有大V已分析动态（时间升序，含用户资料）。"""
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 30))
    posts = get_zhihu_timeline_posts(days=days)
    for p in posts:
        for key in ("created_at_original", "analyzed_at", "fetched_at"):
            val = p.get(key)
            if isinstance(val, datetime):
                p[key] = val.isoformat(sep=" ", timespec="seconds")
            elif val is None:
                p[key] = None
    return jsonify(posts)


# ── 动态 / 分析 ─────────────────────────────────────

@zhihu_bp.route("/api/zhihu/posts/<post_id>/analysis", methods=["GET"])
@login_required
def get_analysis(post_id):
    post = get_zhihu_post_by_id(post_id)
    if not post:
        return jsonify({"error": "post 不存在"}), 404
    for f in ("stance_assets", "sectors", "key_points"):
        if post.get(f):
            try:
                post[f] = json.loads(post[f])
            except (json.JSONDecodeError, TypeError):
                post[f] = []
    return jsonify(post)


@zhihu_bp.route("/api/zhihu/posts/<post_id>/reanalyze", methods=["POST"])
@login_required
def reanalyze_post(post_id):
    def _job():
        r = analyze_post(post_id, force=True)
        if r:
            logger.info(f"重分析完成 {post_id}")
            user = get_zhihu_user_by_token(r.get("url_token", ""))
            if user and user.get("email_notify"):
                display_name = user.get("display_name") or user.get("url_token")
                notify_new_analysis(user["url_token"], display_name, [r])

    threading.Thread(target=_job, daemon=True).start()
    return jsonify({"message": "重分析已启动", "post_id": post_id})


# ── 邮件订阅 ───────────────────────────────────────

@zhihu_bp.route("/api/zhihu/subscriptions", methods=["GET"])
@login_required
def list_subs():
    return jsonify(get_zhihu_subscriptions())


@zhihu_bp.route("/api/zhihu/subscriptions", methods=["POST"])
@login_required
def add_sub():
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").strip()
    tokens = body.get("url_tokens", [])
    if isinstance(tokens, list):
        tokens = json.dumps(tokens, ensure_ascii=False)
    elif not isinstance(tokens, str):
        tokens = "[]"
    sub = add_zhihu_subscription(email, url_tokens=tokens)
    if not sub:
        return jsonify({"error": "邮箱格式无效或已存在"}), 400
    return jsonify(sub), 201


@zhihu_bp.route("/api/zhihu/subscriptions/<int:sub_id>", methods=["PATCH"])
@login_required
def patch_sub(sub_id):
    body = request.get_json(silent=True) or {}
    kwargs = {}
    if "enabled" in body:
        kwargs["enabled"] = 1 if body["enabled"] else 0
    if "url_tokens" in body:
        v = body["url_tokens"]
        kwargs["url_tokens"] = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
    ok = update_zhihu_subscription(sub_id, **kwargs)
    if not ok:
        return jsonify({"error": "更新失败"}), 400
    return jsonify({"message": "已更新"})


@zhihu_bp.route("/api/zhihu/subscriptions/<int:sub_id>", methods=["DELETE"])
@login_required
def remove_sub(sub_id):
    ok = delete_zhihu_subscription(sub_id)
    if not ok:
        return jsonify({"error": "订阅不存在"}), 404
    return jsonify({"message": "已删除"})


# ── SMTP 设置 / 测试 ────────────────────────────────

@zhihu_bp.route("/api/zhihu/email_settings", methods=["GET"])
@login_required
def get_email_settings():
    db = get_zhihu_smtp_settings()
    if db:
        return jsonify({
            "host": db.get("smtp_host", ""),
            "port": db.get("smtp_port", 465),
            "user": db.get("smtp_user", ""),
            "password": mask_password(db.get("smtp_password", "")),
            "from_addr": db.get("smtp_from", ""),
            "use_ssl": bool(db.get("smtp_use_ssl", 1)),
            "source": "db",
        })
    from backend.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_SSL
    if SMTP_HOST:
        return jsonify({
            "host": SMTP_HOST, "port": SMTP_PORT, "user": SMTP_USER,
            "password": mask_password(SMTP_PASSWORD), "from_addr": SMTP_FROM or SMTP_USER,
            "use_ssl": bool(SMTP_USE_SSL), "source": "env",
        })
    return jsonify({
        "host": "", "port": 465, "user": "", "password": "",
        "from_addr": "", "use_ssl": True, "source": "none",
    })


@zhihu_bp.route("/api/zhihu/email_settings", methods=["POST"])
@login_required
def post_email_settings():
    body = request.get_json(silent=True) or {}
    host = (body.get("host") or "").strip()
    port = int(body.get("port") or 465)
    user = (body.get("user") or "").strip()
    password = body.get("password", "") or ""
    smtp_from = (body.get("from_addr") or user).strip()
    use_ssl = bool(body.get("use_ssl", True))

    if not host or not user:
        return jsonify({"error": "host 和 user 必填"}), 400
    ok, msg = save_settings(host, port, user, password, smtp_from, use_ssl)
    if not ok:
        return jsonify({"error": msg}), 500
    return jsonify({"message": "已保存"})


@zhihu_bp.route("/api/zhihu/email_test", methods=["POST"])
@login_required
def email_test():
    body = request.get_json(silent=True) or {}
    to_email = (body.get("email") or "").strip()
    if not to_email or "@" not in to_email:
        return jsonify({"error": "请提供合法邮箱地址"}), 400
    cfg = get_active_settings()
    if not cfg:
        return jsonify({"error": "SMTP 未配置"}), 400
    subject = "【量化交易系统】邮件测试"
    html = """
    <div style="font-family:'Microsoft YaHei',sans-serif;max-width:600px;margin:20px auto;padding:24px;
                border:1px solid #e4e7ed;border-radius:8px;background:#fff;">
      <h2 style="color:#67c23a;margin-top:0;">✅ 邮件测试成功</h2>
      <p style="color:#303133;font-size:14px;">
        这是一封来自量化交易系统的测试邮件。<br>
        如果您能收到，说明 SMTP 配置正确。
      </p>
      <p style="color:#909399;font-size:12px;margin-top:20px;">
        发送时间：""" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """
      </p>
    </div>
    """
    ok, err = send_email(to_email, subject, html, url_token="__test__", post_ids=[])
    if not ok:
        return jsonify({"error": err or "发送失败"}), 500
    return jsonify({"message": "测试邮件已发送，请查收"})


# ── 邮件发送日志 ─────────────────────────────────

@zhihu_bp.route("/api/zhihu/logs", methods=["GET"])
@login_required
def get_email_logs():
    limit = request.args.get("limit", 50, type=int)
    logs = get_zhihu_email_logs(limit=limit)
    for l in logs:
        if l.get("post_ids"):
            try:
                l["post_ids"] = json.loads(l["post_ids"])
            except (json.JSONDecodeError, TypeError):
                l["post_ids"] = []
    return jsonify(logs)
