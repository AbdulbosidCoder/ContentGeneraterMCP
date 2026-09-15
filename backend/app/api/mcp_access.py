"""Shows the user how to connect MCP clients, and lets them revoke access."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from common import config
from common.models import OAuthClient, OAuthToken, User

router = APIRouter(prefix="/mcp", tags=["mcp"])


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
    url = config.mcp_resource_url()
    return {
        "mcp_url": url,
        "claude_code_command": f"claude mcp add --transport http content-ai-generator {url}",
        "https_required_for_remote": not url.startswith("https://"),
        "grants": [{"client_id": r[0], "client_name": r[1], "first_authorized_at": r[2], "last_authorized_at": r[3]}
                   for r in rows],
    }


@router.delete("/grants/{client_id}")
def revoke_grant(client_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    result = db.execute(update(OAuthToken).where(
        OAuthToken.user_id == user.id, OAuthToken.client_id == client_id, OAuthToken.revoked_at.is_(None)
    ).values(revoked_at=datetime.now(timezone.utc)))
    return {"revoked_tokens": result.rowcount}
