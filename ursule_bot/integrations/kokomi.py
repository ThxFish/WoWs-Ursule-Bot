from __future__ import annotations

from urllib.parse import urlparse

import httpx


DEFAULT_API_URL = "http://43.133.59.53:8000/bot/"
DEFAULT_API_TOKEN = "user"
CLIENT_TYPE = "ursule-bot"
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class KokomiCommandError(RuntimeError):
    pass


async def execute_kokomi_message(
    message: str,
    *,
    user_id: str,
    channel_id: str,
    api_url: str = DEFAULT_API_URL,
    token: str = DEFAULT_API_TOKEN,
) -> tuple[str, bytes | None]:
    """Execute one Kokomi-compatible command and normalize its reply."""
    params = {
        "token": token,
        "user_id": user_id,
        "message": message,
        "platform": "qq_bot",
        "platform_id": CLIENT_TYPE,
        "channel_id": channel_id,
    }
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        response = await client.get(api_url, params=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise KokomiCommandError("战绩兼容服务返回了无效数据。") from exc

        reply_type = payload.get("type")
        if reply_type == "msg":
            text = str(payload.get("msg") or "").strip()
            if not text:
                raise KokomiCommandError("战绩兼容服务返回了空消息。")
            return text, None
        if reply_type != "img":
            raise KokomiCommandError("战绩兼容服务返回了未知消息类型。")

        image_url = str(payload.get("img") or "")
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise KokomiCommandError("战绩兼容服务返回了无效图片地址。")
        image_response = await client.get(image_url)
        image_response.raise_for_status()
        content_type = image_response.headers.get("content-type", "").lower()
        image = image_response.content
        if not content_type.startswith("image/") or not image or len(image) > MAX_IMAGE_BYTES:
            raise KokomiCommandError("战绩兼容服务返回的图片无效或过大。")
        return "战绩查询结果", image
