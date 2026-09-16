"""Shows the user how to connect MCP clients, manages personal MCP tokens, and lets them revoke access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.services import mcp_tokens
from common import config
from common.models import McpAccessToken, OAuthClient, OAuthToken, User

router = APIRouter(prefix="/mcp", tags=["mcp"])


class TokenCreate(BaseModel):
    name: str = Field(default="MCP client", max_length=100)


@router.get("")
def mcp_info(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(OAuthClient.client_id, OAuthClient.client_name, func.min(OAuthToken.created_at), func.max(OAuthToken.created_at))
        .join(OAuthToken, OAuthToken.client_id == OAuthClient.client_id)
        .where(OAuthToken.user_id == user.id, OAuthToken.revoked_at.is_(None),
               (OAuthToken.refresh_expires_at > now) | (OAuthToken.expires_at > now))
        .group_by(OAuthClient.client_id, OAuthClient.client_name)
    ).all()
    tokens = db.scalars(
        select(McpAccessToken).where(McpAccessToken.user_id == user.id, McpAccessToken.revoked_at.is_(None))
        .order_by(McpAccessToken.created_at.desc())
    ).all()
    url = config.mcp_resource_url()
    return {
        "mcp_url": url,
        "claude_code_command": f"claude mcp add --transport http content-ai-generator {url}",
        "https_required_for_remote": not url.startswith("https://"),
        "grants": [{"client_id": r[0], "client_name": r[1], "first_authorized_at": r[2], "last_authorized_at": r[3]}
                   for r in rows],
        "tokens": [{"id": str(t.id), "name": t.name, "prefix": t.token_prefix, "created_at": t.created_at,
                    "last_used_at": t.last_used_at} for t in tokens],
    }


@router.post("/tokens")
def create_token(body: TokenCreate, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    """The token itself is returned only here; afterwards only its prefix is shown."""
    row, token = mcp_tokens.create(db, user, body.name)
    return {"id": str(row.id), "name": row.name, "token": token, "connector_url": mcp_tokens.connector_url(token),
            "claude_code_command": f"claude mcp add --transport http content-ai-generator {config.mcp_resource_url()} "
                                   f"--header \"Authorization: Bearer {token}\""}


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    result = db.execute(update(McpAccessToken).where(
        McpAccessToken.id == token_id, McpAccessToken.user_id == user.id, McpAccessToken.revoked_at.is_(None)
    ).values(revoked_at=datetime.now(timezone.utc)))
    if not result.rowcount:
        raise HTTPException(404, "Token not found.")
    return {"revoked": True}


@router.delete("/grants/{client_id}")
def revoke_grant(client_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    result = db.execute(update(OAuthToken).where(
        OAuthToken.user_id == user.id, OAuthToken.client_id == client_id, OAuthToken.revoked_at.is_(None)
    ).values(revoked_at=datetime.now(timezone.utc)))
    return {"revoked_tokens": result.rowcount}
