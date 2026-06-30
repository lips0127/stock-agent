"""
知乎大V抓取服务（v4, 2026-06-30 — 纯 Web 抓取 + 反爬熔断）。

通过解析公开 HTML 页面获取用户资料、文章、回答、想法。
携带 ZHIHU_COOKIE（若配置）以提升成功率；不强制依赖登录态。

v4 变更：知乎对 /people/{token}/posts、/pins 等动态接口返回 403 拦截页（带 cookie
也挡）。加 ZhihuCircuitBreaker：连续 403 达阈值 → 熔断静默跳过，避免每 tick 72 条
WARNING 刷屏。403 不重试（确定性反爬）。冷启动不再立即跑 zhihu_check。

数据来源：
- 用户资料：/people/{url_token} 页面的 js-initialData SSR JSON
- 文章/回答列表：/people/{url_token}/posts 页面的 SSR JSON
- 想法列表：/people/{url_token}/pins 页面的 SSR JSON
- 文章正文：/p/{id} 页面的 SSR JSON
"""
import re
import json
import time
import logging
import requests
from datetime import datetime
from typing import Any
from html import unescape

from backend.core.database import (
    get_connection,
    get_zhihu_user_by_token,
    upsert_zhihu_post,
    update_zhihu_user,
)
from backend.services.stock_service import _no_proxy
from backend.config import ZHIHU_COOKIE

logger = logging.getLogger(__name__)

BASE = "https://www.zhihu.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


# ── 知乎反爬熔断器（v4, 2026-06-30）──────────────────────────────────────
# 问题：知乎对 /people/{token}/posts、/pins 等动态接口返回 403（650 字节固定拦截页），
# 即便携带登录态 cookie 也挡。旧逻辑每个 URL 重试 3 次 × 3 端点 × 8 用户 = 每 tick
# 72 条 WARNING 刷屏，且 fetched=0 全无效。
# 策略：连续 N 次 403 → 打开熔断，后续请求 fast-fail 静默跳过；冷却后半开探测。
# 与 guba 熔断同构。cookie 失效/反爬升级时不再刷屏，前端经 health 端点告警。

class ZhihuCircuitOpen(Exception):
    """知乎熔断打开时抛出，调用方应立即跳过该用户。"""


class ZhihuCircuitBreaker:
    """zhihu.com 主机级熔断器。closed → open → half_open → closed。"""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 600.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._lock = __import__("threading").Lock()

    def acquire(self) -> None:
        """请求前调用；熔断打开时抛 ZhihuCircuitOpen。"""
        import time as _t
        with self._lock:
            if self._state == "open":
                remaining = self.cooldown_seconds - (_t.time() - self._opened_at)
                if remaining > 0:
                    raise ZhihuCircuitOpen(
                        f"zhihu.com 熔断中（剩余 {remaining:.0f}s）"
                    )
                self._state = "half_open"

    def on_success(self) -> None:
        with self._lock:
            if self._state != "closed":
                logger.info(f"[知乎熔断] 探测成功，恢复 closed (前状态={self._state})")
            self._state = "closed"
            self._failures = 0

    def on_403(self) -> None:
        """403 是确定性反爬，计入熔断失败。"""
        import time as _t
        with self._lock:
            self._failures += 1
            if self._state == "half_open":
                self._state = "open"
                self._opened_at = _t.time()
            elif self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = _t.time()
                logger.error(
                    f"[知乎熔断] 连续 {self._failures} 次 403，打开熔断 "
                    f"(cooldown={self.cooldown_seconds}s) —— 知乎反爬升级或 cookie 失效，"
                    f"抓取将静默跳过直至冷却"
                )

    @property
    def state(self) -> dict:
        import time as _t
        with self._lock:
            remaining = max(0, self.cooldown_seconds - (_t.time() - self._opened_at)) \
                if self._state == "open" else 0
            return {
                "state": self._state,
                "failures": self._failures,
                "cooldown_seconds": self.cooldown_seconds,
                "cooldown_remaining": round(remaining, 0),
            }

    def reset(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = 0.0
            logger.info("[知乎熔断] 手动重置")


_ZHIHU_CIRCUIT = ZhihuCircuitBreaker()


# ── 工具函数 ──────────────────────────────────────────────

def extract_url_token(url_or_token: str) -> str:
    """从 URL 或 url_token 中提取。"""
    s = (url_or_token or "").strip()
    m = re.search(r"zhihu\.com/people/([\w-]+)", s, re.IGNORECASE)
    return m.group(1) if m else s.lstrip("@")


def _strip_html(html: str, max_len: int = 4000) -> str:
    """剥离 HTML 标签，返回纯文本，限制长度。"""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


def _extract_text_from_content(content, max_len: int = 4000) -> str:
    """统一提取知乎内容字段为纯文本。"""
    if not content:
        return ""
    if isinstance(content, str):
        return _strip_html(content, max_len=max_len)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                txt = block.get("content") or ""
                if txt:
                    parts.append(_strip_html(txt, max_len=max_len))
            elif btype == "link":
                title = block.get("title") or ""
                url = block.get("url") or ""
                if title:
                    parts.append(_strip_html(title, max_len=200))
                if url:
                    parts.append(url)
            elif btype == "video":
                title = block.get("title") or block.get("description") or ""
                if title:
                    parts.append(_strip_html(title, max_len=400))
        text = "\n".join(parts).strip()
        if len(text) > max_len:
            text = text[:max_len] + "..."
        return text
    return str(content)[:max_len]


def _parse_zhihu_time(ts: Any) -> str | None:
    """知乎时间戳是 ISO8601 字符串或 Unix 秒。"""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(int(ts)).isoformat(sep=" ")
        except (ValueError, OSError):
            return None
    s = str(ts)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).isoformat(sep=" ")
    except ValueError:
        return s


