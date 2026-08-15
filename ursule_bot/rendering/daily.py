from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

from PIL import Image, ImageOps

from .flat import FlatCanvas
from .information import NewsItem
from .kokomi import RATING_COLORS, TEXT_COLORS


RESOURCE_LABELS = {
    "holiday_tokens": "活动代币",
    "coal": "煤炭",
    "steel": "钢铁",
    "research_points": "研发点",
    "free_xp": "全局经验",
    "credits": "银币",
}
WIN_RATE_THRESHOLDS = (0, 45, 47, 49, 52, 54, 56, 60, 65)
DAMAGE_THRESHOLDS = (0, 20_000, 30_000, 40_000, 50_000, 65_000, 80_000, 100_000, 130_000)
FRAGS_THRESHOLDS = (0, .35, .5, .65, .8, 1, 1.2, 1.5, 1.8)
PR_THRESHOLDS = (750, 1100, 1350, 1550, 1750, 2100, 2450)


@dataclass(frozen=True)
class DailyPerformance:
    battles: int = 0
    win_rate: float = 0.0
    personal_rating: int = 0
    average_damage: int = 0
    average_frags: float = 0.0
    average_xp: int = 0


@dataclass(frozen=True)
class DailyReport:
    report_date: date | str
    nickname: str
    account_id: str
    region: str = "EU"
    snapshot_date: date | str = "尚无快照"
    resources: dict[str, int | None] = field(default_factory=dict)
    goal_name: str = "尚未配置活动目标"
    goal_amount: int = 0
    goal_gap: int = 0
    line_name: str = "尚未配置研发线"
    current_ship: str = "—"
    next_checkpoint: str = "—"
    checkpoint_cycle: int = 0
    checkpoint_date: date | str = "待定"
    checkpoint_status: str = "未配置"
    line_xp: int = 0
    checkpoint_xp: int = 0
    performance: DailyPerformance = field(default_factory=DailyPerformance)
    news: tuple[NewsItem, ...] = ()


def _number(value: int | None) -> str:
    return "未知" if value is None else f"{value:,}"


