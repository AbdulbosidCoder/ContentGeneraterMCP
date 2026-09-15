"""OAuth 2.1 endpoints used by MCP clients (served at the site root, not under /api)."""

from __future__ import annotations

import base64
import html
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.deps import get_db, optional_user
from app.services import oauth_server as oauth
from common import config
from common.models import LoginState, User
from common.security import hash_token, new_token

router = APIRouter(tags=["oauth"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _error_json(exc: oauth.OAuthError) -> JSONResponse:
    return JSONResponse(exc.as_dict(), status_code=exc.status, headers=NO_STORE)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
body{{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f6f5f2;color:#1c1a17;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}}
.card{{background:#fff;border:1px solid #e3dfd6;border-radius:14px;padding:28px;max-width:440px;width:100%}}
h1{{font-size:1.25rem;margin:0 0 8px}} p{{color:#5b564d}} ul{{padding-left:20px;color:#3d3932}}
.actions{{display:flex;gap:10px;margin-top:22px}} button{{font:inherit;font-weight:600;border-radius:8px;padding:10px 18px;cursor:pointer;border:1px solid #d9d4ca;background:#fff}}
button.primary{{background:#c2410c;color:#fff;border-color:#c2410c}} code{{background:#f1efea;padding:1px 5px;border-radius:4px}}
@media (prefers-color-scheme:dark){{body{{background:#141311;color:#ece8e1}}.card{{background:#1d1b19;border-color:#34302b}}p,ul{{color:#b3ada3}}button{{background:#26231f;color:#ece8e1;border-color:#3a352f}}code{{background:#26231f}}}}
</style></head><body><div class="card">{body}</div></body></html>""", status_code=status)


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> JSONResponse:
    return JSONResponse(oauth.metadata())


@router.post("/oauth/register")
async def register(request: Request, db: Session = Depends(get_db, scope="function")) -> JSONResponse:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return _error_json(oauth.OAuthError("invalid_client_metadata", "Body must be a JSON object."))
    try:
        client, secret = oauth.register_client(body)
    except oauth.OAuthError as exc:
        return _error_json(exc)
    db.add(client)
    db.flush()
    return JSONResponse(oauth.client_registration_response(client, secret), status_code=201, headers=NO_STORE)


@router.get("/oauth/authorize")
def authorize(request: Request, db: Session = Depends(get_db, scope="function"), user: User | None = Depends(optional_user)):
    params = dict(request.query_params)
    try:
        client, auth_request = oauth.validate_authorize_request(db, params)
    except oauth.OAuthError as exc:
        return _page("Authorization error", f"<h1>Can't authorize this app</h1><p>{html.escape(exc.description)}</p>", 400)

    if user is None:
        return_to = quote(str(request.url.path) + "?" + str(request.url.query), safe="")
        return RedirectResponse(f"/?return_to={return_to}", status_code=302)

    ticket = new_token()
    db.add(LoginState(
        state_hash=hash_token(ticket), provider="mcp_consent", user_id=user.id,
        return_to=base64.urlsafe_b64encode(json.dumps(auth_request).encode()).decode(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    ))
    name = html.escape(client.client_name or client.client_id)
    redirect_host = html.escape(auth_request["redirect_uri"].split("?")[0])
    body = f"""
<h1>Allow {name} to access your account?</h1>
<p>Signed in as <strong>{html.escape(user.email)}</strong>.</p>
<p>{name} will be able to act as you in Content AI Generator:</p>
<ul>
  <li>Read your connected Instagram and Facebook content, insights and classifications</li>
  <li>Run hashtag and competitor research with your Instagram account</li>
  <li>Generate content plans and hashtag suggestions</li>
  <li><strong>Publish posts</strong> to your connected Instagram accounts and Facebook Pages</li>
</ul>
<p style="font-size:.85rem">You'll be sent back to <code>{redirect_host}</code>. You can revoke access at any time from the MCP tab.</p>
<form method="post" action="/oauth/authorize/decision" class="actions">
  <input type="hidden" name="ticket" value="{html.escape(ticket)}">
  <button type="submit" name="decision" value="deny">Deny</button>
  <button type="submit" name="decision" value="allow" class="primary">Allow</button>
</form>"""
    return _page(f"Authorize {client.client_name}", body)


@router.post("/oauth/authorize/decision")
async def authorize_decision(request: Request, db: Session = Depends(get_db, scope="function"), user: User | None = Depends(optional_user)):
    form = await request.form()
    row = db.get(LoginState, hash_token(str(form.get("ticket", ""))))
    if (row is None or row.provider != "mcp_consent" or user is None or row.user_id != user.id
            or row.expires_at <= datetime.now(timezone.utc)):
        return _page("Authorization expired", "<h1>This request expired</h1><p>Start the connection again from your MCP client.</p>", 400)
    auth_request = json.loads(base64.urlsafe_b64decode(row.return_to or ""))
    db.delete(row)
    if form.get("decision") != "allow":
        return RedirectResponse(oauth.redirect_with(auth_request["redirect_uri"], error="access_denied",
                                                    state=auth_request.get("state")), status_code=302)
    code = oauth.issue_code(db, user, auth_request)
    return RedirectResponse(oauth.redirect_with(auth_request["redirect_uri"], code=code, state=auth_request.get("state"),
                                                iss=config.public_base_url()), status_code=302)


def _client_credentials(request: Request, form: dict[str, str]) -> tuple[str | None, str | None]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            client_id, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            return unquote(client_id), unquote(secret)
        except ValueError:
            return None, None
    return form.get("client_id"), form.get("client_secret")


@router.post("/oauth/token")
async def token(request: Request, db: Session = Depends(get_db, scope="function")) -> JSONResponse:
    form = {k: str(v) for k, v in (await request.form()).items()}
    try:
        client = oauth.authenticate_client(db, *_client_credentials(request, form))
        return JSONResponse(oauth.exchange_token(db, form, client), headers=NO_STORE)
    except oauth.OAuthError as exc:
        return _error_json(exc)


@router.post("/oauth/revoke")
async def revoke(request: Request, db: Session = Depends(get_db, scope="function")) -> JSONResponse:
    form = {k: str(v) for k, v in (await request.form()).items()}
    if form.get("token"):
        oauth.revoke(db, form["token"])
    return JSONResponse({}, headers=NO_STORE)  # RFC 7009: 200 even for unknown tokens


@router.post("/oauth/introspect", include_in_schema=False)
async def introspect(request: Request, db: Session = Depends(get_db, scope="function")) -> JSONResponse:
    """Internal only (blocked at nginx): the MCP server validates bearer tokens here."""
    if request.headers.get("authorization") != f"Bearer {config.internal_service_token()}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    form = {k: str(v) for k, v in (await request.form()).items()}
    return JSONResponse(oauth.introspect(db, form.get("token", "")), headers=NO_STORE)
