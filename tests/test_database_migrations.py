from sqlalchemy import create_engine, inspect, text

from ursule_bot.core import database as db_module


def test_empty_database_upgrade_is_complete_and_idempotent(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    monkeypatch.setattr(db_module, "engine", engine)

    db_module.init_db()
    first_tables = set(inspect(engine).get_table_names())
    db_module.init_db()
    second_tables = set(inspect(engine).get_table_names())

    assert first_tables == second_tables
    assert {"alembic_version", "settings", "reward_goals", "daily_snapshots", "manual_overrides"} <= first_tables
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_ursule_baseline"
