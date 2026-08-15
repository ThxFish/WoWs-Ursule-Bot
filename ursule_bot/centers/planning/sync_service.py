from __future__ import annotations

import asyncio
import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.settings import get_setting
from ...core.system_models import DataSourceStatus
from ...integrations.collectors import collect_armory, collect_third_party, collect_wargaming, third_party_totals
from .activity_day import activity_date
from .line_state import update_line_state
from .models import DailySnapshot, ResetPlan, utcnow


def _status(db: Session, name: str, ok: bool, message: str) -> None:
    row = db.get(DataSourceStatus, name) or DataSourceStatus(name=name)
    row.ok = ok
    row.message = message[:1000]
    row.last_attempt_at = utcnow()
    if ok:
        row.last_success_at = utcnow()
    db.add(row)


async def sync_all(db: Session, capture_type: str = "manual") -> DailySnapshot:
    snapshot = DailySnapshot(snapshot_date=activity_date(), capture_type=capture_type)
    statuses: dict[str, dict] = {}
    try:
        armory = await collect_armory()
        for name in ("holiday_tokens", "credits", "gold", "coal", "steel", "research_points", "community_tokens", "free_xp", "elite_commander_xp"):
            setattr(snapshot, name, getattr(armory, name))
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
            previous = db.scalar(select(DailySnapshot).where(DailySnapshot.port_ships_json.is_not(None)).order_by(DailySnapshot.collected_at.desc(), DailySnapshot.id.desc()).limit(1))
            previous_port = json.loads(previous.port_ships_json) if previous and previous.port_ships_json else None
            snapshot.port_ships_json = json.dumps(port_ships)
            if active_plan:
                state = update_line_state(previous_port, port_ships, active_plan.completed_cycles, active_plan.current_ship_index, active_plan.waiting_for_reset)
                active_plan.completed_cycles = state["completed_cycles"]
                active_plan.current_ship_index = state["current_ship_index"]
                active_plan.waiting_for_reset = state["waiting_for_reset"]
                snapshot.line_state_json = json.dumps(state, ensure_ascii=False)
                db.add(active_plan)
        port_available = port_ships is not None
        message = "同步成功" if port_available else "战绩同步成功，但 OAuth 未返回 private.port；线路进度未更新"
        statuses["wargaming"] = {"ok": True, "port_available": port_available}
        _status(db, "wargaming", True, message)
    except Exception as exc:
        statuses["wargaming"] = {"ok": False, "error": str(exc)}
        _status(db, "wargaming", False, str(exc))

    try:
        fallback = third_party_totals(await collect_third_party(account_id))
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
    async with SYNC_LOCK:
        return await sync_all(db, capture_type=capture_type)
