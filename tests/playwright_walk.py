"""Playwright 演示脚本：逐一触发修复的接口并截图。"""
import asyncio
import io
import sys
import os

# 强制 stdout 用 utf-8 (Windows 默认 GBK)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = sys.stdout

from playwright.async_api import async_playwright

BASE = "http://localhost:5000"
SHOT_DIR = "/tmp/screenshots"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await ctx.new_page()
        page.on("console", lambda msg: print(f"  [console.{msg.type}] {msg.text[:100]}"))
        page.on("pageerror", lambda err: print(f"  [pageerror] {err}"))

        # Step 1: 打开根路径
        print("\n=== Step 1: 打开 http://localhost:5000 ===")
        await page.goto(BASE, wait_until="networkidle")
        await page.screenshot(path=f"{SHOT_DIR}/01_login.png")
        print(f"  title: {await page.title()!r}")
        print(f"  url: {page.url}")

        # Step 2: 登录
        print("\n=== Step 2: 登录 admin/admin123 ===")
        await page.wait_for_selector("input", timeout=10000)
        inputs = await page.query_selector_all("input")
        print(f"  found {len(inputs)} inputs")
        # 用 placeholder 区分用户名/密码输入框
        for inp in inputs:
            ph = await inp.get_attribute("placeholder")
            if ph and "用户" in ph:
                await inp.fill("admin")
            elif ph and "密码" in ph:
                await inp.fill("admin123")
        await page.screenshot(path=f"{SHOT_DIR}/02_login_filled.png")
        # 拿唯一的 button 直接点
        btn = await page.query_selector("button")
        await btn.click()
        await page.wait_for_url("**/dashboard**", timeout=15000)
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=f"{SHOT_DIR}/03_dashboard.png")
        print(f"  logged in, url: {page.url}")

        # Step 3: 触发全量扫描
        print("\n=== Step 3: 触发 POST /api/full_refresh ===")
        clicked = False
        for el in await page.query_selector_all("button"):
            txt = (await el.inner_text()).strip()
            if "全市场扫描" in txt:
                await el.click()
                clicked = True
                print(f"  clicked button: {txt!r}")
                break
        if not clicked:
            print("  找不到全市场扫描按钮")
        # 等 API 响应 + taskStore 更新 + ScanProgressBar 渲染"详情"链接
        await page.wait_for_timeout(5000)
        # 同时抓 taskStore 的 taskId
        task_id = await page.evaluate("""() => {
            const pinia = document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
            if (!pinia) return null
            const store = pinia._s.get('task')
            return store?.taskId || null
        }""")
        print(f"  taskId from store: {task_id!r}")
        if not task_id:
            print("  ERROR: taskId 为空，scan 没启动成功")
            await page.screenshot(path=f"{SHOT_DIR}/03b_dashboard_after_click.png", full_page=True)
        # 跳到扫描进度页
        if task_id:
            await page.goto(f"{BASE}/scan/{task_id}", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            await page.screenshot(path=f"{SHOT_DIR}/04_scan_progress_running.png", full_page=True)
            print(f"  navigated to: {page.url}")

        # 提取 task_id
        task_url = page.url
        task_id_full = task_url.split("/scan/")[1] if "/scan/" in task_url else "?"
        task_id = task_id_full[:8] + "..." if len(task_id_full) > 8 else task_id_full
        print(f"  task_id: {task_id}")

        # Step 4: 等任务完成（轮询直到 status != running）
        print("\n=== Step 4: 轮询等任务完成 ===")
        # 先拿 token（在浏览器侧）
        token = await page.evaluate("() => localStorage.getItem('token')")
        print(f"  token: {token[:20] if token else 'None'}...")
        # 构造带 Authorization header 的 request
        api_ctx = page.context.request

        for i in range(36):  # 最多 180s
            await page.wait_for_timeout(5000)
            elapsed = (i+1) * 5
            # 抓取进度数据
            resp = await api_ctx.get(f"{BASE}/api/tasks/{task_id}/progress",
                                      headers={"Authorization": f"Bearer {token}"})
            if not resp.ok:
                print(f"  +{elapsed}s: API error {resp.status}")
                continue
            data = await resp.json()
            task = data.get("task", {})
            status = task.get("status", "?")
            done = task.get("done", 0)
            total = task.get("total", 0)
            result_count = task.get("result_count", "?")
            fail_count = task.get("fail_count", "?")
            print(f"  +{elapsed}s: status={status} done={done}/{total} result={result_count} fail={fail_count}")
            if elapsed % 15 == 0 or status in ("success", "failed", "cancelled"):
                await page.screenshot(path=f"{SHOT_DIR}/05_scan_progress_{elapsed}s.png", full_page=True)
            if status in ("success", "failed", "cancelled"):
                break

        # Step 5: 最终状态截图 + DOM 检查
        print("\n=== Step 5: 最终状态 ===")
        await page.screenshot(path=f"{SHOT_DIR}/06_scan_final.png", full_page=True)
        stat_cards = await page.query_selector_all(".stat-card")
        print(f"  stat-card 数量: {len(stat_cards)}")
        for card in stat_cards:
            label = await card.query_selector(".stat-card__label")
            value = await card.query_selector(".stat-card__value")
            if label and value:
                l = (await label.inner_text()).strip()
                v = (await value.inner_text()).strip()
                print(f"    {l}: {v}")

        banner = await page.query_selector(".result-banner")
        if banner:
            title = await banner.query_selector(".result-banner__title")
            detail = await banner.query_selector(".result-banner__detail")
            tone_class = await banner.get_attribute("class")
            print(f"  result-banner tone: {tone_class}")
            if title:
                print(f"    title: {(await title.inner_text()).strip()}")
            if detail:
                print(f"    detail: {(await detail.inner_text()).strip()}")

        # Step 6: 展开日志面板
        print("\n=== Step 6: 展开日志面板 ===")
        log_btn = None
        for el in await page.query_selector_all("button, a"):
            txt = (await el.inner_text()).strip()
            if "查看" in txt and "日志" in txt:
                log_btn = el
                break
        if log_btn:
            await log_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=f"{SHOT_DIR}/07_logs_panel.png", full_page=True)
            log_lines = await page.query_selector_all(".log-line")
            print(f"  log-line 数量: {len(log_lines)}")
            for line in log_lines[:8]:
                msg = await line.query_selector(".log-line__msg")
                level = await line.query_selector(".log-line__level")
                if msg and level:
                    print(f"    [{await level.inner_text()}] {(await msg.inner_text())[:80]}")
        else:
            print("  找不到'查看日志'按钮")

        await browser.close()
        print("\n=== 截图列表 ===")
        import os
        for f in sorted(os.listdir(SHOT_DIR)):
            sz = os.path.getsize(f"{SHOT_DIR}/{f}")
            print(f"  {f}  ({sz/1024:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
