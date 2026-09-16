"""OAuth 2.1 authorization server for MCP clients (Claude, Claude Code, other agents).

Implements what the MCP authorization spec needs: RFC 8414 metadata, RFC 7591
dynamic client registration, authorization code + PKCE (S256), refresh-token
rotation, RFC 7009 revocation and RFC 7662 introspection (for the MCP server).
Users approve access after signing in with Facebook; tokens are bound to the MCP
resource URL and stored hashed.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import mcp_tokens
from common import config
from common.models import OAuthAuthorizationCode, OAuthClient, OAuthToken, User
from common.security import hash_token, new_token, pkce_challenge

SCOPES = ["mcp"]
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)


class OAuthError(Exception):
    def __init__(self, error: str, description: str, status: int = 400):
        super().__init__(description)
        self.error, self.description, self.status = error, description, status

    def as_dict(self) -> dict[str, str]:
        return {"error": self.error, "error_description": self.description}


def metadata() -> dict[str, Any]:
    base = config.public_base_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "scopes_supported": SCOPES,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
    }


def _valid_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.fragment or not parsed.scheme:
        return False
    if parsed.scheme == "http":
        return parsed.hostname in ("localhost", "127.0.0.1", "::1")
    return True  # https or native-app custom schemes


def register_client(body: dict[str, Any]) -> tuple[OAuthClient, str | None]:
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris or not all(isinstance(u, str) and _valid_redirect(u) for u in redirect_uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be https URLs, custom schemes, or http://localhost.")
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        raise OAuthError("invalid_client_metadata", f"Unsupported token_endpoint_auth_method {method!r}.")
    grants = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if "authorization_code" not in grants:
        raise OAuthError("invalid_client_metadata", "grant_types must include authorization_code.")
    secret = new_token() if method != "none" else None
    client = OAuthClient(
        client_id=f"mcp_{secrets.token_hex(12)}",
        client_secret_hash=hash_token(secret) if secret else None,
        client_name=str(body.get("client_name") or "MCP client")[:255],
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=method,
    )
    return client, secret


def client_registration_response(client: OAuthClient, secret: str | None) -> dict[str, Any]:
    response = {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()) if client.created_at else int(datetime.now().timestamp()),
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": client.token_endpoint_auth_method,
        "scope": " ".join(SCOPES),
    }
    if secret:
        response.update(client_secret=secret, client_secret_expires_at=0)
    return response


def validate_authorize_request(db: Session, params: dict[str, str]) -> tuple[OAuthClient, dict[str, Any]]:
    """Errors before the redirect URI is trusted are shown to the user, never redirected."""
    client = db.get(OAuthClient, params.get("client_id", ""))
    if client is None:
        raise OAuthError("invalid_client", "Unknown client_id. Register the client first.")
    redirect_uri = params.get("redirect_uri") or (client.redirect_uris[0] if len(client.redirect_uris) == 1 else "")
    if redirect_uri not in client.redirect_uris:
        raise OAuthError("invalid_request", "redirect_uri does not match the registered redirect URIs.")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "response_type must be 'code'.")
    if not params.get("code_challenge") or params.get("code_challenge_method", "S256") != "S256":
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    requested = (params.get("scope") or " ".join(SCOPES)).split()
    if any(scope not in SCOPES for scope in requested):
        raise OAuthError("invalid_scope", f"Supported scopes: {' '.join(SCOPES)}.")
    resource = params.get("resource") or config.mcp_resource_url()
    if resource.rstrip("/") != config.mcp_resource_url():
        raise OAuthError("invalid_target", f"This server only issues tokens for {config.mcp_resource_url()}.")
    return client, {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": params["code_challenge"],
        "scopes": requested,
        "state": params.get("state"),
        "resource": config.mcp_resource_url(),
    }


def issue_code(db: Session, user: User, request: dict[str, Any]) -> str:
    code = new_token()
    db.add(OAuthAuthorizationCode(
        code_hash=hash_token(code), client_id=request["client_id"], user_id=user.id,
        redirect_uri=request["redirect_uri"], code_challenge=request["code_challenge"],
        scopes=request["scopes"], resource=request["resource"],
        expires_at=datetime.now(timezone.utc) + CODE_TTL,
    ))
    return code


def redirect_with(uri: str, **params: str | None) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{uri}{'&' if '?' in uri else '?'}{query}"


def authenticate_client(db: Session, client_id: str | None, client_secret: str | None) -> OAuthClient:
    client = db.get(OAuthClient, client_id or "")
    if client is None:
        raise OAuthError("invalid_client", "Unknown client.", 401)
    if client.token_endpoint_auth_method != "none":
        if not client_secret or hash_token(client_secret) != client.client_secret_hash:
            raise OAuthError("invalid_client", "Client authentication failed.", 401)
    return client


def _issue_tokens(db: Session, client_id: str, user_id, scopes: list[str], resource: str | None) -> dict[str, Any]:
    access, refresh = new_token(), new_token()
    now = datetime.now(timezone.utc)
    db.add(OAuthToken(
        access_token_hash=hash_token(access), refresh_token_hash=hash_token(refresh), client_id=client_id,
        user_id=user_id, scopes=scopes, resource=resource, expires_at=now + ACCESS_TOKEN_TTL,
        refresh_expires_at=now + REFRESH_TOKEN_TTL,
    ))
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
            "refresh_token": refresh, "scope": " ".join(scopes)}


def exchange_token(db: Session, form: dict[str, str], client: OAuthClient) -> dict[str, Any]:
    grant = form.get("grant_type")
    now = datetime.now(timezone.utc)
    if grant == "authorization_code":
        row = db.get(OAuthAuthorizationCode, hash_token(form.get("code", "")))
        if row is None or row.client_id != client.client_id or row.used_at or row.expires_at <= now:
            raise OAuthError("invalid_grant", "Authorization code is invalid, expired or already used.")
        if form.get("redirect_uri", row.redirect_uri) != row.redirect_uri:
            raise OAuthError("invalid_grant", "redirect_uri mismatch.")
        verifier = form.get("code_verifier") or ""
        if not verifier or not secrets.compare_digest(pkce_challenge(verifier), row.code_challenge):
            raise OAuthError("invalid_grant", "PKCE verification failed.")
        if form.get("resource") and form["resource"].rstrip("/") != row.resource:
            raise OAuthError("invalid_target", "resource does not match the authorization request.")
        row.used_at = now
        return _issue_tokens(db, client.client_id, row.user_id, row.scopes, row.resource)

    if grant == "refresh_token":
        row = db.scalar(select(OAuthToken).where(OAuthToken.refresh_token_hash == hash_token(form.get("refresh_token", ""))))
        if (row is None or row.client_id != client.client_id or row.revoked_at
                or not row.refresh_expires_at or row.refresh_expires_at <= now):
            raise OAuthError("invalid_grant", "Refresh token is invalid or expired.")
        row.revoked_at = now  # rotate
        return _issue_tokens(db, client.client_id, row.user_id, row.scopes, row.resource)

    raise OAuthError("unsupported_grant_type", "Use authorization_code or refresh_token.")


def revoke(db: Session, token: str) -> None:
    hashed = hash_token(token)
    row = db.scalar(select(OAuthToken).where((OAuthToken.access_token_hash == hashed) | (OAuthToken.refresh_token_hash == hashed)))
    if row and not row.revoked_at:
        row.revoked_at = datetime.now(timezone.utc)


def introspect(db: Session, token: str) -> dict[str, Any]:
    personal = mcp_tokens.lookup(db, token)
    if personal:
        user = db.get(User, personal.user_id)
        return {"active": True, "client_id": mcp_tokens.CLIENT_ID, "scope": " ".join(SCOPES),
                "sub": str(personal.user_id), "username": user.email if user else None,
                "aud": config.mcp_resource_url(), "iss": config.public_base_url()}

    row = db.scalar(select(OAuthToken).where(OAuthToken.access_token_hash == hash_token(token)))
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at or row.expires_at <= now:
        return {"active": False}
    user = db.get(User, row.user_id)
    return {"active": True, "client_id": row.client_id, "scope": " ".join(row.scopes), "sub": str(row.user_id),
            "username": user.email if user else None, "exp": int(row.expires_at.timestamp()), "aud": row.resource,
            "iss": config.public_base_url()}
