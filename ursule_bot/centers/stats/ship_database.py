from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from ...core.config import config


EXPECTED_VALUES_URL = "https://api.wows-numbers.com/personal/rating/expected/json/"
REFRESH_AFTER = timedelta(days=7)


class ShipDatabaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpectedValues:
    damage: float
    frags: float
    win_rate: float


def database_path() -> Path:
    return config.data_dir / "ships" / "expected_pr.json"


def _parse(payload: dict) -> dict[int, ExpectedValues]:
    rows = payload.get("data")
    if not isinstance(rows, dict):
        raise ShipDatabaseError("船只期望值数据格式错误")
    parsed: dict[int, ExpectedValues] = {}
    for ship_id, row in rows.items():
        if not isinstance(row, dict):
            continue
        try:
            values = ExpectedValues(
                damage=float(row["average_damage_dealt"]),
                frags=float(row["average_frags"]),
                win_rate=float(row["win_rate"]),
            )
            numeric_id = int(ship_id)
        except (KeyError, TypeError, ValueError):
            continue
        if values.damage > 0 and values.frags > 0 and values.win_rate > 0:
            parsed[numeric_id] = values
    if len(parsed) < 100:
        raise ShipDatabaseError("船只期望值记录数量异常")
    return parsed


def _read_payload() -> dict | None:
    path = database_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _parse(payload)
        return payload
    except (OSError, ValueError, TypeError, ShipDatabaseError):
        return None


def _is_fresh(path: Path) -> bool:
    from datetime import datetime, timezone

    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return datetime.now(timezone.utc) - modified < REFRESH_AFTER


def _save_payload(payload: dict) -> None:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


async def get_expected_values(client: httpx.AsyncClient) -> dict[int, ExpectedValues]:
    path = database_path()
    cached = _read_payload()
    if cached is not None and _is_fresh(path):
        return _parse(cached)
    try:
        response = await client.get(EXPECTED_VALUES_URL)
        response.raise_for_status()
        payload = response.json()
        parsed = _parse(payload)
        _save_payload(payload)
        return parsed
    except Exception as exc:
        if cached is not None:
            return _parse(cached)
        raise ShipDatabaseError("无法下载船只 PR 期望值数据库") from exc
