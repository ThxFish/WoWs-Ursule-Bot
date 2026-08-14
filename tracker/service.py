from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors import collect_armory, collect_third_party, collect_wargaming, third_party_totals
from .config import config
from .models import DailySnapshot, DataSourceStatus, ManualOverride, ResourceForecast, RewardGoal, ResetPlan, utcnow
from .planner import EVENT_DEADLINE, milestone_status, recurring_occurrences, reset_count, token_plan
from .settings import get_setting


def _status(db: Session, name: str, ok: bool, message: str) -> None:
    row = db.get(DataSourceStatus, name) or DataSourceStatus(name=name)
    row.ok = ok
    row.message = message[:1000]
    row.last_attempt_at = utcnow()
    if ok:
        row.last_success_at = utcnow()
    db.add(row)


async def sync_all(db: Session) -> DailySnapshot:
    today = datetime.now(ZoneInfo(config.timezone)).date()
    existing = db.scalar(select(DailySnapshot).where(DailySnapshot.snapshot_date == today))
    snapshot = existing or DailySnapshot(snapshot_date=today)
    statuses: dict[str, dict] = {}

    try:
        armory = await collect_armory()
        snapshot.holiday_tokens = armory.holiday_tokens
        snapshot.credits = armory.credits
        snapshot.gold = armory.gold
        snapshot.coal = armory.coal
        snapshot.steel = armory.steel
        snapshot.research_points = armory.research_points
        snapshot.community_tokens = armory.community_tokens
        snapshot.free_xp = armory.free_xp
        snapshot.elite_commander_xp = armory.elite_commander_xp
        snapshot.boosters_json = json.dumps(armory.boosters, ensure_ascii=False)
        statuses["armory"] = {"ok": True}
        _status(db, "armory", True, "同步成功")
    except Exception as exc:
        statuses["armory"] = {"ok": False, "error": str(exc)}
        _status(db, "armory", False, str(exc))

    account_id = get_setting(db, "account_id")
    try:
        wg = await collect_wargaming(get_setting(db, "wg_application_id"), account_id, get_setting(db, "wg_access_token"))
        snapshot.ships_json = json.dumps(wg["ships"], ensure_ascii=False)
        snapshot.battles_total = wg["battles"]
        snapshot.xp_total = wg["xp"]
        active_plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if active_plan:
            steps = json.loads(active_plan.ships_json or "[]")
            plan_started = int(active_plan.created_at.timestamp())
            activity = {int(ship["ship_id"]): int(ship.get("last_battle_time") or 0) for ship in wg["ships"] if ship.get("ship_id")}
            matched = [(activity.get(int(step["ship_id"]), 0), index) for index, step in enumerate(steps) if step.get("ship_id")]
            recent = [item for item in matched if item[0] >= plan_started]
            if recent:
                active_plan.current_ship_index = max(recent)[1]
                db.add(active_plan)
        statuses["wargaming"] = {"ok": True}
        _status(db, "wargaming", True, "同步成功")
    except Exception as exc:
        statuses["wargaming"] = {"ok": False, "error": str(exc)}
        _status(db, "wargaming", False, str(exc))

    try:
        third_party = await collect_third_party(account_id)
        fallback = third_party_totals(third_party)
        if snapshot.battles_total is None and fallback["battles"]:
            snapshot.battles_total = fallback["battles"]
        if snapshot.xp_total is None and fallback["xp"]:
            snapshot.xp_total = fallback["xp"]
        statuses["third_party"] = {"ok": True}
        _status(db, "third_party", True, "同步成功")
    except Exception as exc:
        statuses["third_party"] = {"ok": False, "error": str(exc)}
        _status(db, "third_party", False, str(exc))

    snapshot.source_status_json = json.dumps(statuses, ensure_ascii=False)
    snapshot.collected_at = utcnow()
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def dashboard_context(db: Session) -> dict:
    goals = list(db.scalars(select(RewardGoal).where(RewardGoal.active.is_(True)).order_by(RewardGoal.deadline)))
    latest = db.scalar(select(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(1))
    overrides = {}
    for override in db.scalars(select(ManualOverride).order_by(ManualOverride.created_at)):
        overrides[override.field_name] = override.value
    current_tokens = int(overrides.get("holiday_tokens", latest.holiday_tokens if latest and latest.holiday_tokens is not None else 0))
    goal_tokens = sum(goal.token_cost * goal.quantity for goal in goals)
    deadline = EVENT_DEADLINE
    resources = {
        "coal": int(get_setting(db, "committed_coal", "0") or 0),
        "steel": int(get_setting(db, "committed_steel", "0") or 0),
        "research_points": int(get_setting(db, "committed_research_points", "0") or 0),
    }
    available = {
        "coal": latest.coal if latest and latest.coal is not None else 0,
        "steel": latest.steel if latest and latest.steel is not None else 0,
        "research_points": latest.research_points if latest and latest.research_points is not None else 0,
    }
    forecast_additions = {"coal": 0, "steel": 0, "research_points": 0}
    for forecast in db.scalars(select(ResourceForecast).where(ResourceForecast.available_on <= deadline)):
        occurrences = recurring_occurrences(forecast.available_on, deadline, forecast.cadence)
        forecast_additions[forecast.resource_type] += forecast.amount * occurrences
    available = {key: available[key] + forecast_additions[key] for key in available}
    effective_resources = {key: min(resources[key], available[key]) for key in resources}
    today = datetime.now(ZoneInfo(config.timezone)).date()
    remaining_days = max(0, (deadline - today).days)
    daily_tokens = int(get_setting(db, "daily_token_target", "1200") or 0)
    projection = token_plan(goal_tokens, current_tokens, effective_resources, remaining_days * daily_tokens)
    projection["requested_resources"] = resources
    projection["available_resources"] = available
    projection["forecast_additions"] = forecast_additions
    projection["current_resources"] = {key: available[key] - forecast_additions[key] for key in available}
    plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
    projection["resets_required"] = reset_count(projection["additional_research_points"], multiplier=plan.multiplier if plan else 1)
    milestone = None
    if plan:
        actual_index = int(overrides.get("current_ship_index", plan.current_ship_index))
        milestone = milestone_status(json.loads(plan.baseline_json or "[]"), today, actual_index)
    return {
        "goals": goals,
        "latest": latest,
        "boosters": json.loads(latest.boosters_json or "{}") if latest else {},
        "projection": projection,
        "plan": plan,
        "milestone": milestone,
        "statuses": list(db.scalars(select(DataSourceStatus).order_by(DataSourceStatus.name))),
        "overrides": overrides,
    }


def report_text(db: Session) -> str:
    ctx = dashboard_context(db)
    p = ctx["projection"]
    m = ctx["milestone"] or {}
    target = (m.get("target") or {}).get("ship", "未配置")
    latest = ctx["latest"]
    return (
        "战舰世界节日船团日报\n"
        f"代币：{latest.holiday_tokens if latest and latest.holiday_tokens is not None else '未知'} / {p['goal_tokens']}\n"
        f"计入兑换后预计：{p['projected_tokens']}，缺口：{p['gap_tokens']}\n"
        f"今日研发线目标：{target}，状态：{m.get('status', '未配置')}\n"
        f"数据日期：{latest.snapshot_date if latest else '尚无'}"
    )
