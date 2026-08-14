from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....core.security import hash_password, new_session, verify_password
from ....core.settings import get_setting, has_setup, set_setting
from ..dependencies import page_context, require_csrf, templates


router = APIRouter()


def _set_session_cookie(response: RedirectResponse, request: Request, cookie: str) -> None:
    response.set_cookie("ursule_session", cookie, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 14)


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if has_setup(db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("setup.html", page_context(request))


@router.post("/setup")
def setup_submit(request: Request, password: str = Form(...), account_id: str = Form(""), wg_application_id: str = Form(""), db: Session = Depends(get_db)):
    if has_setup(db):
        raise HTTPException(409, "已经完成初始化")
    if len(password) < 10:
        raise HTTPException(400, "管理员密码至少 10 位")
    set_setting(db, "admin_password_hash", hash_password(password), secret=True)
    set_setting(db, "account_id", account_id.strip())
    set_setting(db, "wg_application_id", wg_application_id.strip(), secret=True)
    db.commit()
    cookie, _ = new_session()
    response = RedirectResponse("/settings", status_code=303)
    _set_session_cookie(response, request, cookie)
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", page_context(request, error=""))


@router.post("/login")
def login_submit(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    if not verify_password(get_setting(db, "admin_password_hash"), password):
        return templates.TemplateResponse("login.html", page_context(request, error="密码错误"), status_code=401)
    cookie, _ = new_session()
    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(response, request, cookie)
    return response


@router.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    require_csrf(request, csrf)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("ursule_session")
    response.delete_cookie("tracker_session")
    return response
