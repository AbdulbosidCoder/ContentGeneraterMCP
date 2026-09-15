"""Per-user Meta (Facebook + Instagram) Graph API access.

``client_for_token`` returns a real ``GraphClient`` or a ``MockGraphClient`` with
the same interface, so callers never branch on mock mode.
"""

from __future__ import annotations

from common.meta.graph import GraphAPIError, GraphClient, TokenExpiredError
from common.meta.mock import MockGraphClient


def client_for_token(access_token: str, is_mock: bool, seed: str = "") -> GraphClient | MockGraphClient:
    if is_mock:
        return MockGraphClient(seed or access_token)
    return GraphClient(access_token)


__all__ = ["GraphAPIError", "GraphClient", "MockGraphClient", "TokenExpiredError", "client_for_token"]
