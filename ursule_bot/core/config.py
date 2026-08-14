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
        def env(name: str, default: str) -> str:
            return os.getenv(f"URSULE_{name}", os.getenv(f"TRACKER_{name}", default))

        data_dir = Path(env("DATA_DIR", "./data")).resolve()
        return cls(
            data_dir=data_dir,
            host=env("HOST", "127.0.0.1"),
            port=int(env("PORT", "8000")),
            public_base_url=env("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            timezone=env("TIMEZONE", "Asia/Shanghai"),
            sync_hour=int(env("SYNC_HOUR", "4")),
            sync_minute=int(env("SYNC_MINUTE", "0")),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "auth").mkdir(exist_ok=True)
        (self.data_dir / "backups").mkdir(exist_ok=True)


config = AppConfig.from_env()
