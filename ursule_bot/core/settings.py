from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from .config import config
from .system_models import Setting


def _key() -> bytes:
    path = config.data_dir / "secret.key"
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_bytes().strip()


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    if not row:
        return default
    if row.secret and row.value:
        try:
            return Fernet(_key()).decrypt(row.value.encode()).decode()
        except Exception:
            return default
    return row.value


def set_setting(db: Session, key: str, value: str, secret: bool = False) -> None:
    row = db.get(Setting, key) or Setting(key=key)
    row.secret = secret
    row.value = Fernet(_key()).encrypt(value.encode()).decode() if secret and value else value
    db.add(row)


def has_setup(db: Session) -> bool:
    return bool(get_setting(db, "admin_password_hash"))
