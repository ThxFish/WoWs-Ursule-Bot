from __future__ import annotations

import re
from datetime import timezone
from zoneinfo import ZoneInfo

from ...centers.planning.overview import get_activity_overview
from ...core.config import config
from ...core.database import SessionLocal
from .types import BotReply


SIMPLE_ALIASES = {
    "/帮助": "帮助",
    "/help": "帮助",
    "/活动": "活动",
    "/event": "活动",
    "/新闻": "资讯",
    "/news": "资讯",
    "/我": "战绩",
    "/me": "战绩",
    "/日报": "日报",
    "/daily": "日报",
}
ARGUMENT_ALIASES = {
    "/绑定": "绑定",
    "/bind": "绑定",
    "/近期": "近期",
    "/recent": "近期",
    "/随机": "随机",
    "/random": "随机",
    "/排位": "排位",
    "/rank": "排位",
    "/单船": "单船",
    "/ship": "单船",
    "/类别": "类别",
    "/category": "类别",
}
USAGE = {
    "绑定": "/绑定 eu 游戏昵称 或 /bind eu 游戏昵称",
    "近期": "/近期 参数 或 /recent 参数",
    "随机": "/随机 参数 或 /random 参数",
    "排位": "/排位 参数 或 /rank 参数",
    "单船": "/单船 船名 或 /ship 船名",
    "类别": "/类别 参数 或 /category 参数",
}


