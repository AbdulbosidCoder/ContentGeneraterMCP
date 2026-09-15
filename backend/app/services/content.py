"""Storing posts in PostgreSQL and indexing them into the vector store."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.models import ContentItem, MetaAsset, utcnow
from rag.classification import classify_items
from rag.ingestion import index_items
from rag.vectorstore import ContentStore, engagement


def _parse_time(value: Any) -> datetime | None:
    if not value or isinstance(value, datetime):
        return value or None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def upsert_posts(
    db: Session,
    user_id: uuid.UUID,
    posts: list[dict[str, Any]],
    source: str,
    asset: MetaAsset | None = None,
    query: str | None = None,
) -> list[ContentItem]:
    if not posts:
        return []
    platform_ids = {(post["platform"], str(post["external_id"])) for post in posts}
    existing = {
        (item.platform, item.external_id): item
        for item in db.scalars(select(ContentItem).where(
            ContentItem.user_id == user_id,
            ContentItem.source == source,
            ContentItem.external_id.in_([pid for _, pid in platform_ids]),
        ))
    }
    items = []
    for post in posts:
        key = (post["platform"], str(post["external_id"]))
        item = existing.get(key)
        if item is None:
            item = ContentItem(user_id=user_id, source=source, platform=post["platform"], external_id=key[1])
            db.add(item)
            existing[key] = item
        item.asset_id = asset.id if asset else item.asset_id
        item.author = post.get("author") or (asset.username if asset else None)
        caption_changed = item.caption != (post.get("caption") or "")
        item.caption = post.get("caption") or ""
        item.hashtags = post.get("hashtags") or []
        item.media_type = post.get("media_type") or "UNKNOWN"
        item.media_url = post.get("media_url")
        item.permalink = post.get("permalink")
        item.published_at = _parse_time(post.get("published_at"))
        item.like_count = post.get("like_count")
        item.comments_count = post.get("comments_count")
        item.shares_count = post.get("shares_count")
        item.insights = post.get("insights") or item.insights or {}
        item.query = query
        item.is_mock = bool(post.get("is_mock"))
        item.fetched_at = utcnow()
        if caption_changed:
            item.content_types = []  # re-classify edited captions
        items.append(item)
    db.flush()
    return items


def item_dict(item: ContentItem) -> dict[str, Any]:
    data = {
        "id": str(item.id),
        "user_id": str(item.user_id),
        "asset_id": str(item.asset_id) if item.asset_id else None,
        "source": item.source,
        "platform": item.platform,
        "external_id": item.external_id,
        "author": item.author,
        "caption": item.caption,
        "hashtags": item.hashtags or [],
        "media_type": item.media_type,
        "media_url": item.media_url,
        "permalink": item.permalink,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "like_count": item.like_count,
        "comments_count": item.comments_count,
        "shares_count": item.shares_count,
        "insights": item.insights or {},
        "content_types": item.content_types or [],
        "cluster_id": str(item.cluster_id) if item.cluster_id else None,
        "query": item.query,
        "is_mock": item.is_mock,
    }
    data["engagement"] = engagement(data)
    return data


def index_and_classify(db: Session, items: list[ContentItem], classify: bool = True) -> dict[str, int]:
    """Embed items into Chroma and (optionally) label their content types right away."""
    if not items:
        return {"indexed": 0, "classified": 0}
    store = ContentStore()
    classified = 0
    if classify:
        pending = [item for item in items if not item.content_types]
        results = classify_items([item_dict(item) for item in pending], embedder=store.embedder)
        for item in pending:
            result = results.get(str(item.id))
            if result:
                item.content_types = result["content_types"]
                item.content_type_scores = result["scores"]
                classified += 1
        db.flush()
    indexed = index_items([item_dict(item) for item in items], store=store)
    return {"indexed": indexed, "classified": classified}
