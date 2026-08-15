from datetime import date
from io import BytesIO

from PIL import Image

from ursule_bot.rendering.activity import MILESTONE_BADGE_COLORS, RESOURCE_LABELS, ActivityReport, render_activity_report
from ursule_bot.rendering.daily import DailyPerformance, DailyRenderer, DailyReport, render_daily_report
from ursule_bot.rendering.information import NewsItem, render_information_report
from ursule_bot.rendering.kokomi import RATING_COLORS


def test_activity_report_renders_flat_png_template():
    report = ActivityReport(
        snapshot_date="2026-08-15",
        current_tokens=18_500,
        goal_tokens=42_000,
        projected_tokens=37_500,
        gap_tokens=4_500,
        resources={"credits": 82_000_000, "gold": 13_200, "coal": 485_000, "steel": 26_500, "research_points": 31_000, "free_xp": 1_450_000},
        used_resources={"coal": 150_000, "steel": 1_000},
        line_name="英国轻巡",
        current_ship="爱丁堡",
        completed_cycles=2,
        target_cycles=5,
        line_xp=1_220_000,
        line_total_xp=3_447_500,
        milestone_status="超前",
        daily_xp=24_800,
        goals=(("高级补给箱", 2, 12_000), ("纪念旗帜", 1, 4_500)),
    )
    payload = render_activity_report(report)
    with Image.open(BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 1640)


def test_activity_report_includes_available_account_balances():
    assert RESOURCE_LABELS["credits"] == "银币"
    assert RESOURCE_LABELS["gold"] == "金币 / 达布隆"
    assert RESOURCE_LABELS["free_xp"] == "全局经验"
    assert "elite_commander_xp" not in RESOURCE_LABELS


def test_activity_report_uses_semantic_line_status_colors():
    assert MILESTONE_BADGE_COLORS["落后"] == ("#FBE4E8", "#C43D4F")
    assert MILESTONE_BADGE_COLORS["超前"] == ("#E2F3EC", "#2C8A66")
    assert MILESTONE_BADGE_COLORS["领先"] == MILESTONE_BADGE_COLORS["超前"]


def test_activity_report_height_extends_to_show_every_reward_goal():
    report = ActivityReport(goals=tuple((f"奖励 {index}", 1, index * 1_000) for index in range(1, 6)))
    with Image.open(BytesIO(render_activity_report(report))) as image:
        assert image.size == (1600, 1804)
        # The fifth card is below the old fixed-height content area and must be rendered.
        assert image.getpixel((80, 1600)) == (255, 255, 255)


def test_activity_report_does_not_render_unavailable_line_xp_values():
    base = ActivityReport(line_name="英国轻巡", current_ship="爱丁堡", line_xp=1, line_total_xp=2, daily_xp=3)
    changed_xp = ActivityReport(
        line_name="英国轻巡",
        current_ship="爱丁堡",
        line_xp=999_999,
        line_total_xp=2_000_000,
        daily_xp=88_888,
    )
    assert render_activity_report(base) == render_activity_report(changed_xp)


def test_information_report_height_tracks_news_rows():
    items = [
        NewsItem("版本更新：全新舰船与活动内容", "官网", date(2026, 8, 15), "查看本次版本的主要变化。"),
        NewsItem("Waterline：开发团队答疑", "开发者博客", "2026-08-14"),
        NewsItem("服务器维护公告", "官网", date(2026, 8, 13)),
    ]
    payload = render_information_report(items)
    with Image.open(BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 1659)


def test_information_report_has_empty_state():
    with Image.open(BytesIO(render_information_report([]))) as image:
        assert image.size == (1600, 995)


def test_information_report_caps_board_at_two_by_four_cards():
    items = [NewsItem(f"新闻 {index}", "官网", date(2026, 8, 15)) for index in range(10)]
    with Image.open(BytesIO(render_information_report(items))) as image:
        assert image.size == (1600, 2987)


def test_daily_report_renders_three_section_template():
    report = DailyReport(
        report_date=date(2026, 8, 15),
        nickname="Ursule",
        account_id="500000001",
        resources={
            "holiday_tokens": 18_500,
            "coal": 485_000,
            "steel": 26_500,
            "research_points": 31_000,
            "free_xp": 1_450_000,
            "credits": 82_000_000,
        },
        goal_name="高级补给箱 × 2",
        goal_amount=42_000,
        goal_gap=23_500,
        line_name="英国轻巡",
        current_ship="爱丁堡",
        next_checkpoint="海王星",
        checkpoint_cycle=1,
        checkpoint_date="2026-08-18",
        checkpoint_status="领先",
        line_xp=110_000,
        checkpoint_xp=168_000,
        performance=DailyPerformance(12, 58.33, 1_742, 82_450, 1.08, 1_965),
        news=tuple(NewsItem(f"新闻 {index}", "官网", date(2026, 8, 15)) for index in range(4)),
    )
    with Image.open(BytesIO(render_daily_report(report))) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 2050)


def test_daily_report_ignores_reward_name_and_unavailable_line_xp_values():
    common = {
        "report_date": date(2026, 8, 15),
        "nickname": "Ursule",
        "account_id": "500000001",
        "resources": {"holiday_tokens": 18_500},
        "goal_amount": 42_000,
        "goal_gap": 23_500,
        "line_name": "英国轻巡",
        "current_ship": "爱丁堡",
        "next_checkpoint": "海王星",
        "checkpoint_date": "2026-08-18",
    }
    first = DailyReport(**common, goal_name="目标甲", line_xp=1, checkpoint_xp=2)
    second = DailyReport(**common, goal_name="目标乙", line_xp=999_999, checkpoint_xp=2_000_000)
    assert render_daily_report(first) == render_daily_report(second)


def test_daily_performance_uses_kokomi_rating_classes():
    palette = RATING_COLORS["light"]
    assert palette[DailyRenderer._metric_class(58.33, (0, 45, 47, 49, 52, 54, 56, 60, 65))] == (52, 186, 211)
    assert palette[DailyRenderer._pr_class(1_742)] == (49, 128, 0)
