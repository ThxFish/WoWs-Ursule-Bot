from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from ursule_bot.core import database as db_module
from ursule_bot.centers.planning import sync_service as service
from ursule_bot.integrations.collectors import ArmoryData
from ursule_bot.core.database import Base
from ursule_bot.centers.planning.activity_day import activity_date
from ursule_bot.centers.planning.models import DailySnapshot
from ursule_bot.centers.planning.overview import get_activity_overview


def test_activity_date_changes_at_four_am():
    assert activity_date(datetime(2026, 8, 15, 3, 59, 59)) == date(2026, 8, 14)
    assert activity_date(datetime(2026, 8, 15, 4, 0, 0)) == date(2026, 8, 15)


def test_overview_reads_latest_existing_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    collected_at = datetime(2026, 8, 15, 4, tzinfo=timezone.utc)

    with Session(engine) as session:
        session.add_all([
            DailySnapshot(snapshot_date=date(2026, 8, 15), holiday_tokens=100, collected_at=collected_at),
            DailySnapshot(snapshot_date=date(2026, 8, 15), holiday_tokens=250, collected_at=collected_at + timedelta(hours=2)),
        ])
        session.commit()

        overview = get_activity_overview(session)

    assert overview.latest is not None
    assert overview.latest.holiday_tokens == 250


async def test_each_sync_creates_an_independent_snapshot(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    async def armory():
        return ArmoryData(coal=100)

    async def wargaming(*_args):
        return {"ships": [], "battles": 10, "xp": 20, "port_ships": []}

    async def third_party(_account_id):
        return {}

    monkeypatch.setattr(service, "collect_armory", armory)
    monkeypatch.setattr(service, "collect_wargaming", wargaming)
    monkeypatch.setattr(service, "collect_third_party", third_party)

    with Session(engine) as session:
        first = await service.sync_all(session, capture_type="scheduled")
        second = await service.sync_all(session, capture_type="manual_snapshot")
        rows = list(session.scalars(select(DailySnapshot).order_by(DailySnapshot.id)))

    assert first.id != second.id
    assert len(rows) == 2
    assert rows[0].snapshot_date == rows[1].snapshot_date
    assert [row.capture_type for row in rows] == ["scheduled", "manual_snapshot"]


def test_legacy_unique_date_database_is_migrated(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE daily_snapshots (
                id INTEGER PRIMARY KEY,
                snapshot_date DATE NOT NULL UNIQUE,
                holiday_tokens INTEGER,
                coal INTEGER,
                steel INTEGER,
                research_points INTEGER,
                battles_total INTEGER,
                xp_total INTEGER,
                boosters_json TEXT NOT NULL DEFAULT '{}',
                ships_json TEXT NOT NULL DEFAULT '[]',
                source_status_json TEXT NOT NULL DEFAULT '{}',
                collected_at DATETIME NOT NULL
            )
        """))
        connection.execute(
            text("INSERT INTO daily_snapshots (id, snapshot_date, coal, collected_at) VALUES (1, :day, 50, :at)"),
            {"day": date(2026, 8, 14), "at": datetime(2026, 8, 14, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(db_module, "engine", engine)
    db_module.init_db()

    assert not any(
        constraint.get("column_names") == ["snapshot_date"]
        for constraint in inspect(engine).get_unique_constraints("daily_snapshots")
    )
    with engine.begin() as connection:
        assert connection.execute(text("SELECT coal FROM daily_snapshots WHERE id = 1")).scalar_one() == 50
        connection.execute(text("""
            INSERT INTO daily_snapshots (
                snapshot_date, capture_type, boosters_json, ships_json,
                line_state_json, source_status_json, collected_at
            ) VALUES ('2026-08-14', 'manual_snapshot', '{}', '[]', '{}', '{}', '2026-08-14 12:00:00')
        """))
        assert connection.execute(text("SELECT COUNT(*) FROM daily_snapshots WHERE snapshot_date = '2026-08-14'")).scalar_one() == 2
