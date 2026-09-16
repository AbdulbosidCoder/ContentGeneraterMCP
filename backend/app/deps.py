"""Request dependencies: database session and the authenticated user.

A request is authenticated either by the browser session cookie or by an MCP
bearer token (``Authorization: Bearer ...``): an OAuth access token issued to an
MCP client, or a personal MCP token from the MCP tab. Either way
all data access is scoped to that one user.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import mcp_tokens
from common import config
from common.db import session_factory
from common.models import OAuthToken, User, UserSession
from common.security import hash_token

SESSION_COOKIE = "cag_session"


def get_db() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def user_from_access_token(db: Session, token: str) -> User | None:
    personal = mcp_tokens.lookup(db, token)
    if personal:
        return db.get(User, personal.user_id)
    now = datetime.now(timezone.utc)
    row = db.scalar(select(OAuthToken).where(OAuthToken.access_token_hash == hash_token(token)))
    if not row or row.revoked_at or row.expires_at <= now or row.resource not in (None, config.mcp_resource_url()):
        return None
    return db.get(User, row.user_id)


def optional_user(request: Request, db: Session = Depends(get_db, scope="function")) -> User | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return user_from_access_token(db, authorization[7:].strip())

    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(cookie)))
    if not session or session.expires_at <= datetime.now(timezone.utc):
        return None
    return db.get(User, session.user_id)


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    return user
