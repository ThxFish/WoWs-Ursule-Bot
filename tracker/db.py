from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import config


class Base(DeclarativeBase):
    pass


config.ensure_dirs()
engine = create_engine(
    f"sqlite:///{(config.data_dir / 'tracker.db').as_posix()}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from . import models

    Base.metadata.create_all(engine)
    # Lightweight additive migration for existing MVP databases.
    expected_snapshot_columns = {
        "credits": "INTEGER",
        "gold": "INTEGER",
        "community_tokens": "INTEGER",
        "free_xp": "INTEGER",
        "elite_commander_xp": "INTEGER",
        "port_ships_json": "TEXT",
        "line_state_json": "TEXT DEFAULT '{}'",
        "capture_type": "VARCHAR(24) DEFAULT 'legacy'",
    }
    existing = {column["name"] for column in inspect(engine).get_columns("daily_snapshots")}
    with engine.begin() as connection:
        for name, sql_type in expected_snapshot_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE daily_snapshots ADD COLUMN {name} {sql_type}"))
        forecast_columns = {column["name"] for column in inspect(engine).get_columns("resource_forecasts")}
        if "cadence" not in forecast_columns:
            connection.execute(text("ALTER TABLE resource_forecasts ADD COLUMN cadence VARCHAR(16) DEFAULT 'once'"))
        connection.execute(text("UPDATE resource_forecasts SET cadence = 'once' WHERE cadence IS NULL OR cadence = ''"))
        connection.execute(text("UPDATE reward_goals SET deadline = '2027-02-01'"))
        connection.execute(text("UPDATE reset_plans SET deadline = '2027-02-01'"))
        plan_columns = {column["name"] for column in inspect(engine).get_columns("reset_plans")}
        if "target_resets" not in plan_columns:
            connection.execute(text("ALTER TABLE reset_plans ADD COLUMN target_resets INTEGER DEFAULT 0"))
        if "completed_cycles" not in plan_columns:
            connection.execute(text("ALTER TABLE reset_plans ADD COLUMN completed_cycles INTEGER DEFAULT 0"))
        if "waiting_for_reset" not in plan_columns:
            connection.execute(text("ALTER TABLE reset_plans ADD COLUMN waiting_for_reset BOOLEAN DEFAULT 1"))

    # Older databases enforced one snapshot per date. Rebuild only this table so
    # scheduled and manual captures can coexist while preserving every old row.
    date_is_unique = any(
        constraint.get("column_names") == ["snapshot_date"]
        for constraint in inspect(engine).get_unique_constraints("daily_snapshots")
    )
    if date_is_unique:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE daily_snapshots RENAME TO daily_snapshots_legacy"))
            models.DailySnapshot.__table__.create(connection)
            legacy_columns = {
                column["name"] for column in inspect(connection).get_columns("daily_snapshots_legacy")
            }
            current_columns = [column.name for column in models.DailySnapshot.__table__.columns]
            copied_columns = [name for name in current_columns if name in legacy_columns]
            columns_sql = ", ".join(f'"{name}"' for name in copied_columns)
            connection.execute(text(
                f"INSERT INTO daily_snapshots ({columns_sql}) "
                f"SELECT {columns_sql} FROM daily_snapshots_legacy"
            ))
            connection.execute(text("DROP TABLE daily_snapshots_legacy"))


def get_db():
    with SessionLocal() as session:
        yield session


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