def _normalize_avatar(url: str) -> str:
    """知乎头像 URL 协议自适应。"""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return url


def _looks_like_noise_name(name: str) -> bool:
    """判断知乎返回的 name 是否像噪声。"""
    if not name or len(name.strip()) < 2:
        return True
    noise_patterns = ["makise kurisu", "test", "anonymous", "default"]
    return name.strip().lower() in noise_patterns


# ── HTTP 抓取底层 ──────────────────────────────────────────

def _fetch_html(url: str, referer: str = "", timeout: int = 15,
                max_retries: int = 3) -> str | None:
    """GET 请求，返回 HTML 文本。

    v4 2026-06-30：
    - 走熔断器：熔断打开时 fast-fail（抛 ZhihuCircuitOpen 由调用方降级），不再重试
    - 403 是确定性反爬（带 cookie 也挡），**不重试**，直接计入熔断失败
    - 429/503 限流才指数退避重试
    - 携带 ZHIHU_COOKIE（若配置）——知乎 SSR 页面对部分接口仍认登录态
    """
    _ZHIHU_CIRCUIT.acquire()  # 熔断打开时抛 ZhihuCircuitOpen
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    cookie = ZHIHU_COOKIE
    if cookie:
        headers["Cookie"] = cookie

    for attempt in range(1, max_retries + 1):
        try:
            with _no_proxy():
                r = requests.get(url, headers=headers, timeout=timeout,
                                allow_redirects=True)
            if r.status_code == 200:
                _ZHIHU_CIRCUIT.on_success()
                return r.text
            if r.status_code == 404:
                logger.info(f"知乎 404: {url}")
                _ZHIHU_CIRCUIT.on_success()
                return None
            if r.status_code == 403:
                # 确定性反爬，不重试，计入熔断
                _ZHIHU_CIRCUIT.on_403()
                return None
            if r.status_code in (429, 503):
                wait = 2 ** attempt
                logger.warning(f"知乎 {r.status_code} (限流)，{wait}s 后重试: {url}")
                time.sleep(wait)
                continue
            # 其它非 2xx：不重试
            logger.warning(f"知乎 HTTP {r.status_code}: {url}")
            return None
        except requests.RequestException as e:
            if attempt < max_retries:
                logger.debug(f"知乎请求失败 attempt={attempt}: {e}")
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"知乎请求失败（{max_retries}次）: {url}: {e}")
    return None


