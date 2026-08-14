from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ....centers.planning.sync_service import guarded_sync
from ....core.config import config
from ....core.database import get_db, init_db
from ....core.settings import get_setting, set_setting
from ....integrations.armory_auth import interactive_login_available, login_status, start_interactive_login
from ....integrations.notifications import DEFAULT_QQ_MESSAGE_TEMPLATE, notify_with_fallback, render_message_template, send_email
from ....integrations.wargaming_auth import build_login_url
from ....jobs.backup import create_backup, list_backups, restore_backup
from ..dependencies import page_context, require_csrf, templates


router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    keys = ["account_id", "committed_coal", "committed_steel", "committed_research_points", "daily_token_target", "qq_app_id", "qq_user_openid", "qq_group_openid", "qq_message_template", "qq_daily_target", "qq_target_id", "qq_target_type", "smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_recipient"]
    values = {key: get_setting(db, key) for key in keys}
    if not values["qq_user_openid"] and not values["qq_group_openid"] and values["qq_target_id"]:
        values["qq_group_openid" if values["qq_target_type"] == "group" else "qq_user_openid"] = values["qq_target_id"]
    values["qq_message_template"] = values["qq_message_template"] or DEFAULT_QQ_MESSAGE_TEMPLATE
    values["qq_daily_target"] = values["qq_daily_target"] or values["qq_target_type"] or "user"
    backups = [{"name": path.name, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo(config.timezone))} for path in list_backups(limit=10)]
    return templates.TemplateResponse("settings.html", page_context(
        request,
        active_nav="settings",
        values=values,
        auth_state=(config.data_dir / "auth" / "armory-storage.json").exists(),
        armory_login_status=login_status(),
        armory_interactive=interactive_login_available(),
        backups=backups,
        backup_status={"at": get_setting(db, "last_backup_at"), "file": get_setting(db, "last_backup_file"), "error": get_setting(db, "last_backup_error")},
    ))


@router.post("/api/system/settings")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    secrets = {"wg_application_id", "qq_app_secret", "smtp_password"}
    allowed = {"account_id", "wg_application_id", "committed_coal", "committed_steel", "committed_research_points", "daily_token_target", "qq_app_id", "qq_app_secret", "qq_user_openid", "qq_group_openid", "qq_message_template", "qq_daily_target", "smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_password", "smtp_recipient"}
    clearable = {"qq_user_openid", "qq_group_openid", "qq_message_template"}
    if "qq_message_template" in form:
        try:
            render_message_template(str(form["qq_message_template"]), "测试标题", "测试日报")
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "qq_daily_target" in form and str(form["qq_daily_target"]) not in {"user", "group", "both"}:
        raise HTTPException(400, "未知 QQ 每日通知目标")
    if "smtp_security" in form and str(form["smtp_security"]) not in {"ssl", "starttls"}:
        raise HTTPException(400, "未知 SMTP 加密方式")
    for key in allowed:
        if key in form and (str(form[key]).strip() or key in clearable):
            set_setting(db, key, str(form[key]).strip(), secret=key in secrets)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/system/backups/export")
async def export_backup(request: Request):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    path = create_backup("manual")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/api/system/backups/import")
async def import_backup(request: Request, backup_file: UploadFile | None = None):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    upload = backup_file or form.get("backup_file")
    if not upload or not getattr(upload, "filename", ""):
        raise HTTPException(400, "请选择备份 ZIP 文件")
    raw = await upload.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, "备份文件不能超过 100MB")
    with tempfile.TemporaryDirectory(prefix="ursule-upload-") as temp_dir:
        uploaded = Path(temp_dir) / "backup.zip"
        uploaded.write_bytes(raw)
        try:
            from ....core.database import engine
            engine.dispose()
            safety = restore_backup(uploaded)
            init_db()
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/settings?restored=1&safety={safety.name}", status_code=303)


@router.post("/api/system/auth/armory/import")
async def import_armory_state(request: Request, state_file: UploadFile | None = None):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    upload = state_file or form.get("state_file")
    if not upload:
        raise HTTPException(400, "请选择登录状态文件")
    raw = await upload.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "登录状态文件不能超过 5MB")
    try:
        payload = json.loads(raw)
        if not isinstance(payload.get("cookies"), list):
            raise ValueError
    except Exception as exc:
        raise HTTPException(400, "不是有效的 Playwright storage_state 文件") from exc
    path = config.data_dir / "auth" / "armory-storage.json"
    temporary = path.with_suffix(".upload.json")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return RedirectResponse("/settings", status_code=303)


async def _sync_after_armory_login() -> None:
    from ....core.database import SessionLocal
    with SessionLocal() as db:
        await guarded_sync(db, capture_type="armory_login")


@router.post("/api/system/auth/armory/login")
async def open_armory_login(request: Request):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    if not interactive_login_available():
        raise HTTPException(409, "当前主机没有图形桌面，请在 Windows 登录后导入登录状态")
    start_interactive_login(on_success=_sync_after_armory_login)
    return RedirectResponse("/settings?armory_login=started", status_code=303)


@router.get("/api/system/auth/armory/login/status", response_class=HTMLResponse)
def armory_login_status(request: Request):
    return templates.TemplateResponse("partials/armory_login_status.html", {"request": request, "status": login_status()})


@router.post("/api/system/sync")
async def manual_sync(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    await guarded_sync(db, capture_type="manual_sync")
    return RedirectResponse("/", status_code=303)


@router.post("/api/system/notifications/test/{target}")
async def notification_test(target: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    try:
        if target == "email":
            send_email(db, "Ursule Bot 邮件测试", "Ursule Bot SMTP 邮件测试成功。")
            return RedirectResponse("/settings?notice=email_test", status_code=303)
        if target not in {"user", "group"}:
            raise HTTPException(400, "未知 QQ 测试目标")
        channel = await notify_with_fallback(db, "Ursule Bot 测试", f"Ursule Bot {'好友' if target == 'user' else '群聊'}通知测试成功。", qq_target=target)
        return RedirectResponse(f"/settings?notice={channel}&target={target}", status_code=303)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/api/system/notifications/test")
async def notification_fallback_test(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    try:
        channel = await notify_with_fallback(db, "Ursule Bot 测试", "Ursule Bot 通知测试成功。")
        return RedirectResponse(f"/settings?notice={channel}", status_code=303)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/auth/wargaming/start")
def wargaming_start(db: Session = Depends(get_db)):
    application_id = get_setting(db, "wg_application_id")
    if not application_id:
        raise HTTPException(400, "请先配置 Wargaming Application ID")
    return RedirectResponse(build_login_url(application_id, config.public_base_url + "/auth/wargaming/callback"))


@router.get("/auth/wargaming/callback")
def wargaming_callback(status: str = "", access_token: str = "", account_id: str = "", expires_at: str = "", db: Session = Depends(get_db)):
    if status != "ok" or not access_token:
        raise HTTPException(400, "Wargaming 授权失败")
    set_setting(db, "wg_access_token", access_token, secret=True)
    set_setting(db, "account_id", account_id)
    set_setting(db, "wg_token_expires_at", expires_at)
    db.commit()
    return RedirectResponse("/settings", status_code=303)
