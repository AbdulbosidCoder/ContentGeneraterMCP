"""Sign in with Facebook.

1. The person logs in with Facebook (Facebook Login for Business, or a demo login in mock mode).
2. If their Facebook user id belongs to an existing account, they are signed in and their
   Facebook connection (token, Pages, Instagram accounts) is refreshed.
3. Otherwise the Facebook token is parked in ``pending_signups`` (encrypted, 30 minutes,
   referenced by an HttpOnly cookie) and the app shows a sign-up form (name, email).
   Submitting it creates the account and the connection, and signs them in.

Email verification is intentionally not implemented yet.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.deps import SESSION_COOKIE, current_user, get_db
from app.models import DemoFacebookLogin, SignupRequest
from app.services.meta_accounts import facebook_identity, save_connection
from common import config
from common.meta import oauth as meta_oauth
from common.models import LoginState, MetaConnection, PendingSignup, User, UserSession
from common.security import decrypt, encrypt, hash_token, new_token

router = APIRouter(prefix="/auth", tags=["auth"])
SIGNUP_COOKIE = "cag_signup"
SESSION_TTL = timedelta(days=14)
STATE_TTL = timedelta(minutes=10)
SIGNUP_TTL = timedelta(minutes=30)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DB = Depends(get_db, scope="function")


def safe_return_to(value: str | None) -> str:
    """Only allow same-site relative paths (prevents open redirects)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _secure_cookies() -> bool:
    return config.public_base_url().startswith("https://")


def start_session(db: Session, response: Response, user: User, request: Request) -> None:
    token = new_token()
    db.add(UserSession(
        user_id=user.id, token_hash=hash_token(token), expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        user_agent=(request.headers.get("user-agent") or "")[:512],
    ))
    user.last_login_at = datetime.now(timezone.utc)
    response.set_cookie(SESSION_COOKIE, token, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                        samesite="lax", secure=_secure_cookies(), path="/")


def _find_user(db: Session, facebook_id: str) -> User | None:
    user = db.scalar(select(User).where(User.facebook_id == facebook_id))
    if user is None:  # accounts created before Facebook sign-in existed
        connection = db.scalar(select(MetaConnection).where(MetaConnection.fb_user_id == facebook_id)
                               .order_by(MetaConnection.created_at))
        if connection:
            user = db.get(User, connection.user_id)
            if user and not user.facebook_id:
                user.facebook_id = facebook_id
    return user


def complete_facebook_login(
    db: Session, request: Request, response: Response, *, token: str, expires_at: datetime | None,
    scopes: list[str], is_mock: bool, me: dict[str, Any], return_to: str,
) -> str:
    """Returns "logged_in" or "signup_required" (and sets the matching cookie)."""
    db.execute(delete(PendingSignup).where(PendingSignup.expires_at < datetime.now(timezone.utc)))
    user = _find_user(db, me["id"])
    if user is not None:
        if me.get("picture_url"):
            user.picture_url = me["picture_url"]
        save_connection(db, user, token, expires_at, scopes, is_mock, me=me)
        start_session(db, response, user, request)
        return "logged_in"

    signup_token = new_token()
    db.add(PendingSignup(
        token_hash=hash_token(signup_token), fb_user_id=me["id"], fb_name=me.get("name") or "",
        fb_email=me.get("email"), picture_url=me.get("picture_url"), access_token_enc=encrypt(token),
        token_expires_at=expires_at, scopes=scopes, is_mock=is_mock, return_to=return_to,
        expires_at=datetime.now(timezone.utc) + SIGNUP_TTL,
    ))
    response.set_cookie(SIGNUP_COOKIE, signup_token, max_age=int(SIGNUP_TTL.total_seconds()), httponly=True,
                        samesite="lax", secure=_secure_cookies(), path="/")
    return "signup_required"


@router.get("/config")
def auth_config() -> dict:
    return {"facebook_enabled": config.meta_configured(), "demo_mode": not config.meta_configured()}


