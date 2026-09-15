"""Calls the backend API on behalf of the authenticated MCP user, and validates tokens."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp.exceptions import ToolError


def backend_url() -> str:
    return (os.getenv("BACKEND_INTERNAL_URL", "").strip() or "http://localhost:8000").rstrip("/")


def internal_token() -> str:
    return os.getenv("INTERNAL_SERVICE_TOKEN", "").strip() or "dev-internal-service-token"


class IntrospectionTokenVerifier(TokenVerifier):
    """RFC 7662 introspection against the backend, with a short positive cache."""

    def __init__(self, cache_seconds: float = 30.0) -> None:
        self._cache: dict[str, tuple[float, AccessToken]] = {}
        self._cache_seconds = cache_seconds

    async def verify_token(self, token: str) -> AccessToken | None:
        cached = self._cache.get(token)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{backend_url()}/oauth/introspect",
                data={"token": token},
                headers={"Authorization": f"Bearer {internal_token()}"},
            )
        if response.status_code != 200:
            return None
        data = response.json()
        if not data.get("active"):
            self._cache.pop(token, None)
            return None
        access = AccessToken(
            token=token,
            client_id=data["client_id"],
            scopes=(data.get("scope") or "").split(),
            expires_at=data.get("exp"),
            resource=data.get("aud"),
            subject=data.get("sub"),
        )
        self._cache[token] = (time.monotonic() + self._cache_seconds, access)
        if len(self._cache) > 1000:
            self._cache.clear()
        return access


async def call_backend(method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
    access = get_access_token()
    if access is None:
        raise ToolError("Not authenticated.")
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.request(
            method, f"{backend_url()}/api{path}", json=json, params=params,
            headers={"Authorization": f"Bearer {access.token}"},
        )
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:300]
        if isinstance(detail, list):
            detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail)
        raise ToolError(f"{detail or 'Request failed'} (HTTP {response.status_code})")
    return response.json()
