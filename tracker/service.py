from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors import collect_armory, collect_third_party, collect_wargaming, third_party_totals
from .config import config
from .models import DailySnapshot, DataSourceStatus, ManualOverride, ResourceForecast, RewardGoal, ResetPlan, utcnow
from .planner import (
    BRITISH_LIGHT_CRUISER_LINE,
    EVENT_DEADLINE,
    LINE_XP_PER_RESET,
    line_progress_xp,
    recurring_occurrences,
    reset_count,
    token_plan,
    update_line_state,
)
from .settings import get_setting


def _status(db: Session, name: str, ok: bool, message: str) -> None:
    row = db.get(DataSourceStatus, name) or DataSourceStatus(name=name)
    row.ok = ok
    row.message = message[:1000]
    row.last_attempt_at = utcnow()
    if ok:
        row.last_success_at = utcnow()
    db.add(row)


async def sync_all(db: Session, capture_type: str = "manual") -> DailySnapshot:
    today = datetime.now(ZoneInfo(config.timezone)).date()
    snapshot = DailySnapshot(snapshot_date=today, capture_type=capture_type)
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
        port_ships = wg.get("port_ships")
        if port_ships is not None:
            previous = db.scalar(
                select(DailySnapshot)
                .where(DailySnapshot.port_ships_json.is_not(None))
                .order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc())
                .limit(1)
            )
            previous_port = json.loads(previous.port_ships_json) if previous and previous.port_ships_json else None
            snapshot.port_ships_json = json.dumps(port_ships)
            if active_plan:
                state = update_line_state(
                    previous_port,
                    port_ships,
                    active_plan.completed_cycles,
                    active_plan.current_ship_index,
                    active_plan.waiting_for_reset,
                )
                active_plan.completed_cycles = state["completed_cycles"]
                active_plan.current_ship_index = state["current_ship_index"]
                active_plan.waiting_for_reset = state["waiting_for_reset"]
                snapshot.line_state_json = json.dumps(state, ensure_ascii=False)
                db.add(active_plan)
        port_available = wg.get("port_ships") is not None
        message = "同步成功" if port_available else "战绩同步成功，但 OAuth 未返回 private.port；线路进度未更新"
        statuses["wargaming"] = {"ok": True, "port_available": port_available}
        _status(db, "wargaming", True, message)
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


SYNC_LOCK = asyncio.Lock()


async def guarded_sync(db: Session, capture_type: str = "manual") -> DailySnapshot:
    """Serialize scheduled, web, and QQ-triggered collection runs."""
    async with SYNC_LOCK:
        return await sync_all(db, capture_type=capture_type)


def dashboard_context(db: Session) -> dict:
    goals = list(db.scalars(select(RewardGoal).where(RewardGoal.active.is_(True)).order_by(RewardGoal.deadline)))
    latest = db.scalar(select(DailySnapshot).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(1))
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
        baseline = json.loads(plan.baseline_json or "[]")
        eligible = [item for item in baseline if item["date"] <= today.isoformat()]
        target = (eligible or baseline[:1])[-1] if baseline else None
        actual_xp = line_progress_xp(plan.completed_cycles, plan.current_ship_index, plan.waiting_for_reset)
        if target:
            status = "达标" if actual_xp >= target["target_xp"] else "落后"
            if actual_xp > target["target_xp"]:
                status = "超前"
            reached = [item for item in baseline if item["target_xp"] <= actual_xp]
            expected_date = date.fromisoformat(reached[-1]["date"]) if reached else date.fromisoformat(baseline[0]["date"])
            milestone = {
                "status": status,
                "target": target,
                "delta_days": (expected_date - today).days,
                "actual_xp_floor": actual_xp,
                "actual_ship": "等待重置" if plan.waiting_for_reset else BRITISH_LIGHT_CRUISER_LINE[plan.current_ship_index]["name"],
            }
        projection["line_xp_per_reset"] = LINE_XP_PER_RESET
        projection["line_total_xp"] = plan.target_resets * LINE_XP_PER_RESET
        projection["line_daily_xp"] = baseline[0].get("daily_xp", 0) if baseline else 0
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
