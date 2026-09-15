"""Real Graph API client for one access token (a user's, or one of their Page tokens).

Every method returns plain dicts. Posts are normalized to the same shape for
Instagram and Facebook::

    {external_id, platform, author, caption, hashtags, media_type, media_url,
     permalink, published_at, like_count, comments_count, shares_count, insights, is_mock}
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from common import config
from common.text import extract_hashtags

logger = logging.getLogger("common.meta.graph")

GRAPH_URL = "https://graph.facebook.com"
IG_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,"
    "like_count,comments_count,username"
)
IG_PROFILE_FIELDS = "id,username,name,biography,website,profile_picture_url,followers_count,follows_count,media_count"
PAGE_POST_FIELDS = (
    "id,message,created_time,permalink_url,full_picture,status_type,shares,"
    "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)"
)
ADS_FIELDS = (
    "id,page_id,page_name,ad_creation_time,ad_delivery_start_time,ad_delivery_stop_time,"
    "ad_creative_bodies,ad_creative_link_titles,ad_snapshot_url,publisher_platforms,languages"
)
# Media insight metrics change between API versions; fall back to a minimal set.
IG_INSIGHT_METRICS = ["reach", "saved", "shares", "total_interactions", "views"]
IG_INSIGHT_FALLBACK = ["reach", "saved"]
_TOKEN_ERROR_CODES = {190, 102}
_RATE_LIMIT_CODES = {4, 17, 32, 613}


class GraphAPIError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None, status: int = 0):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.status = status


class TokenExpiredError(GraphAPIError):
    """The access token is invalid or expired; the user must reconnect Facebook."""


class GraphClient:
    is_mock = False

    def __init__(self, access_token: str, timeout: float = 30.0) -> None:
        self.access_token = access_token
        self.timeout = timeout

    # ---------------------------------------------------------------- transport
    def _auth_params(self, token: str | None = None) -> dict[str, str]:
        token = token or self.access_token
        params = {"access_token": token}
        secret = config.env("META_APP_SECRET")
        if secret:
            params["appsecret_proof"] = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        return params

    def request(
        self, method: str, path: str, params: dict[str, Any] | None = None, token: str | None = None
    ) -> dict[str, Any]:
        url = f"{GRAPH_URL}/{config.graph_api_version()}/{path.lstrip('/')}"
        all_params = {**(params or {}), **self._auth_params(token)}
        with httpx.Client(timeout=self.timeout) as client:
            if method == "GET":
                response = client.get(url, params=all_params)
            else:
                response = client.request(method, url, data=all_params)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.is_error or (isinstance(payload, dict) and "error" in payload):
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code, subcode = error.get("code"), error.get("error_subcode")
            message = error.get("message") or response.text[:300]
            if code in _TOKEN_ERROR_CODES:
                raise TokenExpiredError(f"Facebook token invalid or expired: {message}", code, subcode, response.status_code)
            if code in _RATE_LIMIT_CODES:
                message = f"Meta API rate limit reached, try again later ({message})"
            raise GraphAPIError(f"Graph API error {code}/{subcode}: {message}", code, subcode, response.status_code)
        return payload

    def get(self, path: str, params: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
        return self.request("GET", path, params, token)

    def _paginate(self, path: str, params: dict[str, Any], limit: int, token: str | None = None) -> list[dict]:
        items: list[dict] = []
        after = None
        while len(items) < limit:
            page_params = {**params, "limit": min(50, limit - len(items))}
            if after:
                page_params["after"] = after
            payload = self.get(path, page_params, token)
            batch = payload.get("data") or []
            items.extend(batch)
            paging = payload.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not batch or not after or not paging.get("next"):
                break
        return items[:limit]

    # --------------------------------------------------------------- identity
    def me(self) -> dict[str, Any]:
        """id and name; email/picture only if granted (Graph omits fields without permission)."""
        data = self.get("me", {"fields": "id,name,email,picture{url}"})
        data["picture_url"] = ((data.pop("picture", None) or {}).get("data") or {}).get("url")
        return data

    def list_pages(self) -> list[dict[str, Any]]:
        fields = (
            "id,name,access_token,picture{url},followers_count,"
            "instagram_business_account{id,username,name,profile_picture_url,followers_count}"
        )
        pages = self._paginate("me/accounts", {"fields": fields}, 200)
        return [{
            "id": page["id"],
            "name": page.get("name", ""),
            "access_token": page.get("access_token"),
            "picture_url": ((page.get("picture") or {}).get("data") or {}).get("url"),
            "followers_count": page.get("followers_count"),
            "instagram": page.get("instagram_business_account"),
        } for page in pages]

    # -------------------------------------------------------------- instagram
    def ig_account(self, ig_user_id: str) -> dict[str, Any]:
        return self.get(ig_user_id, {"fields": IG_PROFILE_FIELDS})

    def ig_media(self, ig_user_id: str, limit: int = 50, with_insights: bool = True) -> list[dict[str, Any]]:
        media = self._paginate(f"{ig_user_id}/media", {"fields": IG_MEDIA_FIELDS}, limit)
        posts = [_normalize_ig(item, "instagram") for item in media]
        if with_insights:
            for post in posts:
                post["insights"] = self.ig_media_insights(post["external_id"])
        return posts

    def ig_media_insights(self, media_id: str) -> dict[str, Any]:
        for metrics in (IG_INSIGHT_METRICS, IG_INSIGHT_FALLBACK):
            try:
                payload = self.get(f"{media_id}/insights", {"metric": ",".join(metrics)})
                return _parse_insights(payload)
            except TokenExpiredError:
                raise
            except GraphAPIError as exc:
                logger.debug("Insights %s for %s failed: %s", metrics, media_id, exc)
        return {}

    def business_discovery(self, ig_user_id: str, username: str, limit: int = 25) -> dict[str, Any]:
        """Public Business/Creator accounts only; queried as the user's own IG account."""
        fields = (
            f"business_discovery.username({username})"
            "{id,username,name,biography,followers_count,media_count,profile_picture_url,"
            f"media.limit({min(limit, 50)}){{id,caption,media_type,media_product_type,permalink,timestamp,"
            "like_count,comments_count}}"
        )
        payload = self.get(ig_user_id, {"fields": fields})
        discovery = payload.get("business_discovery") or {}
        media = (discovery.pop("media", None) or {}).get("data") or []
        posts = [_normalize_ig({**item, "username": username}, "instagram") for item in media]
        return {"profile": discovery, "media": posts}

    def hashtag_id(self, ig_user_id: str, hashtag: str) -> str:
        payload = self.get("ig_hashtag_search", {"user_id": ig_user_id, "q": hashtag})
        data = payload.get("data") or []
        if not data:
            raise GraphAPIError(f"Instagram has no hashtag #{hashtag}.")
        return data[0]["id"]

    def hashtag_media(
        self, ig_user_id: str, hashtag_id: str, hashtag: str, edge: str = "top_media", limit: int = 25
    ) -> list[dict[str, Any]]:
        fields = "id,caption,media_type,permalink,timestamp,like_count,comments_count"
        media = self._paginate(f"{hashtag_id}/{edge}", {"user_id": ig_user_id, "fields": fields}, limit)
        return [_normalize_ig(item, "instagram") for item in media]

    def ig_publishing_limit(self, ig_user_id: str) -> dict[str, Any]:
        payload = self.get(f"{ig_user_id}/content_publishing_limit", {"fields": "config,quota_usage"})
        data = (payload.get("data") or [{}])[0]
        return {"quota_usage": data.get("quota_usage"), "quota_total": (data.get("config") or {}).get("quota_total")}

    def ig_publish(self, ig_user_id: str, caption: str, media_type: str, media_url: str) -> dict[str, Any]:
        params: dict[str, Any] = {"caption": caption}
        if media_type == "REELS":
            params.update(media_type="REELS", video_url=media_url)
        else:
            params["image_url"] = media_url
        container_id = self.request("POST", f"{ig_user_id}/media", params)["id"]

        deadline = time.monotonic() + 600
        while True:  # videos are processed asynchronously; images are usually FINISHED at once
            status = self.get(container_id, {"fields": "status_code,status"})
            code = status.get("status_code")
            if code in (None, "FINISHED"):
                break
            if code in ("ERROR", "EXPIRED"):
                raise GraphAPIError(f"Instagram could not process the media: {status.get('status')}")
            if time.monotonic() > deadline:
                raise GraphAPIError("Instagram media processing timed out.")
            time.sleep(5)

        media_id = self.request("POST", f"{ig_user_id}/media_publish", {"creation_id": container_id})["id"]
        permalink = self.get(media_id, {"fields": "permalink"}).get("permalink")
        return {"id": media_id, "permalink": permalink}

    # ----------------------------------------------------------- facebook pages
    def page_posts(self, page_id: str, page_token: str, limit: int = 50) -> list[dict[str, Any]]:
        posts = self._paginate(f"{page_id}/posts", {"fields": PAGE_POST_FIELDS}, limit, token=page_token)
        return [_normalize_page_post(post) for post in posts]

    def page_publish(
        self, page_id: str, page_token: str, message: str, image_url: str | None = None, link: str | None = None
    ) -> dict[str, Any]:
        if image_url:
            result = self.request("POST", f"{page_id}/photos", {"url": image_url, "message": message}, token=page_token)
            post_id = result.get("post_id") or result["id"]
        else:
            params = {"message": message, **({"link": link} if link else {})}
            post_id = self.request("POST", f"{page_id}/feed", params, token=page_token)["id"]
        permalink = self.get(post_id, {"fields": "permalink_url"}, token=page_token).get("permalink_url")
        return {"id": post_id, "permalink": permalink}

    # -------------------------------------------------------------- ads library
    def ads_archive(self, search_terms: str, country: str, limit: int = 20) -> list[dict[str, Any]]:
        params = {
            "search_terms": search_terms,
            "ad_reached_countries": json.dumps([country]),
            "ad_active_status": "ALL",
            "fields": ADS_FIELDS,
            "limit": limit,
        }
        return (self.get("ads_archive", params).get("data") or [])[:limit]


