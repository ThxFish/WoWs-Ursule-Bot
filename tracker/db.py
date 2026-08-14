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
    from . import models  # noqa: F401

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
