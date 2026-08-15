"""Data contracts shared by the statistics service and renderers."""

from __future__ import annotations

from dataclasses import dataclass, field


class StatsCollectionError(RuntimeError):
    """Raised when the configured account statistics cannot be collected."""


@dataclass(frozen=True)
class StatsCenterOverview:
    title: str = "战绩中心"
    description: str = "单账号战绩总览；沿用 Kokomi Bot 的原始 PNG 尺寸与渲染样式。"
    available: bool = True


@dataclass
class Metric:
    battles_count: str = "0"
    win_rate: str = "-"
    avg_damage: str = "-"
    avg_frags: str = "-"
    avg_exp: str = "-"
    rating: str = "-"
    rating_next: str = "-"
    win_rate_class: int = 0
    avg_damage_class: int = 0
    avg_frags_class: int = 0
    rating_class: int = 0


@dataclass
class PeriodMetric:
    label: str
    available: bool = False
    battles_delta: int = 0
    rating_delta: int = 0
    win_rate_delta: float = 0.0
    avg_damage_delta: int = 0
    avg_frags_delta: float = 0.0
    avg_exp_delta: int = 0


@dataclass
class PersonalStats:
    account_id: str
    nickname: str
    created_at: int
    region: str = "EU"
    clan_tag: str | None = None
    clan_name: str | None = None
    clan_league: int = 5
    dog_tag_url: str | None = None
    overall: Metric = field(default_factory=Metric)
    battle_type: dict[str, Metric] = field(default_factory=dict)
    ship_type: dict[str, Metric] = field(default_factory=dict)
    chart_data: dict[str, int] = field(default_factory=dict)
    periods: dict[str, PeriodMetric] = field(default_factory=dict)
    collected_at: str = ""
