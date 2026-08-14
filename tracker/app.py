from __future__ import annotations

import json
import tempfile
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .backup import create_backup, list_backups, prune_automatic_backups, restore_backup
from .db import SessionLocal, get_db, init_db
from .models import DailySnapshot, ManualOverride, ResourceForecast, ResetPlan, RewardGoal, utcnow
from .notifications import notify_with_fallback
from .planner import BRITISH_LIGHT_CRUISER_LINE, EVENT_DEADLINE, LINE_XP_PER_RESET, build_regrind_baseline, reset_count
from .security import csrf_valid, hash_password, new_session, read_session, verify_password
from .service import dashboard_context, report_text, sync_all
from .settings import get_setting, has_setup, set_setting
from .wargaming import build_login_url

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["from_json"] = lambda value: json.loads(value or "[]")
templates.env.filters["datetime_local"] = lambda value: (value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value).astimezone(ZoneInfo(config.timezone)).strftime("%Y-%m-%dT%H:%M") if value else ""
scheduler = AsyncIOScheduler(timezone=config.timezone)


async def scheduled_sync() -> None:
    with SessionLocal() as db:
        await sync_all(db)
        try:
            backup_path = create_backup("auto")
            prune_automatic_backups(keep=30)
            set_setting(db, "last_backup_at", utcnow().isoformat())
            set_setting(db, "last_backup_file", backup_path.name)
            set_setting(db, "last_backup_error", "")
            db.commit()
        except Exception as exc:
            set_setting(db, "last_backup_error", str(exc)[:500])
            db.commit()
        try:
            await notify_with_fallback(db, "战舰世界节日船团日报", report_text(db))
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        for plan in db.scalars(select(ResetPlan)):
            plan.deadline = EVENT_DEADLINE
            db.add(plan)
        db.commit()
        active_plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if active_plan and active_plan.line_name != "英国轻巡：利安得 → 米诺陶":
            projection = dashboard_context(db)["projection"]
            target_resets = reset_count(projection["additional_research_points"], multiplier=active_plan.multiplier)
            active_plan.line_name = "英国轻巡：利安得 → 米诺陶"
            active_plan.target_resets = target_resets
            active_plan.completed_cycles = 0
            active_plan.current_ship_index = 4
            active_plan.waiting_for_reset = True
            active_plan.ships_json = json.dumps(list(BRITISH_LIGHT_CRUISER_LINE), ensure_ascii=False)
            active_plan.baseline_json = json.dumps(build_regrind_baseline(date.today(), EVENT_DEADLINE, target_resets), ensure_ascii=False)
            db.add(active_plan)
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
    milestones = []
    previous_key = None
    for item in baseline:
        key = (item.get("cycle"), item.get("ship"))
        if key != previous_key:
            milestones.append(item)
            previous_key = key
    context = dashboard_context(db)
    return templates.TemplateResponse(
        "plan.html",
        page_context(request, plan=plan, baseline=baseline, milestones=milestones, latest=context["latest"], projection=context["projection"], line=BRITISH_LIGHT_CRUISER_LINE, line_xp=LINE_XP_PER_RESET),
    )


