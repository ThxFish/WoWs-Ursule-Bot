from __future__ import annotations

import calendar
import math
from datetime import date


RATES = {
    "coal": (5_000, 1_500),
    "steel": (500, 1_500),
    "research_points": (1_000, 1_500),
}
COAL_EXCHANGE_CAP = 650_000
EVENT_DEADLINE = date(2027, 2, 1)


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
        blocks = min(amount // unit, math.ceil(remaining / tokens_per_block) if remaining else 0)
        used[resource_type] = blocks * unit
        converted[resource_type] = blocks * tokens_per_block
        remaining = max(0, remaining - converted[resource_type])
    projected = current_tokens + max(0, mission_tokens) + sum(converted.values())
    return {
        "goal_tokens": goal_tokens,
        "current_tokens": current_tokens,
        "converted": converted,
        "used": used,
        "mission_tokens": max(0, mission_tokens),
        "projected_tokens": projected,
        "gap_tokens": remaining,
        "additional_research_points": math.ceil(remaining / 1_500) * 1_000 if remaining else 0,
    }


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
            occurrence = date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
            if occurrence > deadline:
                break
            if occurrence >= start:
                count += 1
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return count
    return 1
