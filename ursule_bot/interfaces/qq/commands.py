from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select

from ...centers.planning.models import ResetPlan
from ...centers.planning.overview import get_activity_overview
from ...centers.planning.regrind import BRITISH_LIGHT_CRUISER_LINE, line_progress_xp
from ...centers.planning.sync_service import guarded_sync
from ...core.database import SessionLocal
from .types import BotReply


PREFIX = "/节日船团"
COMMANDS = {"进度", "资源", "爬线", "同步", "帮助"}
COMMAND_PATTERN = re.compile(r"^/节日船团(?:\s+([^\s]+))?\s*$")


def parse_command(content: str) -> str | None:
    if not isinstance(content, str) or len(content) > 256:
        return None
    normalized = content.strip()
    normalized = re.sub(r"^<@!?[^>]+>\s*", "", normalized)
    match = COMMAND_PATTERN.fullmatch(normalized)
    if not match:
        return "未知" if normalized.startswith(PREFIX) else None
    return match.group(1) or "帮助"


def help_text() -> str:
    return (
        "节日船团机器人命令\n"
        "/节日船团 进度 — 当日代币、总目标和缺口\n"
        "/节日船团 资源 — 煤炭、钢铁、研发点和蓝色加成卡\n"
        "/节日船团 爬线 — 当前舰船、完成轮数和下一目标日期\n"
        "/节日船团 同步 — 立即采集（仅授权好友私聊）\n"
        "/节日船团 帮助 — 显示本说明"
    )


def _progress_text() -> str:
    with SessionLocal() as db:
        ctx = get_activity_overview(db)
        latest = ctx.latest
        projection = ctx.projection
        return (
            "节日船团进度\n"
            f"数据日期：{latest.snapshot_date if latest else '尚无'}\n"
            f"当前代币：{latest.holiday_tokens if latest and latest.holiday_tokens is not None else '未知'}\n"
            f"奖励总目标：{projection['goal_tokens']}\n"
            f"兑换后预计：{projection['projected_tokens']}\n"
            f"当前缺口：{projection['gap_tokens']}\n"
            f"额外所需研发点：{projection['additional_research_points']}"
        )


def _resources_text() -> str:
    with SessionLocal() as db:
        ctx = get_activity_overview(db)
        latest = ctx.latest
        if not latest:
            return "尚无资源快照，请先执行同步。"
        boosters = ctx.boosters
        return (
            f"账号资源（{latest.snapshot_date}）\n"
            f"煤炭：{latest.coal if latest.coal is not None else '未知'}\n"
            f"钢铁：{latest.steel if latest.steel is not None else '未知'}\n"
            f"研发点：{latest.research_points if latest.research_points is not None else '未知'}\n"
            "蓝色加成卡：\n"
            f"银币 +160%：{boosters.get('rare_credits', '未知')}\n"
            f"战舰经验 +800%：{boosters.get('rare_ship_xp', '未知')}\n"
            f"指挥官经验 +800%：{boosters.get('rare_commander_xp', '未知')}\n"
            f"全局经验 +2400%：{boosters.get('rare_free_xp', '未知')}"
        )


def _line_text() -> str:
    with SessionLocal() as db:
        plan = db.scalar(select(ResetPlan).where(ResetPlan.active.is_(True)).order_by(ResetPlan.id.desc()).limit(1))
        if not plan:
            return "尚未生成重爬计划。"
        actual_ship = "等待首次重置" if plan.waiting_for_reset else BRITISH_LIGHT_CRUISER_LINE[plan.current_ship_index]["name"]
        actual_xp = line_progress_xp(plan.completed_cycles, plan.current_ship_index, plan.waiting_for_reset)
        baseline = json.loads(plan.baseline_json or "[]")
        next_target = None
        seen = set()
        for item in baseline:
            key = (item.get("cycle"), item.get("ship"))
            if key in seen:
                continue
            seen.add(key)
            if item.get("target_xp", 0) > actual_xp:
                next_target = item
                break
        return (
            "英国轻巡重爬\n"
            f"当前状态：{actual_ship}\n"
            f"已完成轮数：{plan.completed_cycles} / {plan.target_resets}\n"
            f"下一目标：{next_target.get('ship') if next_target else '计划已完成'}\n"
            f"目标日期：{next_target.get('date') if next_target else plan.deadline}"
        )


def _safe_error(value: object) -> str:
    text = str(value).replace("\n", " ")[:240]
    text = re.sub(r"(?i)(access_token|clientSecret|password|cookie)[=: ]+[^ &,;]+", r"\1=[已隐藏]", text)
    return text


async def _sync_text() -> str:
    with SessionLocal() as db:
        snapshot = await guarded_sync(db, capture_type="qq")
        statuses = json.loads(snapshot.source_status_json or "{}")
        succeeded = [name for name, status in statuses.items() if status.get("ok")]
        failed = [f"{name}: {_safe_error(status.get('error', '失败'))}" for name, status in statuses.items() if not status.get("ok")]
        lines = [f"同步完成：{snapshot.snapshot_date}", f"成功数据源：{', '.join(succeeded) if succeeded else '无'}"]
        if failed:
            lines.append("失败数据源：" + "；".join(failed))
        lines.append(_progress_text())
        return "\n".join(lines)


async def execute_command(command: str, allow_sync: bool) -> BotReply:
    if command == "帮助":
        return BotReply(help_text())
    if command == "进度":
        return BotReply(_progress_text())
    if command == "资源":
        return BotReply(_resources_text())
    if command == "爬线":
        return BotReply(_line_text())
    if command == "同步":
        if not allow_sync:
            return BotReply("为保护账户，群聊不允许执行同步；请使用已授权好友私聊机器人。")
        return BotReply(await _sync_text())
    return BotReply("命令格式不正确。\n" + help_text())
