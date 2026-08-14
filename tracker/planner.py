from __future__ import annotations

import json
import math
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


RATES = {
    "coal": (5_000, 1_500),
    "steel": (500, 1_500),
    "research_points": (1_000, 1_500),
}
COAL_EXCHANGE_CAP = 650_000
EVENT_DEADLINE = date(2027, 2, 1)


@dataclass(frozen=True)
class ShipStep:
    name: str
    xp: int
    ship_id: int | None = None


def exchange_tokens(resource_type: str, amount: int) -> int:
    if resource_type not in RATES:
        return 0
    if resource_type == "coal":
        amount = min(amount, COAL_EXCHANGE_CAP)
    block, tokens = RATES[resource_type]
    return max(0, amount) // block * tokens


def token_plan(goal_tokens: int, current_tokens: int, resources: dict[str, int], mission_tokens: int = 0) -> dict:
    remaining = max(0, goal_tokens - current_tokens - max(0, mission_tokens))
    converted: dict[str, int] = {}
    used: dict[str, int] = {}
    for resource_type in ("coal", "steel", "research_points"):
        amount = max(0, int(resources.get(resource_type, 0)))
        if resource_type == "coal":
            amount = min(amount, COAL_EXCHANGE_CAP)
        unit, tokens_per_block = RATES[resource_type]
        available_blocks = amount // unit
        needed_blocks = math.ceil(remaining / tokens_per_block) if remaining else 0
        blocks = min(available_blocks, needed_blocks)
        used[resource_type] = blocks * unit
        converted[resource_type] = blocks * tokens_per_block
        remaining = max(0, remaining - converted[resource_type])
    projected = current_tokens + max(0, mission_tokens) + sum(converted.values())
    gap = remaining
    rp_needed = math.ceil(gap / 1_500) * 1_000 if gap else 0
    return {
        "goal_tokens": goal_tokens,
        "current_tokens": current_tokens,
        "converted": converted,
        "used": used,
        "mission_tokens": max(0, mission_tokens),
        "projected_tokens": projected,
        "gap_tokens": gap,
        "additional_research_points": rp_needed,
    }


def reset_count(required_rp: int, line_base_rp: int = 10_200, multiplier: int = 1) -> int:
    per_reset = max(1, line_base_rp * max(1, multiplier))
    return math.ceil(max(0, required_rp) / per_reset)


def recurring_occurrences(start: date, deadline: date, cadence: str) -> int:
    if start > deadline:
        return 0
    if cadence == "daily":
        return (deadline - start).days + 1
    if cadence == "weekly":
        return (deadline - start).days // 7 + 1
    if cadence == "monthly":
        count = 0
        year, month = start.year, start.month
        while True:
            day = min(start.day, calendar.monthrange(year, month)[1])
            occurrence = date(year, month, day)
            if occurrence > deadline:
                break
            if occurrence >= start:
                count += 1
            month += 1
            if month == 13:
                year += 1
                month = 1
        return count
    return 1


def parse_ship_steps(raw: str | list[dict]) -> list[ShipStep]:
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    return [ShipStep(str(item["name"]), int(item.get("xp", 0)), int(item["ship_id"]) if item.get("ship_id") else None) for item in raw]


def build_baseline(start: date, deadline: date, ships: list[ShipStep], current_index: int = 0) -> list[dict]:
    if not ships or deadline < start:
        return []
    current_index = min(max(0, current_index), len(ships) - 1)
    remaining = ships[current_index:]
    total_xp = sum(max(0, ship.xp) for ship in remaining)
    days = (deadline - start).days + 1
    output: list[dict] = []
    cumulative = 0
    thresholds: list[int] = []
    for ship in remaining:
        cumulative += max(0, ship.xp)
        thresholds.append(cumulative)
    for offset in range(days):
        progress = total_xp if days == 1 else round(total_xp * offset / (days - 1))
        idx = 0
        while idx < len(thresholds) - 1 and thresholds[idx] <= progress:
            idx += 1
        step = remaining[idx]
        output.append({"date": (start + timedelta(days=offset)).isoformat(), "ship": step.name, "ship_index": current_index + idx, "target_xp": progress})
    output[-1]["ship"] = remaining[-1].name
    output[-1]["ship_index"] = len(ships) - 1
    output[-1]["target_xp"] = total_xp
    return output


def milestone_status(baseline: list[dict], on_date: date, actual_index: int) -> dict:
    if not baseline:
        return {"status": "未配置", "target": None, "delta_days": 0}
    eligible = [item for item in baseline if item["date"] <= on_date.isoformat()]
    target = (eligible or baseline[:1])[-1]
    dates_at_actual = [item for item in baseline if item["ship_index"] <= actual_index]
    expected_date = date.fromisoformat(dates_at_actual[-1]["date"]) if dates_at_actual else date.fromisoformat(baseline[0]["date"])
    delta = (expected_date - on_date).days
    status = "达标" if actual_index >= target["ship_index"] else "落后"
    if actual_index > target["ship_index"]:
        status = "超前"
    return {"status": status, "target": target, "delta_days": delta, "actual_index": actual_index}
