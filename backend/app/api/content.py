"""Content library: synced posts, content-type and cluster overview, semantic search."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import ClassifyRequest
from app.services.content import item_dict
from app.services.jobs import enqueue, job_dict
from app.services.research import hashtag_leaderboard
from common.models import ContentCluster, ContentItem, User
from rag.classification import CONTENT_TYPES
from rag.retrieval import retrieve_similar_content
from rag.vectorstore import engagement

router = APIRouter(prefix="/content", tags=["content"])


@router.get("")
def list_content(
    source: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    cluster_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=200),
    missing_hashtags: bool = False,
    sort: str = "recent",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
) -> dict:
    stmt = select(ContentItem).where(ContentItem.user_id == user.id)
    if source:
        stmt = stmt.where(ContentItem.source == source)
    if platform:
        stmt = stmt.where(ContentItem.platform == platform)
    if content_type:
        stmt = stmt.where(ContentItem.content_types.any(content_type))
    if cluster_id:
        stmt = stmt.where(ContentItem.cluster_id == cluster_id)
    if asset_id:
        stmt = stmt.where(ContentItem.asset_id == asset_id)
    if q:
        pattern = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(ContentItem.caption.ilike(pattern), ContentItem.author.ilike(pattern)))
    if missing_hashtags:
        stmt = stmt.where(func.cardinality(ContentItem.hashtags) == 0)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {
        "recent": ContentItem.published_at.desc().nulls_last(),
        "likes": ContentItem.like_count.desc().nulls_last(),
        "comments": ContentItem.comments_count.desc().nulls_last(),
    }.get(sort, ContentItem.published_at.desc().nulls_last())
    items = db.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()
    return {"total": total, "items": [item_dict(i) for i in items]}


@router.get("/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    items = db.scalars(select(ContentItem).where(ContentItem.user_id == user.id)).all()
    by_source: dict[str, int] = defaultdict(int)
    types: dict[str, list[int | None]] = defaultdict(list)
    unclassified = 0
    for item in items:
        by_source[item.source] += 1
        if item.source != "own":
            continue
        data = item_dict(item)
        if not item.content_types:
            unclassified += 1
        for ctype in item.content_types or []:
            types[ctype].append(engagement(data))

    content_types = []
    for name, scores in types.items():
        known = [s for s in scores if s is not None]
        content_types.append({"content_type": name, "posts": len(scores),
                              "avg_engagement": round(sum(known) / len(known)) if known else None})
    content_types.sort(key=lambda r: (r["avg_engagement"] or 0), reverse=True)

    clusters = db.scalars(select(ContentCluster).where(ContentCluster.user_id == user.id)
                          .order_by(ContentCluster.avg_engagement.desc().nulls_last())).all()
    return {
        "totals": {"all": len(items), **by_source},
        "unclassified_own": unclassified,
        "content_types": content_types,
        "taxonomy": CONTENT_TYPES,
        "clusters": [{"id": str(c.id), "label": c.label, "description": c.description, "keywords": c.keywords,
                      "size": c.size, "avg_engagement": c.avg_engagement} for c in clusters],
        "top_hashtags": hashtag_leaderboard(db, user),
    }


@router.post("/classify")
def classify(body: ClassifyRequest, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    return job_dict(enqueue(db, user.id, "classify", {"force": True} if body.force else {}))


@router.get("/search")
def semantic_search(
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(8, ge=1, le=30),
    source: list[str] | None = Query(None),
    content_type: str | None = None,
    user: User = Depends(current_user),
) -> dict:
    results = retrieve_similar_content(q, n, str(user.id), sources=source, content_type=content_type)
    return {"query": q, "results": results}
