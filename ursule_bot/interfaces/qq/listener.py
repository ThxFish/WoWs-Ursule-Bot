from __future__ import annotations

import asyncio
import base64
import logging
import time
import traceback
from collections import OrderedDict

import botpy
from botpy.http import Route
from botpy.message import C2CMessage, GroupMessage

from ...centers.planning.models import utcnow
from ...core.database import SessionLocal
from ...core.settings import get_setting
from ...core.system_models import DataSourceStatus
from ...integrations.notifications import parse_group_openids
from .commands import execute_command, parse_command
from .types import BotReply


Route.DOMAIN = "api.bot.qq.com"
Route.SANDBOX_DOMAIN = "sandbox.api.bot.qq.com"

MESSAGE_RATE_SECONDS = 2
MAX_REPLY_LENGTH = 1800
MAX_REPLAY_IDS = 512

logger = logging.getLogger(__name__)


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


class UrsuleQQClient(botpy.Client):
    def __init__(self):
        super().__init__(intents=botpy.Intents(public_messages=True), bot_log=False)
        self._last_request: dict[str, float] = {}
        self._seen_ids: OrderedDict[str, float] = OrderedDict()

    async def on_ready(self):
        _listener_status(True, "QQ 命令监听已连接")

    async def on_error(self, event_method: str, *args, **kwargs):
        logger.error("QQ event handler failed: %s\n%s", event_method, traceback.format_exc())
        # botpy isolates event callbacks in their own tasks. A failed command
        # does not mean that the gateway listener has disconnected.
        _listener_status(True, f"QQ 单次事件处理失败：{event_method}；监听仍在继续")

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

    async def _dispatch(self, content: str, message_id: str, scope: str) -> BotReply | None:
        command = parse_command(content)
        if command is None or not self._accept_message(message_id, scope):
            return None
        try:
            result = await asyncio.wait_for(execute_command(command), timeout=150)
            return BotReply(result.truncated_text(MAX_REPLY_LENGTH), image=result.image, image_alt=result.image_alt)
        except asyncio.TimeoutError:
            return BotReply("命令执行超时，请稍后重试。")
        except Exception as exc:
            logger.exception("QQ command execution failed: %s", command.partition(" ")[0])
            _listener_status(True, f"QQ 指令执行失败：{type(exc).__name__}；监听仍在继续")
            try:
                from ...integrations.kokomi import KokomiCommandError

                if isinstance(exc, KokomiCommandError):
                    return BotReply(str(exc))
            except ImportError:
                pass
            return BotReply("命令执行失败，请稍后重试；机器人仍会继续监听后续指令。")

    @staticmethod
    async def _upload_image(message: C2CMessage | GroupMessage, target_id: str, image: bytes, *, group: bool):
        """Upload image bytes through QQ's rich-media endpoint.

        qq-botpy 1.2.1 only exposes URL uploads, while the API also accepts
        base64 file_data. Use the SDK transport so authentication and routing
        remain owned by the connected client.
        """
        route_path = "/v2/groups/{target_id}/files" if group else "/v2/users/{target_id}/files"
        route = Route("POST", route_path, target_id=target_id)
        payload = {
            "file_type": 1,
            "file_data": base64.b64encode(image).decode("ascii"),
            "srv_send_msg": False,
        }
        return await message._api._http.request(route, json=payload)

    async def _send_reply(
        self,
        message: C2CMessage | GroupMessage,
        response: BotReply,
        target_id: str,
        *,
        group: bool,
    ) -> None:
        try:
            if response.image:
                media = await self._upload_image(message, target_id, response.image, group=group)
                await message.reply(msg_type=7, content=response.text, media=media)
            else:
                await message.reply(msg_type=0, content=response.text)
        except Exception as exc:
            logger.exception("QQ reply failed; listener remains active")
            _listener_status(True, f"QQ 回复发送失败：{type(exc).__name__}；监听仍在继续")
            if not response.image:
                return
            try:
                await message.reply(
                    msg_type=0,
                    msg_seq=2,
                    content="查询已完成，但结果图片发送失败，请稍后重试；机器人仍在继续监听。",
                )
            except Exception:
                logger.exception("QQ fallback error reply also failed")

    async def on_c2c_message_create(self, message: C2CMessage):
        with SessionLocal() as db:
            allowed_user = get_setting(db, "qq_user_openid") or (get_setting(db, "qq_target_id") if get_setting(db, "qq_target_type", "user") == "user" else "")
        user_openid = message.author.user_openid or ""
        if not allowed_user or user_openid != allowed_user:
            return
        response = await self._dispatch(message.content, message.id, f"user:{user_openid}")
        if response:
            await self._send_reply(message, response, user_openid, group=False)

    async def on_group_at_message_create(self, message: GroupMessage):
        with SessionLocal() as db:
            configured_groups = get_setting(db, "qq_group_openid") or (get_setting(db, "qq_target_id") if get_setting(db, "qq_target_type", "user") == "group" else "")
            allowed_groups = set(parse_group_openids(configured_groups))
        group_openid = message.group_openid or ""
        if group_openid not in allowed_groups:
            return
        response = await self._dispatch(message.content, message.id, f"group:{group_openid}")
        if response:
            await self._send_reply(message, response, group_openid, group=True)


def configured_credentials() -> tuple[str, str] | None:
    with SessionLocal() as db:
        app_id = get_setting(db, "qq_app_id")
        secret = get_setting(db, "qq_app_secret")
    return (app_id, secret) if app_id and secret else None


async def start_listener() -> tuple[UrsuleQQClient, asyncio.Task] | None:
    credentials = configured_credentials()
    if not credentials:
        _listener_status(False, "QQ AppID 或 AppSecret 未配置，命令监听未启动")
        return None
    client = UrsuleQQClient()
    task = asyncio.create_task(client.start(appid=credentials[0], secret=credentials[1]), name="qq-command-listener")
    def record_failure(completed: asyncio.Task) -> None:
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            _listener_status(False, f"QQ 命令监听连接失败：{type(error).__name__}")
    task.add_done_callback(record_failure)
    return client, task
