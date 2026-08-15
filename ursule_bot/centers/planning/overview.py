from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import config
from ...core.settings import get_setting
from ...core.system_models import DataSourceStatus
from .models import DailySnapshot, ManualOverride, ResourceForecast, ResetPlan, RewardGoal
from .regrind import BRITISH_LIGHT_CRUISER_LINE, LINE_XP_PER_RESET, current_regrind_checkpoint, line_progress_xp, reset_count
from .resources import EVENT_DEADLINE, recurring_occurrences, token_plan


@dataclass(frozen=True)
class ActivityOverview:
    goals: list[RewardGoal]
    latest: DailySnapshot | None
    boosters: dict[str, int]
    projection: dict[str, Any]
    plan: ResetPlan | None
    milestone: dict[str, Any] | None
    statuses: list[DataSourceStatus]
    overrides: dict[str, str]

    def template_context(self) -> dict[str, Any]:
        return self.__dict__.copy()


def get_activity_overview(db: Session) -> ActivityOverview:
    goals = list(db.scalars(select(RewardGoal).where(RewardGoal.active.is_(True)).order_by(RewardGoal.deadline)))
    latest = db.scalar(select(DailySnapshot).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(1))
    overrides = {row.field_name: row.value for row in db.scalars(select(ManualOverride).order_by(ManualOverride.created_at))}
    current_tokens = int(overrides.get("holiday_tokens", latest.holiday_tokens if latest and latest.holiday_tokens is not None else 0))
    goal_tokens = sum(goal.token_cost * goal.quantity for goal in goals)
    requested = {key: int(get_setting(db, f"committed_{key}", "0") or 0) for key in ("coal", "steel", "research_points")}
    current = {key: getattr(latest, key) if latest and getattr(latest, key) is not None else 0 for key in requested}
    additions = {key: 0 for key in requested}
    for forecast in db.scalars(select(ResourceForecast).where(ResourceForecast.available_on <= EVENT_DEADLINE)):
        additions[forecast.resource_type] += forecast.amount * recurring_occurrences(forecast.available_on, EVENT_DEADLINE, forecast.cadence)
    available = {key: current[key] + additions[key] for key in current}
    effective = {key: min(requested[key], available[key]) for key in requested}
    today = datetime.now(ZoneInfo(config.timezone)).date()
    remaining_days = max(0, (EVENT_DEADLINE - today).days)
    projection = token_plan(goal_tokens, current_tokens, effective, remaining_days * int(get_setting(db, "daily_token_target", "1200") or 0))
    projection.update({"requested_resources": requested, "available_resources": available, "forecast_additions": additions, "current_resources": current})
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
            expected_date = date.fromisoformat(reached[-1]["date"] if reached else baseline[0]["date"])
            checkpoint = current_regrind_checkpoint(
                baseline,
                plan.completed_cycles,
                plan.current_ship_index,
                plan.waiting_for_reset,
                today,
            )
            milestone = {
                "status": status,
                "target": target,
                "checkpoint": checkpoint,
                "delta_days": (expected_date - today).days,
                "actual_xp_floor": actual_xp,
                "actual_ship": "等待重置" if plan.waiting_for_reset else BRITISH_LIGHT_CRUISER_LINE[plan.current_ship_index]["name"],
            }
        projection.update({"line_xp_per_reset": LINE_XP_PER_RESET, "line_total_xp": plan.target_resets * LINE_XP_PER_RESET, "line_daily_xp": baseline[0].get("daily_xp", 0) if baseline else 0})
    return ActivityOverview(goals, latest, json.loads(latest.boosters_json or "{}") if latest else {}, projection, plan, milestone, list(db.scalars(select(DataSourceStatus).order_by(DataSourceStatus.name))), overrides)


def report_text(db: Session) -> str:
    overview = get_activity_overview(db)
    p, m, latest = overview.projection, overview.milestone or {}, overview.latest
    target = (m.get("target") or {}).get("ship", "未配置")
    return (
        "战舰世界节日船团日报\n"
        f"代币：{latest.holiday_tokens if latest and latest.holiday_tokens is not None else '未知'} / {p['goal_tokens']}\n"
        f"计入兑换后预计：{p['projected_tokens']}，缺口：{p['gap_tokens']}\n"
        f"今日研发线目标：{target}，状态：{m.get('status', '未配置')}\n"
        f"数据日期：{latest.snapshot_date if latest else '尚无'}"
    )
