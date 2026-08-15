from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from .... import __version__
from ....centers.information.service import get_overview as get_information_overview
from ....centers.information.service import get_recent_news
from ....centers.planning.overview import get_activity_overview
from ....centers.stats.service import get_overview as get_stats_overview
from ....centers.stats.service import get_personal_stats, load_cached_stats
from ....core.database import get_db
from ....core.settings import get_setting
from ..dependencies import page_context, templates


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    planning = get_activity_overview(db)
    cached_stats = load_cached_stats()
    healthy_sources = sum(1 for source in planning.statuses if source.ok)
    return templates.TemplateResponse("dashboard.html", page_context(
        request,
        active_nav="dashboard",
        planning=planning,
        stats_center=get_stats_overview(),
        cached_stats=cached_stats,
        information_center=get_information_overview(),
        source_health={"healthy": healthy_sources, "total": len(planning.statuses)},
        backup_status={"at": get_setting(db, "last_backup_at"), "file": get_setting(db, "last_backup_file"), "error": get_setting(db, "last_backup_error")},
    ))


@router.get("/stats", response_class=HTMLResponse)
def stats_center(request: Request):
    return templates.TemplateResponse("centers/stats.html", page_context(
        request,
        active_nav="stats",
        center=get_stats_overview(),
        cached=load_cached_stats(),
    ))


@router.get("/api/stats/image")
async def stats_image(theme: str = "light", refresh: bool = True, db: Session = Depends(get_db)):
    from ....rendering.kokomi import render_personal_stats
    if theme not in {"light", "dark"}:
        raise HTTPException(400, "主题仅支持 light 或 dark")
    try:
        stats = await get_personal_stats(db, refresh=refresh)
        image = render_personal_stats(stats, theme=theme)
    except Exception as exc:
        raise HTTPException(502, "战绩生成失败，请检查账号、Wargaming Application ID 与网络连接。") from exc
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/information", response_class=HTMLResponse)
def information_center(request: Request):
    return templates.TemplateResponse("centers/information.html", page_context(request, active_nav="information", center=get_information_overview()))


@router.get("/api/information/image")
async def information_image():
    from ....rendering.information import NewsItem, render_information_report
    try:
        articles = await get_recent_news()
        items = [
            NewsItem(
                title=article.title,
                source=article.source,
                published_at=article.published_at,
                description=article.description,
                tags=article.tags,
                tag_color=article.tag_color,
                url=article.url,
                thumbnail=article.thumbnail,
            )
            for article in articles
        ]
        image = render_information_report(items)
    except Exception as exc:
        raise HTTPException(502, "新闻获取失败，请稍后重试。") from exc
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})
