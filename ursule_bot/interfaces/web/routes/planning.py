from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....centers.planning.models import DailySnapshot, ManualOverride, ResourceForecast, ResetPlan, RewardGoal
from ....centers.planning.overview import get_activity_overview
from ....centers.planning.regrind import BRITISH_LIGHT_CRUISER_LINE, LINE_XP_PER_RESET
from ....centers.planning.service import add_forecast, add_goal, add_manual_override, delete_forecast, delete_goal, save_regrind_plan, save_resource_allocation
from ....centers.planning.snapshots import list_snapshot_views, update_snapshot
from ....centers.planning.sync_service import guarded_sync
from ....core.database import get_db
from ..dependencies import page_context, require_csrf, templates


router = APIRouter()


@router.get("/planning", response_class=HTMLResponse)
def planning_center(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("planning/overview.html", page_context(request, active_nav="planning", **get_activity_overview(db).template_context()))


@router.get("/planning/goals", response_class=HTMLResponse)
def goals_page(request: Request, db: Session = Depends(get_db)):
    overview = get_activity_overview(db)
    return templates.TemplateResponse("planning/goals.html", page_context(
        request,
        active_nav="planning",
        goals=list(db.scalars(select(RewardGoal).order_by(RewardGoal.deadline))),
        forecasts=list(db.scalars(select(ResourceForecast).order_by(ResourceForecast.available_on))),
        latest=overview.latest,
        projection=overview.projection,
    ))


@router.post("/api/planning/goals")
def goal_create(request: Request, csrf: str = Form(...), name: str = Form(...), quantity: int = Form(1), token_cost: int = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    add_goal(db, name, quantity, token_cost)
    return RedirectResponse("/planning/goals", status_code=303)


@router.post("/api/planning/goals/{goal_id}/delete")
def goal_delete(goal_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    delete_goal(db, goal_id)
    return RedirectResponse("/planning/goals", status_code=303)


@router.post("/api/planning/forecasts")
def forecast_create(request: Request, csrf: str = Form(...), resource_type: str = Form(...), amount: int = Form(...), available_on: date = Form(...), cadence: str = Form("once"), note: str = Form(""), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    try:
        add_forecast(db, resource_type, amount, available_on, cadence, note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/planning/goals", status_code=303)


@router.post("/api/planning/forecasts/{forecast_id}/delete")
def forecast_delete(forecast_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    delete_forecast(db, forecast_id)
    return RedirectResponse("/planning/goals", status_code=303)


@router.post("/api/planning/resource-allocation")
def allocation_save(request: Request, csrf: str = Form(...), coal: int = Form(0), steel: int = Form(0), research_points: int = Form(0), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    save_resource_allocation(db, coal, steel, research_points)
    return RedirectResponse("/planning/goals", status_code=303)


@router.get("/planning/regrind", response_class=HTMLResponse)
def regrind_page(request: Request, db: Session = Depends(get_db)):
    plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
    baseline = json.loads(plan.baseline_json) if plan else []
    milestones, previous_key = [], None
    for item in baseline:
        key = (item.get("cycle"), item.get("ship"))
        if key != previous_key:
            milestones.append(item)
            previous_key = key
    overview = get_activity_overview(db)
    return templates.TemplateResponse("planning/regrind.html", page_context(request, active_nav="planning", plan=plan, baseline=baseline, milestones=milestones, latest=overview.latest, projection=overview.projection, line=BRITISH_LIGHT_CRUISER_LINE, line_xp=LINE_XP_PER_RESET))


@router.post("/api/planning/regrind")
def regrind_save(request: Request, csrf: str = Form(...), multiplier: int = Form(1), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    save_regrind_plan(db, multiplier)
    return RedirectResponse("/planning/regrind", status_code=303)


@router.get("/planning/snapshots", response_class=HTMLResponse)
def snapshots_page(request: Request, db: Session = Depends(get_db)):
    audits = list(db.scalars(select(ManualOverride).where(ManualOverride.field_name.like("snapshot.%")).order_by(ManualOverride.created_at.desc()).limit(50)))
    return templates.TemplateResponse("planning/snapshots.html", page_context(request, active_nav="planning", snapshots=list_snapshot_views(db), audits=audits, line=BRITISH_LIGHT_CRUISER_LINE))


@router.post("/api/planning/snapshots/capture")
async def capture_snapshot(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    await guarded_sync(db, capture_type="manual_snapshot")
    return RedirectResponse("/planning/snapshots?captured=1", status_code=303)


@router.post("/api/planning/snapshots/{snapshot_id}/edit")
async def edit_snapshot(snapshot_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    require_csrf(request, str(form.get("csrf", "")))
    try:
        row = update_snapshot(db, snapshot_id, {key: str(value) for key, value in form.items()})
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/planning/snapshots?edited={row.id}", status_code=303)


@router.get("/api/planning/snapshots")
def snapshots_api(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(DailySnapshot).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(200)))
    return [{"id": row.id, "date": row.snapshot_date, "collected_at": row.collected_at, "capture_type": row.capture_type, "tokens": row.holiday_tokens, "credits": row.credits, "gold": row.gold, "coal": row.coal, "steel": row.steel, "research_points": row.research_points, "community_tokens": row.community_tokens, "free_xp": row.free_xp, "elite_commander_xp": row.elite_commander_xp, "boosters": json.loads(row.boosters_json or "{}"), "battles": row.battles_total, "xp": row.xp_total, "sources": json.loads(row.source_status_json or "{}")} for row in rows]


@router.post("/api/planning/overrides")
def create_override(request: Request, csrf: str = Form(...), field_name: str = Form(...), value: str = Form(...), reason: str = Form(...), db: Session = Depends(get_db)):
    require_csrf(request, csrf)
    try:
        add_manual_override(db, field_name, value, reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/planning/snapshots", status_code=303)