@router.get("/facebook/login")
def facebook_login(return_to: str | None = None, db: Session = DB) -> RedirectResponse:
    if not config.meta_configured():
        raise HTTPException(404, "Facebook login is not configured (META_APP_ID / META_APP_SECRET).")
    state = new_token()
    db.execute(delete(LoginState).where(LoginState.expires_at < datetime.now(timezone.utc)))
    db.add(LoginState(state_hash=hash_token(state), provider="facebook_login", return_to=safe_return_to(return_to),
                      expires_at=datetime.now(timezone.utc) + STATE_TTL))
    return RedirectResponse(meta_oauth.login_url(state, "login"), status_code=302)


@router.get("/facebook/callback")
def facebook_callback(
    request: Request, state: str = "", code: str = "", error: str | None = None, error_reason: str | None = None,
    db: Session = DB,
) -> RedirectResponse:
    row = db.get(LoginState, hash_token(state))
    if row is None or row.provider != "facebook_login" or row.expires_at <= datetime.now(timezone.utc):
        return RedirectResponse("/?login_error=expired", status_code=302)
    db.delete(row)
    if error or not code:
        return RedirectResponse(f"/?login_error={error_reason or error or 'cancelled'}", status_code=302)
    try:
        token, expires_at = meta_oauth.exchange_code_for_long_lived_token(code, "login")
        scopes = meta_oauth.granted_scopes(token)
        me = facebook_identity(token, is_mock=False)
    except Exception:  # noqa: BLE001
        return RedirectResponse("/?login_error=facebook", status_code=302)

    response = RedirectResponse(row.return_to or "/", status_code=302)
    outcome = complete_facebook_login(db, request, response, token=token, expires_at=expires_at, scopes=scopes,
                                      is_mock=False, me=me, return_to=row.return_to or "/")
    if outcome == "signup_required":
        response.headers["location"] = "/?signup=1"
    return response


@router.post("/demo-facebook")
def demo_facebook_login(body: DemoFacebookLogin, request: Request, response: Response, db: Session = DB) -> dict:
    """Mock mode only: stands in for Facebook Login. The same name is always the same Facebook user."""
    if config.meta_configured():
        raise HTTPException(403, "Demo login is disabled when a Meta app is configured.")
    name = body.name.strip()
    token = f"mock-user-token-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'demo'}"
    me = {**facebook_identity(token, is_mock=True), "name": name}
    outcome = complete_facebook_login(db, request, response, token=token, expires_at=None,
                                      scopes=["[MOCK] all permissions"], is_mock=True, me=me,
                                      return_to=safe_return_to(body.return_to))
    return {"status": outcome}


def _pending(db: Session, request: Request) -> PendingSignup:
    cookie = request.cookies.get(SIGNUP_COOKIE)
    row = db.get(PendingSignup, hash_token(cookie)) if cookie else None
    if row is None or row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(404, "Your Facebook login expired. Continue with Facebook again.")
    return row


@router.get("/signup")
def signup_info(request: Request, db: Session = DB) -> dict:
    row = _pending(db, request)
    return {"name": row.fb_name, "email": row.fb_email or "", "picture_url": row.picture_url, "is_mock": row.is_mock}


@router.post("/signup")
def signup(body: SignupRequest, request: Request, response: Response, db: Session = DB) -> dict:
    row = _pending(db, request)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists. Continue with the Facebook account you used before.")
    if _find_user(db, row.fb_user_id):  # signed up in another tab meanwhile
        raise HTTPException(409, "This Facebook account already has an account. Continue with Facebook to sign in.")

    user = User(facebook_id=row.fb_user_id, email=email, name=body.name.strip(), picture_url=row.picture_url,
                is_demo=row.is_mock)
    db.add(user)
    db.flush()
    save_connection(db, user, decrypt(row.access_token_enc), row.token_expires_at, row.scopes, row.is_mock,
                    me={"id": row.fb_user_id, "name": row.fb_name})
    start_session(db, response, user, request)
    return_to = row.return_to or "/"
    db.delete(row)
    response.delete_cookie(SIGNUP_COOKIE, path="/")
    return {"ok": True, "return_to": return_to}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = DB) -> dict:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(cookie)))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = DB) -> dict:
    connections = db.scalar(select(func.count()).select_from(MetaConnection).where(MetaConnection.user_id == user.id))
    return {"id": str(user.id), "email": user.email, "name": user.name, "picture_url": user.picture_url,
            "is_demo": user.is_demo, "connections": connections}
