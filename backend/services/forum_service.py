"""
东财股吧论坛爬取服务。
从 guba.eastmoney.com 获取股票社区帖子数据。
"""

import re
import json
import time
import logging
import threading
import requests
from datetime import datetime, timedelta
from backend.core.database import get_connection, get_sentiment_filters
from backend.services.stock_service import _no_proxy
from backend.config import (
    GUBA_CB_FAILURE_THRESHOLD, GUBA_CB_COOLDOWN_SECONDS,
    GUBA_HTTP_RETRIES, GUBA_HTTP_RETRY_BACKOFF,
    GUBA_DETAIL_MIN_INTERVAL, GUBA_BACKFILL_MAX_PER_RUN,
)

logger = logging.getLogger(__name__)

# 预置过滤关键词（fallback when DB unavailable）
_DEFAULT_FILTER_KEYWORDS = ["转发", "阅读", "股吧", "收藏", "发表于"]


# ── 共享 Session + Cookie 预热（v2, 2026-06-06） ──────────────────────────
# 2026-06 之后 guba 详情页增加了 cookie 鉴权：未携带 qgqp_b_id / st_nvi / nid18 /
# gviem 等老访客 cookie 时，详情页（news,X,Y.html）只返回 ~2.8KB 的引导壳
# （<div id="root"> + fd_guba_validate 资源），里头没有 post_article JSON。
# 列表页（list,X.html）不受影响。
#
# v9 2026-08-31 复盘修正（关键事实变化）：
# 实测 guba 的 cookie 墙已整体放开--不携带任何 cookie 的全新 Session 也能拿到
# 详情页正文；带 2026-06-06 的旧 cookie 同样正常。引导壳真正的触发条件是
# **速率型反爬（验证码墙）**：持续高速抓取（如补抓积压正文、多线程审计/批量
# 并发）后触发；触发后封锁窗口较长（实测 >40 分钟完全静默仍未解除），
# 期间列表页与详情页均返回壳。cookie 注入/预热无法解决，也未观察到
# UA 维度豁免。核心对策是从源头控速，避免触发。
#
# v9 策略（详见 _http_get_with_retry）：
# 1. 保留 bootstrap cookie 注入（遗留兼容，无害；guba 已不校验）
# 2. 详情页全局节流（_throttle_detail_request，GUBA_DETAIL_MIN_INTERVAL），
#    所有线程（补抓/审计/批量）共享同一最小间隔，从源头避免触发反爬
# 3. 引导壳改为退避重试（3s / 9s）；重试仍壳则置 _COOKIE_STALE 告警，
#    但下一次成功的详情页会自动复位（自愈，无需重启或人工换 cookie）
# 4. fetch_forum_posts 的正文补抓限定 days 窗口 + GUBA_BACKFILL_MAX_PER_RUN
#    上限；旧实现会补抓该股 DB 中全部无正文帖子（单股数千条，见 2026-08-31
#    积压 12.7 万条），数小时连续抓取必然触发反爬并长期降级

# 来自真实浏览器会话的 anti-bot cookies（2026-06-06 提取）。
# 这些 cookie 是 guba 域通用的反爬标识，不绑定用户；首次访问时直接注入。
_GUBA_BOOTSTRAP_COOKIES = {
    "qgqp_b_id": "3887f38c95c6219c78d2d464d13dc25b",
    "st_nvi": "YdymadBWtzSdSD6mf1GEVb9eb",
    "nid18": "0aef0cce8a96f5f392327a39a2262793",
    "gviem": "I62K01Ig9bRhbCKTIvTSn70c6",
    "st_si": "83268578334050",
    "st_pvi": "06154531581302",
    "st_sp": "2026-06-06 12:59:54",
    "st_inirUrl": "https://guba.eastmoney.com/list,600584.html",
    "st_sn": "1",
    "st_psi": "20260606131646400-117001354293-2377644603",
    "st_asi": "delete",
}

_GUBA_SESSION = requests.Session()
_GUBA_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
})


def _inject_bootstrap_cookies() -> None:
    """把 _GUBA_BOOTSTRAP_COOKIES 注入到 _GUBA_SESSION。"""
    for k, v in _GUBA_BOOTSTRAP_COOKIES.items():
        _GUBA_SESSION.cookies.set(k, v, domain=".eastmoney.com")


# 启动时立即注入一次
_inject_bootstrap_cookies()

_GUBA_WARMED_UP = True  # 遗留标记（v9 起不再参与重试决策，仅保留兼容）
_GUBA_WARMUP_LOCK = threading.Lock()
# 反爬降级标志（v9 2026-08-31 语义变更）：详情页退避重试后仍返回引导壳时置 True，
# 由 /api/sentiment/circuit_status 透出给前端告警。引导壳是速率型反爬（封锁窗
# 口可达数十分钟），期间抓取层降级为 DB 缓存；周期探测在墙解除后自动复位，
# 无需人工换 cookie 或重启。
_COOKIE_STALE = False
# 引导壳告警节流（v8 2026-06-30）：cookie 过期后，每个详情页请求都会返回引导壳。
# 旧逻辑每次都做无意义 warmup + 打 2 行日志 -> 1000+ 只股票刷屏。改为：
# stale 后静默降级；一次性 error 日志最多每 5 分钟重复一次，防多线程竞争刷屏。
_SHELL_WARN_INTERVAL = 300.0
_last_shell_warn_ts = 0.0
# v9：stale 期间的探测窗口。封锁窗内每个请求都付退避成本太贵；
# 每 _SHELL_PROBE_INTERVAL 秒放行一次带退避的探测请求，墙解除后自动
# 复位；其余时间直接快速返回引导壳（上层转 fetch_error / DB 缓存降级）。
_SHELL_PROBE_INTERVAL = 60.0
_last_shell_probe_ts = 0.0
# v9：引导壳退避序列（独立于网络重试预算，避免互相挤占）
_SHELL_BACKOFFS = (3.0, 9.0)
# v9：详情页全局节流状态（预约时隙实现，见 _throttle_detail_request）
_DETAIL_THROTTLE_LOCK = threading.Lock()
_last_detail_req_ts = [0.0]


