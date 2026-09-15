"""Media uploads and publishing to Instagram / Facebook Pages."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import PublishRequest
from app.services.jobs import enqueue
from app.services.meta_accounts import client_for_asset, get_asset
from common import config
from common.models import PublishedPost, User

router = APIRouter(tags=["publish"])

ALLOWED_MEDIA = {"image/jpeg": ".jpg", "image/png": ".png", "video/mp4": ".mp4", "video/quicktime": ".mov"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.post("/media")
async def upload_media(file: UploadFile = File(...), user: User = Depends(current_user)) -> dict:
    """Store an upload under /media so Meta can fetch it. Meta needs a public HTTPS URL."""
    extension = ALLOWED_MEDIA.get(file.content_type or "")
    if not extension:
        raise HTTPException(415, "Upload a JPEG/PNG image or an MP4/MOV video.")
    target_dir = Path(config.media_dir())
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{extension}"
    size = 0
    with (target_dir / name).open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                (target_dir / name).unlink(missing_ok=True)
                raise HTTPException(413, "File is larger than 100 MB.")
            out.write(chunk)
    url = f"{config.public_base_url()}/media/{name}"
    public = config.public_base_url().startswith("https://") and "localhost" not in config.public_base_url()
    return {"url": url, "media_type": "REELS" if extension in (".mp4", ".mov") else "IMAGE", "publicly_reachable": public}


def post_dict(post: PublishedPost) -> dict:
    return {
        "id": str(post.id), "asset_id": str(post.asset_id), "platform": post.platform, "media_type": post.media_type,
        "caption": post.caption, "media_url": post.media_url, "link_url": post.link_url, "status": post.status,
        "external_id": post.external_id, "permalink": post.permalink, "error": post.error, "is_mock": post.is_mock,
        "created_at": post.created_at, "published_at": post.published_at,
    }


@router.post("/posts")
def create_post(body: PublishRequest, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = get_asset(db, user, body.asset_id)
    if asset.kind == "instagram_account":
        if body.media_type == "TEXT" or not body.media_url:
            raise HTTPException(422, "Instagram posts need an image or video (media_url).")
    elif body.media_type == "REELS":
        raise HTTPException(422, "Publishing videos to Facebook Pages isn't supported here; use an image or text post.")
    if body.media_type == "TEXT" and not (body.caption.strip() or body.link_url):
        raise HTTPException(422, "A text post needs a message or a link.")
    post = PublishedPost(
        user_id=user.id, asset_id=asset.id, platform="instagram" if asset.kind == "instagram_account" else "facebook",
        media_type=body.media_type, caption=body.caption, media_url=body.media_url if body.media_type != "TEXT" else None,
        link_url=body.link_url, is_mock=asset.connection.is_mock,
    )
    db.add(post)
    db.flush()
    enqueue(db, user.id, "publish", {"post_id": str(post.id)})
    return post_dict(post)


@router.get("/posts")
def list_posts(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    posts = db.scalars(select(PublishedPost).where(PublishedPost.user_id == user.id)
                       .order_by(PublishedPost.created_at.desc()).limit(50)).all()
    return {"posts": [post_dict(p) for p in posts]}


@router.get("/assets/{asset_id}/publishing-limit")
def publishing_limit(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = get_asset(db, user, asset_id, "instagram_account")
    client, _ = client_for_asset(db, asset)
    return client.ig_publishing_limit(asset.external_id)