def parse_command(content: str) -> str | None:
    if not isinstance(content, str) or len(content) > 256:
        return None
    normalized = content.strip()
    normalized = re.sub(r"^<@!?[^>]+>\s*", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    original_bind = re.fullmatch(r"/?wws\s+(?:bind|set|绑定)(?:\s+(.+))?", normalized, re.IGNORECASE)
    if original_bind:
        argument = original_bind.group(1)
        return f"绑定 {argument}" if argument else "绑定"
    lookup = normalized.lower()
    simple = SIMPLE_ALIASES.get(lookup) or SIMPLE_ALIASES.get(f"/{lookup}")
    if simple:
        return simple
    head, separator, argument = normalized.partition(" ")
    head_lookup = head.lower()
    parameterized = ARGUMENT_ALIASES.get(head_lookup) or ARGUMENT_ALIASES.get(f"/{head_lookup}")
    if parameterized:
        return f"{parameterized} {argument}" if separator and argument else parameterized
    return None


def help_text() -> str:
    return (
        "Ursule Bot 指令（/ 可省略）\n"
        "/帮助 /help — 显示本说明\n"
        "/活动 /event — 当前活动状态图\n"
        "/新闻 /news — 最近一周新闻图\n"
        "/我 /me — 个人战绩图\n"
        "/近期 /recent 参数 — 近期战绩\n"
        "/绑定 /bind eu 游戏昵称 — 绑定兼容战绩账号\n"
        "/随机 /random 参数 — 近期随机战绩\n"
        "/排位 /rank 参数 — 近期排位战绩\n"
        "/单船 /ship 船名 — 单船数据\n"
        "/类别 /category 参数 — 筛选舰船数据\n"
        "/日报 /daily — 生成日报图片"
    )


def build_kokomi_message(command: str, account_id: str) -> str:
    """Translate a short command to the arguments following the /wws prefix."""
    name, _, argument = command.partition(" ")
    if name == "绑定":
        if not argument:
            raise ValueError(USAGE["绑定"])
        return f"bind {argument}"
    if not argument:
        raise ValueError(USAGE.get(name, "指令缺少参数"))
    target = "me"
    if name == "近期":
        return f"{target} recent {argument}"
    if name == "随机":
        return f"{target} pvp recent {argument}"
    if name == "排位":
        return f"{target} rank recent {argument}"
    if name == "单船":
        return f"{target} ship {argument}"
    if name == "类别":
        return f"{target} ships {argument}"
    raise ValueError("不支持的战绩兼容指令")


async def _kokomi_reply(command: str) -> BotReply:
    from ...integrations.kokomi import execute_kokomi_message

    name, _, argument = command.partition(" ")
    if name in USAGE and not argument:
        return BotReply(f"缺少必要参数。\n用法：{USAGE[name]}")
    with SessionLocal() as db:
        from ...core.settings import get_setting

        account_id = get_setting(db, "account_id")
        api_url = get_setting(db, "kokomi_api_url")
        api_token = get_setting(db, "kokomi_api_token")
    if not account_id:
        return BotReply("请先在设置页配置欧服 Account ID。")
    message = build_kokomi_message(command, account_id)
    text, image = await execute_kokomi_message(
        message,
        user_id=account_id,
        channel_id=account_id,
        **({"api_url": api_url} if api_url else {}),
        **({"token": api_token} if api_token else {}),
    )
    return BotReply(text, image=image, image_alt="战舰世界战绩查询结果" if image else None)


def _metric_number(value: str, *, decimal: bool = False) -> float | int:
    cleaned = value.replace("%", "").replace(" ", "")
    if cleaned in {"", "-"}:
        return 0.0 if decimal else 0
    return float(cleaned) if decimal else int(round(float(cleaned)))


async def _daily_reply() -> BotReply:
    from ...centers.information.service import get_recent_news
    from ...centers.planning.activity_day import activity_date
    from ...centers.stats.service import get_daily_metric, get_personal_stats
    from ...integrations.news import NewsCollectionError
    from ...rendering.daily import DailyPerformance, DailyReport, render_daily_report
    from ...rendering.information import NewsItem

    with SessionLocal() as db:
        overview = get_activity_overview(db)
        stats = await get_personal_stats(db)
    try:
        articles = await get_recent_news()
    except NewsCollectionError:
        # News is supplementary: an upstream outage must not suppress the
        # activity and account sections of the daily report.
        articles = []
    latest = overview.latest
    projection = overview.projection
    plan = overview.plan
    milestone = overview.milestone or {}
    target = milestone.get("target") or {}
    checkpoint = milestone.get("checkpoint") or {}
    metric = get_daily_metric(stats.account_id)
    performance = DailyPerformance()
    if metric is not None:
        performance = DailyPerformance(
            battles=_metric_number(metric.battles_count),
            win_rate=_metric_number(metric.win_rate, decimal=True),
            personal_rating=_metric_number(metric.rating),
            average_damage=_metric_number(metric.avg_damage),
            average_frags=_metric_number(metric.avg_frags, decimal=True),
            average_xp=_metric_number(metric.avg_exp),
        )
    resources = {
        key: getattr(latest, key, None) if latest else None
        for key in ("holiday_tokens", "coal", "steel", "research_points", "free_xp", "credits")
    }
    resources["holiday_tokens"] = int(projection.get("current_tokens", resources["holiday_tokens"] or 0))
    goals = "、".join(f"{goal.name} × {goal.quantity}" for goal in overview.goals[:2]) or "尚未配置活动目标"
    news = tuple(
        NewsItem(
            title=article.title,
            source=article.source,
            published_at=article.published_at,
            description=article.description,
            tags=article.tags,
            tag_color=article.tag_color,
            url=article.url,
            thumbnail=article.thumbnail,
        )
        for article in articles[:2]
    )
    report = DailyReport(
        report_date=activity_date(),
        nickname=stats.nickname,
        account_id=stats.account_id,
        region=stats.region,
        snapshot_date=(
            (latest.collected_at.replace(tzinfo=timezone.utc) if latest.collected_at.tzinfo is None else latest.collected_at)
            .astimezone(ZoneInfo(config.timezone))
            .strftime("%Y-%m-%d %H:%M")
            if latest else "尚无快照"
        ),
        resources=resources,
        goal_name=goals,
        goal_amount=int(projection.get("goal_tokens", 0)),
        goal_gap=int(projection.get("gap_tokens", 0)),
        line_name=plan.line_name if plan else "尚未配置研发线",
        current_ship=str(milestone.get("actual_ship", "—")),
        next_checkpoint=str(checkpoint.get("ship", target.get("ship", "—"))),
        checkpoint_cycle=int(checkpoint.get("cycle", 0)),
        checkpoint_date=str(checkpoint.get("date", target.get("date", "待定"))),
        checkpoint_status=str(checkpoint.get("status", milestone.get("status", "未配置"))),
        line_xp=int(milestone.get("actual_xp_floor", 0)),
        checkpoint_xp=int(target.get("target_xp", 0)),
        performance=performance,
        news=news,
    )
    return BotReply(
        f"{stats.nickname} · {activity_date()} 日报",
        image=render_daily_report(report),
        image_alt="战舰世界活动、昨日战绩与新闻日报",
    )


async def execute_command(command: str) -> BotReply:
    command_name = command.partition(" ")[0]
    if command_name in {"绑定", "近期", "随机", "排位", "单船", "类别"}:
        return await _kokomi_reply(command)
    if command == "活动":
        from ...rendering.activity import render_activity_overview

        with SessionLocal() as db:
            overview = get_activity_overview(db)
        return BotReply(
            "当前活动状态",
            image=render_activity_overview(overview),
            image_alt="节日船团活动状态图",
        )
    if command == "战绩":
        from ...centers.stats.service import get_personal_stats
        from ...rendering.kokomi import render_personal_stats
        with SessionLocal() as db:
            stats = await get_personal_stats(db)
        return BotReply(
            f"{stats.nickname} 的个人战绩",
            image=render_personal_stats(stats),
            image_alt="Kokomi 风格个人战绩卡",
        )
    if command == "资讯":
        from ...centers.information.service import get_recent_news
        from ...rendering.information import NewsItem, render_information_report
        articles = await get_recent_news()
        items = [
            NewsItem(
                title=article.title,
                source=article.source,
                published_at=article.published_at,
                description=article.description,
                tags=article.tags,
                tag_color=article.tag_color,
                url=article.url,
                thumbnail=article.thumbnail,
            )
            for article in articles
        ]
        return BotReply(
            f"最近一周新闻 · {len(items)} 条",
            image=render_information_report(items),
            image_alt="战舰世界官网与开发者博客新闻列表",
        )
    if command == "帮助":
        return BotReply(help_text())
    if command == "日报":
        return await _daily_reply()
    return BotReply("命令格式不正确。\n" + help_text())
