from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from ...core.config import config
from ...core.security import csrf_valid, read_session


ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["from_json"] = lambda value: json.loads(value or "[]")
templates.env.filters["datetime_local"] = lambda value: (
    (value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value)
    .astimezone(ZoneInfo(config.timezone))
    .strftime("%Y-%m-%dT%H:%M:%S")
    if value else ""
)


def page_context(request: Request, *, active_nav: str = "", **values):
    session = read_session(request.cookies.get("ursule_session")) or read_session(request.cookies.get("tracker_session")) or {}
    return {"request": request, "csrf": session.get("csrf", ""), "active_nav": active_nav, **values}


def require_csrf(request: Request, supplied: str) -> None:
    cookie = request.cookies.get("ursule_session") or request.cookies.get("tracker_session")
    if not csrf_valid(read_session(cookie), supplied):
        raise HTTPException(403, "CSRF 校验失败")
