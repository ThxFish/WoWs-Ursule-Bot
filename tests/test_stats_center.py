from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

from ursule_bot.centers.stats import service
from ursule_bot.centers.stats.service import BATTLE_TYPES, SHIP_TYPES, Metric, PeriodMetric, PersonalStats, _metric, _valid_dog_tag_url, get_daily_metric
from ursule_bot.centers.stats.ship_database import ExpectedValues, _parse
from ursule_bot.rendering.kokomi import render_personal_stats


def test_metric_uses_wows_numbers_published_example():
    result = _metric({
        "battles": 5,
        "wins": 4,
        "damage": 378_514,
        "frags": 6,
        "xp": 7_500,
        "pr_damage": 378_514,
        "pr_wins": 4,
        "pr_frags": 6,
        "expected_damage": 256_608.43921139,
        "expected_wins": 2.5279414667358,
        "expected_frags": 3.5517450247925,
    })
    assert result.battles_count == "5"
    assert result.win_rate == "80.00%"
    assert result.rating == "2 225"
    assert result.rating_class == 7


def test_ship_database_parses_expected_values():
    rows = {
        str(4_000_000_000 + index): {
            "average_damage_dealt": 50_000 + index,
            "average_frags": 0.75,
            "win_rate": 50.0,
        }
        for index in range(100)
    }
    result = _parse({"time": 1, "data": rows})
    assert result[4_000_000_000] == ExpectedValues(50_000, 0.75, 50.0)


def test_dog_tag_url_only_accepts_kokomi_asset_host():
    expected = "https://v3-api.wows.shinoaki.com/nahida-static/root/500000001.png"
    assert _valid_dog_tag_url(expected) == expected
    assert _valid_dog_tag_url("http://v3-api.wows.shinoaki.com/tag.png") is None
    assert _valid_dog_tag_url("https://example.com/tag.png") is None


def test_period_metrics_use_cumulative_snapshot_delta(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "history_path", lambda: tmp_path / "history.json")
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    baseline = {
        "battles": 100, "wins": 50, "damage": 5_000_000, "frags": 100, "xp": 100_000,
        "pr_damage": 5_000_000, "pr_wins": 50, "pr_frags": 100,
        "expected_damage": 5_000_000, "expected_wins": 50, "expected_frags": 100,
    }
    current = {
        "battles": 110, "wins": 56, "damage": 5_700_000, "frags": 112, "xp": 112_000,
        "pr_damage": 5_700_000, "pr_wins": 56, "pr_frags": 112,
        "expected_damage": 5_500_000, "expected_wins": 55, "expected_frags": 110,
    }

    service._period_metrics("500000001", baseline, started)
    periods = service._period_metrics("500000001", current, started + timedelta(days=7))

    assert periods["previous"].available is True
    assert periods["previous"].battles_delta == 10
    assert periods["week"].available is True
    assert periods["week"].battles_delta == 10
    assert periods["week"].win_rate_delta == pytest.approx(0.91)
    assert periods["week"].avg_damage_delta == 1_818
    assert periods["month"].available is False

    newer = current | {"battles": 112, "wins": 57, "damage": 5_820_000, "frags": 113, "xp": 114_500}
    newer_periods = service._period_metrics("500000001", newer, started + timedelta(days=7, hours=1))

    assert newer_periods["previous"].battles_delta == 2
    assert newer_periods["week"].battles_delta == 12


def test_daily_metric_uses_account_history_delta(monkeypatch):
    baseline = {
        "collected_at": "2026-08-14T10:00:00+00:00",
        "totals": {
            "battles": 100, "wins": 50, "damage": 5_000_000, "frags": 100, "xp": 100_000,
            "pr_damage": 5_000_000, "pr_wins": 50, "pr_frags": 100,
            "expected_damage": 5_000_000, "expected_wins": 50, "expected_frags": 100,
        },
    }
    latest = {
        "collected_at": "2026-08-15T10:30:00+00:00",
        "totals": {
            "battles": 110, "wins": 56, "damage": 5_700_000, "frags": 112, "xp": 112_000,
            "pr_damage": 5_700_000, "pr_wins": 56, "pr_frags": 112,
            "expected_damage": 5_500_000, "expected_wins": 55, "expected_frags": 110,
        },
    }
    monkeypatch.setattr(service, "_load_history", lambda account_id: (latest, [baseline, latest]))

    metric = get_daily_metric("500000001")

    assert metric is not None
    assert metric.battles_count == "10"
    assert metric.win_rate == "60.00%"
    assert metric.avg_damage == "70 000"


def test_kokomi_renderer_keeps_original_png_dimensions():
    metric = Metric("100", "55.00%", "65 000", "1.10", "1 500", "1 800", "300", 5, 5, 5, 6)
    stats = PersonalStats(
        account_id="500000001",
        nickname="Ursule",
        created_at=1_700_000_000,
        overall=metric,
        battle_type={name: metric for name in BATTLE_TYPES},
        ship_type={name: metric for name in SHIP_TYPES},
        chart_data={str(tier): tier * 10 for tier in range(1, 12)},
        periods={
            "previous": PeriodMetric("上次查询", True, 25, 150, 0.5, 1_000, 0.02, 80),
            "week": PeriodMetric("最近一周", True, 120, 90, 0.25, 650, 0.01, 45),
            "month": PeriodMetric("最近一月"),
            "half_year": PeriodMetric("最近半年", True, 1_200, -50, -1.0, -3_000, -0.03, -120),
        },
    )
    payload = render_personal_stats(stats)
    with Image.open(BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.size == (2428, 4050)
