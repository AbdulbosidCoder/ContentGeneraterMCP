"""Facebook Login (for Business) authorization-code flow.

Used twice: to sign in to the service (``purpose="login"``) and, for a signed-in
user, to connect an additional Facebook login (``purpose="connect"``). Both
redirect URIs must be listed under "Valid OAuth Redirect URIs" in the Meta app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from common import config
from common.meta.graph import GRAPH_URL, GraphAPIError

Purpose = Literal["login", "connect"]
_CALLBACK_PATHS = {"login": "/api/auth/facebook/callback", "connect": "/api/connections/meta/callback"}


def redirect_uri(purpose: Purpose) -> str:
    return f"{config.public_base_url()}{_CALLBACK_PATHS[purpose]}"


def login_url(state: str, purpose: Purpose) -> str:
    params = {
        "client_id": config.env("META_APP_ID"),
        "redirect_uri": redirect_uri(purpose),
        "state": state,
        "response_type": "code",
    }
    config_id = config.env("META_LOGIN_CONFIG_ID")
    if config_id:
        params["config_id"] = config_id  # Facebook Login for Business configuration
    else:
        params["scope"] = ",".join(config.META_PERMISSIONS)
    return f"https://www.facebook.com/{config.graph_api_version()}/dialog/oauth?{urlencode(params)}"


def _oauth_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{GRAPH_URL}/{config.graph_api_version()}/{path}"
    with httpx.Client(timeout=30) as client:
        response = client.get(url, params=params)
    payload = response.json() if response.content else {}
    if response.is_error or "error" in payload:
        message = (payload.get("error") or {}).get("message") or response.text[:300]
        raise GraphAPIError(f"Facebook login failed: {message}", status=response.status_code)
    return payload


def exchange_code_for_long_lived_token(code: str, purpose: Purpose) -> tuple[str, datetime | None]:
    """code -> short-lived user token -> long-lived user token (about 60 days)."""
    app_id, app_secret = config.env("META_APP_ID"), config.env("META_APP_SECRET")
    short = _oauth_get("oauth/access_token", {
        "client_id": app_id, "client_secret": app_secret, "redirect_uri": redirect_uri(purpose), "code": code,
    })
    long_lived = _oauth_get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
        "fb_exchange_token": short["access_token"],
    })
    expires_in = long_lived.get("expires_in")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in else None
    return long_lived["access_token"], expires_at


def granted_scopes(user_token: str) -> list[str]:
    app_token = f"{config.env('META_APP_ID')}|{config.env('META_APP_SECRET')}"
    data = _oauth_get("debug_token", {"input_token": user_token, "access_token": app_token}).get("data") or {}
    return sorted(data.get("scopes") or [])
