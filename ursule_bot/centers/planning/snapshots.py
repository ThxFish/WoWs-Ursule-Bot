from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import config
from .models import DailySnapshot, ManualOverride, ResetPlan, utcnow
from .regrind import BRITISH_LIGHT_CRUISER_LINE


@dataclass(frozen=True)
class SnapshotView:
    row: DailySnapshot
    boosters: dict
    state: dict
    line_ship: str


def list_snapshot_views(db: Session, limit: int = 200) -> list[SnapshotView]:
    rows = list(db.scalars(select(DailySnapshot).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(limit)))
    line_ids = {int(ship["ship_id"]): ship["name"] for ship in BRITISH_LIGHT_CRUISER_LINE}
    output = []
    for row in rows:
        state = json.loads(row.line_state_json or "{}")
        port = json.loads(row.port_ships_json) if row.port_ships_json else []
        index = state.get("current_ship_index")
        if state.get("waiting_for_reset"):
            line_ship = "等待首次重置"
        elif isinstance(index, int) and 0 <= index < len(BRITISH_LIGHT_CRUISER_LINE):
            line_ship = BRITISH_LIGHT_CRUISER_LINE[index]["name"]
        else:
            owned = [line_ids[ship_id] for ship_id in port if ship_id in line_ids]
            line_ship = "、".join(owned) if owned else "未记录"
        output.append(SnapshotView(row, json.loads(row.boosters_json or "{}"), state, line_ship))
    return output


def update_snapshot(db: Session, snapshot_id: int, values: dict[str, str]) -> DailySnapshot:
    snapshot = db.get(DailySnapshot, snapshot_id)
    if not snapshot:
        raise LookupError("快照不存在")
    reason = values.get("reason", "").strip()
    if not reason:
        raise ValueError("请填写修改原因")
    integer_fields = ("holiday_tokens", "credits", "gold", "coal", "steel", "research_points", "community_tokens", "free_xp", "elite_commander_xp", "battles_total")
    try:
        parsed = {name: None if values.get(name, "").strip() == "" else max(0, int(values[name])) for name in integer_fields}
        booster_values = {name: None if values.get(name, "").strip() == "" else max(0, int(values[name])) for name in ("rare_credits", "rare_ship_xp", "rare_commander_xp", "rare_free_xp")}
        line_stage = int(values.get("line_stage", "-1"))
        completed_cycles = max(0, int(values.get("completed_cycles", "0")))
    except (ValueError, KeyError) as exc:
        raise ValueError("数值字段格式不正确") from exc
    for name, new_value in parsed.items():
        if getattr(snapshot, name) != new_value:
            setattr(snapshot, name, new_value)
            db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.{name}", value="" if new_value is None else str(new_value), reason=reason))
    boosters = json.loads(snapshot.boosters_json or "{}")
    for name, new_value in booster_values.items():
        if boosters.get(name) != new_value:
            boosters.pop(name, None) if new_value is None else boosters.__setitem__(name, new_value)
            db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.{name}", value="" if new_value is None else str(new_value), reason=reason))
    snapshot.boosters_json = json.dumps(boosters, ensure_ascii=False)
    if raw_time := values.get("collected_at", "").strip():
        local_time = datetime.fromisoformat(raw_time)
        if local_time.tzinfo is None:
            local_time = local_time.replace(tzinfo=ZoneInfo(config.timezone))
        snapshot.collected_at = local_time.astimezone(timezone.utc)
    state = json.loads(snapshot.line_state_json or "{}")
    waiting, current_index = line_stage < 0, 4 if line_stage < 0 else min(line_stage, 3)
    if (state.get("waiting_for_reset"), state.get("current_ship_index"), state.get("completed_cycles")) != (waiting, current_index, completed_cycles):
        state.update({"waiting_for_reset": waiting, "current_ship_index": current_index, "completed_cycles": completed_cycles, "event": f"手工修正：{reason}"})
        snapshot.line_state_json = json.dumps(state, ensure_ascii=False)
        db.add(ManualOverride(snapshot_date=snapshot.snapshot_date, field_name=f"snapshot.{snapshot.id}.line_state", value=json.dumps(state, ensure_ascii=False), reason=reason))
        latest_id = db.scalar(select(DailySnapshot.id).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(1))
        plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if snapshot.id == latest_id and plan:
            plan.waiting_for_reset, plan.current_ship_index, plan.completed_cycles = waiting, current_index, completed_cycles
            db.add(plan)
    statuses = json.loads(snapshot.source_status_json or "{}")
    statuses["manual_edit"] = {"ok": True, "edited_at": utcnow().isoformat(), "reason": reason}
    snapshot.source_status_json = json.dumps(statuses, ensure_ascii=False)
    db.add(snapshot)
    db.commit()
    return snapshot
