from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    host: str
    port: int
    public_base_url: str
    timezone: str
    sync_hour: int
    sync_minute: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = Path(os.getenv("TRACKER_DATA_DIR", "./data")).resolve()
        return cls(
            data_dir=data_dir,
            host=os.getenv("TRACKER_HOST", "127.0.0.1"),
            port=int(os.getenv("TRACKER_PORT", "8000")),
            public_base_url=os.getenv("TRACKER_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            timezone=os.getenv("TRACKER_TIMEZONE", "Asia/Shanghai"),
            sync_hour=int(os.getenv("TRACKER_SYNC_HOUR", "4")),
            sync_minute=int(os.getenv("TRACKER_SYNC_MINUTE", "0")),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "auth").mkdir(exist_ok=True)
        (self.data_dir / "backups").mkdir(exist_ok=True)


config = AppConfig.from_env()

