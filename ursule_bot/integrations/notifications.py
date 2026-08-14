from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from ..core.settings import get_setting

DEFAULT_QQ_MESSAGE_TEMPLATE = "{report}"
QQ_API_BASE = "https://api.bot.qq.com"


def render_message_template(template: str, subject: str, report: str) -> str:
    template = template.strip() or DEFAULT_QQ_MESSAGE_TEMPLATE
    try:
        rendered = template.format(subject=subject, report=report)
    except (KeyError, ValueError) as exc:
        raise RuntimeError("QQ 消息模板仅支持 {subject} 和 {report}，普通花括号请写成 {{ 和 }}") from exc
    if not rendered.strip():
        raise RuntimeError("QQ 消息模板生成了空消息")
    return rendered


def qq_targets(user_openid: str, group_openid: str, target: str = "both") -> list[tuple[str, str]]:
    targets = []
    if target in {"user", "both"} and user_openid.strip():
        targets.append(("好友", f"/v2/users/{user_openid.strip()}/messages"))
    if target in {"group", "both"} and group_openid.strip():
        targets.append(("群", f"/v2/groups/{group_openid.strip()}/messages"))
    return targets


async def send_qq(db: Session, content: str, target: str = "scheduled") -> None:
    app_id = get_setting(db, "qq_app_id")
    secret = get_setting(db, "qq_app_secret")
    user_openid = get_setting(db, "qq_user_openid")
    group_openid = get_setting(db, "qq_group_openid")
    if not user_openid and not group_openid:
        legacy_id = get_setting(db, "qq_target_id")
        if get_setting(db, "qq_target_type", "user") == "group":
            group_openid = legacy_id
        else:
            user_openid = legacy_id
    if target == "scheduled":
        target = get_setting(db, "qq_daily_target", get_setting(db, "qq_target_type", "user"))
    if target not in {"user", "group", "both"}:
        raise RuntimeError("未知 QQ 发送目标")
    targets = qq_targets(user_openid, group_openid, target)
    if not app_id or not secret or not targets:
        label = {"user": "好友 User OpenID", "group": "群 Group OpenID", "both": "好友和群 OpenID"}[target]
        raise RuntimeError(f"QQ 机器人配置不完整：请检查 AppID、AppSecret 和{label}")
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post("https://bots.qq.com/app/getAppAccessToken", json={"appId": app_id, "clientSecret": secret})
        token_response.raise_for_status()
        token_payload = token_response.json()
        token = token_payload.get("access_token")
        if not token:
            raise RuntimeError(f"QQ Access Token 获取失败：{token_payload}")
        failures = []
        for label, path in targets:
            response = await client.post(
                QQ_API_BASE + path,
                headers={"Authorization": f"QQBot {token}"},
                json={"content": content, "msg_type": 0},
            )
            try:
                response.raise_for_status()
                payload = response.json()
                if payload.get("err_code") not in (None, 0):
                    raise RuntimeError(f"{payload.get('err_code')}: {payload.get('message', '未知错误')}，trace_id={payload.get('trace_id', '无')}")
            except Exception as exc:
                failures.append(f"{label}发送失败：{exc}")
        if failures:
            raise RuntimeError("；".join(failures))


def send_email(db: Session, subject: str, content: str) -> None:
    host = get_setting(db, "smtp_host")
    port = int(get_setting(db, "smtp_port", "465"))
    username = get_setting(db, "smtp_username")
    password = get_setting(db, "smtp_password")
    recipient = get_setting(db, "smtp_recipient")
    security = get_setting(db, "smtp_security", "ssl" if port == 465 else "starttls").lower()
    if not all((host, username, password, recipient)):
        raise RuntimeError("SMTP 配置不完整")
    if security not in {"ssl", "starttls"}:
        raise RuntimeError("SMTP 加密方式无效")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = username
    message["To"] = recipient
    message.set_content(content)
    smtp_class = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    with smtp_class(host, port, timeout=20) as smtp:
        if security == "starttls":
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


async def notify_with_fallback(db: Session, subject: str, content: str, qq_target: str = "scheduled") -> str:
    try:
        template = get_setting(db, "qq_message_template", DEFAULT_QQ_MESSAGE_TEMPLATE)
        await send_qq(db, render_message_template(template, subject, content), qq_target)
        return "qq"
    except Exception as qq_error:
        try:
            send_email(db, subject, content)
            return "email"
        except Exception as mail_error:
            raise RuntimeError(f"QQ: {qq_error}; Email: {mail_error}") from mail_error
