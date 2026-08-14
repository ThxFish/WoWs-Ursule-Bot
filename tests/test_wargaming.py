from urllib.parse import parse_qs, urlparse

from ursule_bot.integrations.wargaming_auth import build_login_url


def test_wargaming_openid_uses_shared_wot_auth_endpoint():
    url = build_login_url("app-id", "http://127.0.0.1:8000/auth/wargaming/callback")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "api.worldoftanks.eu"
    assert parsed.path == "/wot/auth/login/"
    assert query["application_id"] == ["app-id"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/auth/wargaming/callback"]
    assert query["expires_at"] == ["1209600"]
    assert "nofollow" not in query
