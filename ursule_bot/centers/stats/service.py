from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from ...core.config import config
from ...core.settings import get_setting
from .models import Metric, PeriodMetric, PersonalStats, StatsCenterOverview, StatsCollectionError
from .ship_database import ExpectedValues, get_expected_values


SHIP_TYPES = ("AirCarrier", "Battleship", "Cruiser", "Destroyer", "Submarine")
BATTLE_TYPES = ("pvp_solo", "pvp_div2", "pvp_div3", "rank_solo")
RATING_THRESHOLDS = (750, 1100, 1350, 1550, 1750, 2100, 2450)
RATING_NEXT = (*RATING_THRESHOLDS, 3000)
CACHE_FILE = "personal_stats.json"
HISTORY_FILE = "personal_stats_history.json"
PROFILE_API_URL = "https://v3-api.wows.shinoaki.com/public/wows/account/info/eu/user"
PROFILE_IMAGE_HOSTS = {"v3-api.wows.shinoaki.com"}
PROFILE_CLIENT_TYPE = "URSULE;0.2.0"
MAX_DOG_TAG_BYTES = 2 * 1024 * 1024
PERIODS = (("previous", "上次查询", None), ("week", "最近一周", 7), ("month", "最近一月", 30), ("half_year", "最近半年", 180))


def get_overview() -> StatsCenterOverview:
    return StatsCenterOverview()


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _number(node: dict, *names: str) -> float:
    for name in names:
        value = node.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _class(value: float, thresholds: tuple[float, ...]) -> int:
    return min(8, sum(value >= threshold for threshold in thresholds) - 1) if value else 0


def _rating_class(value: int) -> int:
    return min(8, 1 + sum(value >= threshold for threshold in RATING_THRESHOLDS))


def _format_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _empty_accumulator() -> dict[str, float]:
    return {
        "battles": 0,
        "wins": 0,
        "damage": 0,
        "frags": 0,
        "xp": 0,
        "pr_damage": 0,
        "pr_wins": 0,
        "pr_frags": 0,
        "expected_damage": 0,
        "expected_wins": 0,
        "expected_frags": 0,
    }


def _add(target: dict[str, float], source: dict, expected: ExpectedValues | None) -> None:
    battles = _number(source, "battles")
    wins = _number(source, "wins")
    damage = _number(source, "damage_dealt", "damage")
    frags = _number(source, "frags")
    target["battles"] += battles
    target["wins"] += wins
    target["damage"] += damage
    target["frags"] += frags
    target["xp"] += _number(source, "xp")
    if expected is not None and battles > 0:
        target["pr_damage"] += damage
        target["pr_wins"] += wins
        target["pr_frags"] += frags
        target["expected_damage"] += battles * expected.damage
        target["expected_wins"] += battles * expected.win_rate / 100
        target["expected_frags"] += battles * expected.frags


def _metric(data: dict[str, float]) -> Metric:
    battles = data["battles"]
    if battles <= 0:
        return Metric()
    win_rate = data["wins"] / battles * 100
    avg_damage = data["damage"] / battles
    avg_frags = data["frags"] / battles
    avg_xp = data["xp"] / battles
    if min(data["expected_damage"], data["expected_wins"], data["expected_frags"]) <= 0:
        return Metric(
            battles_count=_format_int(battles),
            win_rate=f"{win_rate:.2f}%",
            avg_damage=_format_int(avg_damage),
            avg_frags=f"{avg_frags:.2f}",
            avg_exp=_format_int(avg_xp),
            win_rate_class=_class(win_rate, (0, 45, 47, 49, 52, 54, 56, 60, 65)),
            avg_damage_class=_class(avg_damage, (0, 20_000, 30_000, 40_000, 50_000, 65_000, 80_000, 100_000, 130_000)),
            avg_frags_class=_class(avg_frags, (0, .35, .5, .65, .8, 1, 1.2, 1.5, 1.8)),
        )
    r_damage = data["pr_damage"] / data["expected_damage"]
    r_wins = data["pr_wins"] / data["expected_wins"]
    r_frags = data["pr_frags"] / data["expected_frags"]
    n_damage = max(0, (r_damage - 0.4) / 0.6)
    n_wins = max(0, (r_wins - 0.7) / 0.3)
    n_frags = max(0, (r_frags - 0.1) / 0.9)
    rating = int(round(700 * n_damage + 300 * n_frags + 150 * n_wins))
    rating_class = _rating_class(rating)
    next_threshold = RATING_NEXT[rating_class - 1]
    return Metric(
        battles_count=_format_int(battles),
        win_rate=f"{win_rate:.2f}%",
        avg_damage=_format_int(avg_damage),
        avg_frags=f"{avg_frags:.2f}",
        avg_exp=_format_int(avg_xp),
        rating=_format_int(rating),
        rating_next=_format_int(abs(next_threshold - rating)),
        win_rate_class=_class(win_rate, (0, 45, 47, 49, 52, 54, 56, 60, 65)),
        avg_damage_class=_class(avg_damage, (0, 20_000, 30_000, 40_000, 50_000, 65_000, 80_000, 100_000, 130_000)),
        avg_frags_class=_class(avg_frags, (0, .35, .5, .65, .8, 1, 1.2, 1.5, 1.8)),
        rating_class=rating_class,
    )


