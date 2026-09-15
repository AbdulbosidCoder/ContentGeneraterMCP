"""Connecting Facebook/Instagram, choosing which assets to sync, and job status."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import AssetUpdate
from app.services.jobs import enqueue, job_dict
from app.services.meta_accounts import asset_dict, connection_dict, get_asset, save_connection
from common import config
from common.meta import oauth as meta_oauth
from common.models import ContentItem, Job, LoginState, MetaAsset, MetaConnection, User
from common.security import hash_token, new_token
from rag.vectorstore import ContentStore

logger = logging.getLogger("backend.accounts")
router = APIRouter(tags=["accounts"])


@router.get("/connections")
def list_connections(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    rows = db.scalars(select(MetaConnection).where(MetaConnection.user_id == user.id).order_by(MetaConnection.created_at)).all()
    return {"meta_enabled": config.meta_configured(), "connections": [connection_dict(c) for c in rows]}


@router.get("/connections/meta/login")
def meta_login(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> RedirectResponse:
    if not config.meta_configured():
        # Mock mode: no Facebook dialog; create a demo connection with demo Pages/IG accounts.
        save_connection(db, user, f"mock-user-token-{user.id}", None, ["[MOCK] all permissions"], is_mock=True)
        return RedirectResponse("/?tab=accounts&connected=mock", status_code=302)
    state = new_token()
    db.add(LoginState(state_hash=hash_token(state), provider="meta", user_id=user.id,
                      expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
    return RedirectResponse(meta_oauth.login_url(state, "connect"), status_code=302)


@router.get("/connections/meta/callback")
def meta_callback(
    state: str = "", code: str = "", error: str | None = None, error_reason: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db, scope="function"),
) -> RedirectResponse:
    row = db.get(LoginState, hash_token(state))
    if row is None or row.provider != "meta" or row.user_id != user.id or row.expires_at <= datetime.now(timezone.utc):
        return RedirectResponse("/?tab=accounts&connect_error=expired", status_code=302)
    db.delete(row)
    if error or not code:
        return RedirectResponse(f"/?tab=accounts&connect_error={error_reason or error or 'cancelled'}", status_code=302)
    try:
        token, expires_at = meta_oauth.exchange_code_for_long_lived_token(code, "connect")
        scopes = meta_oauth.granted_scopes(token)
        save_connection(db, user, token, expires_at, scopes, is_mock=False)
    except Exception:  # noqa: BLE001
        logger.exception("Facebook connection failed")
        return RedirectResponse("/?tab=accounts&connect_error=facebook", status_code=302)
    return RedirectResponse("/?tab=accounts&connected=1", status_code=302)


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    connection = db.get(MetaConnection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(404, "Connection not found.")
    asset_ids = [a.id for a in connection.assets]
    item_ids = [str(i) for i in db.scalars(select(ContentItem.id).where(ContentItem.asset_id.in_(asset_ids)))]
    ContentStore().delete_items(item_ids)
    db.delete(connection)  # cascades to assets, their posts, and the encrypted tokens
    return {"deleted": True, "removed_posts": len(item_ids)}


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: str, body: AssetUpdate, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = get_asset(db, user, asset_id)
    asset.is_selected = body.is_selected
    if body.is_selected and asset.sync_status == "never":
        asset.sync_status = "queued"
        enqueue(db, user.id, "sync_asset", {"asset_id": str(asset.id)})
    return asset_dict(asset)


@router.post("/assets/{asset_id}/sync")
def sync_asset(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = get_asset(db, user, asset_id)
    asset.sync_status = "queued"
    return job_dict(enqueue(db, user.id, "sync_asset", {"asset_id": str(asset.id)}))


@router.post("/sync")
def sync_all(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    assets = db.scalars(select(MetaAsset).where(MetaAsset.user_id == user.id, MetaAsset.is_selected.is_(True))).all()
    jobs = []
    for asset in assets:
        asset.sync_status = "queued"
        jobs.append(job_dict(enqueue(db, user.id, "sync_asset", {"asset_id": str(asset.id)})))
    return {"jobs": jobs}


@router.get("/jobs")
def list_jobs(limit: int = 20, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    jobs = db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(min(limit, 100))).all()
    return {"jobs": [job_dict(j) for j in jobs], "active": any(j.status in ("queued", "running") for j in jobs)}
