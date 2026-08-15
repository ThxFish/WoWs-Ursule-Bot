import base64

import pytest

from ursule_bot.interfaces.qq import listener
from ursule_bot.interfaces.qq.types import BotReply


class FakeHTTP:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.payload = None

    async def request(self, route, *, json):
        if self.fail:
            raise RuntimeError("upload failed")
        self.payload = json
        return {"file_info": "media-token"}


class FakeMessage:
    def __init__(self, *, upload_fails=False):
        self._api = type("API", (), {"_http": FakeHTTP(fail=upload_fails)})()
        self.replies = []

    async def reply(self, **kwargs):
        self.replies.append(kwargs)


def make_client():
    return object.__new__(listener.UrsuleQQClient)


@pytest.mark.asyncio
async def test_image_reply_uses_qq_rich_media_upload():
    client = make_client()
    message = FakeMessage()

    await client._send_reply(message, BotReply("查询结果", image=b"png"), "openid", group=False)

    assert message._api._http.payload["file_type"] == 1
    assert base64.b64decode(message._api._http.payload["file_data"]) == b"png"
    assert message.replies == [
        {"msg_type": 7, "content": "查询结果", "media": {"file_info": "media-token"}}
    ]


@pytest.mark.asyncio
async def test_failed_image_upload_returns_text_and_does_not_escape(monkeypatch):
    statuses = []
    monkeypatch.setattr(listener, "_listener_status", lambda ok, text: statuses.append((ok, text)))
    client = make_client()
    message = FakeMessage(upload_fails=True)

    await client._send_reply(message, BotReply("查询结果", image=b"png"), "openid", group=False)

    assert statuses[-1][0] is True
    assert "监听仍在继续" in statuses[-1][1]
    assert message.replies[0]["msg_type"] == 0
    assert "图片发送失败" in message.replies[0]["content"]


@pytest.mark.asyncio
async def test_command_error_is_returned_without_stopping_listener(monkeypatch):
    async def fail_command(command):
        raise RuntimeError("private upstream detail")

    statuses = []
    monkeypatch.setattr(listener, "execute_command", fail_command)
    monkeypatch.setattr(listener, "_listener_status", lambda ok, text: statuses.append((ok, text)))
    client = make_client()
    client._accept_message = lambda message_id, scope: True

    response = await client._dispatch("/ship 蒙大拿", "message-id", "user:openid")

    assert response is not None
    assert "命令执行失败" in response.text
    assert "继续监听" in response.text
    assert statuses[-1][0] is True