def _date_text(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class DailyRenderer:
    """Compact daily digest combining planning, performance, and news."""

    width = 1600
    height = 2050
    margin = 70

    def render(self, report: DailyReport) -> bytes:
        card = FlatCanvas(self.width, self.height)
        self._header(card, report)
        self._activity(card, report)
        self._performance(card, report.performance)
        self._news(card, report.news[:2])
        card.footer("URSULE BOT  ·  每日简报")
        return card.png()

    @staticmethod
    def _header(card: FlatCanvas, report: DailyReport) -> None:
        card.text("DAILY BRIEF", (70, 48), 22, fill=card.accent)
        card.text("战舰世界日报", (70, 83), 52)
        card.text(
            f"{report.nickname}  ·  {report.region}  ·  ID {report.account_id}",
            (70, 151),
            24,
            fill=card.ink_muted,
        )
        label = _date_text(report.report_date)
        width = int(card.draw.textlength(label, font=card.font(25))) + 42
        card.draw.rectangle((1530 - width, 72, 1530, 123), fill=card.accent_soft)
        card.text(label, (1509, 97), 25, fill=card.accent, anchor="rm")

    def _activity(self, card: FlatCanvas, report: DailyReport) -> None:
        card.text("活动信息", (self.margin, 225), 34)
        card.text(f"资源快照 · {_date_text(report.snapshot_date)}", (1530, 232), 21, fill=card.ink_muted, anchor="ra")

        for index, key in enumerate(RESOURCE_LABELS):
            column = index % 3
            row = index // 3
            x = self.margin + column * 490
            y = 285 + row * 116
            card.rounded((x, y, x + 475, y + 102), 0)
            card.text(RESOURCE_LABELS[key], (x + 24, y + 22), 20, fill=card.ink_muted)
            card.text(_number(report.resources.get(key)), (x + 24, y + 56), 31)

        card.rounded((70, 535, 1530, 755), 0)
        card.draw.line((800, 565, 800, 725), fill=card.divider, width=2)
        card.text("当前活动代币", (110, 570), 22, fill=card.ink_muted)
        card.text(_number(report.resources.get("holiday_tokens")), (110, 615), 48)
        card.text(f"目标 {_number(report.goal_amount)}", (110, 685), 22, fill=card.accent)

        card.text("预计活动缺口", (850, 570), 22, fill=card.ink_muted)
        gap_color = card.warning if report.goal_gap > 0 else card.success
        gap_label = _number(report.goal_gap) if report.goal_gap > 0 else "目标已达成"
        card.text(gap_label, (850, 615), 48, fill=gap_color)
        card.text("兑换与每日收入计入后", (850, 685), 22, fill=card.accent)

        card.rounded((70, 780, 1530, 1025), 0)
        card.text("下一个爬线 CHECKPOINT", (110, 815), 22, fill=card.accent)
        card.text(report.line_name, (110, 858), 22, fill=card.ink_muted)
        checkpoint_label = (
            f"第{report.checkpoint_cycle}轮 · {report.next_checkpoint}"
            if report.checkpoint_cycle
            else report.next_checkpoint
        )
        card.text(checkpoint_label, (110, 918), 38)
        card.text(f"计划日期  {_date_text(report.checkpoint_date)}", (1450, 908), 23, fill=card.ink_muted, anchor="rs")
        badge_fill, badge_ink = {
            "领先": ("#E2F3EC", "#2C8A66"),
            "落后": ("#FBE4E8", "#C43D4F"),
        }.get(report.checkpoint_status, (card.surface_muted, card.ink_muted))
        card.pill(report.checkpoint_status, (1325, 942), fill=badge_fill, ink=badge_ink, size=21)

    def _performance(self, card: FlatCanvas, performance: DailyPerformance) -> None:
        card.text("昨日战绩", (self.margin, 1090), 34)
        neutral = TEXT_COLORS["light"][2]
        rating = RATING_COLORS["light"]
        metrics = (
            ("场次", _number(performance.battles), neutral),
            ("胜率", f"{performance.win_rate:.2f}%", rating[self._metric_class(performance.win_rate, WIN_RATE_THRESHOLDS)]),
            ("个人评级 PR", _number(performance.personal_rating), rating[self._pr_class(performance.personal_rating)]),
            ("场均伤害", _number(performance.average_damage), rating[self._metric_class(performance.average_damage, DAMAGE_THRESHOLDS)]),
            ("场均击沉", f"{performance.average_frags:.2f}", rating[self._metric_class(performance.average_frags, FRAGS_THRESHOLDS)]),
            ("场均经验", _number(performance.average_xp), neutral),
        )
        for index, (label, value, color) in enumerate(metrics):
            column = index % 3
            row = index // 3
            x = self.margin + column * 490
            y = 1145 + row * 126
            card.rounded((x, y, x + 475, y + 112), 0)
            card.text(label, (x + 24, y + 23), 20, fill=card.ink_muted)
            card.text(value, (x + 24, y + 60), 34, fill=color)

    @staticmethod
    def _metric_class(value: float, thresholds: tuple[float, ...]) -> int:
        return min(8, sum(value >= threshold for threshold in thresholds) - 1) if value else 0

    @staticmethod
    def _pr_class(value: int) -> int:
        return min(8, 1 + sum(value >= threshold for threshold in PR_THRESHOLDS)) if value else 0

    def _news(self, card: FlatCanvas, items: tuple[NewsItem, ...]) -> None:
        card.text("最近新闻", (self.margin, 1455), 34)
        card.text("最近 2 条", (1530, 1462), 21, fill=card.ink_muted, anchor="ra")
        if not items:
            card.rounded((70, 1515, 1530, 1875), 0)
            card.text("暂无新闻", (800, 1690), 30, fill=card.ink_muted, anchor="mm")
            return
        for index, item in enumerate(items):
            y = 1515 + index * 184
            card.rounded((70, y, 1530, y + 166), 0)
            self._thumbnail(card, item, (70, y, 340, y + 166))
            card.text(item.source or "新闻", (375, y + 25), 20, fill=card.accent)
            card.text(_date_text(item.published_at), (1495, y + 25), 19, fill=card.ink_muted, anchor="ra")
            text_y = y + 60
            for line in card.wrapped_lines(item.title, 1085, 29, 2):
                card.text(line, (375, text_y), 29)
                text_y += 39

    @staticmethod
    def _thumbnail(card: FlatCanvas, item: NewsItem, box: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = box
        if item.thumbnail:
            try:
                with Image.open(BytesIO(item.thumbnail)) as source:
                    fitted = ImageOps.fit(source.convert("RGB"), (x2 - x1, y2 - y1))
                    card.image.paste(fitted, (x1, y1))
                return
            except (OSError, ValueError):
                pass
        card.draw.rectangle(box, fill="#304A5A")
        initial = (item.source.strip() or "讯")[0]
        card.text(initial, ((x1 + x2) // 2, (y1 + y2) // 2), 52, fill="#A9EDF1", anchor="mm")


def render_daily_report(report: DailyReport) -> bytes:
    return DailyRenderer().render(report)
