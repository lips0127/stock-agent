"""检查登录页 DOM 找正确 selector。"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=True,
        )
        page = await browser.new_page()
        await page.goto("http://localhost:5000", wait_until="networkidle")
        # 打印所有 button 的文本
        buttons = await page.query_selector_all("button")
        print(f"=== {len(buttons)} 个 button ===")
        for b in buttons:
            txt = (await b.inner_text()).strip()
            print(f"  button: {txt!r}")
        # 打印所有 input
        inputs = await page.query_selector_all("input")
        print(f"\n=== {len(inputs)} 个 input ===")
        for i in inputs:
            ph = await i.get_attribute("placeholder")
            t = await i.get_attribute("type")
            print(f"  input: type={t!r} placeholder={ph!r}")
        # 打印所有 a
        links = await page.query_selector_all("a")
        print(f"\n=== {len(links)} 个 a ===")
        for a in links[:10]:
            txt = (await a.inner_text()).strip()
            print(f"  a: {txt!r}")
        await page.screenshot(path="/tmp/screenshots/login_inspect.png", full_page=True)
        await browser.close()

asyncio.run(main())
