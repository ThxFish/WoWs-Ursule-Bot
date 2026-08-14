from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .db import SessionLocal, get_db, init_db
from .models import DailySnapshot, ManualOverride, ResourceForecast, ResetPlan, RewardGoal
from .notifications import notify_with_fallback
from .planner import EVENT_DEADLINE, build_baseline, parse_ship_steps
from .security import csrf_valid, hash_password, new_session, read_session, verify_password
from .service import dashboard_context, report_text, sync_all
from .settings import get_setting, has_setup, set_setting
from .wargaming import build_login_url

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["from_json"] = lambda value: json.loads(value or "[]")
scheduler = AsyncIOScheduler(timezone=config.timezone)


async def scheduled_sync() -> None:
    with SessionLocal() as db:
        await sync_all(db)
        try:
            await notify_with_fallback(db, "战舰世界节日船团日报", report_text(db))
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        for plan in db.scalars(select(ResetPlan)):
            baseline = json.loads(plan.baseline_json or "[]")
            if not baseline or baseline[-1].get("date") != EVENT_DEADLINE.isoformat():
                start = plan.created_at.date() if plan.created_at else date.today()
                plan.baseline_json = json.dumps(build_baseline(start, EVENT_DEADLINE, parse_ship_steps(plan.ships_json), plan.current_ship_index), ensure_ascii=False)
                plan.deadline = EVENT_DEADLINE
                db.add(plan)
        db.commit()
    if not scheduler.running:
        scheduler.add_job(scheduled_sync, "cron", hour=config.sync_hour, minute=config.sync_minute, id="daily-sync", replace_existing=True, coalesce=True, max_instances=1)
        scheduler.start()
    with SessionLocal() as db:
        if has_setup(db):
            today = datetime.now().date()
            if not db.scalar(select(DailySnapshot).where(DailySnapshot.snapshot_date == today)):
                import asyncio
                asyncio.create_task(scheduled_sync())
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="WoWS Marathon Tracker", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public = ("/static", "/health", "/setup", "/login")
    if request.url.path.startswith(public):
        return await call_next(request)
    with SessionLocal() as db:
        if not has_setup(db):
            return RedirectResponse("/setup", status_code=303)
    if not read_session(request.cookies.get("tracker_session")):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


def page_context(request: Request, **values):
    session = read_session(request.cookies.get("tracker_session")) or {}
    return {"request": request, "csrf": session.get("csrf", ""), **values}


def require_csrf(request: Request, supplied: str) -> None:
    if not csrf_valid(read_session(request.cookies.get("tracker_session")), supplied):
        raise HTTPException(403, "CSRF 校验失败")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if has_setup(db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("setup.html", page_context(request))


@app.post("/setup")
def setup_submit(
    request: Request,
    password: str = Form(...),
    account_id: str = Form(""),
    wg_application_id: str = Form(""),
    db: Session = Depends(get_db),
):
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
    response.set_cookie("tracker_session", cookie, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 14)
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", page_context(request, error=""))


@app.post("/login")
def login_submit(request: Request, password: str = Form(...), db: Session = Depends(get_db)):
    if not verify_password(get_setting(db, "admin_password_hash"), password):
        return templates.TemplateResponse("login.html", page_context(request, error="密码错误"), status_code=401)
    cookie, _ = new_session()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("tracker_session", cookie, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 14)
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    require_csrf(request, csrf)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("tracker_session")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("dashboard.html", page_context(request, **dashboard_context(db)))


@app.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request, db: Session = Depends(get_db)):
    goals = list(db.scalars(select(RewardGoal).order_by(RewardGoal.deadline)))
    forecasts = list(db.scalars(select(ResourceForecast).order_by(ResourceForecast.available_on)))
    context = dashboard_context(db)
    return templates.TemplateResponse("goals.html", page_context(request, goals=goals, forecasts=forecasts, latest=context["latest"], projection=context["projection"]))


