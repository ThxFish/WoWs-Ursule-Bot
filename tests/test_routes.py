import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ursule_bot.application import create_app
from ursule_bot.interfaces.web import dependencies


def test_new_pages_are_registered_and_old_pages_are_removed():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert {"/", "/planning", "/planning/goals", "/planning/regrind", "/planning/snapshots", "/stats", "/information", "/settings"} <= paths
    assert {"/goals", "/plan", "/history"}.isdisjoint(paths)
    assert any(path.startswith("/api/planning/") for path in paths)
    assert any(path.startswith("/api/system/") for path in paths)


def test_csrf_rejects_mismatched_token(monkeypatch):
    monkeypatch.setattr(dependencies, "read_session", lambda _cookie: {"csrf": "expected"})
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", b"ursule_session=signed")]})
    with pytest.raises(HTTPException) as error:
        dependencies.require_csrf(request, "wrong")
    assert error.value.status_code == 403
