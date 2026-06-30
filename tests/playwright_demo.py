"""Playwright 演示脚本：演示修复后的失败信号可观测性。

策略：
1. 登录
2. 直接打开 fake task 的 ScanProgressView（fail_count=520）
3. 截图展示 5 张卡片 + 完成横幅 + 日志面板
"""
import asyncio
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = sys.stdout

from playwright.async_api import async_playwright

BASE = "http://localhost:5000"
SHOT_DIR = "/tmp/screenshots"
FAKE_TASK_ID = "aaaa1111bbbb2222cccc3333dddd4444"  # fail_count=520, status=success


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=True,
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await ctx.new_page()
        page.on("pageerror", lambda err: print(f"  [pageerror] {err}"))

        # === 1. 登录 ===
        print("\n=== 1. 登录 ===")
        await page.goto(BASE, wait_until="networkidle")
        await page.screenshot(path=f"{SHOT_DIR}/01_login.png")
        inputs = await page.query_selector_all("input")
        for inp in inputs:
            ph = await inp.get_attribute("placeholder")
            if ph and "用户" in ph:
                await inp.fill("admin")
            elif ph and "密码" in ph:
                await inp.fill("admin123")
        btn = await page.query_selector("button")
        await btn.click()
        await page.wait_for_url("**/dashboard**", timeout=15000)
        await page.wait_for_load_state("networkidle")
        print("  logged in")

        # === 2. Dashboard 截图 ===
        print("\n=== 2. Dashboard 截图 ===")
        await page.screenshot(path=f"{SHOT_DIR}/02_dashboard.png", full_page=True)

        # === 3. 触发真实全量扫描（拿 task_id，1s 后再切到 fake task）===
        print("\n=== 3. 触发 POST /api/full_refresh（看真实 task 启动） ===")
        for el in await page.query_selector_all("button"):
            txt = (await el.inner_text()).strip()
            if "全市场扫描" in txt:
                await el.click()
                print(f"  clicked: {txt!r}")
                break
        await page.wait_for_timeout(3000)
        real_task_id = await page.evaluate("""() => {
            const pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
            if (!pinia) return null
            const store = pinia._s.get('task')
            return store?.taskId || null
        }""")
        print(f"  真实 task_id: {real_task_id!r}")

        # === 4. 跳到 fake task 演示完成态（fail_count=520, status=success） ===
        print(f"\n=== 4. 打开 /scan/{FAKE_TASK_ID[:8]}... 展示完成态 ===")
        await page.goto(f"{BASE}/scan/{FAKE_TASK_ID}", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{SHOT_DIR}/03_scan_complete_with_failures.png", full_page=True)

        # 打印 stat-card
        stat_cards = await page.query_selector_all(".stat-card")
        print(f"  stat-card 数量: {len(stat_cards)}")
        for card in stat_cards:
            label = await card.query_selector(".stat-card__label")
            value = await card.query_selector(".stat-card__value")
            if label and value:
                l = (await label.inner_text()).strip()
                v = (await value.inner_text()).strip()
                print(f"    {l}: {v}")

        # 打印 result-banner
        banner = await page.query_selector(".result-banner")
        if banner:
            title = await banner.query_selector(".result-banner__title")
            detail = await banner.query_selector(".result-banner__detail")
            tone = await banner.get_attribute("class")
            print(f"  result-banner tone: {tone}")
            if title:
                print(f"    title:   {(await title.inner_text()).strip()}")
            if detail:
                print(f"    detail:  {(await detail.inner_text()).strip()}")

        # === 5. 展开日志面板 ===
        print("\n=== 5. 展开任务日志面板 ===")
        # 找包含"日志"和数字的按钮
        log_btn = None
        for el in await page.query_selector_all("button"):
            txt = (await el.inner_text()).strip()
            if "日志" in txt:
                log_btn = el
                print(f"  found: {txt!r}")
                break
        if log_btn:
            await log_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=f"{SHOT_DIR}/04_logs_panel_expanded.png", full_page=True)
            log_lines = await page.query_selector_all(".log-line")
            print(f"  log-line 数量: {len(log_lines)}")
            for line in log_lines:
                msg_el = await line.query_selector(".log-line__msg")
                level_el = await line.query_selector(".log-line__level")
                if msg_el and level_el:
                    print(f"    [{await level_el.inner_text()}] {(await msg_el.inner_text())[:80]}")

        # === 6. 跳到任务中心（任务列表） ===
        print("\n=== 6. 打开任务中心（任务列表） ===")
        # 找左侧菜单里的"任务调度"
        for el in await page.query_selector_all(".el-menu-item, a, li"):
            txt = (await el.inner_text()).strip()
            if "任务" in txt and ("调度" in txt or "中心" in txt):
                await el.click()
                print(f"  clicked: {txt!r}")
                break
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{SHOT_DIR}/05_task_center.png", full_page=True)
        # 检查任务列表是否含 fail_count
        list_rows = await page.query_selector_all("tr, .task-row, .el-table__row")
        print(f"  table rows: {len(list_rows)}")

        # === 7. 跳回 ScanProgressView 但用真实的 task_id（演示 running 态） ===
        if real_task_id:
            print(f"\n=== 7. 跳到真实 task /scan/{real_task_id[:8]}... 展示 running 态 ===")
            await page.goto(f"{BASE}/scan/{real_task_id}", wait_until="networkidle")
            await page.wait_for_timeout(2500)
            await page.screenshot(path=f"{SHOT_DIR}/06_scan_running.png", full_page=True)
            stat_cards = await page.query_selector_all(".stat-card")
            print(f"  stat-card 数量: {len(stat_cards)}")
            for card in stat_cards:
                label = await card.query_selector(".stat-card__label")
                value = await card.query_selector(".stat-card__value")
                if label and value:
                    print(f"    {await label.inner_text()}: {await value.inner_text()}")

        await browser.close()
        print("\n=== 截图列表 ===")
        import os
        for f in sorted(os.listdir(SHOT_DIR)):
            sz = os.path.getsize(f"{SHOT_DIR}/{f}")
            print(f"  {f}  ({sz/1024:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
