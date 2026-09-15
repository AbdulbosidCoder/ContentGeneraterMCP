"""Hashtag research & suggestions, competitor lookups, Ads Library search."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import AdsSearchRequest, CompetitorRequest, HashtagResearchRequest, HashtagSuggestRequest
from app.services.content import item_dict
from app.services.meta_accounts import AssetNotFound, client_for_asset, default_instagram_asset, get_asset
from app.services.research import hashtag_quota, research_competitor, research_hashtag
from common.models import ContentItem, MetaAsset, User
from rag.hashtags import suggest_hashtags

router = APIRouter(tags=["research"])


def _ig_asset(db: Session, user: User, asset_id: str | None) -> MetaAsset:
    return get_asset(db, user, asset_id, "instagram_account") if asset_id else default_instagram_asset(db, user)


@router.get("/hashtags/quota")
def quota(asset_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    return hashtag_quota(db, _ig_asset(db, user, asset_id))


@router.post("/hashtags/research")
def hashtag_research(body: HashtagResearchRequest, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = _ig_asset(db, user, body.asset_id)
    return research_hashtag(db, user, asset, body.hashtag, body.edge, body.limit)


@router.post("/hashtags/suggest")
def hashtag_suggest(body: HashtagSuggestRequest, user: User = Depends(current_user)) -> dict:
    return {"caption": body.caption, **suggest_hashtags(body.caption, str(user.id), body.count)}


@router.get("/hashtags/missing")
def posts_missing_hashtags(limit: int = 5, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    """The user's own posts published without hashtags, each with suggested hashtags."""
    base = select(ContentItem).where(
        ContentItem.user_id == user.id, ContentItem.source == "own", func.cardinality(ContentItem.hashtags) == 0
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(ContentItem.published_at.desc().nulls_last()).limit(min(limit, 10))).all()
    return {
        "total": total,
        "posts": [{"post": item_dict(item), **suggest_hashtags(item.caption, str(user.id), 8)} for item in items],
    }


@router.post("/competitors/research")
def competitor_research(body: CompetitorRequest, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = _ig_asset(db, user, body.asset_id)
    return research_competitor(db, user, asset, body.username, body.limit)


@router.post("/ads/search")
def ads_search(body: AdsSearchRequest, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")) -> dict:
    asset = db.scalar(select(MetaAsset).where(MetaAsset.user_id == user.id).order_by(MetaAsset.created_at))
    if asset is None:
        raise AssetNotFound("Connect a Facebook account first; the Ads Library is queried with your access.")
    client, _ = client_for_asset(db, asset)
    ads = client.ads_archive(body.search_terms, body.country.upper(), body.limit)
    return {"search_terms": body.search_terms, "country": body.country.upper(), "ads": ads,
            "note": "Outside the EU/UK the Ads Library API only returns social issue, electoral or political ads."}
