from dataclasses import dataclass


@dataclass(frozen=True)
class InformationCenterOverview:
    title: str = "信息中心"
    description: str = "更新公告、维护提醒与活动情报将在这里聚合。"
    available: bool = False


def get_overview() -> InformationCenterOverview:
    return InformationCenterOverview()
