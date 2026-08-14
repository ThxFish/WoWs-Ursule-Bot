from dataclasses import dataclass


@dataclass(frozen=True)
class StatsCenterOverview:
    title: str = "战绩中心"
    description: str = "账号、周期与单舰战绩分析将在这里汇总。"
    available: bool = False


def get_overview() -> StatsCenterOverview:
    return StatsCenterOverview()
