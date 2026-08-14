from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "data" / "auth" / "armory-storage.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    print("即将打开欧服军械库。请在浏览器中完成登录，确认能看到账号资源后返回此窗口。")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://armory.worldofwarships.eu/zh-sg/")
        input("登录完成后按 Enter 保存登录状态……")
        await context.storage_state(path=str(destination))
        await browser.close()
    print(f"已保存：{destination}")
    print("该文件包含敏感登录 Cookie，请勿分享或提交到 Git。")


if __name__ == "__main__":
    asyncio.run(main())

