"""Hashtag research and competitor lookups (both run as the user's own IG account)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.content import index_and_classify, item_dict, upsert_posts
from app.services.meta_accounts import client_for_asset, mark_expired
from common.meta import TokenExpiredError
from common.models import HashtagSearch, MetaAsset, User
from common.text import normalize_hashtag, normalize_username

HASHTAG_LIMIT = 30  # unique hashtags per IG account per rolling 7 days (Instagram rule)
HASHTAG_WINDOW = timedelta(days=7)


class QuotaExceeded(RuntimeError):
    pass


def hashtag_quota(db: Session, asset: MetaAsset) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - HASHTAG_WINDOW
    used = db.scalars(
        select(HashtagSearch.hashtag).where(HashtagSearch.ig_user_id == asset.external_id, HashtagSearch.searched_at >= since)
        .group_by(HashtagSearch.hashtag)
    ).all()
    return {"ig_account": asset.username, "used": len(used), "limit": HASHTAG_LIMIT,
            "remaining": max(0, HASHTAG_LIMIT - len(used)), "hashtags": sorted(used)}


def research_hashtag(
    db: Session, user: User, asset: MetaAsset, hashtag: str, edge: str = "top_media", limit: int = 25
) -> dict[str, Any]:
    hashtag = normalize_hashtag(hashtag)
    if edge not in ("top_media", "recent_media"):
        raise ValueError("edge must be top_media or recent_media")
    quota = hashtag_quota(db, asset)
    if hashtag not in quota["hashtags"] and quota["remaining"] <= 0:
        raise QuotaExceeded(
            f"Instagram allows {HASHTAG_LIMIT} unique hashtag searches per account every 7 days; "
            f"@{asset.username} has used them all. Re-searching an already used hashtag is still allowed."
        )
    client, _ = client_for_asset(db, asset)
    try:
        hashtag_id = client.hashtag_id(asset.external_id, hashtag)
        posts = client.hashtag_media(asset.external_id, hashtag_id, hashtag, edge, limit)
    except TokenExpiredError as exc:
        mark_expired(db, asset, exc)
        raise
    db.add(HashtagSearch(user_id=user.id, ig_user_id=asset.external_id, hashtag=hashtag, hashtag_external_id=hashtag_id))
    items = upsert_posts(db, user.id, posts, source="hashtag", query=hashtag)
    stats = index_and_classify(db, items)
    return {"hashtag": hashtag, "edge": edge, "posts": [item_dict(i) for i in items], **stats,
            "quota": hashtag_quota(db, asset)}


def research_competitor(db: Session, user: User, asset: MetaAsset, username: str, limit: int = 25) -> dict[str, Any]:
    """business_discovery: only public Instagram Business/Creator accounts can be read."""
    username = normalize_username(username)
    client, _ = client_for_asset(db, asset)
    try:
        result = client.business_discovery(asset.external_id, username, limit)
    except TokenExpiredError as exc:
        mark_expired(db, asset, exc)
        raise
    items = upsert_posts(db, user.id, result["media"], source="competitor", query=username)
    stats = index_and_classify(db, items)
    return {"username": username, "profile": result["profile"], "posts": [item_dict(i) for i in items], **stats}


def hashtag_leaderboard(db: Session, user: User, limit: int = 20) -> list[dict[str, Any]]:
    """The user's own hashtags ranked by average engagement."""
    from common.models import ContentItem

    rows = db.execute(
        select(
            func.unnest(ContentItem.hashtags).label("tag"),
            ContentItem.like_count, ContentItem.comments_count, ContentItem.shares_count,
        ).where(ContentItem.user_id == user.id, ContentItem.source == "own")
    ).all()
    buckets: dict[str, list[int]] = {}
    for tag, likes, comments, shares in rows:
        if likes is None:
            continue
        buckets.setdefault(tag, []).append(likes + (comments or 0) + (shares or 0))
    ranked = [{"hashtag": t, "posts": len(v), "avg_engagement": round(sum(v) / len(v))} for t, v in buckets.items()]
    ranked.sort(key=lambda r: (r["avg_engagement"], r["posts"]), reverse=True)
    return ranked[:limit]
