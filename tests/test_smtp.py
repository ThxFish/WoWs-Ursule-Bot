from ursule_bot.integrations import notifications


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def smtp_settings(security, port):
    return {
        "smtp_host": "smtp.example.com",
        "smtp_port": str(port),
        "smtp_security": security,
        "smtp_username": "sender@example.com",
        "smtp_password": "secret",
        "smtp_recipient": "recipient@example.com",
    }


def test_send_email_uses_ssl(monkeypatch):
    values = smtp_settings("ssl", 465)
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notifications, "get_setting", lambda _db, key, default="": values.get(key, default))
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", FakeSMTP)

    notifications.send_email(object(), "subject", "body")

    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 465)
    assert smtp.started_tls is False
    assert smtp.login_args == ("sender@example.com", "secret")
    assert smtp.message["To"] == "recipient@example.com"


def test_send_email_uses_starttls(monkeypatch):
    values = smtp_settings("starttls", 587)
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notifications, "get_setting", lambda _db, key, default="": values.get(key, default))
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)

    notifications.send_email(object(), "subject", "body")

    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.started_tls is True


def test_legacy_port_587_defaults_to_starttls(monkeypatch):
    values = smtp_settings("", 587)
    values.pop("smtp_security")
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notifications, "get_setting", lambda _db, key, default="": values.get(key, default))
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)

    notifications.send_email(object(), "subject", "body")

    assert FakeSMTP.instances[-1].started_tls is True
