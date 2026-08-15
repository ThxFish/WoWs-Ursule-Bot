from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .flat import FlatCanvas

if TYPE_CHECKING:
    from ..centers.planning.overview import ActivityOverview


RESOURCE_LABELS = {
    "credits": "银币",
    "gold": "金币 / 达布隆",
    "coal": "煤炭",
    "steel": "钢铁",
    "research_points": "研发点",
    "free_xp": "全局经验",
}

MILESTONE_BADGE_COLORS = {
    "落后": ("#FBE4E8", "#C43D4F"),
    "超前": ("#E2F3EC", "#2C8A66"),
    "领先": ("#E2F3EC", "#2C8A66"),
}
DEFAULT_MILESTONE_BADGE_COLORS = ("#E9EDF2", "#667584")


@dataclass(frozen=True)
class ActivityReport:
    snapshot_date: str = "尚无快照"
    current_tokens: int = 0
    goal_tokens: int = 0
    projected_tokens: int = 0
    gap_tokens: int = 0
    resources: dict[str, int | None] = field(default_factory=dict)
    used_resources: dict[str, int] = field(default_factory=dict)
    line_name: str = "尚未配置重爬计划"
    current_ship: str = "—"
    completed_cycles: int = 0
    target_cycles: int = 0
    line_xp: int = 0
    line_total_xp: int = 0
    milestone_status: str = "未配置"
    daily_xp: int = 0
    goals: tuple[tuple[str, int, int], ...] = ()

    @classmethod
    def from_overview(cls, overview: ActivityOverview) -> "ActivityReport":
        latest = overview.latest
        projection = overview.projection
        plan = overview.plan
        milestone = overview.milestone or {}
        resources = {key: getattr(latest, key, None) if latest else None for key in RESOURCE_LABELS}
        return cls(
            snapshot_date=str(latest.snapshot_date) if latest else "尚无快照",
            current_tokens=int(projection.get("current_tokens", 0)),
            goal_tokens=int(projection.get("goal_tokens", 0)),
            projected_tokens=int(projection.get("projected_tokens", 0)),
            gap_tokens=int(projection.get("gap_tokens", 0)),
            resources=resources,
            used_resources={key: int(value) for key, value in projection.get("used", {}).items()},
            line_name=plan.line_name if plan else "尚未配置重爬计划",
            current_ship=str(milestone.get("actual_ship", "—")),
            completed_cycles=plan.completed_cycles if plan else 0,
            target_cycles=plan.target_resets if plan else 0,
            line_xp=int(milestone.get("actual_xp_floor", 0)),
            line_total_xp=int(projection.get("line_total_xp", 0)),
            milestone_status=str(milestone.get("status", "未配置")),
            daily_xp=int(projection.get("line_daily_xp", 0)),
            goals=tuple((goal.name, goal.quantity, goal.token_cost) for goal in overview.goals),
        )


def _number(value: int | None) -> str:
    return "未知" if value is None else f"{value:,}"


def _badge(card: FlatCanvas, label: str, xy: tuple[int, int], *, fill: str, ink: str, size: int = 23) -> None:
    font = card.font(size)
    width = int(card.draw.textlength(label, font=font)) + 34
    x, y = xy
    card.draw.rectangle((x, y, x + width, y + size + 22), fill=fill)
    card.text(label, (x + 17, y + 8), size, fill=ink)


