import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ursule_bot.application import create_app
from ursule_bot.interfaces.web import dependencies
from ursule_bot.interfaces.web.routes import dashboard


def test_new_pages_are_registered_and_old_pages_are_removed():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert {"/", "/planning", "/planning/goals", "/planning/regrind", "/planning/snapshots", "/stats", "/information", "/settings"} <= paths
    assert {"/goals", "/plan", "/history"}.isdisjoint(paths)
    assert any(path.startswith("/api/planning/") for path in paths)
    assert "/api/stats/image" in paths
    assert "/api/information/image" in paths
    assert any(path.startswith("/api/system/") for path in paths)


def test_csrf_rejects_mismatched_token(monkeypatch):
    monkeypatch.setattr(dependencies, "read_session", lambda _cookie: {"csrf": "expected"})
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", b"ursule_session=signed")]})
    with pytest.raises(HTTPException) as error:
        dependencies.require_csrf(request, "wrong")
    assert error.value.status_code == 403


def test_dashboard_exposes_cached_stats_and_source_health(monkeypatch):
    class Source:
        def __init__(self, ok):
            self.ok = ok

    class Planning:
        statuses = [Source(True), Source(False), Source(True)]

    captured = {}
    monkeypatch.setattr(dashboard, "get_activity_overview", lambda _db: Planning())
    monkeypatch.setattr(dashboard, "load_cached_stats", lambda: "cached")
    monkeypatch.setattr(dashboard, "get_setting", lambda *_args: "")
    monkeypatch.setattr(dashboard.templates, "TemplateResponse", lambda name, context: captured.update(name=name, context=context) or context)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    dashboard.dashboard(request, db=object())

    assert captured["name"] == "dashboard.html"
    assert captured["context"]["cached_stats"] == "cached"
    assert captured["context"]["source_health"] == {"healthy": 2, "total": 3}
