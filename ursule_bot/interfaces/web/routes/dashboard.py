from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ....centers.information.service import get_overview as get_information_overview
from ....centers.planning.overview import get_activity_overview
from ....centers.stats.service import get_overview as get_stats_overview
from ....core.database import get_db
from ....core.settings import get_setting
from ..dependencies import page_context, templates


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    planning = get_activity_overview(db)
    return templates.TemplateResponse("dashboard.html", page_context(
        request,
        active_nav="dashboard",
        planning=planning,
        stats_center=get_stats_overview(),
        information_center=get_information_overview(),
        backup_status={"at": get_setting(db, "last_backup_at"), "file": get_setting(db, "last_backup_file"), "error": get_setting(db, "last_backup_error")},
    ))


@router.get("/stats", response_class=HTMLResponse)
def stats_center(request: Request):
    return templates.TemplateResponse("centers/stats.html", page_context(request, active_nav="stats", center=get_stats_overview()))


@router.get("/information", response_class=HTMLResponse)
def information_center(request: Request):
    return templates.TemplateResponse("centers/information.html", page_context(request, active_nav="information", center=get_information_overview()))
