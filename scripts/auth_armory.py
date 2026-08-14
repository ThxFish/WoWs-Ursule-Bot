from __future__ import annotations

import asyncio

from ursule_bot.integrations.armory_auth import login_status, run_interactive_login


async def main() -> None:
    print("即将打开欧服军械库；已有会话会自动复用，无需手动按 Enter。")
    await run_interactive_login()
    print(login_status()["message"])
    print("该文件包含敏感登录 Cookie，请勿分享或提交到 Git。")


if __name__ == "__main__":
    asyncio.run(main())
