from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import config


class Base(DeclarativeBase):
    pass


config.ensure_dirs()
database_path = config.data_dir / "tracker.db"
database_url = f"sqlite:///{database_path.as_posix()}"
engine = create_engine(database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(root / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", str(engine.url).replace("%", "%%"))
    return alembic_config


def _load_models() -> None:
    from . import system_models  # noqa: F401
    from ..centers.planning import models  # noqa: F401


def _upgrade_legacy_schema() -> None:
    """Normalize every pre-Alembic MVP database before stamping the baseline."""
    from ..centers.planning import models

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
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
    snapshot_columns = {column["name"] for column in inspector.get_columns("daily_snapshots")}
    with engine.begin() as connection:
        for name, sql_type in expected_snapshot_columns.items():
            if name not in snapshot_columns:
                connection.execute(text(f"ALTER TABLE daily_snapshots ADD COLUMN {name} {sql_type}"))
        forecast_columns = {column["name"] for column in inspect(connection).get_columns("resource_forecasts")}
        if "cadence" not in forecast_columns:
            connection.execute(text("ALTER TABLE resource_forecasts ADD COLUMN cadence VARCHAR(16) DEFAULT 'once'"))
        connection.execute(text("UPDATE resource_forecasts SET cadence = 'once' WHERE cadence IS NULL OR cadence = ''"))
        connection.execute(text("UPDATE reward_goals SET deadline = '2027-02-01'"))
        connection.execute(text("UPDATE reset_plans SET deadline = '2027-02-01'"))
        plan_columns = {column["name"] for column in inspect(connection).get_columns("reset_plans")}
        for name, sql_type in {
            "target_resets": "INTEGER DEFAULT 0",
            "completed_cycles": "INTEGER DEFAULT 0",
            "waiting_for_reset": "BOOLEAN DEFAULT 1",
        }.items():
            if name not in plan_columns:
                connection.execute(text(f"ALTER TABLE reset_plans ADD COLUMN {name} {sql_type}"))

    date_is_unique = any(
        constraint.get("column_names") == ["snapshot_date"]
        for constraint in inspect(engine).get_unique_constraints("daily_snapshots")
    )
    if date_is_unique:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE daily_snapshots RENAME TO daily_snapshots_legacy"))
            models.DailySnapshot.__table__.create(connection)
            legacy_columns = {column["name"] for column in inspect(connection).get_columns("daily_snapshots_legacy")}
            copied = [column.name for column in models.DailySnapshot.__table__.columns if column.name in legacy_columns]
            columns_sql = ", ".join(f'"{name}"' for name in copied)
            connection.execute(text(f"INSERT INTO daily_snapshots ({columns_sql}) SELECT {columns_sql} FROM daily_snapshots_legacy"))
            connection.execute(text("DROP TABLE daily_snapshots_legacy"))


def init_db() -> None:
    _load_models()
    tables = set(inspect(engine).get_table_names())
    alembic_config = _alembic_config()
    legacy_tables = tables - {"alembic_version"}
    if legacy_tables and "alembic_version" not in tables:
        _upgrade_legacy_schema()
        command.stamp(alembic_config, "head")
    else:
        command.upgrade(alembic_config, "head")


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