@app.post("/api/goals")
def add_goal(request: Request, csrf: str = Form(...), name: str = Form(...), quantity: int = Form(1), token_cost: int = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    db.add(RewardGoal(name=name.strip(), quantity=max(1, quantity), token_cost=max(0, token_cost), deadline=EVENT_DEADLINE))
    db.commit()
    return RedirectResponse("/goals", status_code=303)


@app.post("/api/goals/{goal_id}/delete")
def delete_goal(goal_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    row = db.get(RewardGoal, goal_id)
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/goals", status_code=303)


@app.post("/api/forecasts")
def add_forecast(request: Request, csrf: str = Form(...), resource_type: str = Form(...), amount: int = Form(...), available_on: date = Form(...), cadence: str = Form("once"), note: str = Form(""), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    if resource_type not in {"coal", "steel", "research_points"}:
        raise HTTPException(400, "未知资源类型")
    if cadence not in {"once", "daily", "weekly", "monthly"}:
        raise HTTPException(400, "未知周期")
    db.add(ResourceForecast(resource_type=resource_type, amount=max(0, amount), available_on=available_on, cadence=cadence, note=note.strip()))
    db.commit()
    return RedirectResponse("/goals", status_code=303)


@app.post("/api/forecasts/{forecast_id}/delete")
def delete_forecast(forecast_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    row = db.get(ResourceForecast, forecast_id)
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/goals", status_code=303)


@app.post("/api/resource-allocation")
def save_resource_allocation(request: Request, csrf: str = Form(...), coal: int = Form(0), steel: int = Form(0), research_points: int = Form(0), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    set_setting(db, "committed_coal", str(max(0, coal)))
    set_setting(db, "committed_steel", str(max(0, steel)))
    set_setting(db, "committed_research_points", str(max(0, research_points)))
    db.commit()
    return RedirectResponse("/goals", status_code=303)


@app.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, db: Session = Depends(get_db)):
    plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
    baseline = json.loads(plan.baseline_json) if plan else []
    return templates.TemplateResponse("plan.html", page_context(request, plan=plan, baseline=baseline))


@app.post("/api/plan")
def save_plan(request: Request, csrf: str = Form(...), line_name: str = Form(...), multiplier: int = Form(1), current_ship_index: int = Form(0), ships: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    parsed = []
    for line in ships.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(":")]
        parsed.append({"name": parts[0], "xp": int(parts[1]) if len(parts) > 1 else 0, "ship_id": int(parts[2]) if len(parts) > 2 and parts[2] else None})
    steps = parse_ship_steps(parsed)
    if not steps:
        raise HTTPException(400, "至少填写一艘舰船")
    for old in db.scalars(select(ResetPlan).where(ResetPlan.active.is_(True))):
        old.active = False
    baseline = build_baseline(date.today(), EVENT_DEADLINE, steps, current_ship_index)
    db.add(ResetPlan(line_name=line_name.strip(), multiplier=max(1, multiplier), deadline=EVENT_DEADLINE, current_ship_index=max(0, current_ship_index), ships_json=json.dumps(parsed, ensure_ascii=False), baseline_json=json.dumps(baseline, ensure_ascii=False)))
    db.commit()
    return RedirectResponse("/plan", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)):
    snapshots = list(db.scalars(select(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(90)))
    return templates.TemplateResponse("history.html", page_context(request, snapshots=snapshots))


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    keys = ["account_id", "committed_coal", "committed_steel", "committed_research_points", "daily_token_target", "qq_app_id", "qq_target_id", "qq_target_type", "smtp_host", "smtp_port", "smtp_username", "smtp_recipient"]
    values = {key: get_setting(db, key) for key in keys}
    return templates.TemplateResponse("settings.html", page_context(request, values=values, auth_state=(config.data_dir / "auth" / "armory-storage.json").exists()))


@app.post("/api/settings")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    secrets = {"wg_application_id", "qq_app_secret", "smtp_password"}
    allowed = {"account_id", "wg_application_id", "committed_coal", "committed_steel", "committed_research_points", "daily_token_target", "qq_app_id", "qq_app_secret", "qq_target_id", "qq_target_type", "smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_recipient"}
    for key in allowed:
        if key in form and str(form[key]).strip():
            set_setting(db, key, str(form[key]).strip(), secret=key in secrets)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/api/auth/armory/import")
async def import_armory_state(request: Request, csrf: str = Form(...), state_file: UploadFile = None):
    require_csrf(request, csrf)
    if state_file is None:
        raise HTTPException(400, "请选择登录状态文件")
    raw = await state_file.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload.get("cookies"), list):
            raise ValueError
    except Exception:
        raise HTTPException(400, "不是有效的 Playwright storage_state 文件")
    path = config.data_dir / "auth" / "armory-storage.json"
    path.write_bytes(raw)
    return RedirectResponse("/settings", status_code=303)


@app.post("/api/sync")
async def manual_sync(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    await sync_all(db)
    return RedirectResponse("/", status_code=303)


@app.post("/api/overrides")
def add_override(request: Request, csrf: str = Form(...), field_name: str = Form(...), value: str = Form(...), reason: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    if field_name not in {"holiday_tokens", "current_ship_index", "coal", "steel", "research_points"}:
        raise HTTPException(400, "不允许修正该字段")
    try:
        int(value)
    except ValueError:
        raise HTTPException(400, "修正值必须为整数")
    db.add(ManualOverride(snapshot_date=date.today(), field_name=field_name, value=value, reason=reason.strip()))
    db.commit()
    return RedirectResponse("/history", status_code=303)


@app.post("/api/notify/test")
async def notification_test(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    try:
        channel = await notify_with_fallback(db, "WoWS Tracker 测试", "WoWS Tracker 通知测试成功。")
        return RedirectResponse(f"/settings?notice={channel}", status_code=303)
    except Exception as exc:
        raise HTTPException(502, str(exc))


@app.get("/auth/wargaming/start")
def wargaming_start(db: Session = Depends(get_db)):
    application_id = get_setting(db, "wg_application_id")
    if not application_id:
        raise HTTPException(400, "请先配置 Wargaming Application ID")
    return RedirectResponse(build_login_url(application_id, config.public_base_url + "/auth/wargaming/callback"))


@app.get("/auth/wargaming/callback")
def wargaming_callback(status: str = "", access_token: str = "", account_id: str = "", expires_at: str = "", db: Session = Depends(get_db)):
    if status != "ok" or not access_token:
        raise HTTPException(400, "Wargaming 授权失败")
    set_setting(db, "wg_access_token", access_token, secret=True)
    set_setting(db, "account_id", account_id)
    set_setting(db, "wg_token_expires_at", expires_at)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.get("/api/history")
def history_api(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(90)))
    return [{"date": row.snapshot_date, "tokens": row.holiday_tokens, "credits": row.credits, "gold": row.gold, "coal": row.coal, "steel": row.steel, "research_points": row.research_points, "community_tokens": row.community_tokens, "free_xp": row.free_xp, "elite_commander_xp": row.elite_commander_xp, "boosters": json.loads(row.boosters_json), "battles": row.battles_total, "xp": row.xp_total, "sources": json.loads(row.source_status_json)} for row in rows]
