from __future__ import annotations

from urllib.parse import urlencode


# Wargaming OpenID is shared by its PC games and remains hosted by the WoT API.
# World of Warships data endpoints still use api.worldofwarships.eu/wows/.
WG_AUTH_LOGIN_ENDPOINT = "https://api.worldoftanks.eu/wot/auth/login/"


def build_login_url(application_id: str, callback_url: str, expires_in: int = 14 * 24 * 60 * 60) -> str:
    query = urlencode(
        {
            "application_id": application_id,
            "redirect_uri": callback_url,
            "expires_at": expires_in,
        }
    )
    return WG_AUTH_LOGIN_ENDPOINT + "?" + query
