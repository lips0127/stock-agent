"""guba 验证码墙 cookie 采集工具（运维用，非业务代码）。

2026-08-31 复盘：guba 的「身份核实」引导壳是速率型反爬 + 静默 JS 挑战。
真实浏览器会自动通过挑战并种下"已验证"访客 cookie；脚本请求一旦触发
限流，需要携带这类新鲜 cookie 才能继续取数（旧 cookie 失效即"session
过期"现象）。

用法：
    python -m tools.guba_cookie_harvest          # 采集并写 $CACHE_DIR/guba_cookies.json
    python -m tools.guba_cookie_harvest --verify # 采集后立即验证有效性

cookie 文件路径为 $CACHE_DIR/guba_cookies.json（与 stocks.db 同目录、
Docker 中位于 /data 卷，重建容器不丢）；forum_service 启动及 stale 探测
时会自动热加载该文件，采集后约 1 分钟内生效，无需重启。
"""
import asyncio
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__import__("os").environ.get("CACHE_DIR", str(PROJECT_ROOT)))
COOKIE_FILE = CACHE_DIR / "guba_cookies.json"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

PROBE_URL = "https://guba.eastmoney.com/list,600584.html"


async def harvest() -> list[dict]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=EDGE,
            headless=True,
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )
        page = await ctx.new_page()
        print(f"[harvest] 打开 {PROBE_URL}，等待静默挑战通过...")
        await page.goto(PROBE_URL, wait_until="domcontentloaded", timeout=30000)

        # 挑战页会自动检测浏览器环境；通过后 SPA 渲染出帖子数据。
        # 轮询等待页面出现真实内容（article_list JSON 或 .listitem 等节点），
        # 最多等 25s。
        ok = False
        for _ in range(25):
            await page.wait_for_timeout(1000)
            html = await page.content()
            if "article_list" in html or "listitem" in html:
                ok = True
                break
        print(f"[harvest] 页面内容出现: {ok}（title={await page.title()!r}）")

        cookies = await ctx.cookies()
        await browser.close()

    em = [c for c in cookies if "eastmoney" in c["domain"]]
    print(f"[harvest] 共 {len(em)} 条 eastmoney cookie")
    COOKIE_FILE.write_text(
        json.dumps(em, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[harvest] 已写入 {COOKIE_FILE}（不入 Git）")
    return em
def verify_sync(cookies: list[dict]) -> bool:
    """用采集到的 cookie 同步请求验证能否拿到列表正文。"""
    import requests

    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        ),
    })
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c["domain"])
    r = s.get(PROBE_URL, timeout=15)
    ok = "article_list" in r.text
    print(f"[verify] 列表页 len={len(r.text)} 正文可见={ok}")
    return ok


def main():
    cookies = asyncio.run(harvest())
    if "--verify" in sys.argv:
        if verify_sync(cookies):
            print("[verify] 通过：cookie 文件可用，服务将在约 1 分钟内热加载")
            return
        # 坏采集（挑战未完成时种下的凭证可能被 CDN 拒绝）→ 立即弃用，
        # 避免毒害服务侧请求。等几分钟或换时段重跑本工具。
        COOKIE_FILE.unlink(missing_ok=True)
        print("[verify] 失败：本次采集无效，已删除 cookie 文件；请稍后重试")
        sys.exit(1)


if __name__ == "__main__":
    main()
