from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from .settings import get_setting


async def send_qq(db: Session, content: str) -> None:
    app_id = get_setting(db, "qq_app_id")
    secret = get_setting(db, "qq_app_secret")
    target_id = get_setting(db, "qq_target_id")
    target_type = get_setting(db, "qq_target_type", "user")
    if not all((app_id, secret, target_id)):
        raise RuntimeError("QQ 机器人配置不完整")
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post("https://bots.qq.com/app/getAppAccessToken", json={"appId": app_id, "clientSecret": secret})
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        path = f"/v2/groups/{target_id}/messages" if target_type == "group" else f"/v2/users/{target_id}/messages"
        response = await client.post(
            "https://api.sgroup.qq.com" + path,
            headers={"Authorization": f"QQBot {token}"},
            json={"content": content, "msg_type": 0},
        )
        response.raise_for_status()


def send_email(db: Session, subject: str, content: str) -> None:
    host = get_setting(db, "smtp_host")
    port = int(get_setting(db, "smtp_port", "465"))
    username = get_setting(db, "smtp_username")
    password = get_setting(db, "smtp_password")
    recipient = get_setting(db, "smtp_recipient")
    if not all((host, username, password, recipient)):
        raise RuntimeError("SMTP 配置不完整")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = recipient
    message.set_content(content)
    with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)


async def notify_with_fallback(db: Session, subject: str, content: str) -> str:
    try:
        await send_qq(db, content)
        return "qq"
    except Exception as qq_error:
        try:
            send_email(db, subject, content)
            return "email"
        except Exception as mail_error:
            raise RuntimeError(f"QQ: {qq_error}; Email: {mail_error}") from mail_error

