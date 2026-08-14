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

BRITISH_LIGHT_CRUISER_LINE = (
    {"name": "利安得", "tier": 6, "ship_id": 4183734224, "xp_to_next": 82_000},
    {"name": "斐济", "tier": 7, "ship_id": 4182685648, "xp_to_next": 126_500},
    {"name": "爱丁堡", "tier": 8, "ship_id": 4181637072, "xp_to_next": 201_000},
    {"name": "涅普顿", "tier": 9, "ship_id": 4180588496, "xp_to_next": 280_000},
    {"name": "米诺陶", "tier": 10, "ship_id": 4179539920, "xp_to_next": 0},
)
LINE_XP_PER_RESET = sum(ship["xp_to_next"] for ship in BRITISH_LIGHT_CRUISER_LINE)


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


def line_progress_xp(completed_cycles: int, current_ship_index: int, waiting_for_reset: bool) -> int:
    """Return conservative, milestone-based XP progress for the fixed line."""
    progress = max(0, completed_cycles) * LINE_XP_PER_RESET
    if waiting_for_reset:
        return progress
    index = min(max(0, current_ship_index), len(BRITISH_LIGHT_CRUISER_LINE) - 1)
    return progress + sum(ship["xp_to_next"] for ship in BRITISH_LIGHT_CRUISER_LINE[:index])


def build_regrind_baseline(start: date, deadline: date, resets: int) -> list[dict]:
    """Evenly distribute all required line XP over the available calendar days."""
    if deadline < start or resets <= 0:
        return []
    days = (deadline - start).days + 1
    total_xp = resets * LINE_XP_PER_RESET
    daily_xp = math.ceil(total_xp / days)
    thresholds = []
    cumulative = 0
    for cycle in range(1, resets + 1):
        for index, ship in enumerate(BRITISH_LIGHT_CRUISER_LINE[:-1]):
            cumulative += ship["xp_to_next"]
            thresholds.append((cumulative, cycle, index))
    output = []
    for offset in range(days):
        target_xp = min(total_xp, round(total_xp * (offset + 1) / days))
        cycle = resets
        ship_index = len(BRITISH_LIGHT_CRUISER_LINE) - 1
        for threshold, candidate_cycle, candidate_index in thresholds:
            if target_xp < threshold:
                cycle = candidate_cycle
                ship_index = candidate_index
                break
        output.append({
            "date": (start + timedelta(days=offset)).isoformat(),
            "cycle": cycle,
            "ship": BRITISH_LIGHT_CRUISER_LINE[ship_index]["name"],
            "ship_index": ship_index,
            "target_xp": target_xp,
            "daily_xp": daily_xp,
        })
    output[-1].update({"cycle": resets, "ship": "米诺陶可研发并重置", "ship_index": 4, "target_xp": total_xp})
    return output


def update_line_state(previous_port: list[int] | None, current_port: list[int] | None, completed_cycles: int, current_ship_index: int, waiting_for_reset: bool) -> dict:
    """Advance state only from authoritative private.port snapshots."""
    state = {
        "completed_cycles": max(0, completed_cycles),
        "current_ship_index": min(max(0, current_ship_index), 4),
        "waiting_for_reset": bool(waiting_for_reset),
        "event": "",
    }
    if current_port is None:
        return state
    current = set(map(int, current_port))
    previous = set(map(int, previous_port)) if previous_port is not None else None
    ids = [int(ship["ship_id"]) for ship in BRITISH_LIGHT_CRUISER_LINE]
    minotaur = ids[-1]

    if previous is None:
        owned = [index for index, ship_id in enumerate(ids) if ship_id in current]
        if owned and not state["waiting_for_reset"]:
            state["current_ship_index"] = max(owned)
        return state

    if state["waiting_for_reset"] and minotaur in previous and minotaur not in current:
        state["waiting_for_reset"] = False
        state["current_ship_index"] = max((index for index, ship_id in enumerate(ids[:-1]) if ship_id in current), default=0)
        state["event"] = "检测到米诺陶离港，本轮重置开始"
        return state

    if not state["waiting_for_reset"]:
        if ids[3] in previous and ids[3] not in current and ids[0] in current:
            state["completed_cycles"] += 1
            state["current_ship_index"] = 0
            state["waiting_for_reset"] = False
            state["event"] = "检测到涅普顿离港且利安得入港：上一轮完成，下一轮开始"
            return state
        higher = [index for index, ship_id in enumerate(ids) if ship_id in current and index > state["current_ship_index"]]
        if higher:
            old_name = BRITISH_LIGHT_CRUISER_LINE[state["current_ship_index"]]["name"]
            state["current_ship_index"] = max(higher)
            state["event"] = f"检测到{old_name}之后的高级舰船入港"
    return state


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
