"""MCP server for content-ai-generator, protected per user.

Two ways to authenticate, both resolving to one user:
- OAuth: an MCP client (Claude, Claude Code, ...) discovers the authorization server via
  /.well-known/oauth-protected-resource/mcp, the user signs in and approves access.
- Personal token: the connector URL carries it, {MCP_PUBLIC_URL}/mcp?token=mcp_...
  (created in the MCP tab). It is moved into the Authorization header before auth runs.

Every tool call then runs as that user against their own connected Instagram accounts
and Facebook Pages.

Run: ``python server.py`` (streamable-HTTP on MCP_SERVER_HOST:MCP_SERVER_PORT, path /mcp).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode

import uvicorn
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api_client import IntrospectionTokenVerifier, call_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mcp.server")

HOST = os.getenv("MCP_SERVER_HOST", "").strip() or "127.0.0.1"
PORT = int(os.getenv("MCP_SERVER_PORT", "").strip() or "8765")
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "").strip() or "http://localhost").rstrip("/")
MCP_PUBLIC_URL = (os.getenv("MCP_PUBLIC_URL", "").strip() or PUBLIC_BASE_URL).rstrip("/")

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
RESEARCH = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
PUBLISH = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

mcp = FastMCP(
    "content-ai-generator",
    instructions=(
        "Tools act on the signed-in user's own connected Instagram professional accounts and Facebook Pages. "
        "Start with list_my_accounts to get account ids. Results with is_mock=true are demo data. "
        "Always confirm the exact caption and media with the user before calling a publish tool."
    ),
    host=HOST,
    port=PORT,
    stateless_http=True,
    json_response=True,
    token_verifier=IntrospectionTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(PUBLIC_BASE_URL),
        resource_server_url=AnyHttpUrl(f"{MCP_PUBLIC_URL}/mcp"),
        required_scopes=["mcp"],
        validate_token_resource=True,
    ),
)


@mcp.tool(annotations=READ_ONLY)
async def list_my_accounts() -> dict[str, Any]:
    """List the user's connected Facebook logins with their Pages and Instagram accounts (ids, sync status)."""
    return await call_backend("GET", "/connections")


@mcp.tool(annotations=READ_ONLY)
async def get_content_overview() -> dict[str, Any]:
    """Summary of the user's synced content: counts, content types with average engagement,
    unsupervised topic clusters, and their best-performing hashtags."""
    return await call_backend("GET", "/content/overview")


@mcp.tool(annotations=READ_ONLY)
async def list_my_content(
    source: Literal["own", "competitor", "hashtag"] | None = "own",
    platform: Literal["instagram", "facebook"] | None = None,
    content_type: str | None = None,
    sort: Literal["recent", "likes", "comments"] = "recent",
    limit: int = 20,
) -> dict[str, Any]:
    """List synced posts with captions, metrics, insights and content-type labels.

    Args:
        source: own posts, competitor posts, or posts from hashtag research.
        platform: filter by platform.
        content_type: e.g. interactive, educational, promotional, party_event, critical_opinion.
        sort: order by recency, likes or comments.
        limit: 1-100.
    """
    params = {"source": source, "platform": platform, "content_type": content_type, "sort": sort, "limit": limit}
    return await call_backend("GET", "/content", params={k: v for k, v in params.items() if v})


@mcp.tool(annotations=READ_ONLY)
async def search_my_content(query: str, n: int = 8, content_type: str | None = None) -> dict[str, Any]:
    """Semantic search over the user's synced posts (own, competitor and hashtag research)."""
    params = {"q": query, "n": n, **({"content_type": content_type} if content_type else {})}
    return await call_backend("GET", "/content/search", params=params)


@mcp.tool(annotations=READ_ONLY)
async def generate_content_plan(topic: str, n_examples: int = 6) -> dict[str, Any]:
    """Generate 3 post ideas (format, content type, caption, hashtags, rationale) grounded in similar past posts."""
    return await call_backend("POST", "/plan", json={"topic": topic, "n_examples": n_examples})


@mcp.tool(annotations=READ_ONLY)
async def suggest_hashtags(caption: str, count: int = 10) -> dict[str, Any]:
    """Suggest hashtags for a draft caption, based on the user's similar well-performing posts."""
    return await call_backend("POST", "/hashtags/suggest", json={"caption": caption, "count": count})


