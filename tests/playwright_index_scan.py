"""演示 POST /api/index_scan 的前端表现：跳到 fake scan_index 任务的 ScanProgressView。"""
import asyncio
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = sys.stdout

from playwright.async_api import async_playwright

BASE = "http://localhost:5000"
SHOT_DIR = "/tmp/screenshots"
FAKE_INDEX_TASK = "bbbb2222cccc3333dddd4444eeee5555"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=True,
        )
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = await ctx.new_page()

        # 登录
        print("=== 1. 登录 ===")
        await page.goto(BASE, wait_until="networkidle")
        for inp in await page.query_selector_all("input"):
            ph = await inp.get_attribute("placeholder")
            if ph and "用户" in ph:
                await inp.fill("admin")
            elif ph and "密码" in ph:
                await inp.fill("admin123")
        btn = await page.query_selector("button")
        await btn.click()
        await page.wait_for_url("**/dashboard**", timeout=15000)
        await page.wait_for_load_state("networkidle")

        # 截图 Dashboard 顶部按钮（看红利指数扫描入口）
        print("=== 2. Dashboard 顶部按钮 ===")
        await page.screenshot(path=f"{SHOT_DIR}/07_dashboard_buttons.png")
        for el in await page.query_selector_all("button"):
            txt = (await el.inner_text()).strip()
            if "红利" in txt or "全市场" in txt:
                print(f"  按钮: {txt!r}")

        # 跳到 fake scan_index 任务页
        print(f"=== 3. 打开 /scan/{FAKE_INDEX_TASK[:8]}... (scan_index 完成态) ===")
        await page.goto(f"{BASE}/scan/{FAKE_INDEX_TASK}", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{SHOT_DIR}/08_index_scan_complete.png", full_page=True)

        # 输出 stat-card
        for card in await page.query_selector_all(".stat-card"):
            label = await card.query_selector(".stat-card__label")
            value = await card.query_selector(".stat-card__value")
            if label and value:
                print(f"  {(await label.inner_text()).strip()}: {(await value.inner_text()).strip()}")

        # banner
        banner = await page.query_selector(".result-banner")
        if banner:
            title = await banner.query_selector(".result-banner__title")
            detail = await banner.query_selector(".result-banner__detail")
            tone = await banner.get_attribute("class")
            print(f"  banner tone: {tone}")
            if title: print(f"    title:  {(await title.inner_text()).strip()}")
            if detail: print(f"    detail: {(await detail.inner_text()).strip()}")

        # 展开日志
        print("=== 4. 展开日志面板 ===")
        for el in await page.query_selector_all("button"):
            txt = (await el.inner_text()).strip()
            if "日志" in txt:
                await el.click()
                print(f"  clicked: {txt!r}")
                break
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{SHOT_DIR}/09_index_scan_logs.png", full_page=True)
        for line in await page.query_selector_all(".log-line"):
            level = await line.query_selector(".log-line__level")
            msg = await line.query_selector(".log-line__msg")
            if level and msg:
                print(f"  [{await level.inner_text()}] {(await msg.inner_text())[:80]}")

        # 任务中心
        print("=== 5. 任务中心 ===")
        # 点 "任务调度" 导航
        for el in await page.query_selector_all("a, .el-menu-item, li"):
            txt = (await el.inner_text()).strip()
            if "任务" in txt:
                await el.click()
                print(f"  clicked: {txt!r}")
                break
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{SHOT_DIR}/10_task_center_with_index.png", full_page=True)

        await browser.close()
        print("\n=== 截图列表 ===")
        import os
        for f in sorted(os.listdir(SHOT_DIR)):
            if f.startswith(("07_", "08_", "09_", "10_")):
                sz = os.path.getsize(f"{SHOT_DIR}/{f}")
                print(f"  {f}  ({sz/1024:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
