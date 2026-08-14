from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import config
from .settings import get_setting

ph = PasswordHasher()


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return ph.verify(stored_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def _serializer() -> URLSafeTimedSerializer:
    key_path = config.data_dir / "session.key"
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return URLSafeTimedSerializer(key_path.read_text(encoding="utf-8").strip(), salt="tracker-session")


def new_session() -> tuple[str, str]:
    csrf = secrets.token_urlsafe(32)
    return _serializer().dumps({"authenticated": True, "csrf": csrf}), csrf


def read_session(cookie: str | None, max_age: int = 60 * 60 * 24 * 14) -> dict | None:
    if not cookie:
        return None
    try:
        value = _serializer().loads(cookie, max_age=max_age)
        return value if value.get("authenticated") else None
    except BadSignature:
        return None


def csrf_valid(session: dict | None, supplied: str | None) -> bool:
    return bool(session and supplied and hmac.compare_digest(session.get("csrf", ""), supplied))

