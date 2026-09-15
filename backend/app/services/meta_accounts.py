"""Connecting a user's Facebook login, discovering their Pages and Instagram accounts,
and building an API client for any of their assets."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.jobs import enqueue
from common import config
from common.meta import GraphClient, MockGraphClient, TokenExpiredError, client_for_token
from common.models import MetaAsset, MetaConnection, User
from common.security import decrypt, encrypt

logger = logging.getLogger("backend.meta")


class AssetNotFound(LookupError):
    pass


def facebook_identity(access_token: str, is_mock: bool) -> dict[str, Any]:
    """The Facebook user behind a token: {id, name, email?, picture_url?}.
    Mock tokens are deterministic, so the same demo name is always the same Facebook user."""
    return client_for_token(access_token, is_mock).me()


def save_connection(
    db: Session, user: User, access_token: str, expires_at: datetime | None, scopes: list[str], is_mock: bool,
    me: dict[str, Any] | None = None,
) -> MetaConnection:
    client = client_for_token(access_token, is_mock)
    me = me or client.me()
    connection = db.scalar(select(MetaConnection).where(
        MetaConnection.user_id == user.id, MetaConnection.fb_user_id == me["id"]
    ))
    if connection is None:
        connection = MetaConnection(user_id=user.id, fb_user_id=me["id"], fb_user_name=me.get("name", ""),
                                    access_token_enc="")
        db.add(connection)
    connection.fb_user_name = me.get("name", "")
    connection.access_token_enc = encrypt(access_token)
    connection.token_expires_at = expires_at
    connection.scopes = scopes
    connection.is_mock = is_mock
    connection.status = "active"
    connection.last_error = None
    db.flush()

    refresh_assets(db, connection, client)
    for asset in connection.assets:
        if asset.is_selected:
            asset.sync_status = "queued"
            enqueue(db, user.id, "sync_asset", {"asset_id": str(asset.id)})
    return connection


def refresh_assets(db: Session, connection: MetaConnection, client: GraphClient | MockGraphClient) -> None:
    existing = {(a.kind, a.external_id): a for a in connection.assets}
    for page in client.list_pages():
        page_asset = existing.get(("facebook_page", page["id"]))
        if page_asset is None:
            page_asset = MetaAsset(user_id=connection.user_id, connection=connection, kind="facebook_page",
                                   external_id=page["id"], name=page["name"])
            db.add(page_asset)
        page_asset.name = page["name"]
        page_asset.picture_url = page.get("picture_url")
        page_asset.followers_count = page.get("followers_count")
        page_asset.page_token_enc = encrypt(page["access_token"]) if page.get("access_token") else None

        instagram = page.get("instagram")
        if instagram:
            ig_asset = existing.get(("instagram_account", instagram["id"]))
            if ig_asset is None:
                ig_asset = MetaAsset(user_id=connection.user_id, connection=connection, kind="instagram_account",
                                     external_id=instagram["id"], name=instagram.get("name") or instagram.get("username", ""))
                db.add(ig_asset)
            ig_asset.name = instagram.get("name") or instagram.get("username", "")
            ig_asset.username = instagram.get("username")
            ig_asset.picture_url = instagram.get("profile_picture_url")
            ig_asset.followers_count = instagram.get("followers_count")
            ig_asset.page_external_id = page["id"]
    db.flush()


def get_asset(db: Session, user: User, asset_id: str | uuid.UUID, kind: str | None = None) -> MetaAsset:
    try:
        asset = db.get(MetaAsset, uuid.UUID(str(asset_id)))
    except ValueError:
        asset = None
    if asset is None or asset.user_id != user.id or (kind and asset.kind != kind):
        raise AssetNotFound(f"{(kind or 'account').replace('_', ' ').title()} not found.")
    return asset


def default_instagram_asset(db: Session, user: User) -> MetaAsset:
    asset = db.scalar(select(MetaAsset).where(
        MetaAsset.user_id == user.id, MetaAsset.kind == "instagram_account"
    ).order_by(MetaAsset.is_selected.desc(), MetaAsset.created_at))
    if asset is None:
        raise AssetNotFound("Connect a Facebook account with a linked Instagram professional account first.")
    return asset


def _page_token_for(db: Session, asset: MetaAsset) -> str | None:
    if asset.kind == "facebook_page":
        return decrypt(asset.page_token_enc) if asset.page_token_enc else None
    page = db.scalar(select(MetaAsset).where(
        MetaAsset.connection_id == asset.connection_id,
        MetaAsset.kind == "facebook_page",
        MetaAsset.external_id == asset.page_external_id,
    ))
    return decrypt(page.page_token_enc) if page and page.page_token_enc else None


def client_for_asset(db: Session, asset: MetaAsset) -> tuple[GraphClient | MockGraphClient, str | None]:
    """Return (client, page_token). Instagram calls use the linked Page token when available,
    because Page tokens derived from a long-lived user token do not expire."""
    connection = asset.connection
    if connection.status == "expired" and not connection.is_mock:
        raise TokenExpiredError("Facebook access expired. Reconnect your Facebook account.")
    if not connection.is_mock and not config.meta_configured():
        raise RuntimeError("This connection uses the real Meta API, but META_APP_ID/META_APP_SECRET are not set.")
    page_token = _page_token_for(db, asset)
    token = page_token or decrypt(connection.access_token_enc)
    # Mock clients are seeded by the token, so synced demo posts match the demo accounts' niche.
    return client_for_token(token, connection.is_mock), page_token


def mark_expired(db: Session, asset: MetaAsset, error: Exception) -> None:
    asset.connection.status = "expired"
    asset.connection.last_error = str(error)
    db.flush()


def connection_dict(connection: MetaConnection) -> dict[str, Any]:
    expired = bool(connection.token_expires_at and connection.token_expires_at <= datetime.now(timezone.utc))
    return {
        "id": str(connection.id),
        "fb_user_name": connection.fb_user_name,
        "status": "expired" if expired and connection.status == "active" else connection.status,
        "is_mock": connection.is_mock,
        "scopes": connection.scopes or [],
        "token_expires_at": connection.token_expires_at,
        "last_error": connection.last_error,
        "created_at": connection.created_at,
        "assets": [asset_dict(a) for a in sorted(connection.assets, key=lambda a: (a.kind != "instagram_account", a.name))],
    }


def asset_dict(asset: MetaAsset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "kind": asset.kind,
        "external_id": asset.external_id,
        "name": asset.name,
        "username": asset.username,
        "picture_url": asset.picture_url,
        "followers_count": asset.followers_count,
        "is_selected": asset.is_selected,
        "sync_status": asset.sync_status,
        "last_synced_at": asset.last_synced_at,
        "last_error": asset.last_error,
    }
