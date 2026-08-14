from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .core.database import SessionLocal
from .core.security import read_session
from .core.settings import has_setup
from .interfaces.web.routes import auth, dashboard, planning, system
from .jobs.runtime import initialize_database_and_plans, schedule_startup_sync, scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database_and_plans()
    start_scheduler()
    from .interfaces.qq.listener import start_listener
    qq_runtime = await start_listener()
    schedule_startup_sync()
    try:
        yield
    finally:
        if qq_runtime:
            qq_client, qq_task = qq_runtime
            await qq_client.close()
            qq_task.cancel()
            await asyncio.gather(qq_task, return_exceptions=True)
        if scheduler.running:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Ursule Bot", version="0.2.0", lifespan=lifespan)
    root = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        public = ("/static", "/health", "/setup", "/login")
        if request.url.path.startswith(public):
            return await call_next(request)
        with SessionLocal() as db:
            if not has_setup(db):
                return RedirectResponse("/setup", status_code=303)
        cookie = request.cookies.get("ursule_session") or request.cookies.get("tracker_session")
        if not read_session(cookie):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    for router in (auth.router, dashboard.router, planning.router, system.router):
        app.include_router(router)
    return app


app = create_app()
