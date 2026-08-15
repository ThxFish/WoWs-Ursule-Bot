from datetime import datetime, timedelta, timezone

from ursule_bot.integrations.news import (
    NewsArticle,
    parse_devblog_news,
    parse_official_news,
    recent_articles,
)


def test_official_news_keeps_original_title_image_and_url():
    payload = {"items": [{
        "title": "15.8版本：周年庆典",
        "slug": "update-158-anniversary",
        "published_at": 1_786_712_400,
        "preview_image_url": "https://wows-wowsp-global.gcdn.co/media/preview.webp",
    }]}
    article = parse_official_news(payload, {0: ("游戏更新", "#E4A23F")})[0]
    assert article.title == "15.8版本：周年庆典"
    assert article.source == "官网"
    assert article.image_url.endswith("preview.webp")
    assert article.url == "https://worldofwarships.eu/zh-sg/news/update-158-anniversary/"


def test_devblog_news_keeps_english_title_without_translation():
    payload = {"items": [{
        "title": "Public Test 15.8 — Balance Changes",
        "slug": "public-test-158-balance-changes",
        "publication_date": "2026-08-14 10:00:00",
        "preview_image": "https://wows-media-devblog-prod.wgcdn.co/media/preview.jpg",
        "categories": ["Balance Changes", "Public Test", "15.8"],
        "short_content": "<p>We are applying <strong>balance changes</strong>.</p>",
    }]}
    article = parse_devblog_news(payload)[0]
    assert article.title == "Public Test 15.8 — Balance Changes"
    assert article.source == "开发者博客"
    assert article.url == "https://blog.worldofwarships.com/blog/public-test-158-balance-changes"
    assert article.tags == ("Balance Changes", "Public Test", "15.8")
    assert article.description == "We are applying balance changes."


def test_recent_articles_filters_one_week_and_sorts_newest_first_with_limit():
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    articles = [
        NewsArticle(f"news-{index}", "官网", now - timedelta(days=index), f"https://example/{index}", "")
        for index in range(10)
    ]
    selected = recent_articles(articles, now=now, days=7, limit=8)
    assert [item.title for item in selected] == [f"news-{index}" for index in range(8)]


def test_recent_articles_excludes_future_publications():
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    future = NewsArticle("scheduled", "官网", now + timedelta(minutes=1), "https://example/future", "")
    assert recent_articles([future], now=now) == []
