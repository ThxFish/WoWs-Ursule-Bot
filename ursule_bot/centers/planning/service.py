from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.settings import set_setting
from .models import ManualOverride, ResourceForecast, ResetPlan, RewardGoal
from .overview import get_activity_overview
from .regrind import BRITISH_LIGHT_CRUISER_LINE, build_regrind_baseline, reset_count
from .resources import EVENT_DEADLINE


VALID_RESOURCES = {"coal", "steel", "research_points"}
VALID_CADENCES = {"once", "daily", "weekly", "monthly"}


def add_goal(db: Session, name: str, quantity: int, token_cost: int) -> RewardGoal:
    goal = RewardGoal(name=name.strip(), quantity=max(1, quantity), token_cost=max(0, token_cost), deadline=EVENT_DEADLINE)
    db.add(goal)
    db.commit()
    return goal


def delete_goal(db: Session, goal_id: int) -> None:
    if row := db.get(RewardGoal, goal_id):
        db.delete(row)
        db.commit()


def add_forecast(db: Session, resource_type: str, amount: int, available_on: date, cadence: str, note: str) -> ResourceForecast:
    if resource_type not in VALID_RESOURCES:
        raise ValueError("未知资源类型")
    if cadence not in VALID_CADENCES:
        raise ValueError("未知周期")
    row = ResourceForecast(resource_type=resource_type, amount=max(0, amount), available_on=available_on, cadence=cadence, note=note.strip())
    db.add(row)
    db.commit()
    return row


def delete_forecast(db: Session, forecast_id: int) -> None:
    if row := db.get(ResourceForecast, forecast_id):
        db.delete(row)
        db.commit()


def save_resource_allocation(db: Session, coal: int, steel: int, research_points: int) -> None:
    for key, amount in {"coal": coal, "steel": steel, "research_points": research_points}.items():
        set_setting(db, f"committed_{key}", str(max(0, amount)))
    db.commit()


def save_regrind_plan(db: Session, multiplier: int) -> ResetPlan:
    multiplier = max(1, multiplier)
    target_resets = reset_count(get_activity_overview(db).projection["additional_research_points"], multiplier=multiplier)
    for old in db.scalars(select(ResetPlan).where(ResetPlan.active.is_(True))):
        old.active = False
    row = ResetPlan(
        line_name="英国轻巡：利安得 → 米诺陶",
        multiplier=multiplier,
        deadline=EVENT_DEADLINE,
        current_ship_index=4,
        target_resets=target_resets,
        completed_cycles=0,
        waiting_for_reset=True,
        ships_json=json.dumps(list(BRITISH_LIGHT_CRUISER_LINE), ensure_ascii=False),
        baseline_json=json.dumps(build_regrind_baseline(date.today(), EVENT_DEADLINE, target_resets), ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return row


def add_manual_override(db: Session, field_name: str, value: str, reason: str) -> ManualOverride:
    if field_name not in {"holiday_tokens", "current_ship_index", "coal", "steel", "research_points"}:
        raise ValueError("不允许修正该字段")
    try:
        int(value)
    except ValueError as exc:
        raise ValueError("修正值必须为整数") from exc
    row = ManualOverride(snapshot_date=date.today(), field_name=field_name, value=value, reason=reason.strip())
    db.add(row)
    db.commit()
    return row