def _throttle_detail_request(url: str) -> None:
    """详情页（/news,*.html）全局节流：所有线程共享的最小请求间隔。

    引导壳是速率型反爬：审计线程池（4 workers）+ 批量分析（5 workers）+
    正文补抓循环并发打详情页时，实际速率远超单线程 0.3s sleep 的预期。
    这里在请求入口统一限速（GUBA_DETAIL_MIN_INTERVAL，默认 0.8s/请求），
    从源头避免触发反爬；列表页不节流。

    实现为「预约时隙」：锁内计算自己应等待的时隙并登记，锁外 sleep，
    保证并发线程的请求在时间上互不重叠。
    """
    if "/news," not in url:
        return
    with _DETAIL_THROTTLE_LOCK:
        now = time.time()
        wait = max(0.0, _last_detail_req_ts[0] + GUBA_DETAIL_MIN_INTERVAL - now)
        _last_detail_req_ts[0] = now + wait
    if wait > 0:
        time.sleep(wait)


def _warmup_guba_session() -> bool:
    """重新注入 bootstrap cookies（遗留接口，v9 起仅作兼容保留）。

    v9 实测：guba 已不校验这些 cookie（空 cookie 也能取正文），warmup 对
    引导壳无恢复作用；universe_service._prewarm_guba 仍调用本函数，保留
    注入行为以维持既有导入契约。

    Returns:
        True 注入成功（不保证详情页可用）；
        False 注入失败。
    """
    global _GUBA_WARMED_UP
    with _GUBA_WARMUP_LOCK:
        try:
            _inject_bootstrap_cookies()
            cookies = list(_GUBA_SESSION.cookies.keys())
            logger.info(f"[guba 预热] 重新注入 cookie 成功，当前 {len(cookies)} 个")
            _GUBA_WARMED_UP = True
            return True
        except Exception as e:
            logger.warning(f"[guba 预热] 失败: {e}")
            return False


# ── 网络韧性：熔断器 + 重试（v1, 2026-06-04） ──────────────────────────

class CircuitOpenError(Exception):
    """熔断器打开时抛出的异常，调用方应立即跳过。"""


class GubaCircuitBreaker:
    """guba.eastmoney.com 主机级熔断器。

    状态机：closed → open → half_open → closed
    - 连续 N 次网络失败 → 打开（fast-fail 后续请求，避免 15s×N 等待）
    - 冷却 cooldown 秒后 → half_open（允许 1 个探测请求）
    - 探测成功 → closed；失败 → 重新打开
    """

    def __init__(self, failure_threshold: int = None, cooldown_seconds: float = None):
        self.failure_threshold = failure_threshold or GUBA_CB_FAILURE_THRESHOLD
        self.cooldown_seconds = cooldown_seconds or GUBA_CB_COOLDOWN_SECONDS
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def call(self, fn, *args, **kwargs):
        with self._lock:
            if self._state == "open":
                elapsed = time.time() - self._opened_at
                if elapsed > self.cooldown_seconds:
                    self._state = "half_open"
                else:
                    raise CircuitOpenError(
                        f"guba.eastmoney.com 熔断中（剩余 {self.cooldown_seconds - elapsed:.0f}s）"
                    )
        try:
            result = fn(*args, **kwargs)
        except (requests.RequestException, CircuitOpenError):
            self._on_failure()
            raise
        self._on_success()
        return result

    def _on_success(self):
        with self._lock:
            if self._state != "closed":
                logger.info(f"[guba 熔断] 探测成功，恢复 closed (前状态={self._state})")
            self._state = "closed"
            self._failures = 0

    def _on_failure(self):
        with self._lock:
            self._failures += 1
            if self._state == "half_open":
                # 探测失败 → 重新打开
                self._state = "open"
                self._opened_at = time.time()
                logger.warning(f"[guba 熔断] 探测失败，重新打开 (cooldown={self.cooldown_seconds}s)")
            elif self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = time.time()
                logger.warning(
                    f"[guba 熔断] 连续 {self._failures} 次失败，打开熔断 "
                    f"(cooldown={self.cooldown_seconds}s)"
                )

    @property
    def state(self) -> dict:
        with self._lock:
            if self._state == "open":
                remaining = max(0, self.cooldown_seconds - (time.time() - self._opened_at))
            else:
                remaining = 0
            return {
                "state": self._state,
                "failures": self._failures,
                "cooldown_seconds": self.cooldown_seconds,
                "cooldown_remaining": remaining,
            }

    def reset(self):
        """手动重置熔断器（用于测试 / 运维）。"""
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._opened_at = 0.0
            logger.info("[guba 熔断] 手动重置")


