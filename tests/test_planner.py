from datetime import date

from tracker.planner import ShipStep, build_baseline, exchange_tokens, milestone_status, recurring_occurrences, reset_count, token_plan


def test_exchange_blocks_and_coal_cap():
    assert exchange_tokens("coal", 4_999) == 0
    assert exchange_tokens("coal", 5_001) == 1_500
    assert exchange_tokens("coal", 999_999) == 195_000
    assert exchange_tokens("steel", 1_499) == 3_000
    assert exchange_tokens("research_points", 2_999) == 3_000


def test_token_plan_and_reset_count():
    result = token_plan(140_000, 20_000, {"coal": 100_000, "steel": 1_000, "research_points": 10_000})
    assert result["projected_tokens"] == 68_000
    assert result["gap_tokens"] == 72_000
    assert result["additional_research_points"] == 48_000
    assert reset_count(48_000, multiplier=1) == 5
    assert reset_count(48_000, multiplier=2) == 3


def test_resource_allocation_uses_blocks_and_stops_after_goal():
    result = token_plan(10_000, 1_000, {"coal": 100_000, "steel": 5_000, "research_points": 10_000})
    assert result["used"] == {"coal": 30_000, "steel": 0, "research_points": 0}
    assert result["converted"] == {"coal": 9_000, "steel": 0, "research_points": 0}
    assert result["gap_tokens"] == 0
    assert result["additional_research_points"] == 0


def test_baseline_is_stable_and_reaches_last_ship():
    ships = [ShipStep("V", 20_000), ShipStep("VI", 40_000), ShipStep("VII", 80_000)]
    baseline = build_baseline(date(2026, 8, 14), date(2026, 8, 18), ships)
    assert len(baseline) == 5
    assert baseline[0]["ship"] == "V"
    assert baseline[-1]["ship"] == "VII"
    assert baseline[-1]["target_xp"] == 140_000
    assert milestone_status(baseline, date(2026, 8, 16), 0)["status"] == "落后"


def test_recurring_resource_occurrences():
    deadline = date(2027, 2, 1)
    assert recurring_occurrences(date(2027, 1, 30), deadline, "daily") == 3
    assert recurring_occurrences(date(2027, 1, 1), deadline, "weekly") == 5
    assert recurring_occurrences(date(2026, 11, 30), deadline, "monthly") == 3
    assert recurring_occurrences(date(2027, 2, 2), deadline, "daily") == 0
