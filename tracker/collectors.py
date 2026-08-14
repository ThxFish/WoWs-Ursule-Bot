from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright

from .config import config


class CollectionError(RuntimeError):
    pass


@dataclass
class ArmoryData:
    holiday_tokens: int | None = None
    credits: int | None = None
    gold: int | None = None
    coal: int | None = None
    steel: int | None = None
    research_points: int | None = None
    community_tokens: int | None = None
    free_xp: int | None = None
    elite_commander_xp: int | None = None
    boosters: dict[str, int] = field(default_factory=dict)


BALANCE_FIELDS = {
    "eventum_10": "holiday_tokens",
    "credits": "credits",
    "gold": "gold",
    "coal": "coal",
    "steel": "steel",
    "paragon_xp": "research_points",
    "recruitment_points": "community_tokens",
    "free_xp": "free_xp",
    "elite_xp": "elite_commander_xp",
}

RARE_BOOSTER_IDS = {
    "4281331632": "rare_credits",
    "4270845872": "rare_ship_xp",
    "4260360112": "rare_commander_xp",
    "4249874352": "rare_free_xp",
}


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def parse_armory_inventory(payload: Any) -> ArmoryData:
    data = ArmoryData()
    item_storage = payload.get("data", {}).get("items_storage", {}) if isinstance(payload, dict) else {}
    if isinstance(item_storage, dict):
        for item_id, booster_name in RARE_BOOSTER_IDS.items():
            data.boosters[booster_name] = int(item_storage.get(item_id, 0) or 0)
    aliases = {
        "coal": "coal",
        "steel": "steel",
        "researchpoints": "research_points",
        "research_points": "research_points",
        "paragon_xp": "research_points",
        "holidayconvoytoken": "holiday_tokens",
        "holiday_convoy_token": "holiday_tokens",
    }
    for node in _walk(payload):
        identifier = str(node.get("id", node.get("name", node.get("currency", node.get("type", ""))))).lower().replace(" ", "")
        amount = node.get("amount", node.get("count", node.get("value", node.get("quantity"))))
        if not isinstance(amount, (int, float)):
            continue
        for alias, field_name in aliases.items():
            if alias in identifier:
                setattr(data, field_name, int(amount))
        if "boost" in identifier or "economic" in identifier:
            data.boosters[identifier] = int(amount)
    return data


def parse_account_balance(payload: Any) -> ArmoryData:
    data = ArmoryData()
    rows = payload.get("balance", []) if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_name = BALANCE_FIELDS.get(str(row.get("currency", "")))
        value = row.get("value")
        if field_name and isinstance(value, (int, float)):
            setattr(data, field_name, int(value))
    return data


async def collect_armory(storage_state: Path | None = None, timeout_seconds: int = 45) -> ArmoryData:
    state = storage_state or config.data_dir / "auth" / "armory-storage.json"
    if not state.exists():
        raise CollectionError("尚未导入军械库登录状态")
    inventory_payloads: list[Any] = []
    account_payloads: list[Any] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(state), service_workers="block")
        page = await context.new_page()

        async def capture(response):
            try:
                if response.url.rstrip("/").endswith("/api/inventory"):
                    inventory_payloads.append(await response.json())
                elif response.url.rstrip("/").endswith("/zh-sg/api/account/info"):
                    account_payloads.append(await response.json())
            except Exception:
                pass

        page.on("response", capture)
        try:
            await page.goto("https://armory.worldofwarships.eu/zh-sg/", wait_until="networkidle", timeout=timeout_seconds * 1000)
            await page.wait_for_timeout(2500)
        finally:
            await browser.close()
    if not inventory_payloads:
        raise CollectionError("未捕获 inventory 响应，登录可能已失效或军械库结构已变化")
    if not account_payloads:
        raise CollectionError("未捕获 account/info 资源响应，登录可能已失效或军械库结构已变化")
    result = ArmoryData()
    for payload in inventory_payloads:
        parsed = parse_armory_inventory(payload)
        result.boosters.update(parsed.boosters)
    for payload in account_payloads:
        parsed = parse_account_balance(payload)
        for field_name in BALANCE_FIELDS.values():
            value = getattr(parsed, field_name)
            if value is not None:
                setattr(result, field_name, value)
    return result


async def collect_wargaming(application_id: str, account_id: str, access_token: str = "") -> dict:
    if not application_id or not account_id:
        raise CollectionError("Wargaming Application ID 或账号 ID 未配置")
    params = {"application_id": application_id, "account_id": account_id, "fields": "ship_id,last_battle_time,pvp.battles,pvp.xp"}
    if access_token:
        params["access_token"] = access_token
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get("https://api.worldofwarships.eu/wows/ships/stats/", params=params)
        response.raise_for_status()
        payload = response.json()
    if payload.get("status") != "ok":
        raise CollectionError(str(payload.get("error", "Wargaming API 返回错误")))
    rows = payload.get("data", {}).get(str(account_id)) or []
    return {
        "ships": [{"ship_id": row.get("ship_id"), "last_battle_time": row.get("last_battle_time")} for row in rows],
        "battles": sum(int((row.get("pvp") or {}).get("battles") or 0) for row in rows),
        "xp": sum(int((row.get("pvp") or {}).get("xp") or 0) for row in rows),
    }


async def collect_third_party(account_id: str) -> dict:
    if not account_id:
        raise CollectionError("账号 ID 未配置")
    headers = {"Yuyuko-Client-Type": "WOWS-MARATHON-TRACKER;0.1.0"}
    params = {"server": "eu", "accountId": account_id}
    url = "https://recent.wows.shinoaki.com:8890/public/wows/account/ship/info/list"
    async with httpx.AsyncClient(timeout=25, verify=True) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if int(payload.get("code", 0)) not in (0, 200):
        raise CollectionError(str(payload.get("message", "第三方 API 返回错误")))
    return payload.get("data") or {}


def third_party_totals(payload: dict) -> dict[str, int]:
    """Extract conservative totals from Yuyuko's public ship list response.

    Schema additions are ignored. We only use explicit battle/xp counters and never
    infer ownership from the mere presence of a historical ship-stat row.
    """
    battles = 0
    xp = 0
    for node in _walk(payload.get("shipInfo", [])):
        for key, value in node.items():
            normalized = str(key).lower().replace("_", "")
            if not isinstance(value, (int, float)):
                continue
            if normalized in {"battles", "battlecount"}:
                battles += int(value)
            elif normalized in {"xp", "totalxp"}:
                xp += int(value)
    return {"battles": battles, "xp": xp}