# 模块级单例：所有 guba 请求共享同一个熔断器
_GUBA_CIRCUIT = GubaCircuitBreaker()


def _http_get_with_retry(url: str, headers: dict, timeout: int,
                         retries: int = None, backoff: float = None) -> requests.Response:
    """带指数退避的 GET 重试（封装 _GUBA_CIRCUIT.call）。

    v9 2026-08-31：引导壳（< 3KB + id="root"）实测为速率型间歇反爬，与 cookie
    无关（空 cookie 也能取正文）。行为改为：
    - 详情页请求前全局节流（_throttle_detail_request），从源头控制速率
    - 引导壳时按 _SHELL_BACKOFFS 退避重试（不计入网络重试预算）
    - stale 期间每 _SHELL_PROBE_INTERVAL 秒放行一次探测请求，成功即自愈复位
    - warmup / bootstrap cookie 不再参与引导壳恢复路径

    其余行为不变：
    - 走熔断器：熔断打开时立即 raise CircuitOpenError（< 1ms）
    - 网络异常（ConnectionError / Timeout / ChunkedEncodingError）-> 指数退避重试
    - 5xx / 429 -> 同样重试
    - 4xx（除 429）-> 不重试，不计入熔断失败（反爬响应）

    Args:
        url: 请求 URL
        headers: HTTP 头（忽略，cookie/UA 由共享 Session 维护；参数保留兼容旧调用点）
        timeout: 超时秒数
        retries: 网络重试次数（不含首次），默认 GUBA_HTTP_RETRIES
        backoff: 网络重试退避基数秒，默认 GUBA_HTTP_RETRY_BACKOFF
    """
    if retries is None:
        retries = GUBA_HTTP_RETRIES
    if backoff is None:
        backoff = GUBA_HTTP_RETRY_BACKOFF

    def _is_shell(r: requests.Response) -> bool:
        return (r.status_code == 200
                and len(r.text) < 3000
                and "id=\"root\"" in r.text)

    def _do():
        with _no_proxy():
            # 详情页节流：所有线程共享最小间隔（预约时隙）
            _throttle_detail_request(url)
            # 用共享 Session 自动带上 cookie
            return _GUBA_SESSION.get(url, timeout=timeout)

    last_exc = None
    network_attempt = 0   # 网络异常 / 5xx / 429 重试计数
    shell_retry_idx = 0   # 引导壳退避重试计数（独立预算）
    while True:
        try:
            r = _GUBA_CIRCUIT.call(_do)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            last_exc = e
            if network_attempt < retries:
                sleep_s = backoff * (2 ** network_attempt)
                network_attempt += 1
                logger.debug(f"网络错误 -> 重试 sleep={sleep_s:.1f}s: {e}")
                time.sleep(sleep_s)
                continue
            raise
        except CircuitOpenError:
            raise  # 熔断中，不重试

        # 5xx / 429 视为服务端瞬时错误，走网络重试预算
        if r.status_code == 429 or r.status_code >= 500:
            if network_attempt < retries:
                sleep_s = backoff * (2 ** network_attempt)
                network_attempt += 1
                logger.debug(
                    f"HTTP {r.status_code} -> 重试 sleep={sleep_s:.1f}s"
                )
                time.sleep(sleep_s)
                continue
            return r  # 预算耗尽，交由上层按非 200 处理

        # 200 但内容是引导壳 -> 速率型反爬触发
        global _COOKIE_STALE, _last_shell_warn_ts, _last_shell_probe_ts
        if _is_shell(r):
            # stale 已置位：仅在探测窗口放行（每 _SHELL_PROBE_INTERVAL 一次），
            # 其余快速失败返回壳（上层转 fetch_error），避免每请求都付退避成本
            if _COOKIE_STALE:
                now = time.time()
                if now - _last_shell_probe_ts < _SHELL_PROBE_INTERVAL:
                    return r
                with _GUBA_WARMUP_LOCK:
                    _last_shell_probe_ts = now
            # 退避重试：给反爬冷却窗口（独立预算，不挤占网络重试）
            if shell_retry_idx < len(_SHELL_BACKOFFS):
                sleep_s = _SHELL_BACKOFFS[shell_retry_idx]
                shell_retry_idx += 1
                logger.info(
                    f"[guba] 详情页返回引导壳（len={len(r.text)}），"
                    f"退避 {sleep_s:.0f}s 后重试（速率型反爬）"
                )
                time.sleep(sleep_s)
                continue
            # 退避后仍引导壳 -> 置 stale 告警，等待周期探测自愈
            _COOKIE_STALE = True
            now = time.time()
            if now - _last_shell_warn_ts > _SHELL_WARN_INTERVAL:
                logger.error(
                    "[guba] 引导壳退避重试后仍失败，判定触发速率型反爬 -- "
                    "正文抓取临时降级（列表页标题仍可用）；已启用周期探测，"
                    "反爬解除后自动恢复"
                )
                _last_shell_warn_ts = now
            return r

        # 成功响应；详情页成功即反爬解除，复位 stale 告警
        if _COOKIE_STALE and "/news," in url:
            _COOKIE_STALE = False
            logger.info("[guba] 详情页恢复正常，反爬自愈，复位 stale 告警")
        return r