class ActivityRenderer:
    width = 1600
    base_height = 1640
    goal_row_height = 82
    goals_visible_at_base_height = 3

    def render(self, report: ActivityReport) -> bytes:
        extra_goal_rows = max(0, len(report.goals) - self.goals_visible_at_base_height)
        height = self.base_height + extra_goal_rows * self.goal_row_height
        card = FlatCanvas(self.width, height)
        self._header(card, report)
        self._token_summary(card, report)
        self._resources(card, report)
        self._line_progress(card, report)
        self._goals(card, report)
        card.footer("URSULE BOT  ·  活动追踪")
        return card.png()

    @staticmethod
    def _header(card: FlatCanvas, report: ActivityReport) -> None:
        card.text("ACTIVITY TRACKER", (70, 52), 22, fill=card.accent)
        card.text("活动追踪", (70, 88), 52)
        card.text("资源、兑换与研发线进度概览", (70, 154), 25, fill=card.ink_muted)
        _badge(card, f"数据 · {report.snapshot_date}", (1190, 72), fill=card.accent_soft, ink=card.accent)

    @staticmethod
    def _token_summary(card: FlatCanvas, report: ActivityReport) -> None:
        card.rounded((70, 210, 1530, 470), 0)
        card.text("活动代币", (110, 245), 25, fill=card.ink_muted)
        card.text(_number(report.current_tokens), (110, 288), 62)
        card.text(f"/ {_number(report.goal_tokens)}", (380, 324), 28, fill=card.ink_muted)
        ratio = report.current_tokens / report.goal_tokens if report.goal_tokens else 0
        card.progress((110, 392, 930, 420), ratio, radius=0)
        card.text(f"完成 {ratio:.0%}", (110, 454), 21, fill=card.ink_muted, anchor="ls")
        card.draw.line((1010, 245, 1010, 435), fill=card.divider, width=2)
        card.text("兑换后预计", (1060, 260), 23, fill=card.ink_muted)
        card.text(_number(report.projected_tokens), (1060, 302), 42)
        gap_color = card.warning if report.gap_tokens else card.success
        gap_label = f"仍缺 {_number(report.gap_tokens)}" if report.gap_tokens else "目标可达成"
        _badge(card, gap_label, (1060, 380), fill="#FCE9DF" if report.gap_tokens else "#E2F3EC", ink=gap_color)

    @staticmethod
    def _resources(card: FlatCanvas, report: ActivityReport) -> None:
        card.text("资源库存", (70, 530), 31)
        card.text("兑换计划会优先消耗煤炭、钢铁与研发点", (240, 534), 22, fill=card.ink_muted)
        for index, (key, label) in enumerate(RESOURCE_LABELS.items()):
            column, row = index % 3, index // 3
            x, y = 70 + column * 490, 580 + row * 118
            card.rounded((x, y, x + 480, y + 108), 0)
            card.text(label, (x + 24, y + 24), 21, fill=card.ink_muted)
            card.text(_number(report.resources.get(key)), (x + 24, y + 58), 32)
            used = report.used_resources.get(key, 0)
            if used:
                card.text(f"投入 {_number(used)}", (x + 452, y + 82), 18, fill=card.accent, anchor="rs")

    @staticmethod
    def _line_progress(card: FlatCanvas, report: ActivityReport) -> None:
        card.rounded((70, 880, 1530, 1135), 0)
        card.text("研发线进度", (110, 915), 28)
        badge_fill, badge_ink = MILESTONE_BADGE_COLORS.get(
            report.milestone_status,
            DEFAULT_MILESTONE_BADGE_COLORS,
        )
        _badge(card, report.milestone_status, (1320, 905), fill=badge_fill, ink=badge_ink, size=21)
        card.text(report.line_name, (110, 970), 23, fill=card.ink_muted)
        card.text(report.current_ship, (110, 1008), 38)
        card.text(f"{report.completed_cycles} / {report.target_cycles} 轮", (1450, 1020), 27, fill=card.ink_muted, anchor="rs")
        card.text("经验数据暂不可用，仅展示舰船与轮次信息", (110, 1087), 19, fill=card.ink_muted)

    @staticmethod
    def _goals(card: FlatCanvas, report: ActivityReport) -> None:
        card.text("奖励目标", (70, 1200), 31)
        goals = report.goals
        if not goals:
            card.rounded((70, 1250, 1530, 1430), 0)
            card.text("尚未配置奖励目标", (110, 1320), 27, fill=card.ink_muted)
            return
        y = 1250
        for name, quantity, cost in goals:
            card.rounded((70, y, 1530, y + 72), 0)
            card.text(name, (104, y + 36), 24, anchor="lm")
            card.text(f"× {quantity}", (1210, y + 36), 22, fill=card.ink_muted, anchor="rm")
            card.text(f"{_number(cost * quantity)} 代币", (1495, y + 36), 23, fill=card.accent, anchor="rm")
            y += 82


def render_activity_report(report: ActivityReport) -> bytes:
    return ActivityRenderer().render(report)


def render_activity_overview(overview: ActivityOverview) -> bytes:
    return render_activity_report(ActivityReport.from_overview(overview))
