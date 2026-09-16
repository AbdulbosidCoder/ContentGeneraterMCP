"""Personal MCP tokens: a per-user secret put in the connector URL ({MCP_PUBLIC_URL}/mcp?token=...).

Meant for clients that can't run the OAuth flow. Tokens don't expire, are stored hashed,
and each one acts as its owner until revoked from the MCP tab.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from common import config
from common.models import McpAccessToken, User
from common.security import hash_token, new_token

PREFIX = "mcp_"
CLIENT_ID = "personal-token"  # reported by introspection in place of an OAuth client_id
_LAST_USED_RESOLUTION = timedelta(minutes=5)  # avoid a DB write on every tool call


def create(db: Session, user: User, name: str) -> tuple[McpAccessToken, str]:
    token = PREFIX + new_token()
    row = McpAccessToken(user_id=user.id, name=name.strip()[:100] or "MCP client",
                         token_hash=hash_token(token), token_prefix=token[:12])
    db.add(row)
    db.flush()
    return row, token


def connector_url(token: str) -> str:
    return f"{config.mcp_resource_url()}?token={token}"


def lookup(db: Session, token: str) -> McpAccessToken | None:
    if not token.startswith(PREFIX):
        return None
    row = db.scalar(select(McpAccessToken).where(McpAccessToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at:
        return None
    now = datetime.now(timezone.utc)
    if row.last_used_at is None or now - row.last_used_at > _LAST_USED_RESOLUTION:
        row.last_used_at = now
    return row
