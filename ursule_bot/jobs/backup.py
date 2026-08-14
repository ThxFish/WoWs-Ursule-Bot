from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core.config import config


BACKUP_VERSION = 1
REQUIRED_TABLES = {"settings", "reward_goals", "resource_forecasts", "reset_plans", "daily_snapshots"}


def _database_path() -> Path:
    return config.data_dir / "tracker.db"


def create_backup(kind: str = "manual", source_db: Path | None = None, backup_dir: Path | None = None) -> Path:
    source = source_db or _database_path()
    destination_dir = backup_dir or config.data_dir / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo(config.timezone))
    if kind == "auto":
        filename = f"tracker-auto-{now:%Y-%m-%d}.zip"
    else:
        filename = f"tracker-{kind}-{now:%Y%m%d-%H%M%S}.zip"
    destination = destination_dir / filename

    with tempfile.TemporaryDirectory(prefix="wows-tracker-backup-") as temp_dir:
        snapshot_db = Path(temp_dir) / "tracker.db"
        with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(snapshot_db)) as copy:
            live.backup(copy)
        manifest = {
            "format": "wows-marathon-tracker-backup",
            "version": BACKUP_VERSION,
            "created_at": now.isoformat(),
            "contains": ["tracker.db"],
            "excluded": ["auth/armory-storage.json"],
        }
        temp_zip = Path(temp_dir) / "backup.zip"
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_db, "tracker.db")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        shutil.copy2(temp_zip, destination)
    return destination


def prune_automatic_backups(backup_dir: Path | None = None, keep: int = 30) -> None:
    directory = backup_dir or config.data_dir / "backups"
    backups = sorted(directory.glob("tracker-auto-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep):]:
        old.unlink(missing_ok=True)


def restore_backup(archive_path: Path, target_db: Path | None = None, backup_dir: Path | None = None) -> Path:
    target = target_db or _database_path()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if names != {"tracker.db", "manifest.json"}:
            raise ValueError("备份结构不正确")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "wows-marathon-tracker-backup" or manifest.get("version") != BACKUP_VERSION:
            raise ValueError("备份版本不兼容")
        db_info = archive.getinfo("tracker.db")
        if db_info.file_size > 512 * 1024 * 1024:
            raise ValueError("备份数据库过大")
        with tempfile.TemporaryDirectory(prefix="wows-tracker-restore-") as temp_dir:
            imported_db = Path(temp_dir) / "tracker.db"
            with archive.open("tracker.db") as source, imported_db.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            with closing(sqlite3.connect(imported_db)) as imported:
                if imported.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("备份数据库完整性校验失败")
                tables = {row[0] for row in imported.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not REQUIRED_TABLES.issubset(tables):
                    raise ValueError("备份缺少必要数据表")
            safety_backup = create_backup("pre-import", target, backup_dir)
            with closing(sqlite3.connect(imported_db)) as source, closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
    return safety_backup


def list_backups(backup_dir: Path | None = None, limit: int = 30) -> list[Path]:
    directory = backup_dir or config.data_dir / "backups"
    return sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
