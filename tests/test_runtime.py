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

    runtime.start_scheduler()
    runtime.start_scheduler()

    assert scheduler.starts == 1
    assert len(scheduler.jobs) == 2
    assert scheduler.jobs[0][1]["id"] == "daily-sync"
    assert scheduler.jobs[0][1]["hour"] == 4
    assert scheduler.jobs[0][1]["minute"] == 0
    assert scheduler.jobs[0][1]["max_instances"] == 1
    assert scheduler.jobs[1][1]["id"] == "daily-report"
    assert scheduler.jobs[1][1]["hour"] == 10
    assert scheduler.jobs[1][1]["minute"] == 0
    assert scheduler.jobs[1][1]["max_instances"] == 1
