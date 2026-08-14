from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from ..centers.planning.models import DailySnapshot, ResetPlan, utcnow
from ..centers.planning.overview import get_activity_overview, report_text
from ..centers.planning.regrind import BRITISH_LIGHT_CRUISER_LINE, build_regrind_baseline, reset_count
from ..centers.planning.resources import EVENT_DEADLINE
from ..centers.planning.sync_service import guarded_sync
from ..core.config import config
from ..core.database import SessionLocal, init_db
from ..core.settings import has_setup, set_setting
from ..integrations.notifications import notify_with_fallback
from .backup import create_backup, prune_automatic_backups


scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def scheduled_sync() -> None:
    with SessionLocal() as db:
        await guarded_sync(db, capture_type="scheduled")
        try:
            backup_path = create_backup("auto")
            prune_automatic_backups(keep=30)
            set_setting(db, "last_backup_at", utcnow().isoformat())
            set_setting(db, "last_backup_file", backup_path.name)
            set_setting(db, "last_backup_error", "")
            db.commit()
        except Exception as exc:
            set_setting(db, "last_backup_error", str(exc)[:500])
            db.commit()


async def scheduled_report() -> None:
    with SessionLocal() as db:
        try:
            await notify_with_fallback(db, "战舰世界节日船团日报", report_text(db))
        except Exception:
            pass


def initialize_database_and_plans() -> None:
    init_db()
    with SessionLocal() as db:
        for plan in db.scalars(select(ResetPlan)):
            plan.deadline = EVENT_DEADLINE
            db.add(plan)
        db.commit()
        active = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if active and active.line_name != "英国轻巡：利安得 → 米诺陶":
            projection = get_activity_overview(db).projection
            target_resets = reset_count(projection["additional_research_points"], multiplier=active.multiplier)
            active.line_name = "英国轻巡：利安得 → 米诺陶"
            active.target_resets = target_resets
            active.completed_cycles = 0
            active.current_ship_index = 4
            active.waiting_for_reset = True
            active.ships_json = json.dumps(list(BRITISH_LIGHT_CRUISER_LINE), ensure_ascii=False)
            active.baseline_json = json.dumps(build_regrind_baseline(date.today(), EVENT_DEADLINE, target_resets), ensure_ascii=False)
            db.add(active)
            db.commit()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.add_job(scheduled_sync, "cron", hour=4, minute=0, id="daily-sync", replace_existing=True, coalesce=True, max_instances=1)
        scheduler.add_job(scheduled_report, "cron", hour=10, minute=0, id="daily-report", replace_existing=True, coalesce=True, max_instances=1)
        scheduler.start()


def schedule_startup_sync() -> None:
    with SessionLocal() as db:
        if not has_setup(db):
            return
        today = datetime.now(ZoneInfo(config.timezone)).date()
        exists = db.scalar(select(DailySnapshot).where(DailySnapshot.snapshot_date == today, DailySnapshot.capture_type == "scheduled"))
        if not exists:
            asyncio.create_task(scheduled_sync())
