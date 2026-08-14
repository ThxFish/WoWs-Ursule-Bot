from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import async_playwright

from .collectors import ArmoryResponseCapture, CollectionError, save_storage_state, trigger_armory_wallet
from .config import config


ARMORY_URL = "https://armory.worldofwarships.eu/zh-sg/"
LOGIN_TIMEOUT_SECONDS = 10 * 60
_task: asyncio.Task | None = None
_status = {"state": "idle", "message": "尚未启动登录窗口", "updated_at": None}


def interactive_login_available() -> bool:
    return sys.platform == "win32" or bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def login_status() -> dict:
    return dict(_status)


def _set_status(state: str, message: str) -> None:
    _status.update({"state": state, "message": message[:1000], "updated_at": datetime.now(timezone.utc)})


async def run_interactive_login(destination: Path | None = None) -> None:
    state_path = destination or config.data_dir / "auth" / "armory-storage.json"
    if not interactive_login_available():
        raise CollectionError("当前主机没有图形桌面，无法弹出登录窗口；请在 Windows 登录后导入 storage_state")
    _set_status("opening", "正在打开 Chromium；若已有登录状态，将自动复用")
    capture = ArmoryResponseCapture()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context_options = {}
        if state_path.exists():
            context_options["storage_state"] = str(state_path)
        context = await browser.new_context(**context_options)
        watched_pages = set()

        def watch_page(page) -> None:
            if page in watched_pages:
                return
            watched_pages.add(page)
            page.on("response", capture.handle)

        context.on("page", watch_page)
        page = await context.new_page()
        watch_page(page)
        _set_status("waiting", "请在弹出的窗口完成登录；资源加载成功后窗口会自动关闭")
        try:
            await page.goto(ARMORY_URL, wait_until="domcontentloaded", timeout=60_000)
            wallet_triggered = False
            for _ in range(LOGIN_TIMEOUT_SECONDS * 2):
                if capture.ready():
                    await save_storage_state(context, state_path)
                    _set_status("success", f"登录状态已保存，已识别资源和物品数据。{capture.diagnostic()}")
                    return
                if not browser.is_connected():
                    raise CollectionError("登录窗口已关闭，但尚未获取到完整资源数据")
                if not capture.has_inventory and not wallet_triggered:
                    for candidate_page in reversed(context.pages):
                        if await trigger_armory_wallet(candidate_page):
                            wallet_triggered = True
                            _set_status("waiting", "已自动打开钱包，正在读取资源和物品数据")
                            break
                await asyncio.sleep(0.5)
            raise CollectionError(f"登录等待超时。{capture.diagnostic()}")
        finally:
            if browser.is_connected():
                await browser.close()


def start_interactive_login(on_success: Callable[[], Awaitable[None]] | None = None) -> bool:
    global _task
    if _task and not _task.done():
        return False

    async def runner() -> None:
        try:
            await run_interactive_login()
            if on_success:
                _set_status("syncing", "登录成功，正在自动同步军械库数据")
                await on_success()
                _set_status("success", "登录成功，军械库数据已自动同步并保存为新快照")
        except Exception as exc:
            _set_status("error", str(exc))

    _task = asyncio.create_task(runner())
    return True