def filter_posts(posts: list[dict], filter_type: str = "title_keyword") -> list[dict]:
    """根据过滤规则白名单过滤帖子列表。

    Args:
        posts: 原始帖子列表
        filter_type: 过滤类型，目前仅支持 title_keyword

    Returns:
        过滤后的帖子列表
    """
    # 从 DB 获取过滤关键词，失败时用预置列表
    try:
        rules = get_sentiment_filters(filter_type=filter_type, enabled_only=True)
        keywords = [r["filter_key"] for r in rules]
    except Exception:
        keywords = _DEFAULT_FILTER_KEYWORDS

    if not keywords:
        return posts

    filtered = []
    for p in posts:
        title = p.get("title", "")
        if not title:
            # 标题为空时，用内容的前30字作为标题尝试
            content = p.get("content", "") or ""
            if len(content) < 5:
                continue  # 内容也太短，跳过
            title = content[:30]

        # 跳过标题含白名单关键词的帖子
        skip = False
        for kw in keywords:
            if kw in title:
                skip = True
                logger.debug(f"过滤帖子 [keyword={kw}]: {title[:40]}")
                break
        if skip:
            continue

        # 跳过标题过短（<5字）的帖子
        if len(title.strip()) < 5:
            continue

        filtered.append(p)

    if len(filtered) < len(posts):
        logger.info(f"过滤完成: {len(filtered)}/{len(posts)} 条保留")
    return filtered

def _extract_json(text: str, key: str) -> dict | None:
    """从 JavaScript 赋值语句中提取 JSON 对象（括号计数法）。

    Args:
        text: HTML/JS 文本
        key: 变量名，如 'article_list' 或 'post_article'

    Returns:
        解析后的 dict，失败返回 None
    """
    match = re.search(key + r"\s*=\s*", text)
    if not match:
        return None
    try:
        start = text.index("{", match.end())
    except ValueError:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '"' and i > start and text[i-1] != "\\":
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    return None
    return None


GUBA_LIST_URL = "https://guba.eastmoney.com/list,{code}.html"
GUBA_POST_URL = "https://guba.eastmoney.com/news,{code},{post_id}.html"
# 兼容旧调用点（_http_get_with_retry 当前会忽略此 dict，cookie 由 _GUBA_SESSION 维护）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _parse_timestamp(ts) -> float | None:
    """解析股吧时间戳（可能是 Unix 秒级时间戳或字符串）。"""
    if not ts:
        return None
    try:
        return float(int(ts))
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(str(ts)).timestamp()
        except (ValueError, OSError):
            return None


def fetch_post_list(code: str, days: int = 7, max_posts: int = 100) -> list[dict]:
    """获取东财股吧某只股票最近N天的帖子列表。

    按 post_last_time（最后回复时间）筛选最近 days 天的帖子，
    优先取最新讨论活跃的帖子。

    Args:
        code: 6位股票代码
        days: 取最近多少天的帖子
        max_posts: 最多获取帖子数

    Returns:
        帖子列表，每条包含 post_id, title, author, click_count,
        comment_count, publish_time, last_time
    """
    code = str(code).strip().zfill(6)
    cutoff = time.time() - days * 86400
    posts = []

    for page in range(1, 4):  # 最多翻3页
        url = GUBA_LIST_URL.format(code=code)
        if page > 1:
            url = f"https://guba.eastmoney.com/list,{code}_{page}.html"

        try:
            r = _http_get_with_retry(url, HEADERS, timeout=15)
            r.encoding = "utf-8"

            if r.status_code != 200:
                break

            data = _extract_json(r.text, "article_list")
            if not data:
                # v9 2026-08-31：列表页也可能被速率型反爬打壳（返回「身份核实」
                # 引导壳而非帖子数据）。壳响应不 raise，这里显式置 stale，
                # 让 fetch_forum_posts 的 DB 缓存降级路径能被正确触发。
                if r.status_code == 200 and len(r.text) < 3000 and "id=\"root\"" in r.text:
                    global _COOKIE_STALE
                    if not _COOKIE_STALE:
                        logger.warning(
                            f"[guba] 列表页返回引导壳（len={len(r.text)}），"
                            "判定触发速率型反爬，置降级标志"
                        )
                        _COOKIE_STALE = True
                break
            items = data.get("re", [])

            # 建立 HTML href 映射：post_id → full_url
            html_url_map = {}
            for href_full, href_code, href_pid in re.findall(
                r'<a[^>]*href="(/news,(\d+),(\d+)\.html)"[^>]*>',
                r.text
            ):
                if href_code == code:
                    html_url_map[href_pid] = f"https://guba.eastmoney.com{href_full}"

            for item in items:
                # 过滤：只保留当前股票的帖子，排除推广和跨股帖子
                if str(item.get("stockbar_code", "")) != code:
                    continue

                publish_ts = _parse_timestamp(item.get("post_publish_time"))
                last_ts = _parse_timestamp(item.get("post_last_time"))
                active_ts = last_ts or publish_ts

                if active_ts and active_ts < cutoff:
                    continue

                item_pid = str(item.get("post_id", ""))
                # 用 HTML 中提取的真实 URL（由 post_id 匹配）
                real_url = html_url_map.get(item_pid, "")

                posts.append({
                    "post_id": item_pid,
                    "title": item.get("post_title", ""),
                    "author": item.get("user_nickname", ""),
                    "click_count": item.get("post_click_count", 0),
                    "comment_count": item.get("post_comment_count", 0),
                    "publish_time": (
                        datetime.fromtimestamp(publish_ts).isoformat() if publish_ts else ""
                    ),
                    "last_time": (
                        datetime.fromtimestamp(last_ts).isoformat() if last_ts else ""
                    ),
                    "url": real_url,
                })

                if len(posts) >= max_posts:
                    break

            if len(posts) >= max_posts:
                break

            # 如果该页最后一帖的时间已超出窗口，不用翻下一页
            if items and _parse_timestamp(items[-1].get("post_last_time") or items[-1].get("post_publish_time")) or 0 < cutoff:
                break

        except (json.JSONDecodeError, requests.RequestException, CircuitOpenError) as e:
            logger.error(f"获取股吧帖子列表失败: {code} page={page}: {e}")
            break

    # 按活跃时间降序排列
    posts.sort(key=lambda p: p.get("last_time") or p.get("publish_time") or "", reverse=True)
    logger.info(f"获取股吧帖子: {code} 最近{days}天共 {len(posts)} 条")
    return posts


