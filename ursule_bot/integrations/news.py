from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx


OFFICIAL_NEWS_API = "https://worldofwarships.eu/papi/v1/news/"
OFFICIAL_CATEGORIES_API = "https://worldofwarships.eu/papi/v1/categories/"
OFFICIAL_NEWS_ROOT = "https://worldofwarships.eu/zh-sg/news/"
DEVBLOG_API = "https://blog.worldofwarships.com/api/posts/"
DEVBLOG_ROOT = "https://blog.worldofwarships.com/blog/"
REQUEST_HEADERS = {"User-Agent": "Ursule-Bot/0.2 (+self-hosted WoWS news reader)"}


class NewsCollectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewsArticle:
    title: str
    source: str
    published_at: datetime
    url: str
    image_url: str
    description: str = ""
    tags: tuple[str, ...] = ()
    tag_color: str = "#147D92"
    thumbnail: bytes | None = None


def parse_official_categories(payload: Any) -> dict[int, tuple[str, str]]:
    output: dict[int, tuple[str, str]] = {}
    for row in payload.get("items", []) if isinstance(payload, dict) else []:
        try:
            output[int(row["id"])] = (str(row["title"]).strip(), str(row.get("background_color") or "#E4A23F"))
        except (KeyError, TypeError, ValueError):
            continue
    return output


def parse_official_news(payload: Any, categories: dict[int, tuple[str, str]] | None = None) -> list[NewsArticle]:
    output: list[NewsArticle] = []
    for row in payload.get("items", []) if isinstance(payload, dict) else []:
        try:
            published = datetime.fromtimestamp(int(row["published_at"]), timezone.utc)
            title = str(row["title"]).strip()
            slug = str(row["slug"]).strip()
            image = str(row.get("preview_image_url") or row.get("image_url") or "").strip()
            category = (categories or {}).get(int(row.get("category", 0)), ("官网新闻", "#E4A23F"))
            description = str(row.get("description") or "").strip()
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if title and slug:
            output.append(NewsArticle(
                title, "官网", published, f"{OFFICIAL_NEWS_ROOT}{slug}/", image,
                description=description, tags=(category[0],), tag_color=category[1],
            ))
    return output


def parse_devblog_news(payload: Any) -> list[NewsArticle]:
    output: list[NewsArticle] = []
    for row in payload.get("items", []) if isinstance(payload, dict) else []:
        try:
            published = datetime.strptime(str(row["publication_date"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            title = str(row["title"]).strip()
            slug = str(row["slug"]).strip()
            image = str(row.get("preview_image") or "").strip()
            tags = tuple(str(value).strip() for value in row.get("categories", []) if str(value).strip())
            description = re.sub(r"<[^>]+>", " ", str(row.get("short_content") or ""))
            description = " ".join(html.unescape(description).split())
            description = re.sub(r"\s+([.,!?;:])", r"\1", description)
            description = re.sub(r"\s+([.,!?;:])", r"\1", description)
        except (KeyError, TypeError, ValueError):
            continue
        if title and slug:
            output.append(NewsArticle(
                title, "开发者博客", published, f"{DEVBLOG_ROOT}{slug}", image,
                description=description, tags=tags, tag_color="#151719",
            ))
    return output


def recent_articles(
    articles: list[NewsArticle],
    *,
    now: datetime,
    days: int = 7,
    limit: int = 8,
) -> list[NewsArticle]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - timedelta(days=days)
    unique: dict[str, NewsArticle] = {}
    for article in articles:
        published = article.published_at.astimezone(timezone.utc)
        if cutoff <= published <= now.astimezone(timezone.utc):
            unique[article.url] = article
    return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)[:limit]


def _trusted_image_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host.endswith(".wgcdn.co") or host.endswith(".gcdn.co"))


async def _download_thumbnail(client: httpx.AsyncClient, article: NewsArticle) -> NewsArticle:
    if not article.image_url or not _trusted_image_url(article.image_url):
        return article
    try:
        response = await client.get(article.image_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        payload = response.content
        if content_type.startswith("image/") and len(payload) <= 8 * 1024 * 1024:
            return replace(article, thumbnail=payload)
    except (httpx.HTTPError, ValueError):
        pass
    return article


async def _collect_with_client(
    client: httpx.AsyncClient,
    *,
    now: datetime,
    days: int,
    limit: int,
) -> list[NewsArticle]:
    requests = (
        client.get(OFFICIAL_NEWS_API, params={"page": "1", "lang": "zh-sg"}),
        client.get(OFFICIAL_CATEGORIES_API, params={"lang": "zh-sg"}),
        client.get(DEVBLOG_API, params={"limit": "20"}),
    )
    responses = await asyncio.gather(*requests, return_exceptions=True)
    articles: list[NewsArticle] = []
    succeeded = 0
    official_response, categories_response, devblog_response = responses
    categories: dict[int, tuple[str, str]] = {}
    if not isinstance(categories_response, BaseException):
        try:
            categories_response.raise_for_status()
            categories = parse_official_categories(categories_response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            pass
    for response, parser in (
        (official_response, lambda payload: parse_official_news(payload, categories)),
        (devblog_response, parse_devblog_news),
    ):
        if not isinstance(response, BaseException):
            try:
                response.raise_for_status()
                articles.extend(parser(response.json()))
                succeeded += 1
            except (httpx.HTTPError, ValueError, TypeError):
                pass
    if not succeeded:
        raise NewsCollectionError("官网新闻与开发者博客暂时均不可用")
    selected = recent_articles(articles, now=now, days=days, limit=limit)
    return list(await asyncio.gather(*(_download_thumbnail(client, article) for article in selected)))


async def collect_recent_news(
    *,
    now: datetime | None = None,
    days: int = 7,
    limit: int = 8,
    client: httpx.AsyncClient | None = None,
) -> list[NewsArticle]:
    current = now or datetime.now(timezone.utc)
    if client is not None:
        return await _collect_with_client(client, now=current, days=days, limit=limit)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=REQUEST_HEADERS) as owned_client:
        return await _collect_with_client(owned_client, now=current, days=days, limit=limit)
