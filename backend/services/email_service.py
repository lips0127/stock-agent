"""
SMTP 邮件发送服务。
- 配置优先取 DB（zhihu_smtp_settings），env 兜底
- 失败时记录到 zhihu_email_log
- 支持 HTML 正文
"""
import os
import smtplib
import logging
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Iterable

from backend.core.database import (
    get_zhihu_smtp_settings,
    add_zhihu_email_log,
)
from backend.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM, SMTP_USE_SSL,
)

logger = logging.getLogger(__name__)


def _decode_pwd(p: str) -> str:
    """DB 存的密码若带 base64 前缀则解码，否则原样返回。"""
    if not p:
        return ""
    if p.startswith("b64:"):
        try:
            return base64.b64decode(p[4:]).decode("utf-8")
        except Exception:
            return p
    return p


def _encode_pwd(p: str) -> str:
    """入库前用 base64 简单脱敏。"""
    if not p:
        return ""
    return "b64:" + base64.b64encode(p.encode("utf-8")).decode("ascii")


def mask_password(p: str) -> str:
    """前端回显：仅显示末 4 位。"""
    if not p:
        return ""
    if len(p) <= 4:
        return "****"
    return "*" * (len(p) - 4) + p[-4:]


def get_active_settings() -> dict | None:
    """获取生效的 SMTP 配置（DB 优先，env 兜底）。"""
    db = get_zhihu_smtp_settings()
    if db and (db.get("smtp_host") or "").strip():
        return {
            "host": db["smtp_host"],
            "port": int(db.get("smtp_port") or 465),
            "user": db.get("smtp_user") or "",
            "password": _decode_pwd(db.get("smtp_password") or ""),
            "from_addr": db.get("smtp_from") or db.get("smtp_user") or "",
            "use_ssl": bool(db.get("smtp_use_ssl", 1)),
        }
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        return {
            "host": SMTP_HOST,
            "port": int(SMTP_PORT or 465),
            "user": SMTP_USER,
            "password": SMTP_PASSWORD,
            "from_addr": SMTP_FROM or SMTP_USER,
            "use_ssl": bool(SMTP_USE_SSL),
        }
    return None


def save_settings(host: str, port: int, user: str, password: str,
                  smtp_from: str, use_ssl: bool) -> tuple[bool, str]:
    """保存 SMTP 配置。password 为空时表示不修改。"""
    from backend.core.database import save_zhihu_smtp_settings
    # 若 password 为占位符（前端回显的 *），保持原密码
    if not password or set(str(password)) == {"*"}:
        existing = get_zhihu_smtp_settings()
        if existing and existing.get("smtp_password"):
            password = existing["smtp_password"]
        else:
            password = ""
    encoded = _encode_pwd(password)
    ok = save_zhihu_smtp_settings(host, int(port or 465), user, encoded,
                                  smtp_from or user, 1 if use_ssl else 0)
    return ok, "保存成功" if ok else "保存失败"