def fetch_post_content(code: str, post_id: str) -> str | None:
    """获取单条帖子的正文内容（向后兼容的薄包装）。

    Args:
        code: 6位股票代码
        post_id: 帖子ID

    Returns:
        帖子正文文本，失败返回 None
    """
    result = fetch_post_full(code, post_id)
    if not result:
        return None
    return result.get("content")


def fetch_post_full(code: str, post_id: str) -> dict | None:
    """获取单条帖子的完整数据：真实标题 + 正文 + 抓取状态。

    用于审计和数据完整性校验。比 fetch_post_content 多返回 post_article JSON
    中的 post_title 字段（与列表页 article_list 的 post_title 经常不一致）。

    2026-06 之后 guba 详情页改造：
    - 高速抓取时只返回 2.8KB 引导壳（速率型反爬，v9 起由退避重试 + 自愈探测处理）
    - post_id 形如 1xxxxxxxxx 的"转发/转载"帖，post_article.post_title 是 "转发"，
      真实标题在 source_post_title 字段。本函数对这种帖会自动取源帖标题作为 actual_title

    Args:
        code: 6位股票代码
        post_id: 帖子ID

    Returns:
        {
          "actual_title": str | None,   # 帖子页面的真实标题（转发帖取源帖标题）
          "content": str | None,        # 帖子正文
          "fetch_error": str | None,    # 抓取失败原因
        }
        整个请求失败时返回 None
    """
    code = str(code).strip().zfill(6)
    url = GUBA_POST_URL.format(code=code, post_id=post_id)

    try:
        r = _http_get_with_retry(url, HEADERS, timeout=10)
        # guba 服务端不带 charset；强制 UTF-8（guba 实际就是 utf-8），
        # 否则 requests 会按 ISO-8859-1 兜底，导致中文乱码。
        r.encoding = "utf-8"

        if r.status_code != 200:
            return {
                "actual_title": None,
                "content": None,
                "fetch_error": f"HTTP {r.status_code}",
            }

        # 提取帖子页面的 JSON
        data = _extract_json(r.text, "post_article")
        if data:
            actual_title = (data.get("post_title") or "").strip() or None
            content = data.get("post_content", "")
            # 转发/转载：post_title 是"转发"占位，真实标题在 source_post_title
            # 仅在源帖存在且当前帖 post_type=0/20（普通用户帖）时替换
            source_title = (data.get("source_post_title") or "").strip()
            if (actual_title in ("转发", "转载", "轉發")
                    and source_title
                    and data.get("source_post_id")
                    and str(data.get("source_post_id")) != str(data.get("post_id"))):
                actual_title = source_title

            if content:
                content = re.sub(r"<[^>]+>", "", content)
                content = re.sub(r"&nbsp;", " ", content)
                content = re.sub(r"\s+", " ", content).strip()
            if not content:
                content = None
            return {
                "actual_title": actual_title,
                "content": content,
                "fetch_error": None,
            }

        # 回退：直接从 HTML 提取（无标题信息）
        match = re.search(
            r'<div[^>]*class="[^"]*stockcodec[^"]*"[^>]*>(.*?)</div>',
            r.text, re.DOTALL
        )
        if match:
            content = match.group(1)
            content = re.sub(r"<[^>]+>", "", content)
            content = re.sub(r"\s+", " ", content).strip()
            return {
                "actual_title": None,
                "content": content,
                "fetch_error": "no_post_article_json",
            }

        return {
            "actual_title": None,
            "content": None,
            "fetch_error": "no_content_in_html",
        }
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.warning(f"获取帖子内容失败 {post_id}: {e}")
        return {
            "actual_title": None,
            "content": None,
            "fetch_error": str(e)[:200],
        }


