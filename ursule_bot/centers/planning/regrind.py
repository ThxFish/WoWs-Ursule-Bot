from __future__ import annotations

import math
from datetime import date, timedelta


BRITISH_LIGHT_CRUISER_LINE = (
    {"name": "利安得", "tier": 6, "ship_id": 4183734224, "xp_to_next": 82_000},
    {"name": "斐济", "tier": 7, "ship_id": 4182685648, "xp_to_next": 126_500},
    {"name": "爱丁堡", "tier": 8, "ship_id": 4181637072, "xp_to_next": 201_000},
    {"name": "涅普顿", "tier": 9, "ship_id": 4180588496, "xp_to_next": 280_000},
    {"name": "米诺陶", "tier": 10, "ship_id": 4179539920, "xp_to_next": 0},
)
LINE_XP_PER_RESET = sum(ship["xp_to_next"] for ship in BRITISH_LIGHT_CRUISER_LINE)


def reset_count(required_rp: int, line_base_rp: int = 10_200, multiplier: int = 1) -> int:
    return math.ceil(max(0, required_rp) / max(1, line_base_rp * max(1, multiplier)))


def line_progress_xp(completed_cycles: int, current_ship_index: int, waiting_for_reset: bool) -> int:
    progress = max(0, completed_cycles) * LINE_XP_PER_RESET
    if waiting_for_reset:
        return progress
    index = min(max(0, current_ship_index), len(BRITISH_LIGHT_CRUISER_LINE) - 1)
    return progress + sum(ship["xp_to_next"] for ship in BRITISH_LIGHT_CRUISER_LINE[:index])


def build_regrind_baseline(start: date, deadline: date, resets: int) -> list[dict]:
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
        cycle, ship_index = resets, len(BRITISH_LIGHT_CRUISER_LINE) - 1
        for threshold, candidate_cycle, candidate_index in thresholds:
            if target_xp < threshold:
                cycle, ship_index = candidate_cycle, candidate_index
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