def history_path() -> Path:
    return config.data_dir / HISTORY_FILE


def _metric_number(value: str) -> float | None:
    if value == "-":
        return None
    try:
        return float(value.replace("%", "").replace(" ", ""))
    except ValueError:
        return None


def _load_history(account_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = history_path()
    if not path.exists():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("account_id") == account_id:
            latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else None
            daily = payload.get("daily") if isinstance(payload.get("daily"), list) else []
            return latest, [row for row in daily if isinstance(row, dict) and isinstance(row.get("totals"), dict)]
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict) and row.get("account_id") == account_id and isinstance(row.get("totals"), dict)]
            return (rows[-1] if rows else None), rows
    except (OSError, ValueError, TypeError):
        pass
    return None, []


def get_daily_metric(account_id: str, days: int = 1) -> Metric | None:
    """Build a period metric by subtracting cumulative account snapshots."""
    latest, history = _load_history(account_id)
    if latest is None or not history or days < 1:
        return None
    try:
        current_at = datetime.fromisoformat(str(latest["collected_at"]))
        if current_at.tzinfo is None:
            current_at = current_at.replace(tzinfo=timezone.utc)
        cutoff = current_at - timedelta(days=days)
        baseline = None
        for row in history:
            stamp = datetime.fromisoformat(str(row["collected_at"]))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp <= cutoff:
                baseline = row
            else:
                break
        if baseline is None:
            return None
        current_totals = latest["totals"]
        baseline_totals = baseline["totals"]
        delta = {
            key: max(0.0, float(value) - float(baseline_totals.get(key, 0)))
            for key, value in current_totals.items()
        }
        return _metric(delta) if delta.get("battles", 0) > 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def _period_metrics(account_id: str, totals: dict[str, float], now: datetime) -> dict[str, PeriodMetric]:
    previous, history = _load_history(account_id)
    current = {key: float(value) for key, value in totals.items()}
    current_row = {"account_id": account_id, "collected_at": now.isoformat(), "totals": current}
    history.append(current_row)
    history.sort(key=lambda row: row.get("collected_at", ""))

    # One latest point per UTC day is sufficient for period deltas and keeps
    # the local history bounded even when the image is refreshed repeatedly.
    daily: dict[str, dict[str, Any]] = {}
    for row in history:
        try:
            stamp = datetime.fromisoformat(str(row["collected_at"]))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError):
            continue
        if stamp >= now - timedelta(days=370):
            daily[stamp.astimezone(timezone.utc).date().isoformat()] = row
    history = sorted(daily.values(), key=lambda row: row["collected_at"])
    target = history_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"account_id": account_id, "latest": current_row, "daily": history}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)

    overall = _metric(current)
    result: dict[str, PeriodMetric] = {}
    for key, label, days in PERIODS:
        baseline = previous if days is None else None
        if days is not None:
            cutoff = now - timedelta(days=days)
            for row in history:
                stamp = datetime.fromisoformat(row["collected_at"])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp <= cutoff:
                    baseline = row
                else:
                    break
        period = PeriodMetric(label=label)
        if baseline is None:
            result[key] = period
            continue
        baseline_totals = baseline["totals"]
        if current.get("battles", 0) < float(baseline_totals.get("battles", 0)):
            result[key] = period
            continue
        baseline_metric = _metric({name: float(baseline_totals.get(name, 0)) for name in current})

        def difference(current_value: str, baseline_value: str) -> float:
            left, right = _metric_number(current_value), _metric_number(baseline_value)
            return (left - right) if left is not None and right is not None else 0

        result[key] = PeriodMetric(
            label=label,
            available=True,
            battles_delta=round(current["battles"] - float(baseline_totals.get("battles", 0))),
            rating_delta=round(difference(overall.rating, baseline_metric.rating)),
            win_rate_delta=difference(overall.win_rate, baseline_metric.win_rate),
            avg_damage_delta=round(difference(overall.avg_damage, baseline_metric.avg_damage)),
            avg_frags_delta=difference(overall.avg_frags, baseline_metric.avg_frags),
            avg_exp_delta=round(difference(overall.avg_exp, baseline_metric.avg_exp)),
        )
    return result


