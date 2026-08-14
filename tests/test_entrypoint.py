from ursule_bot import __main__


def test_module_entrypoint_starts_ursule_application(monkeypatch):
    called = {}
    monkeypatch.setattr(__main__.uvicorn, "run", lambda target, **options: called.update(target=target, **options))

    __main__.main()

    assert called["target"] == "ursule_bot.application:app"
    assert called["workers"] == 1