def audit_post_title(code: str, post_id: str, url: str,
                     stored_title: str, forum_type: str = "eastmoney") -> dict:
    """审计单条帖子的标题真实性，并把结果写回 DB。

    Args:
        code: 6位股票代码
        post_id: 帖子ID
        url: 帖子 URL（未使用，预留）
        stored_title: DB 中存储的标题
        forum_type: 论坛类型

    Returns:
        {
          "post_id": str, "match": bool | None,
          "actual_title": str | None, "stored_title": str,
          "fetch_error": str | None, "audit_status": str,
        }
    """
    from backend.core.database import update_post_audit

    full = fetch_post_full(code, post_id)
    if not full:
        return {
            "post_id": post_id, "match": None,
            "actual_title": None, "stored_title": stored_title,
            "fetch_error": "request_failed",
            "audit_status": "pending",
        }

    actual = (full.get("actual_title") or "").strip()
    fetch_error = full.get("fetch_error")

    # 抓取失败但没有 actual_title → pending，等下次再试
    if fetch_error and not actual:
        audit_status = "pending"
        match = None
    elif not actual:
        # 抓到了页面但没拿到标题（极少数，可能是反爬）
        audit_status = "pending"
        match = None
    else:
        # guba 详情页 URL 已经失效：返回的可能是"帖子不存在"页面或完全不同的帖子
        # 这种情况不算 title mismatch（用户看到的是列表页的标题，列表页正常），
        # 应该标 pending 让用户手动 accept 或下次重试
        if actual in ("很抱歉，您访问的帖子不存在", "很抱歉,您访问的帖子不存在",
                      "帖子不存在", "该帖已被删除"):
            audit_status = "pending"
            match = None
        else:
            # 成功拿到实际标题，对比
            match = _normalize(stored_title) == _normalize(actual)
            audit_status = "verified" if match else "mismatch"

    # 找到 DB id 并写回
    from backend.core.database import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM forum_posts WHERE stock_code=? AND forum_type=? AND url LIKE ?",
            (code, forum_type, f"%,{post_id}.html"),
        )
        row = cur.fetchone()
        if row:
            update_post_audit(
                row["id"],
                actual_title=actual or None,
                title_match=match,
                audit_status=audit_status,
                audit_note=fetch_error,
            )

    return {
        "post_id": post_id,
        "match": match,
        "actual_title": actual or None,
        "stored_title": stored_title,
        "fetch_error": fetch_error,
        "audit_status": audit_status,
    }


def _normalize(title: str) -> str:
    """标题归一化：去空白 + 去常见装饰符号。"""
    if not title:
        return ""
    t = re.sub(r"\s+", "", title)
    # 去除东财常见的方括号装饰（但保留内部内容）
    return t.strip()


def audit_posts(posts: list[dict], forum_type: str = "eastmoney",
                sleep_seconds: float = 0.3,
                max_workers: int = None) -> dict:
    """批量审计帖子标题真实性。

    v2 2026-06-04：网络韧性调优 - 并发执行。
    - 用 ThreadPoolExecutor 并行抓取，默认 4 workers
    - 熔断器打开时短路（CircuitOpenError）→ 剩余帖子不再尝试
    - 已审计过（audit_status='verified'/'manual_accepted'/'broken'）的帖子跳过

    Args:
        posts: 帖子列表，每条需含 {post_id, title, code, url}
        forum_type: 论坛类型
        sleep_seconds: 请求间隔（仅作日志提示，并发场景不再 sleep）
        max_workers: 并发线程数（默认 GUBA_AUDIT_MAX_WORKERS）

    Returns:
        {
          "audited": N, "matched": N, "mismatched": N,
          "fetch_errors": N, "skipped": N,
          "mismatches": [...],   # 详细不一致列表
        }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.core.database import get_connection
    from backend.config import GUBA_AUDIT_MAX_WORKERS

    if max_workers is None:
        max_workers = GUBA_AUDIT_MAX_WORKERS

    summary = {
        "audited": 0, "matched": 0, "mismatched": 0,
        "fetch_errors": 0, "skipped": 0, "mismatches": [],
    }

    # 找出需要审计的帖子（跳过已 verified/manual_accepted/broken 的）
    pending_posts = []
    for p in posts:
        post_id = str(p.get("post_id", ""))
        if not post_id:
            summary["skipped"] += 1
            continue
        # 检查 DB 当前审计状态
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT audit_status FROM forum_posts
                   WHERE stock_code=? AND forum_type=? AND url LIKE ?""",
                (p.get("code", ""), forum_type, f"%,{post_id}.html"),
            )
            row = cur.fetchone()
        status = row["audit_status"] if row else None
        if status in ("verified", "manual_accepted", "broken"):
            summary["skipped"] += 1
            continue
        pending_posts.append(p)

    if not pending_posts:
        return summary

    # 熔断器预先检测：避免给熔断中的 guba 提交任务
    if _GUBA_CIRCUIT.state["state"] == "open":
        logger.warning("guba 熔断中，跳过整批审计")
        summary["skipped"] += len(pending_posts)
        summary["circuit_open"] = True
        return summary

    def _audit_one(p):
        return audit_post_title(
            p.get("code", ""),
            str(p.get("post_id", "")),
            p.get("url", ""),
            p.get("title", ""),
            forum_type,
        )

    circuit_broken = False
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="audit") as ex:
        future_to_post = {
            ex.submit(_audit_one, p): p for p in pending_posts
        }
        for future in as_completed(future_to_post):
            p = future_to_post[future]
            post_id = str(p.get("post_id", ""))
            stored = p.get("title", "")
            try:
                result = future.result()
            except CircuitOpenError as e:
                # 熔断开了：把剩余全部标记为跳过
                logger.warning(f"guba 熔断触发，跳过剩余审计: {e}")
                remaining = sum(1 for f in future_to_post if not f.done())
                summary["skipped"] += remaining
                circuit_broken = True
                # 取消未启动的 future
                for f in future_to_post:
                    f.cancel()
                break
            except Exception as e:
                logger.error(f"审计异常: {post_id}: {e}", exc_info=True)
                summary["fetch_errors"] += 1
                continue

            summary["audited"] += 1
            if result.get("fetch_error"):
                summary["fetch_errors"] += 1
            if result.get("match") is True:
                summary["matched"] += 1
            elif result.get("match") is False:
                summary["mismatched"] += 1
                summary["mismatches"].append({
                    "post_id": post_id,
                    "stored": stored,
                    "actual": result.get("actual_title"),
                    "url": p.get("url", ""),
                })

    if circuit_broken:
        summary["circuit_open"] = True

    logger.info(
        f"标题审计完成: {summary['audited']} 审计, "
        f"{summary['matched']} 一致, {summary['mismatched']} 不一致, "
        f"{summary['fetch_errors']} 抓取失败, {summary['skipped']} 跳过"
        f" (workers={max_workers})"
    )
    return summary


