from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ShipStep:
    name: str
    xp: int
    ship_id: int | None = None


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
    cumulative = 0
    thresholds = []
    for ship in remaining:
        cumulative += max(0, ship.xp)
        thresholds.append(cumulative)
    output = []
    for offset in range(days):
        progress = total_xp if days == 1 else round(total_xp * offset / (days - 1))
        idx = 0
        while idx < len(thresholds) - 1 and thresholds[idx] <= progress:
            idx += 1
        output.append({"date": (start + timedelta(days=offset)).isoformat(), "ship": remaining[idx].name, "ship_index": current_index + idx, "target_xp": progress})
    output[-1].update({"ship": remaining[-1].name, "ship_index": len(ships) - 1, "target_xp": total_xp})
    return output


def milestone_status(baseline: list[dict], on_date: date, actual_index: int) -> dict:
    if not baseline:
        return {"status": "未配置", "target": None, "delta_days": 0}
    eligible = [item for item in baseline if item["date"] <= on_date.isoformat()]
    target = (eligible or baseline[:1])[-1]
    dates = [item for item in baseline if item["ship_index"] <= actual_index]
    expected = date.fromisoformat(dates[-1]["date"] if dates else baseline[0]["date"])
    status = "达标" if actual_index >= target["ship_index"] else "落后"
    if actual_index > target["ship_index"]:
        status = "超前"
    return {"status": status, "target": target, "delta_days": (expected - on_date).days, "actual_index": actual_index}
