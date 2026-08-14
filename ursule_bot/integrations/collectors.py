from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.async_api import async_playwright

from ..core.config import config


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
    for node in _walk(payload):
        if "items_storage" not in node:
            continue
        item_storage = node.get("items_storage")
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
    for node in _walk(payload):
        rows = node.get("balance", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            field_name = BALANCE_FIELDS.get(str(row.get("currency", "")))
            value = row.get("value")
            if field_name and isinstance(value, (int, float)):
                setattr(data, field_name, int(value))
    return data


ARMORY_RESOURCE_FIELDS = tuple(dict.fromkeys(BALANCE_FIELDS.values()))


def merge_armory_data(target: ArmoryData, source: ArmoryData) -> None:
    target.boosters.update(source.boosters)
    for field_name in ARMORY_RESOURCE_FIELDS:
        value = getattr(source, field_name)
        if value is not None:
            setattr(target, field_name, value)


def _payload_has_key(payload: Any, key: str) -> bool:
    return any(key in node for node in _walk(payload))


class ArmoryResponseCapture:
    """Collect Armory JSON by payload shape instead of unstable endpoint URLs."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []
        self.paths: set[str] = set()
        self.has_inventory = False
        self.has_balance = False

    async def handle(self, response) -> None:
        try:
            if response.request.resource_type not in {"xhr", "fetch"}:
                return
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                return
            payload = await response.json()
            path = urlsplit(response.url).path
            inventory = "inventory" in path.lower() or _payload_has_key(payload, "items_storage") or _payload_has_key(payload, "inventory")
            balance = "account" in path.lower() or _payload_has_key(payload, "balance")
            parsed_balance = parse_account_balance(payload)
            balance = balance or any(getattr(parsed_balance, field) is not None for field in ARMORY_RESOURCE_FIELDS)
            if inventory or balance:
                self.payloads.append(payload)
                self.paths.add(path)
                self.has_inventory = self.has_inventory or inventory
                self.has_balance = self.has_balance or balance
        except Exception:
            return

    def result(self) -> ArmoryData:
        result = ArmoryData()
        for payload in self.payloads:
            merge_armory_data(result, parse_armory_inventory(payload))
            merge_armory_data(result, parse_account_balance(payload))
        return result

    def ready(self) -> bool:
        result = self.result()
        has_resources = any(getattr(result, field) is not None for field in ARMORY_RESOURCE_FIELDS)
        return self.has_inventory and has_resources

    def diagnostic(self) -> str:
        paths = ", ".join(sorted(self.paths)) or "未发现军械库 JSON 接口"
        return f"inventory={'是' if self.has_inventory else '否'}，balance={'是' if self.has_balance else '否'}；接口：{paths}"


async def save_storage_state(context, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{id(context)}.tmp")
    await context.storage_state(path=str(temporary), indexed_db=True)
    os.replace(temporary, destination)


async def trigger_armory_wallet(page, allow_navigation_fallback: bool = False) -> bool:
    """Open the lazy-loaded wallet so the Armory emits inventory data."""
    selectors = (
        ".armory__auto--wallet_icon",
        '[data-menu-item="wallet"]',
        'a[href*="/wallet/"]',
    )
    try:
        for selector in selectors:
            candidates = page.locator(selector)
            for index in range(min(await candidates.count(), 5)):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    await candidate.click(timeout=3_000)
                    return True
        for label in ("钱包", "所有资源", "Wallet", "Resources"):
            candidates = page.get_by_text(label, exact=True)
            for index in range(min(await candidates.count(), 5)):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    await candidate.click(timeout=3_000)
                    return True
        if allow_navigation_fallback and "/wallet" not in page.url:
            await page.goto("https://armory.worldofwarships.eu/zh-sg/wallet/", wait_until="domcontentloaded", timeout=30_000)
            return True
    except Exception:
        return False
    return False


async def collect_armory(storage_state: Path | None = None, timeout_seconds: int = 45) -> ArmoryData:
    state = storage_state or config.data_dir / "auth" / "armory-storage.json"
    if not state.exists():
        raise CollectionError("尚未导入军械库登录状态")
    capture = ArmoryResponseCapture()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(state))
        page = await context.new_page()
        page.on("response", capture.handle)
        try:
            await page.goto("https://armory.worldofwarships.eu/zh-sg/", wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            wallet_triggered = False
            for _ in range(min(timeout_seconds, 20) * 2):
                if capture.ready():
                    break
                if not capture.has_inventory and not wallet_triggered:
                    wallet_triggered = await trigger_armory_wallet(page, allow_navigation_fallback=True)
                await page.wait_for_timeout(500)
            if capture.ready():
                await save_storage_state(context, state)
        finally:
            await browser.close()
    if not capture.ready():
        raise CollectionError(f"军械库未返回完整资源数据，登录可能失效或页面尚未加载完成。{capture.diagnostic()}")
    return capture.result()


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
        port_ships = None
        if access_token:
            private_response = await client.get(
                "https://api.worldofwarships.eu/wows/account/info/",
                params={
                    "application_id": application_id,
                    "account_id": account_id,
                    "access_token": access_token,
                    "extra": "private.port",
                    "fields": "private.port",
                },
            )
            private_response.raise_for_status()
            private_payload = private_response.json()
            private_row = (private_payload.get("data") or {}).get(str(account_id)) or {}
            private_data = private_row.get("private")
            if isinstance(private_data, dict) and isinstance(private_data.get("port"), list):
                port_ships = [int(ship_id) for ship_id in private_data["port"]]
    if payload.get("status") != "ok":
        raise CollectionError(str(payload.get("error", "Wargaming API 返回错误")))
    rows = payload.get("data", {}).get(str(account_id)) or []
    return {
        "ships": [{"ship_id": row.get("ship_id"), "last_battle_time": row.get("last_battle_time")} for row in rows],
        "battles": sum(int((row.get("pvp") or {}).get("battles") or 0) for row in rows),
        "xp": sum(int((row.get("pvp") or {}).get("xp") or 0) for row in rows),
        "port_ships": port_ships,
    }


async def collect_third_party(account_id: str) -> dict:
    if not account_id:
        raise CollectionError("账号 ID 未配置")
    headers = {"Yuyuko-Client-Type": "WOWS-URSULE-BOT;0.2.0"}
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