def _parse_insights(payload: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for metric in payload.get("data") or []:
        value = (metric.get("total_value") or {}).get("value")
        if value is None and metric.get("values"):
            value = metric["values"][0].get("value")
        result[metric.get("name")] = value
    return result


def _normalize_ig(item: dict[str, Any], platform: str) -> dict[str, Any]:
    caption = item.get("caption") or ""
    media_type = item.get("media_type") or "UNKNOWN"
    if item.get("media_product_type") == "REELS":
        media_type = "REELS"
    return {
        "external_id": item["id"],
        "platform": platform,
        "author": item.get("username"),
        "caption": caption,
        "hashtags": extract_hashtags(caption),
        "media_type": media_type,
        "media_url": item.get("thumbnail_url") or item.get("media_url"),
        "permalink": item.get("permalink"),
        "published_at": item.get("timestamp"),
        "like_count": item.get("like_count"),  # omitted when the owner hides likes
        "comments_count": item.get("comments_count"),
        "shares_count": None,
        "insights": {},
        "is_mock": False,
    }


def _normalize_page_post(post: dict[str, Any]) -> dict[str, Any]:
    message = post.get("message") or ""
    status_type = post.get("status_type") or ""
    media_type = "VIDEO" if "video" in status_type else ("IMAGE" if post.get("full_picture") else "TEXT")
    return {
        "external_id": post["id"],
        "platform": "facebook",
        "author": None,
        "caption": message,
        "hashtags": extract_hashtags(message),
        "media_type": media_type,
        "media_url": post.get("full_picture"),
        "permalink": post.get("permalink_url"),
        "published_at": post.get("created_time"),
        "like_count": ((post.get("reactions") or {}).get("summary") or {}).get("total_count"),
        "comments_count": ((post.get("comments") or {}).get("summary") or {}).get("total_count"),
        "shares_count": (post.get("shares") or {}).get("count", 0),
        "insights": {},
        "is_mock": False,
    }