def _extract_initial_data(html: str) -> dict | None:
    """从知乎页面 HTML 中提取 js-initialData SSR JSON。"""
    m = re.search(
        r'<script\s+id="js-initialData"[^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, TypeError):
        return None


# ── 用户资料 ──────────────────────────────────────────────

def fetch_user_profile(url_token: str) -> dict | None:
    """从公开页面抓取知乎用户资料（无需 cookie）。

    解析 /people/{url_token} 页面的 SSR JSON。
    """
    html = _fetch_html(f"{BASE}/people/{url_token}",
                       referer=f"{BASE}/people/")
    if not html:
        return None

    data = _extract_initial_data(html)
    if not data:
        # 降级：从 HTML meta/title 提取
        name = ""
        m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
        if m:
            desc = m.group(1)
            name_match = re.match(r'(.+?) - 知乎', desc)
            if name_match:
                name = name_match.group(1).strip()
        if not name:
            m = re.search(r'<title[^>]*>(.+?)\s*-\s*知乎</title>', html, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
        if _looks_like_noise_name(name):
            name = url_token
        return {
            "url_token": url_token,
            "display_name": name or url_token,
            "avatar_url": "",
            "headline": "",
            "follower_count": 0,
        }

    # 从 SSR JSON 提取
    initial = data.get("initialState") or {}
    # 用户实体在 entities.users 里
    users = (initial.get("entities") or {}).get("users") or {}
    user_data = users.get(url_token) or {}

    name = (user_data.get("name") or "").strip()
    if _looks_like_noise_name(name):
        name = url_token

    return {
        "url_token": url_token,
        "display_name": name,
        "avatar_url": _normalize_avatar(user_data.get("avatarUrl") or user_data.get("avatar_url") or ""),
        "headline": user_data.get("headline", "") or "",
        "follower_count": int(user_data.get("followerCount", 0) or 0),
    }


# ── 动态列表（文章 + 回答） ──────────────────────────────

def fetch_user_activities(url_token: str, max_pages: int = 2) -> list[dict]:
    """从公开页面抓取用户最近文章+回答（无需 cookie）。

    解析 /people/{url_token}/posts 页面的 SSR JSON。
    """
    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"{BASE}/people/{url_token}/posts?page={page}"
        html = _fetch_html(url, referer=f"{BASE}/people/{url_token}")
        if not html:
            break

        posts = _parse_activities_html(html, url_token, seen_urls)
        new_count = sum(1 for p in posts if p["url"] not in seen_urls)
        for p in posts:
            if p["url"] not in seen_urls:
                all_posts.append(p)
                seen_urls.add(p["url"])
        if new_count == 0:
            break
        time.sleep(0.5)

    all_posts.sort(key=lambda p: p.get("created_at_original") or "", reverse=True)
    logger.info(f"知乎抓取 {url_token}: {len(all_posts)} 条动态 (pages={max_pages})")
    return all_posts


def _parse_activities_html(html: str, url_token: str,
                           seen_urls: set[str]) -> list[dict]:
    """从 posts 页面 HTML 解析文章/回答列表。"""
    posts: list[dict] = []
    data = _extract_initial_data(html)

    if data:
        try:
            entities = (data.get("initialState") or {}).get("entities") or {}
            articles = entities.get("articles") or {}
            answers = entities.get("answers") or {}

            for aid, art in articles.items():
                if not isinstance(art, dict):
                    continue
                pid = str(aid)
                full_url = f"{BASE}/p/{pid}"
                if full_url in seen_urls:
                    continue
                title = art.get("title", "") or ""
                excerpt = _strip_html(str(art.get("excerpt", "") or ""), max_len=400)
                content = _strip_html(str(art.get("content", "") or ""), max_len=4000)
                if not content:
                    content = excerpt
                posts.append({
                    "post_id": pid,
                    "post_type": "article",
                    "title": title,
                    "excerpt": excerpt,
                    "content_text": content,
                    "url": full_url,
                    "voteup_count": int(art.get("voteupCount", 0) or 0),
                    "comment_count": int(art.get("commentCount", 0) or 0),
                    "created_at_original": _parse_zhihu_time(
                        art.get("created") or art.get("updated")
                    ),
                })

            for aid, ans in answers.items():
                if not isinstance(ans, dict):
                    continue
                pid = str(aid)
                q = ans.get("question") or {}
                qid = str(q.get("id", ""))
                full_url = f"{BASE}/question/{qid}/answer/{pid}" if qid else ""
                if not full_url or full_url in seen_urls:
                    continue
                q_title = q.get("title", "") or ""
                excerpt = _strip_html(str(ans.get("excerpt", "") or ""), max_len=400)
                content = _strip_html(str(ans.get("content", "") or ""), max_len=4000)
                if not content:
                    content = excerpt
                posts.append({
                    "post_id": pid,
                    "post_type": "answer",
                    "title": q_title or excerpt[:50],
                    "excerpt": excerpt,
                    "content_text": content,
                    "url": full_url,
                    "voteup_count": int(ans.get("voteupCount", 0) or 0),
                    "comment_count": int(ans.get("commentCount", 0) or 0),
                    "created_at_original": _parse_zhihu_time(
                        ans.get("createdTime") or ans.get("updatedTime")
                    ),
                })

            if posts:
                return posts
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"SSR 解析失败 {url_token}: {e}")

    # 正则兜底
    article_pattern = re.compile(
        r'<h2[^>]*ContentItem-title[^>]*>\s*<a[^>]*href="(/p/\d+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in article_pattern.finditer(html):
        href = m.group(1)
        title = _strip_html(m.group(2), max_len=200)
        pid_match = re.search(r"/p/(\d+)", href)
        pid = pid_match.group(1) if pid_match else href.lstrip("/p/")
        full_url = f"{BASE}{href}"
        if full_url in seen_urls:
            continue
        posts.append({
            "post_id": pid, "post_type": "article",
            "title": title, "excerpt": "", "content_text": "",
            "url": full_url, "voteup_count": 0, "comment_count": 0,
            "created_at_original": None,
        })

    answer_pattern = re.compile(
        r'href="(/question/(\d+)/answer/(\d+))"[^>]*>',
        re.IGNORECASE,
    )
    for m in answer_pattern.finditer(html):
        href = m.group(1)
        qid = m.group(2)
        aid = m.group(3)
        full_url = f"{BASE}{href}"
        if full_url in seen_urls:
            continue
        posts.append({
            "post_id": aid, "post_type": "answer",
            "title": f"回答 {qid}", "excerpt": "", "content_text": "",
            "url": full_url, "voteup_count": 0, "comment_count": 0,
            "created_at_original": None,
        })

    return posts


# ── 想法（Pins） ──────────────────────────────────────────

def fetch_user_pins(url_token: str, max_pages: int = 1) -> list[dict]:
    """从公开页面抓取用户最近的想法（无需 cookie）。

    解析 /people/{url_token}/pins 页面。
    """
    all_pins: list[dict] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"{BASE}/people/{url_token}/pins?page={page}"
        html = _fetch_html(url, referer=f"{BASE}/people/{url_token}")
        if not html:
            break

        data = _extract_initial_data(html)
        new_count = 0
        if data:
            try:
                pins = ((data.get("initialState") or {})
                        .get("entities") or {}).get("pins") or {}
                for pid, pin in pins.items():
                    if not isinstance(pin, dict):
                        continue
                    pid_str = str(pid)
                    full_url = f"{BASE}/pin/{pid_str}"
                    if pid_str in seen:
                        continue
                    content_text = _extract_text_from_content(
                        pin.get("content"), max_len=4000
                    )
                    excerpt = content_text[:200] if content_text else ""
                    all_pins.append({
                        "post_id": pid_str,
                        "post_type": "pin",
                        "title": excerpt[:50] if excerpt else "（无文本）",
                        "excerpt": excerpt,
                        "content_text": content_text,
                        "url": full_url,
                        "voteup_count": int(pin.get("likeCount", 0) or 0),
                        "comment_count": int(pin.get("commentCount", 0) or 0),
                        "created_at_original": _parse_zhihu_time(
                            pin.get("created") or pin.get("updated")
                        ),
                    })
                    seen.add(pid_str)
                    new_count += 1
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.debug(f"Pins SSR 解析失败 {url_token}: {e}")

        if new_count == 0:
            break
        time.sleep(0.5)

    all_pins.sort(key=lambda p: p.get("created_at_original") or "", reverse=True)
    return all_pins


# ── 文章正文（单篇） ──────────────────────────────────────

def fetch_article_full_content(article_id: str) -> str | None:
    """从公开页面抓取文章完整正文（无需 cookie）。

    解析 /p/{id} 页面的 SSR JSON。
    """
    if not article_id:
        return None
    html = _fetch_html(f"{BASE}/p/{article_id}")
    if not html:
        return None
    data = _extract_initial_data(html)
    if not data:
        return None
    try:
        articles = ((data.get("initialState") or {})
                    .get("entities") or {}).get("articles") or {}
        art = articles.get(str(article_id)) or {}
        content = art.get("content", "") or ""
        return _strip_html(str(content), max_len=8000) or None
    except Exception:
        return None


# ── 主入口：刷新单个用户 ──────────────────────────────────

def refresh_user(url_token: str, max_pages: int = 2) -> dict:
    """抓取并入库单个用户的最新动态（纯 Web 抓取，无需 cookie）。

    Returns:
        {"profile": {...}, "fetched": N, "new_posts": N, "errors": [...]}
    """
    result = {"profile": None, "fetched": 0, "new_posts": 0, "errors": []}

    # 熔断中：知乎反爬墙已确认生效（持续 403），整用户静默跳过，不再逐端点打日志
    if _ZHIHU_CIRCUIT.state["state"] == "open":
        logger.debug(f"知乎熔断中，跳过 {url_token}")
        result["errors"].append("circuit_open")
        return result

    # 1. 拉取用户资料
    try:
        profile = fetch_user_profile(url_token)
    except ZhihuCircuitOpen:
        # 资料页就把熔断打满了，后续端点必失败，整用户跳过
        logger.debug(f"知乎熔断触发，跳过 {url_token}")
        result["errors"].append("circuit_open")
        return result
    if profile:
        result["profile"] = profile
    else:
        result["errors"].append("user_profile_failed")

    # 2. 拉取动态（文章 + 回答）
    posts = []
    try:
        posts = fetch_user_activities(url_token, max_pages=max_pages)
    except Exception as e:
        logger.error(f"抓取 {url_token} 动态失败: {e}", exc_info=True)
        result["errors"].append(f"activities_failed: {e}")
        update_zhihu_user_by_token(url_token, last_error=str(e)[:200])
        return result

    # 3. 拉取想法
    try:
        pins = fetch_user_pins(url_token, max_pages=1)
        posts.extend(pins)
        posts.sort(key=lambda p: p.get("created_at_original") or "", reverse=True)
    except Exception as e:
        logger.warning(f"抓取 {url_token} 想法失败: {e}")

    result["fetched"] = len(posts)

    # 4. 入库
    for p in posts:
        try:
            inserted, _ = upsert_zhihu_post(
                url_token=url_token,
                post_id=p["post_id"],
                post_type=p["post_type"],
                title=p.get("title", ""),
                excerpt=p.get("excerpt", ""),
                content_text=p.get("content_text", ""),
                url=p["url"],
                voteup_count=p.get("voteup_count", 0),
                comment_count=p.get("comment_count", 0),
                created_at_original=p.get("created_at_original") or "",
            )
            if inserted:
                result["new_posts"] += 1
        except Exception as e:
            logger.warning(f"入库知乎动态失败 {p.get('post_id')}: {e}")

    # 5. 更新 zhihu_users
    update_kwargs = {
        "last_checked_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }
    if profile:
        update_kwargs.update({
            "display_name": profile["display_name"],
            "avatar_url": profile["avatar_url"],
            "headline": profile["headline"],
            "follower_count": profile["follower_count"],
        })
    if result["errors"]:
        update_kwargs["last_error"] = "; ".join(result["errors"])[:200]
    else:
        update_kwargs["last_error"] = ""
    update_zhihu_user_by_token(url_token, **update_kwargs)

    logger.info(f"知乎刷新 {url_token}: fetched={result['fetched']} new={result['new_posts']}")
    return result


def update_zhihu_user_by_token(url_token: str, **kwargs) -> bool:
    """通过 url_token 更新用户字段。"""
    with get_connection() as conn:
        cur = conn.cursor()
        allowed = {"display_name", "avatar_url", "headline", "follower_count",
                   "enabled", "email_notify", "last_checked_at",
                   "last_notified_at", "last_error"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return False
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [url_token]
        cur.execute(f"UPDATE zhihu_users SET {sets} WHERE url_token=?", vals)
        return cur.rowcount > 0


def refresh_all_enabled() -> dict:
    """批量刷新所有 enabled=1 的用户（调度任务调用）。"""
    from backend.core.database import get_zhihu_users
    users = get_zhihu_users(enabled_only=True)
    summary = {"total": len(users), "ok": 0, "failed": 0, "new_posts": 0}
    for u in users:
        try:
            r = refresh_user(u["url_token"], max_pages=1)
            if r.get("errors"):
                summary["failed"] += 1
            else:
                summary["ok"] += 1
            summary["new_posts"] += r.get("new_posts", 0)
        except Exception as e:
            summary["failed"] += 1
            logger.error(f"刷新 {u['url_token']} 失败: {e}")
        time.sleep(1.5)
    return summary
