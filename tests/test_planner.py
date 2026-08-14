from datetime import date

from ursule_bot.centers.planning.line_state import update_line_state
from ursule_bot.centers.planning.regrind import LINE_XP_PER_RESET, build_regrind_baseline, reset_count
from ursule_bot.centers.planning.resources import exchange_tokens, recurring_occurrences, token_plan
from ursule_bot.centers.planning.timeline import ShipStep, build_baseline, milestone_status


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


def test_fixed_line_xp_and_even_daily_baseline():
    assert LINE_XP_PER_RESET == 689_500
    baseline = build_regrind_baseline(date(2027, 1, 29), date(2027, 2, 1), 2)
    assert len(baseline) == 4
    assert baseline[0]["daily_xp"] == 344_750
    assert baseline[-1]["target_xp"] == 1_379_000
    assert baseline[-1]["ship"] == "米诺陶可研发并重置"


def test_port_transitions_advance_ship_and_finish_cycle():
    leander, fiji, _, neptune, minotaur = [4183734224, 4182685648, 4181637072, 4180588496, 4179539920]
    reset = update_line_state([minotaur], [leander], 0, 4, True)
    assert reset["waiting_for_reset"] is False
    assert reset["current_ship_index"] == 0
    advanced = update_line_state([leander], [fiji], 0, 0, False)
    assert advanced["current_ship_index"] == 1
    complete = update_line_state([neptune], [leander], 0, 3, False)
    assert complete["completed_cycles"] == 1
    assert complete["waiting_for_reset"] is False
    assert complete["current_ship_index"] == 0


def test_missing_private_port_never_changes_progress():
    state = update_line_state([4183734224], None, 2, 1, False)
    assert state == {"completed_cycles": 2, "current_ship_index": 1, "waiting_for_reset": False, "event": ""}


def test_repeated_same_day_port_state_is_idempotent():
    leander = 4183734224
    state = update_line_state([leander], [leander], 1, 0, False)
    assert state["completed_cycles"] == 1
    assert state["current_ship_index"] == 0
