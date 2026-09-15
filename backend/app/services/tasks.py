"""Background tasks executed by the worker: syncing, classification/clustering, publishing."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.services.content import index_and_classify, item_dict, upsert_posts
from app.services.jobs import enqueue
from app.services.meta_accounts import client_for_asset, mark_expired
from common.meta import TokenExpiredError
from common.models import ContentCluster, ContentItem, MetaAsset, PublishedPost, utcnow
from rag.classification import classify_items, cluster_items
from rag.vectorstore import ContentStore

logger = logging.getLogger("worker.tasks")

SYNC_LIMIT = 100


def sync_asset(db: Session, user_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    asset = db.get(MetaAsset, uuid.UUID(payload["asset_id"]))
    if asset is None or asset.user_id != user_id:
        return {"skipped": "asset no longer exists"}
    asset.sync_status = "syncing"
    db.commit()
    try:
        client, page_token = client_for_asset(db, asset)
        if asset.kind == "instagram_account":
            posts = client.ig_media(asset.external_id, SYNC_LIMIT)
        else:
            if not page_token:
                raise RuntimeError("No Page access token; reconnect Facebook and grant Page access.")
            posts = client.page_posts(asset.external_id, page_token, SYNC_LIMIT)
        items = upsert_posts(db, user_id, posts, source="own", asset=asset)
        stats = index_and_classify(db, items, classify=False)
        asset.sync_status, asset.last_synced_at, asset.last_error = "ok", utcnow(), None
        enqueue(db, user_id, "classify", {})
        return {"asset": asset.name, "fetched": len(posts), **stats}
    except TokenExpiredError as exc:
        mark_expired(db, asset, exc)
        asset.sync_status, asset.last_error = "error", str(exc)
        db.commit()
        raise
    except Exception as exc:
        db.rollback()
        asset = db.get(MetaAsset, uuid.UUID(payload["asset_id"]))
        if asset:
            asset.sync_status, asset.last_error = "error", str(exc)[:1000]
            db.commit()
        raise


def classify_user(db: Session, user_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """Label unlabeled posts, then re-cluster the user's own posts (all posts if too few)."""
    items = list(db.scalars(select(ContentItem).where(ContentItem.user_id == user_id)))
    if not items:
        return {"classified": 0, "clusters": 0}
    store = ContentStore()

    pending = [item for item in items if not item.content_types or payload.get("force")]
    results = classify_items([item_dict(i) for i in pending], embedder=store.embedder)
    for item in pending:
        if str(item.id) in results:
            item.content_types = results[str(item.id)]["content_types"]
            item.content_type_scores = results[str(item.id)]["scores"]
    db.flush()

    own = [item for item in items if item.source == "own"]
    population = own if len(own) >= 6 else items
    embeddings = store.embeddings_for([str(i.id) for i in population])
    missing = [i for i in population if str(i.id) not in embeddings]
    if missing:  # e.g. the embedding provider changed since indexing
        index_and_classify(db, missing, classify=False)
        embeddings = store.embeddings_for([str(i.id) for i in population])

    clusters = cluster_items([item_dict(i) for i in population], embeddings)
    db.execute(delete(ContentCluster).where(ContentCluster.user_id == user_id))  # sets item.cluster_id NULL
    by_id = {str(i.id): i for i in items}
    for item in items:
        item.cluster_id = None
    for cluster in clusters:
        row = ContentCluster(user_id=user_id, label=cluster["label"][:120], description=cluster["description"],
                             keywords=cluster["keywords"], size=len(cluster["member_ids"]),
                             avg_engagement=cluster["avg_engagement"])
        db.add(row)
        db.flush()
        for member in cluster["member_ids"]:
            by_id[member].cluster_id = row.id
    db.commit()  # don't hold row locks while talking to the vector store

    store.update_labels({
        str(i.id): {"content_types": i.content_types or [], "cluster_id": str(i.cluster_id) if i.cluster_id else ""}
        for i in items
    })
    return {"classified": len(results), "clusters": len(clusters), "clustered_posts": len(embeddings)}


def publish_post(db: Session, user_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    post = db.get(PublishedPost, uuid.UUID(payload["post_id"]))
    if post is None or post.user_id != user_id:
        return {"skipped": "post no longer exists"}
    asset = db.get(MetaAsset, post.asset_id)
    post.status = "publishing"
    db.commit()
    try:
        client, page_token = client_for_asset(db, asset)
        if asset.kind == "instagram_account":
            result = client.ig_publish(asset.external_id, post.caption, post.media_type, post.media_url or "")
        else:
            if not page_token:
                raise RuntimeError("No Page access token; reconnect Facebook and grant Page access.")
            result = client.page_publish(asset.external_id, page_token, post.caption,
                                         image_url=post.media_url, link=post.link_url)
        post.status, post.external_id, post.permalink = "published", result["id"], result.get("permalink")
        post.is_mock, post.published_at, post.error = client.is_mock, datetime.now(timezone.utc), None
        enqueue(db, user_id, "sync_asset", {"asset_id": str(asset.id)})
        return {"external_id": post.external_id, "permalink": post.permalink}
    except Exception as exc:
        db.rollback()
        post = db.get(PublishedPost, uuid.UUID(payload["post_id"]))
        if isinstance(exc, TokenExpiredError):
            mark_expired(db, asset, exc)
        post.status, post.error = "failed", str(exc)[:1000]
        db.commit()
        raise


HANDLERS = {"sync_asset": sync_asset, "classify": classify_user, "publish": publish_post}