async def _wg_get(client: httpx.AsyncClient, path: str, application_id: str, **params) -> dict:
    response = await client.get(f"https://api.worldofwarships.eu{path}", params={"application_id": application_id, **params})
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "ok":
        raise StatsCollectionError(str(payload.get("error", "Wargaming API 返回错误")))
    return payload.get("data") or {}


async def _ship_catalog(client: httpx.AsyncClient, application_id: str, ship_ids: list[int]) -> dict[int, dict]:
    catalog: dict[int, dict] = {}
    for offset in range(0, len(ship_ids), 100):
        chunk = ship_ids[offset:offset + 100]
        data = await _wg_get(client, "/wows/encyclopedia/ships/", application_id, ship_id=",".join(map(str, chunk)), fields="ship_id,type,tier")
        for key, value in data.items():
            if isinstance(value, dict):
                catalog[int(key)] = value
    return catalog


def dog_tag_path(account_id: str) -> Path:
    return config.data_dir / "dog_tags" / f"{account_id}.png"


def _valid_dog_tag_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in PROFILE_IMAGE_HOSTS:
        return None
    return value


async def _profile_metadata(client: httpx.AsyncClient, account_id: str) -> dict[str, Any]:
    """Fetch the dog tag and clan metadata used by the original Kokomi card."""
    response = await client.get(
        PROFILE_API_URL,
        params={"accountId": account_id},
        headers={"Yuyuko-Client-Type": PROFILE_CLIENT_TYPE},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        return {}
    return payload["data"]


async def _cache_dog_tag(client: httpx.AsyncClient, account_id: str, url: object) -> str | None:
    validated_url = _valid_dog_tag_url(url)
    if not validated_url:
        return None
    response = await client.get(validated_url)
    response.raise_for_status()
    content = response.content
    if not content or len(content) > MAX_DOG_TAG_BYTES or not response.headers.get("content-type", "").lower().startswith("image/png"):
        return None
    target = dog_tag_path(account_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(content)
    temporary.replace(target)
    return validated_url


async def collect_personal_stats(db: Session) -> PersonalStats:
    account_id = get_setting(db, "account_id")
    application_id = get_setting(db, "wg_application_id")
    if not account_id or not application_id:
        raise StatsCollectionError("请先在设置页配置欧服 Account ID 和 Wargaming Application ID。")
    fields = ",".join(["ship_id", *[f"{mode}.{name}" for mode in ("pvp", *BATTLE_TYPES) for name in ("battles", "wins", "damage_dealt", "frags", "xp")]])
    async with httpx.AsyncClient(timeout=30) as client:
        account_data = await _wg_get(client, "/wows/account/info/", application_id, account_id=account_id, fields="account_id,nickname,created_at")
        account = account_data.get(str(account_id)) or {}
        ship_data = await _wg_get(
            client,
            "/wows/ships/stats/",
            application_id,
            account_id=account_id,
            extra=",".join(BATTLE_TYPES),
            fields=fields,
        )
        rows = ship_data.get(str(account_id)) or []
        catalog = await _ship_catalog(client, application_id, [int(row["ship_id"]) for row in rows if row.get("ship_id")])
        expected_values = await get_expected_values(client)
        clan_tag = None
        clan_name = None
        clan_league = 5
        dog_tag_url = None
        try:
            membership_data = await _wg_get(client, "/wows/clans/accountinfo/", application_id, account_id=account_id, fields="clan_id")
            clan_id = (membership_data.get(str(account_id)) or {}).get("clan_id")
            if clan_id:
                clan_data = await _wg_get(client, "/wows/clans/info/", application_id, clan_id=clan_id, fields="tag,name")
                clan = clan_data.get(str(clan_id)) or {}
                clan_tag = clan.get("tag")
                clan_name = clan.get("name")
        except Exception:
            pass
        try:
            profile = await _profile_metadata(client, str(account_id))
            clan = profile.get("clanInfo") if isinstance(profile.get("clanInfo"), dict) else {}
            clan_tag = clan.get("tag") or clan_tag
            clan_name = clan.get("name") or clan_name
            dog_tag_url = await _cache_dog_tag(client, str(account_id), profile.get("dogTag"))
        except (httpx.HTTPError, ValueError, TypeError, OSError):
            # Official statistics and clan data remain usable if the optional
            # Kokomi-compatible metadata service is temporarily unavailable.
            pass

    overall = _empty_accumulator()
    by_battle = {name: _empty_accumulator() for name in BATTLE_TYPES}
    by_ship = {name: _empty_accumulator() for name in SHIP_TYPES}
    chart = {str(tier): 0 for tier in range(1, 12)}
    for row in rows:
        meta = catalog.get(int(row.get("ship_id") or 0), {})
        ship_type = meta.get("type") if meta.get("type") in SHIP_TYPES else "Cruiser"
        expected = expected_values.get(int(row.get("ship_id") or 0))
        _add(overall, row.get("pvp") or {}, expected)
        _add(by_ship[ship_type], row.get("pvp") or {}, expected)
        tier = int(meta.get("tier") or 0)
        if 1 <= tier <= 11:
            chart[str(tier)] += int(_number(row.get("pvp") or {}, "battles"))
        for name in BATTLE_TYPES:
            _add(by_battle[name], row.get(name) or {}, expected)
    collected_at = datetime.now(timezone.utc)
    stats = PersonalStats(
        account_id=str(account_id),
        nickname=str(account.get("nickname") or account_id),
        created_at=int(account.get("created_at") or 0),
        clan_tag=clan_tag,
        clan_name=clan_name,
        clan_league=clan_league,
        dog_tag_url=dog_tag_url,
        overall=_metric(overall),
        battle_type={name: _metric(value) for name, value in by_battle.items()},
        ship_type={name: _metric(value) for name, value in by_ship.items()},
        chart_data=chart,
        periods=_period_metrics(str(account_id), overall, collected_at),
        collected_at=collected_at.isoformat(),
    )
    save_cached_stats(stats)
    return stats


def cache_path() -> Path:
    return config.data_dir / CACHE_FILE


def save_cached_stats(stats: PersonalStats) -> None:
    target = cache_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(stats), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_cached_stats() -> PersonalStats | None:
    path = cache_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["overall"] = Metric(**raw["overall"])
        raw["battle_type"] = {key: Metric(**value) for key, value in raw["battle_type"].items()}
        raw["ship_type"] = {key: Metric(**value) for key, value in raw["ship_type"].items()}
        raw["periods"] = {
            key: (
                PeriodMetric(label=str(value.get("label", key)))
                if "battles_count" in value
                else PeriodMetric(**value)
            )
            for key, value in raw.get("periods", {}).items()
            if isinstance(value, dict)
        }
        return PersonalStats(**raw)
    except (OSError, ValueError, TypeError, KeyError):
        return None


async def get_personal_stats(db: Session, refresh: bool = True) -> PersonalStats:
    if refresh:
        try:
            return await collect_personal_stats(db)
        except Exception:
            cached = load_cached_stats()
            if cached:
                return cached
            raise
    cached = load_cached_stats()
    return cached or await collect_personal_stats(db)
