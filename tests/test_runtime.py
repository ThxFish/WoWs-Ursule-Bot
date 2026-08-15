from contextlib import contextmanager
from types import SimpleNamespace

from ursule_bot.jobs import runtime


class FakeScheduler:
    def __init__(self):
        self.running = False
        self.jobs = []
        self.starts = 0

    def add_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))

    def start(self):
        self.running = True
        self.starts += 1


def test_scheduler_is_registered_only_once(monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(runtime, "scheduler", scheduler)
    monkeypatch.setattr(runtime, "config", SimpleNamespace(sync_hour=3, sync_minute=15))

    runtime.start_scheduler()
    runtime.start_scheduler()

    assert scheduler.starts == 1
    assert len(scheduler.jobs) == 2
    assert scheduler.jobs[0][1]["id"] == "daily-sync"
    assert scheduler.jobs[0][1]["hour"] == 3
    assert scheduler.jobs[0][1]["minute"] == 15
    assert scheduler.jobs[0][1]["max_instances"] == 1
    assert scheduler.jobs[1][1]["id"] == "daily-report"
    assert scheduler.jobs[1][1]["hour"] == 10
    assert scheduler.jobs[1][1]["minute"] == 0
    assert scheduler.jobs[1][1]["max_instances"] == 1


async def test_scheduled_report_uses_latest_existing_snapshot_without_sync(monkeypatch):
    events = []
    sync_calls = []
    db = object()

    @contextmanager
    def session_local():
        yield db

    def render(session):
        assert session is db
        events.append(("render", None))
        return "latest report"

    async def notify(session, subject, content):
        assert session is db
        assert content == "latest report"
        events.append(("notify", subject))

    async def unexpected_sync(*args, **kwargs):
        sync_calls.append((args, kwargs))

    monkeypatch.setattr(runtime, "SessionLocal", session_local)
    monkeypatch.setattr(runtime, "guarded_sync", unexpected_sync)
    monkeypatch.setattr(runtime, "report_text", render)
    monkeypatch.setattr(runtime, "notify_with_fallback", notify)

    await runtime.scheduled_report()

    assert events == [
        ("render", None),
        ("notify", "战舰世界节日船团日报"),
    ]
    assert sync_calls == []