@mcp.tool(annotations=RESEARCH)
async def research_hashtag(
    hashtag: str, edge: Literal["top_media", "recent_media"] = "top_media", ig_account_id: str | None = None
) -> dict[str, Any]:
    """Fetch top or recent public posts for a hashtag and add them to the user's research library.

    Instagram limits each account to 30 unique hashtags per rolling 7 days; the response includes the quota.
    """
    body = {"hashtag": hashtag, "edge": edge, **({"asset_id": ig_account_id} if ig_account_id else {})}
    return await call_backend("POST", "/hashtags/research", json=body)


@mcp.tool(annotations=RESEARCH)
async def research_competitor(username: str, limit: int = 25, ig_account_id: str | None = None) -> dict[str, Any]:
    """Fetch a public Instagram Business/Creator account's profile and recent posts (business_discovery).
    Private and personal accounts cannot be read."""
    body = {"username": username, "limit": limit, **({"asset_id": ig_account_id} if ig_account_id else {})}
    return await call_backend("POST", "/competitors/research", json=body)


@mcp.tool(annotations=READ_ONLY)
async def search_ads_library(search_terms: str, country: str = "US", limit: int = 20) -> dict[str, Any]:
    """Search the public Facebook Ads Library. Outside the EU/UK only social issue/political ads are returned."""
    return await call_backend("POST", "/ads/search", json={"search_terms": search_terms, "country": country, "limit": limit})


@mcp.tool(annotations=PUBLISH)
async def publish_instagram_post(
    ig_account_id: str, media_url: str, caption: str, media_type: Literal["IMAGE", "REELS"] = "IMAGE"
) -> dict[str, Any]:
    """Publish an image or Reel to one of the user's Instagram accounts. This posts publicly.

    Args:
        ig_account_id: the account id from list_my_accounts (kind=instagram_account).
        media_url: public HTTPS URL of a JPEG image or MP4 video that Instagram can download.
        caption: final caption including hashtags.
        media_type: IMAGE or REELS.
    """
    return await call_backend("POST", "/posts", json={
        "asset_id": ig_account_id, "media_url": media_url, "caption": caption, "media_type": media_type,
    })


@mcp.tool(annotations=PUBLISH)
async def publish_facebook_page_post(
    page_id: str, message: str, image_url: str | None = None, link_url: str | None = None
) -> dict[str, Any]:
    """Publish a text, link or photo post to one of the user's Facebook Pages. This posts publicly.

    Args:
        page_id: the account id from list_my_accounts (kind=facebook_page).
        message: post text.
        image_url: optional public HTTPS image URL (creates a photo post).
        link_url: optional link to attach (text posts only).
    """
    return await call_backend("POST", "/posts", json={
        "asset_id": page_id, "caption": message, "media_type": "IMAGE" if image_url else "TEXT",
        "media_url": image_url, "link_url": link_url,
    })


@mcp.tool(annotations=READ_ONLY)
async def get_publish_status() -> dict[str, Any]:
    """Recent publish requests and their status (pending, publishing, published, failed)."""
    return await call_backend("GET", "/posts")


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


class QueryTokenAuth:
    """Accepts ?token=... for clients that can only be given a URL: it becomes the bearer token.

    An explicit Authorization header wins, and the token is dropped from the query string.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and b"token=" in scope.get("query_string", b""):
            params = parse_qsl(scope["query_string"].decode("latin-1"), keep_blank_values=True)
            token = next((v for k, v in params if k == "token"), "")
            headers = list(scope["headers"])
            if token and not any(name == b"authorization" for name, _ in headers):
                headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))
            scope = {**scope, "headers": headers,
                     "query_string": urlencode([(k, v) for k, v in params if k != "token"]).encode("latin-1")}
        await self.app(scope, receive, send)


class RedactTokens(logging.Filter):
    """Keeps personal tokens out of the access log."""

    _pattern = re.compile(r"(token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._pattern.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


if __name__ == "__main__":
    logging.getLogger("uvicorn.access").addFilter(RedactTokens())
    logger.info("Serving MCP at %s/mcp (OAuth via %s, or ?token=)", MCP_PUBLIC_URL, PUBLIC_BASE_URL)
    uvicorn.run(QueryTokenAuth(mcp.streamable_http_app()), host=HOST, port=PORT, log_config=None)