@app.post("/api/plan")
def save_plan(request: Request, csrf: str = Form(...), multiplier: int = Form(1), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    multiplier = max(1, multiplier)
    context = dashboard_context(db)
    target_resets = reset_count(context["projection"]["additional_research_points"], multiplier=multiplier)
    for old in db.scalars(select(ResetPlan).where(ResetPlan.active.is_(True))):
        old.active = False
    baseline = build_regrind_baseline(date.today(), EVENT_DEADLINE, target_resets)
    db.add(ResetPlan(
        line_name="英国轻巡：利安得 → 米诺陶",
        multiplier=multiplier,
        deadline=EVENT_DEADLINE,
        current_ship_index=4,
        target_resets=target_resets,
        completed_cycles=0,
        waiting_for_reset=True,
        ships_json=json.dumps(list(BRITISH_LIGHT_CRUISER_LINE), ensure_ascii=False),
        baseline_json=json.dumps(baseline, ensure_ascii=False),
    ))
    db.commit()
    return RedirectResponse("/plan", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)):
    snapshots = list(db.scalars(select(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(90)))
    snapshot_views = []
    line_ids = {int(ship["ship_id"]): ship["name"] for ship in BRITISH_LIGHT_CRUISER_LINE}
    for snapshot in snapshots:
        boosters = json.loads(snapshot.boosters_json or "{}")
        state = json.loads(snapshot.line_state_json or "{}")
        port = json.loads(snapshot.port_ships_json) if snapshot.port_ships_json else []
        state_index = state.get("current_ship_index")
        if state.get("waiting_for_reset"):
            line_ship = "等待首次重置"
        elif isinstance(state_index, int) and 0 <= state_index < len(BRITISH_LIGHT_CRUISER_LINE):
            line_ship = BRITISH_LIGHT_CRUISER_LINE[state_index]["name"]
        else:
            owned = [line_ids[ship_id] for ship_id in port if ship_id in line_ids]
            line_ship = "、".join(owned) if owned else "未记录"
        snapshot_views.append({"row": snapshot, "boosters": boosters, "state": state, "line_ship": line_ship})
    audits = list(db.scalars(select(ManualOverride).where(ManualOverride.field_name.like("snapshot.%")).order_by(ManualOverride.created_at.desc()).limit(50)))
    return templates.TemplateResponse("history.html", page_context(request, snapshots=snapshot_views, audits=audits, line=BRITISH_LIGHT_CRUISER_LINE))


@app.post("/api/snapshots/capture")
async def capture_snapshot(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    await sync_all(db)
    return RedirectResponse("/history?captured=1", status_code=303)


@app.post("/api/snapshots/{snapshot_id}/edit")
async def edit_snapshot(snapshot_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    snapshot = db.get(DailySnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "快照不存在")
    reason = str(form.get("reason", "")).strip()
    if not reason:
        raise HTTPException(400, "请填写修改原因")

    integer_fields = (
        "holiday_tokens", "credits", "gold", "coal", "steel", "research_points",
        "community_tokens", "free_xp", "elite_commander_xp", "battles_total",
    )
    try:
        parsed_integers = {field_name: (None if str(form.get(field_name, "")).strip() == "" else max(0, int(str(form.get(field_name, "")).strip()))) for field_name in integer_fields}
        parsed_boosters = {booster_name: (None if str(form.get(booster_name, "")).strip() == "" else max(0, int(str(form.get(booster_name, "")).strip()))) for booster_name in ("rare_credits", "rare_ship_xp", "rare_commander_xp", "rare_free_xp")}
        line_stage = int(str(form.get("line_stage", "-1")))
        completed_cycles = max(0, int(str(form.get("completed_cycles", "0"))))
    except ValueError:
        raise HTTPException(400, "数值字段格式不正确")
    for field_name in integer_fields:
        new_value = parsed_integers[field_name]
        if getattr(snapshot, field_name) != new_value:
            setattr(snapshot, field_name, new_value)
            db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.{field_name}", value="" if new_value is None else str(new_value), reason=reason))

    boosters = json.loads(snapshot.boosters_json or "{}")
    for booster_name in ("rare_credits", "rare_ship_xp", "rare_commander_xp", "rare_free_xp"):
        new_value = parsed_boosters[booster_name]
        old_value = boosters.get(booster_name)
        if old_value != new_value:
            if new_value is None:
                boosters.pop(booster_name, None)
            else:
                boosters[booster_name] = new_value
            db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.{booster_name}", value="" if new_value is None else str(new_value), reason=reason))
    snapshot.boosters_json = json.dumps(boosters, ensure_ascii=False)

    raw_time = str(form.get("collected_at", "")).strip()
    if raw_time:
        local_time = datetime.fromisoformat(raw_time)
        if local_time.tzinfo is None:
            local_time = local_time.replace(tzinfo=ZoneInfo(config.timezone))
        new_time = local_time.astimezone(timezone.utc)
        current_time = snapshot.collected_at
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        if current_time != new_time:
            snapshot.collected_at = new_time
            db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.collected_at", value=new_time.isoformat(), reason=reason))

    state = json.loads(snapshot.line_state_json or "{}")
    waiting = line_stage < 0
    current_index = 4 if waiting else min(line_stage, 3)
    if state.get("waiting_for_reset") != waiting or state.get("current_ship_index") != current_index or state.get("completed_cycles") != completed_cycles:
        state.update({"waiting_for_reset": waiting, "current_ship_index": current_index, "completed_cycles": completed_cycles, "event": f"手工修正：{reason}"})
        snapshot.line_state_json = json.dumps(state, ensure_ascii=False)
        db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.line_state", value=json.dumps(state, ensure_ascii=False), reason=reason))
        latest_id = db.scalar(select(DailySnapshot.id).order_by(DailySnapshot.snapshot_date.desc()).limit(1))
        active_plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if snapshot.id == latest_id and active_plan:
            active_plan.waiting_for_reset = waiting
            active_plan.current_ship_index = current_index
            active_plan.completed_cycles = completed_cycles
            db.add(active_plan)

    statuses = json.loads(snapshot.source_status_json or "{}")
    statuses["manual_edit"] = {"ok": True, "edited_at": utcnow().isoformat(), "reason": reason}
    snapshot.source_status_json = json.dumps(statuses, ensure_ascii=False)
    db.add(snapshot)
    db.commit()
    return RedirectResponse(f"/history?edited={snapshot.id}", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    keys = ["account_id", "committed_coal", "committed_steel", "committed_research_points", "daily_token_target", "qq_app_id", "qq_target_id", "qq_target_type", "smtp_host", "smtp_port", "smtp_username", "smtp_recipient"]
    values = {key: get_setting(db, key) for key in keys}
    backups = [{"name": path.name, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo(config.timezone))} for path in list_backups(limit=10)]
    backup_status = {"at": get_setting(db, "last_backup_at"), "file": get_setting(db, "last_backup_file"), "error": get_setting(db, "last_backup_error")}
    return templates.TemplateResponse("settings.html", page_context(request, values=values, auth_state=(config.data_dir / "auth" / "armory-storage.json").exists(), backups=backups, backup_status=backup_status))


@app.post("/api/backup/export")
def export_backup(request: Request, csrf: str = Form(...)):
    require_csrf(request, csrf)
    path = create_backup("manual")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/backup/import")
async def import_backup(request: Request, csrf: str = Form(...), backup_file: UploadFile = None):
    require_csrf(request, csrf)
    if backup_file is None or not backup_file.filename:
        raise HTTPException(400, "请选择备份 ZIP 文件")
    raw = await backup_file.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, "备份文件不能超过 100MB")
    with tempfile.TemporaryDirectory(prefix="wows-tracker-upload-") as temp_dir:
        uploaded = Path(temp_dir) / "backup.zip"
        uploaded.write_bytes(raw)
        try:
            from .db import engine
            engine.dispose()
            safety = restore_backup(uploaded)
            init_db()
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc))
    return RedirectResponse(f"/settings?restored=1&safety={safety.name}", status_code=303)


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
