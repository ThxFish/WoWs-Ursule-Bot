import httpx
import pytest

from ursule_bot.integrations.kokomi import KokomiCommandError, execute_kokomi_message


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", content_type="application/json"):
        self._payload = payload
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses, **kwargs):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return next(self.responses)


@pytest.mark.asyncio
async def test_kokomi_adapter_returns_text(monkeypatch):
    client = FakeClient([FakeResponse(payload={"type": "msg", "msg": "查询成功"})])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    text, image = await execute_kokomi_message("eu500 recent", user_id="500", channel_id="500")

    assert (text, image) == ("查询成功", None)
    assert client.requests[0][1]["params"]["message"] == "eu500 recent"


@pytest.mark.asyncio
async def test_kokomi_adapter_downloads_valid_image(monkeypatch):
    client = FakeClient([
        FakeResponse(payload={"type": "img", "img": "https://example.com/result.png"}),
        FakeResponse(content=b"png", content_type="image/png"),
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    text, image = await execute_kokomi_message("help", user_id="500", channel_id="500")

    assert text == "战绩查询结果"
    assert image == b"png"


@pytest.mark.asyncio
async def test_kokomi_adapter_rejects_non_image(monkeypatch):
    client = FakeClient([
        FakeResponse(payload={"type": "img", "img": "https://example.com/result.png"}),
        FakeResponse(content=b"html", content_type="text/html"),
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    with pytest.raises(KokomiCommandError):
        await execute_kokomi_message("help", user_id="500", channel_id="500")