def fetch_forum_posts(code: str, forum_type: str = "eastmoney",
                      days: int = 7, fetch_content: bool = True,
                      audit: bool = True) -> tuple[list[dict], dict | None]:
    """获取股票论坛帖子（爬取 + 缓存到 DB）。

    v2 2026-06-04：网络韧性调优
    - 新增 audit 参数：prefetch 场景可关掉以节省网络
    - 返回类型改为 tuple：(posts, audit_summary)
    - audit_summary 仅在 audit=True 时返回，prefetch (audit=False) 时为 None

    Args:
        code: 6位股票代码
        forum_type: 论坛类型，目前仅支持 eastmoney
        days: 取最近多少天的帖子（默认7天）
        fetch_content: 是否获取帖子正文
        audit: 是否在抓取后跑标题真实性审计

    Returns:
        (posts, audit_summary) - 帖子列表 + 审计摘要
    """
    if forum_type != "eastmoney":
        logger.warning(f"暂不支持的论坛类型: {forum_type}")
        return [], None

    code = str(code).strip().zfill(6)
    try:
        posts = fetch_post_list(code, days=days, max_posts=100)
    except CircuitOpenError as e:
        # 熔断中：直接返回 DB 缓存（降级）
        logger.warning(f"抓取帖子列表被熔断: {code}: {e}")
        cached = get_recent_posts(code, forum_type, limit=100)
        return cached, {"audited": 0, "matched": 0, "mismatched": 0,
                        "fetch_errors": 0, "skipped": 0,
                        "circuit_open": True}

    # 过滤无意义帖子
    posts = filter_posts(posts)

    if not posts:
        # 列表页被反爬墙（返回壳，无 article_list）时 posts 为空。v9 2026-08-31：
        # 与熔断同样走 DB 缓存降级，而不是静默返回空（上层会把空当成
        # no_posts 故障）。缓存为空时保持空返回 + 明确日志。
        if _COOKIE_STALE or _GUBA_CIRCUIT.state["state"] != "closed":
            logger.warning(
                f"[{code}] guba 反爬降级中（stale={_COOKIE_STALE}），回退 DB 缓存"
            )
            cached = get_recent_posts(code, forum_type, limit=100)
            if cached:
                return cached, {"audited": 0, "matched": 0, "mismatched": 0,
                                "fetch_errors": 0, "skipped": 0,
                                "degraded": True}
            logger.warning(f"[{code}] DB 缓存也为空，本次返回空列表")
        return [], None

    # 缓存帖子到 DB，去重
    new_posts = []
    with get_connection() as conn:
        cur = conn.cursor()
        for p in posts:
            try:
                cur.execute(
                    """INSERT OR IGNORE INTO forum_posts
                       (stock_code, forum_type, title, author, post_time, url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (code, forum_type, p["title"], p["author"],
                     p["publish_time"], p["url"]),
                )
                if cur.rowcount > 0:
                    new_posts.append(p)
            except Exception:
                pass

    logger.info(f"论坛帖子缓存完成: {code} 新增 {len(new_posts)}/{len(posts)} 条")

    # 获取新增帖子的正文内容
    if fetch_content:
        # v9 2026-08-31：补抓范围限定 days 窗口 + 每轮上限。
        # 旧实现补抓该股 DB 中全部无正文帖子（历史积压可达数千条/股），
        # 数小时连续抓取触发速率型反爬，且抓到的旧正文对 days 窗口内的
        # 情绪分析毫无价值。窗口内积压由多轮 prefetch（fetch_content=False）
        # 后的日常分析逐步消化；每轮上限保护单次调用的总时长。
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT url FROM forum_posts
                   WHERE stock_code=? AND forum_type=? AND (content IS NULL OR content='')
                     AND post_time >= ?
                   ORDER BY post_time DESC
                   LIMIT ?""",
                (code, forum_type, cutoff, GUBA_BACKFILL_MAX_PER_RUN),
            )
            posts_need_content = [row["url"] for row in cur.fetchall()]

        for url in posts_need_content:
            # 熔断检测：遇到熔断就跳出循环
            if _GUBA_CIRCUIT.state["state"] == "open":
                logger.warning(f"抓取帖子正文时熔断打开: {code} 剩余 {len(posts_need_content)} 条未抓")
                break
            # 反爬降级中：本轮放弃补抓（stale 告警由探测自动恢复）
            if _COOKIE_STALE:
                logger.warning(f"[{code}] 反爬降级中，本轮跳过正文补抓（{len(posts_need_content)} 条待抓）")
                break
            # 从 URL 提取 post_id: .../news,{code},{post_id}.html
            pid_match = re.search(r"/news,\d+,(\d+)\.html", url)
            if not pid_match:
                continue
            post_id = pid_match.group(1)
            try:
                content = fetch_post_content(code, post_id)
            except CircuitOpenError:
                logger.warning(f"抓取正文被熔断: {code} {post_id}")
                break
            if content:
                try:
                    with get_connection() as conn:
                        conn.cursor().execute(
                            "UPDATE forum_posts SET content=? WHERE url=?",
                            (content, url),
                        )
                except Exception:
                    pass

    # 返回所有帖子（带审计字段，过滤掉 broken 但保留 NULL）
    result = []
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, title, actual_title, title_match, audit_status,
                      title_verified_at, content, author, post_time, url
               FROM forum_posts
               WHERE stock_code=? AND forum_type=?
                 AND (audit_status IS NULL OR audit_status != 'broken')
               ORDER BY post_time DESC LIMIT 100""",
            (code, forum_type),
        )
        for row in cur.fetchall():
            result.append({
                "post_id": row["id"],
                "title": row["title"],
                "actual_title": row["actual_title"],
                "title_match": row["title_match"],
                "audit_status": row["audit_status"],
                "title_verified_at": row["title_verified_at"],
                "content": row["content"] or "",
                "author": row["author"],
                "post_time": row["post_time"],
                "url": row["url"],
            })

    # 标题真实性审计（默认开启，prefetch 场景可关掉）
    audit_summary = None
    if audit and result:
        try:
            audit_summary = audit_posts(
                [{"post_id": p["post_id"], "title": p["title"],
                  "code": code, "url": p["url"]}
                 for p in result if p.get("post_id")],
                forum_type=forum_type,
            )
        except CircuitOpenError:
            audit_summary = {"audited": 0, "matched": 0, "mismatched": 0,
                             "fetch_errors": 0, "skipped": 0,
                             "circuit_open": True}

    return result, audit_summary


def test_post_attribution(code: str) -> dict:
    """测试用例：验证 fetch_post_list 返回的帖子都来自目标股票。

    先通过 fetch_post_list（含 stockbar_code filter）获取帖子，
    再额外对原始 JSON 做全量扫描，对比过滤前后差异。

    Returns:
        {"filtered": N, "total_raw": N, "mismatch": N, "details": [...]}
    """
    code = str(code).strip().zfill(6)

    # 1. 通过带 filter 的标准函数获取
    filtered_posts = fetch_post_list(code, days=7, max_posts=80)
    # 2. 对原始 JSON 做全量扫描
    result = {"filtered": len(filtered_posts), "total_raw": 0, "mismatch": 0, "details": []}

    try:
        r = _http_get_with_retry(GUBA_LIST_URL.format(code=code), HEADERS, timeout=15)
        r.encoding = "utf-8"
        data = _extract_json(r.text, "article_list")
        if data:
            for item in data.get("re", []):
                item_code = str(item.get("stockbar_code", "")).zfill(6)
                result["total_raw"] += 1
                if item_code != code and item_code != "000000":
                    result["mismatch"] += 1
                    result["details"].append({
                        "title": item.get("post_title", "")[:40],
                        "stockbar_code": item_code,
                        "stockbar_name": item.get("stockbar_name", ""),
                    })

        pass_rate = (1 - result["mismatch"] / result["total_raw"]) * 100 if result["total_raw"] else 0
        logger.info(
            f"归属测试 {code}: filtered={result['filtered']}/{result['total_raw']} "
            f"cross_stock={result['mismatch']} rate={pass_rate:.1f}%"
        )
    except Exception as e:
        logger.error(f"归属测试失败: {code}: {e}")

    return result


def get_recent_posts(code: str, forum_type: str = "eastmoney",
                     limit: int = 20) -> list[dict]:
    """从 DB 缓存中获取最近的帖子（不重新爬取）。

    v1 2026-06-04：附带审计字段（actual_title, title_match, audit_status, post_id）。
    审计字段让前端可以在帖子列表展示审计 badge 和 diff 面板。
    """
    code = str(code).strip().zfill(6)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, title, actual_title, title_match, audit_status,
                      title_verified_at, content, author, post_time, url
               FROM forum_posts
               WHERE stock_code=? AND forum_type=?
                 AND (audit_status IS NULL OR audit_status != 'broken')
               ORDER BY post_time DESC LIMIT ?""",
            (code, forum_type, limit),
        )
        return [{
            "post_id": row["id"],
            "title": row["title"],
            "actual_title": row["actual_title"],
            "title_match": row["title_match"],
            "audit_status": row["audit_status"],
            "title_verified_at": row["title_verified_at"],
            "content": row["content"] or "",
            "author": row["author"],
            "post_time": row["post_time"],
            "url": row["url"],
        } for row in cur.fetchall()]
