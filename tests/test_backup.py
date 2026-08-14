import json
import sqlite3
import zipfile
from contextlib import closing

import pytest

from ursule_bot.jobs.backup import create_backup, restore_backup


SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE reward_goals (id INTEGER PRIMARY KEY);
CREATE TABLE resource_forecasts (id INTEGER PRIMARY KEY);
CREATE TABLE reset_plans (id INTEGER PRIMARY KEY);
CREATE TABLE daily_snapshots (id INTEGER PRIMARY KEY);
"""


def make_database(path, value):
    with closing(sqlite3.connect(path)) as database:
        database.executescript(SCHEMA)
        database.execute("INSERT INTO settings VALUES ('marker', ?)", (value,))
        database.commit()


def test_backup_round_trip_and_manifest(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    backups = tmp_path / "backups"
    make_database(source, "from-backup")
    make_database(target, "before-import")

    archive = create_backup("manual", source, backups)
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {"tracker.db", "manifest.json"}
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["excluded"] == ["auth/armory-storage.json"]

    safety = restore_backup(archive, target, backups)
    assert safety.exists()
    with closing(sqlite3.connect(target)) as database:
        assert database.execute("SELECT value FROM settings WHERE key='marker'").fetchone()[0] == "from-backup"


def test_restore_rejects_unknown_zip_layout(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("unexpected.txt", "no")
    with pytest.raises(ValueError, match="结构"):
        restore_backup(archive, tmp_path / "target.db", tmp_path / "backups")