def _build_msg(from_addr: str, to_addrs: list[str], subject: str,
               html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("量化交易系统", from_addr))
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(to_addrs: Iterable[str], subject: str,
               html_body: str, url_token: str = "",
               post_ids: list[str] = None) -> tuple[bool, str]:
    """发送邮件。返回 (success, error_message)。"""
    cfg = get_active_settings()
    if not cfg:
        msg = "未配置 SMTP，请在 .env 或前端邮箱设置中填写"
        logger.error(msg)
        for email in to_addrs:
            add_zhihu_email_log(email, subject, url_token,
                                str(post_ids or []), "failed", msg)
        return False, msg

    to_list = list(to_addrs) if not isinstance(to_addrs, str) else [to_addrs]
    msg = _build_msg(cfg["from_addr"], to_list, subject, html_body)

    # 兜底：禁止 SMTP 走代理（Win 系统代理不影响 SMTP，但 SMTP_PROXY env 可能
    # 由其他工具链设置）。代理日志可能泄露邮件密码，故必须显式禁止。
    os.environ.pop("SMTP_PROXY", None)

    try:
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as s:
                s.login(cfg["user"], cfg["password"])
                s.sendmail(cfg["from_addr"], to_list, msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
                s.starttls()
                s.login(cfg["user"], cfg["password"])
                s.sendmail(cfg["from_addr"], to_list, msg.as_string())
        for email in to_list:
            add_zhihu_email_log(email, subject, url_token,
                                str(post_ids or []), "success", "")
        logger.info(f"邮件已发送 → {to_list} 主题: {subject}")
        return True, ""
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.error(f"邮件发送失败: {err}")
        for email in to_list:
            add_zhihu_email_log(email, subject, url_token,
                                str(post_ids or []), "failed", err[:500])
        return False, err


def render_notification_html(url_token: str, display_name: str,
                              posts_with_analysis: list[dict]) -> str:
    """渲染通知邮件 HTML。"""
    rows_html = ""
    stance_color = {
        "bullish": "#67c23a",
        "bearish": "#f56c6c",
        "neutral": "#909399",
        "mixed": "#e6a23c",
    }
    stance_label = {
        "bullish": "看多",
        "bearish": "看空",
        "neutral": "中性",
        "mixed": "混合",
    }
    for p in posts_with_analysis:
        title = p.get("title", "") or ""
        url = p.get("url", "#")
        stance = p.get("stance") or "neutral"
        summary = p.get("summary", "") or ""
        action = p.get("action_suggestion", "") or ""
        key_points = p.get("key_points") or []
        assets = p.get("stance_assets") or []
        confidence = p.get("confidence") or 0
        created = p.get("created_at_original", "") or ""

        assets_html = ""
        for a in assets[:6]:
            a_stance = a.get("stance", "neutral")
            assets_html += (
                f'<span style="display:inline-block;margin:2px 4px 2px 0;'
                f'padding:2px 8px;border-radius:10px;font-size:12px;'
                f'background:{stance_color.get(a_stance, "#909399")};color:#fff;">'
                f'{a.get("asset", "")} · {stance_label.get(a_stance, "中性")}'
                f'</span>'
            )

        kp_html = "".join(
            f'<li style="margin:2px 0;font-size:13px;color:#555;">{kp}</li>'
            for kp in key_points[:4]
        )

        rows_html += f"""
        <div style="border:1px solid #e4e7ed;border-radius:8px;padding:14px 18px;margin:14px 0;background:#fff;">
          <div style="font-size:12px;color:#909399;margin-bottom:6px;">
            {created} · {p.get("post_type", "")}
          </div>
          <div style="font-size:16px;font-weight:600;margin-bottom:8px;">
            <a href="{url}" style="color:#303133;text-decoration:none;">{title}</a>
          </div>
          <div style="margin:8px 0;">
            <span style="display:inline-block;padding:3px 10px;border-radius:12px;
                  background:{stance_color.get(stance, "#909399")};color:#fff;font-size:13px;">
              立场：{stance_label.get(stance, "中性")} · 置信度 {confidence}
            </span>
            <span style="margin-left:8px;">{assets_html}</span>
          </div>
          <div style="font-size:14px;color:#303133;margin:8px 0;">{summary}</div>
          <div style="font-size:13px;color:#67c23a;background:#f0f9eb;padding:8px 12px;border-radius:4px;margin:8px 0;">
            <b>建议：</b>{action}
          </div>
          {f'<ul style="padding-left:20px;margin:8px 0;">{kp_html}</ul>' if kp_html else ''}
          <div style="margin-top:10px;">
            <a href="{url}" style="display:inline-block;padding:6px 14px;
               background:#409eff;color:#fff;text-decoration:none;border-radius:4px;font-size:13px;">
              打开知乎原文 →
            </a>
          </div>
        </div>
        """

    return f"""
    <div style="max-width:680px;margin:0 auto;font-family:'Microsoft YaHei',sans-serif;
                background:#f5f7fa;padding:20px;">
      <div style="background:linear-gradient(135deg,#409eff,#67c23a);
                  color:#fff;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;font-size:20px;">知乎大V动态更新</h2>
        <div style="margin-top:6px;font-size:13px;opacity:.9;">
          {display_name or url_token} · {len(posts_with_analysis)} 条新动态
        </div>
      </div>
      <div style="background:#fafbfc;padding:18px 24px;border-radius:0 0 8px 8px;">
        {rows_html}
        <div style="font-size:12px;color:#909399;margin-top:20px;padding-top:14px;border-top:1px solid #ebeef5;">
          本邮件由量化交易系统自动生成，仅供参考，不构成投资建议。
        </div>
      </div>
    </div>
    """


def notify_new_analysis(url_token: str, display_name: str,
                         posts_with_analysis: list[dict]) -> tuple[int, int, str]:
    """有新分析时，给所有启用的订阅发邮件（节流后）。

    Returns:
        (sent_count, skipped_count, error_message)
    """
    from backend.core.database import (
        get_zhihu_subscriptions, get_zhihu_user_by_token,
    )
    from datetime import datetime, timedelta
    from backend.config import ZHIHU_NOTIFY_MIN_INTERVAL_HOURS

    user = get_zhihu_user_by_token(url_token)
    if not user or not user.get("email_notify"):
        return 0, 0, "用户未启用邮件通知"

    # 节流：同一用户 6h 内只发一次
    last_notified = user.get("last_notified_at")
    if last_notified:
        try:
            last_dt = datetime.fromisoformat(str(last_notified))
            if datetime.now() - last_dt < timedelta(hours=ZHIHU_NOTIFY_MIN_INTERVAL_HOURS):
                return 0, 1, f"距上次通知不足 {ZHIHU_NOTIFY_MIN_INTERVAL_HOURS}h，已跳过"
        except ValueError:
            pass

    # 找到该用户的所有启用的订阅
    subs = get_zhihu_subscriptions(enabled_only=True)
    target_subs = []
    import json as _json
    for s in subs:
        try:
            tokens = _json.loads(s.get("url_tokens") or "[]")
        except _json.JSONDecodeError:
            tokens = []
        if not tokens or url_token in tokens:
            target_subs.append(s)
    if not target_subs:
        return 0, 0, "无匹配的订阅邮箱"

    subject = f"【知乎更新】{display_name or url_token} · {len(posts_with_analysis)} 条新动态"
    html = render_notification_html(url_token, display_name, posts_with_analysis)
    post_ids = [p.get("post_id", "") for p in posts_with_analysis]

    sent = 0
    skipped = 0
    for s in target_subs:
        ok, err = send_email(s["email"], subject, html,
                             url_token=url_token, post_ids=post_ids)
        if ok:
            sent += 1
        else:
            skipped += 1
        # 标记已发送（每个订阅者一次）
    # 更新 last_notified_at
    from backend.services.zhihu_service import update_zhihu_user_by_token
    update_zhihu_user_by_token(url_token, last_notified_at=datetime.now().isoformat(sep=" ", timespec="seconds"))
    return sent, skipped, ""
