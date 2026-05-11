"""
东财股吧论坛爬取服务。
从 guba.eastmoney.com 获取股票社区帖子数据。
"""

import re
import json
import time
import logging
import requests
from datetime import datetime
from backend.core.database import get_connection
from backend.services.stock_service import _no_proxy

logger = logging.getLogger(__name__)

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
            with _no_proxy():
                r = requests.get(url, headers=HEADERS, timeout=15)
            r.encoding = "utf-8"

            if r.status_code != 200:
                break

            data = _extract_json(r.text, "article_list")
            if not data:
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

        except (json.JSONDecodeError, requests.RequestException) as e:
            logger.error(f"获取股吧帖子列表失败: {code} page={page}: {e}")
            break

    # 按活跃时间降序排列
    posts.sort(key=lambda p: p.get("last_time") or p.get("publish_time") or "", reverse=True)
    logger.info(f"获取股吧帖子: {code} 最近{days}天共 {len(posts)} 条")
    return posts


def fetch_post_content(code: str, post_id: str) -> str | None:
    """获取单条帖子的正文内容。

    Args:
        code: 6位股票代码
        post_id: 帖子ID

    Returns:
        帖子正文文本，失败返回 None
    """
    code = str(code).strip().zfill(6)
    url = GUBA_POST_URL.format(code=code, post_id=post_id)

    try:
        with _no_proxy():
            r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "utf-8"

        if r.status_code != 200:
            return None

        # 提取帖子正文
        data = _extract_json(r.text, "post_article")
        if data:
            content = data.get("post_content", "")
            if content:
                # 去除 HTML 标签
                content = re.sub(r"<[^>]+>", "", content)
                content = re.sub(r"&nbsp;", " ", content)
                content = re.sub(r"\s+", " ", content).strip()
                return content

        # 回退：尝试直接从 HTML 提取
        match = re.search(
            r'<div[^>]*class="[^"]*stockcodec[^"]*"[^>]*>(.*?)</div>',
            r.text, re.DOTALL
        )
        if match:
            content = match.group(1)
            content = re.sub(r"<[^>]+>", "", content)
            content = re.sub(r"\s+", " ", content).strip()
            return content
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.warning(f"获取帖子内容失败 {post_id}: {e}")

    return None


def fetch_forum_posts(code: str, forum_type: str = "eastmoney",
                      days: int = 7, fetch_content: bool = True) -> list[dict]:
    """获取股票论坛帖子（爬取 + 缓存到 DB）。

    Args:
        code: 6位股票代码
        forum_type: 论坛类型，目前仅支持 eastmoney
        days: 取最近多少天的帖子（默认7天）
        fetch_content: 是否获取帖子正文

    Returns:
        帖子列表，每条含 title, content, author, post_time 等字段
    """
    if forum_type != "eastmoney":
        logger.warning(f"暂不支持的论坛类型: {forum_type}")
        return []

    code = str(code).strip().zfill(6)
    posts = fetch_post_list(code, days=days, max_posts=100)

    if not posts:
        return []

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
        # 对没有内容的帖子补充正文（包括缓存中已有的）
        posts_need_content = []
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT url FROM forum_posts
                   WHERE stock_code=? AND forum_type=? AND (content IS NULL OR content='')""",
                (code, forum_type),
            )
            posts_need_content = [row["url"] for row in cur.fetchall()]

        for url in posts_need_content:
            # 从 URL 提取 post_id: .../news,{code},{post_id}.html
            pid_match = re.search(r"/news,\d+,(\d+)\.html", url)
            if not pid_match:
                continue
            post_id = pid_match.group(1)
            content = fetch_post_content(code, post_id)
            if content:
                try:
                    with get_connection() as conn:
                        conn.cursor().execute(
                            "UPDATE forum_posts SET content=? WHERE url=?",
                            (content, url),
                        )
                except Exception:
                    pass
            time.sleep(0.3)  # 避免请求过快

    # 返回所有帖子
    result = []
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT title, content, author, post_time, url FROM forum_posts
               WHERE stock_code=? AND forum_type=?
               ORDER BY post_time DESC LIMIT 100""",
            (code, forum_type),
        )
        for row in cur.fetchall():
            result.append({
                "title": row["title"],
                "content": row["content"] or "",
                "author": row["author"],
                "post_time": row["post_time"],
                "url": row["url"],
            })

    return result


def get_recent_posts(code: str, forum_type: str = "eastmoney",
                     limit: int = 20) -> list[dict]:
    """从 DB 缓存中获取最近的帖子（不重新爬取）。"""
    code = str(code).strip().zfill(6)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT title, content, author, post_time, url FROM forum_posts
               WHERE stock_code=? AND forum_type=?
               ORDER BY post_time DESC LIMIT ?""",
            (code, forum_type, limit),
        )
        return [{
            "title": row["title"],
            "content": row["content"] or "",
            "author": row["author"],
            "post_time": row["post_time"],
            "url": row["url"],
        } for row in cur.fetchall()]
