from dataclasses import dataclass

from ...integrations.news import NewsArticle, collect_recent_news


@dataclass(frozen=True)
class InformationCenterOverview:
    title: str = "信息中心"
    description: str = "最近一周的官网新闻与开发者博客，保留原始标题和图片。"
    available: bool = True


def get_overview() -> InformationCenterOverview:
    return InformationCenterOverview()


async def get_recent_news() -> list[NewsArticle]:
    return await collect_recent_news(days=7, limit=8)
