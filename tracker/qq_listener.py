from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

import botpy
from botpy.http import Route
from botpy.message import C2CMessage, GroupMessage

from .db import SessionLocal
from .models import DataSourceStatus, utcnow
from .qq_commands import execute_command, parse_command
from .settings import get_setting


Route.DOMAIN = "api.bot.qq.com"
Route.SANDBOX_DOMAIN = "sandbox.api.bot.qq.com"

SYNC_COOLDOWN_SECONDS = 300
MESSAGE_RATE_SECONDS = 2
MAX_REPLY_LENGTH = 1800
MAX_REPLAY_IDS = 512


def _listener_status(ok: bool, message: str) -> None:
    with SessionLocal() as db:
        row = db.get(DataSourceStatus, "qq_listener") or DataSourceStatus(name="qq_listener")
        row.ok = ok
        row.message = message[:500]
        row.last_attempt_at = utcnow()
        if ok:
            row.last_success_at = utcnow()
        db.add(row)
        db.commit()


class TrackerQQClient(botpy.Client):
    def __init__(self):
        super().__init__(intents=botpy.Intents(public_messages=True), bot_log=False)
        self._last_request: dict[str, float] = {}
        self._sync_last_at = 0.0
        self._seen_ids: OrderedDict[str, float] = OrderedDict()

    async def on_ready(self):
        _listener_status(True, "QQ 命令监听已连接")

    async def on_error(self, event_method: str, *args, **kwargs):
        _listener_status(False, f"QQ 事件处理失败：{event_method}")

    def _accept_message(self, message_id: str, scope: str) -> bool:
        now = time.monotonic()
        if message_id in self._seen_ids:
            return False
        self._seen_ids[message_id] = now
        while len(self._seen_ids) > MAX_REPLAY_IDS:
            self._seen_ids.popitem(last=False)
        last = self._last_request.get(scope, 0.0)
        if now - last < MESSAGE_RATE_SECONDS:
            return False
        self._last_request[scope] = now
        return True

    async def _dispatch(self, content: str, message_id: str, scope: str, allow_sync: bool) -> str | None:
        command = parse_command(content)
        if command is None or not self._accept_message(message_id, scope):
            return None
        if command == "同步" and allow_sync:
            now = time.monotonic()
            if now - self._sync_last_at < SYNC_COOLDOWN_SECONDS:
                remaining = int(SYNC_COOLDOWN_SECONDS - (now - self._sync_last_at))
                return f"同步冷却中，请在 {remaining} 秒后重试。"
            self._sync_last_at = now
        try:
            result = await asyncio.wait_for(execute_command(command, allow_sync=allow_sync), timeout=150)
            return result[:MAX_REPLY_LENGTH]
        except asyncio.TimeoutError:
            return "命令执行超时，请稍后重试。"
        except Exception:
            return "命令执行失败，详细原因已记录在服务端；敏感信息不会通过 QQ 返回。"

    async def on_c2c_message_create(self, message: C2CMessage):
        with SessionLocal() as db:
            allowed_user = get_setting(db, "qq_user_openid") or (get_setting(db, "qq_target_id") if get_setting(db, "qq_target_type", "user") == "user" else "")
        user_openid = message.author.user_openid or ""
        if not allowed_user or user_openid != allowed_user:
            return
        response = await self._dispatch(message.content, message.id, f"user:{user_openid}", allow_sync=True)
        if response:
            await message.reply(msg_type=0, content=response)

    async def on_group_at_message_create(self, message: GroupMessage):
        with SessionLocal() as db:
            allowed_group = get_setting(db, "qq_group_openid") or (get_setting(db, "qq_target_id") if get_setting(db, "qq_target_type", "user") == "group" else "")
        group_openid = message.group_openid or ""
        if not allowed_group or group_openid != allowed_group:
            return
        response = await self._dispatch(message.content, message.id, f"group:{group_openid}", allow_sync=False)
        if response:
            await message.reply(msg_type=0, content=response)


def configured_credentials() -> tuple[str, str] | None:
    with SessionLocal() as db:
        app_id = get_setting(db, "qq_app_id")
        secret = get_setting(db, "qq_app_secret")
    return (app_id, secret) if app_id and secret else None


async def start_listener() -> tuple[TrackerQQClient, asyncio.Task] | None:
    credentials = configured_credentials()
    if not credentials:
        _listener_status(False, "QQ AppID 或 AppSecret 未配置，命令监听未启动")
        return None
    client = TrackerQQClient()
    task = asyncio.create_task(client.start(appid=credentials[0], secret=credentials[1]), name="qq-command-listener")
    def record_failure(completed: asyncio.Task) -> None:
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            _listener_status(False, f"QQ 命令监听连接失败：{type(error).__name__}")
    task.add_done_callback(record_failure)
    return client, task
