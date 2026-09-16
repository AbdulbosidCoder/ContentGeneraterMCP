"""Environment-driven settings. Blank values count as unset.

Meta (Facebook/Instagram) is real when META_APP_ID and META_APP_SECRET are set. Then
people sign in with Facebook Login. Otherwise sign-in is a demo Facebook login and all
Facebook/Instagram data is mock content.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("common.config")

MOCK_PREFIX = "[MOCK]"

# Permissions requested with Facebook Login (ignored when META_LOGIN_CONFIG_ID is used,
# because a Login for Business configuration carries its own permission set).
META_PERMISSIONS = [
    "public_profile",
    "email",
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_manage_posts",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_manage_insights",
    "instagram_content_publish",
]


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, "").strip()
    return value or default


def public_base_url() -> str:
    return (env("PUBLIC_BASE_URL", "http://localhost") or "").rstrip("/")


def mcp_public_url() -> str:
    """Where MCP clients reach nginx; defaults to PUBLIC_BASE_URL (e.g. set https://mcp.example.com)."""
    return (env("MCP_PUBLIC_URL") or public_base_url()).rstrip("/")


def mcp_resource_url() -> str:
    return f"{mcp_public_url()}/mcp"


def database_url() -> str:
    return env("DATABASE_URL", "postgresql+psycopg://content_ai:content_ai@localhost:5432/content_ai")  # type: ignore[return-value]


def meta_configured() -> bool:
    return bool(env("META_APP_ID") and env("META_APP_SECRET"))


def graph_api_version() -> str:
    return env("META_GRAPH_API_VERSION", "v22.0")  # type: ignore[return-value]


def media_dir() -> str:
    return env("MEDIA_DIR", "./.media")  # type: ignore[return-value]


def internal_service_token() -> str:
    token = env("INTERNAL_SERVICE_TOKEN")
    if not token:
        logger.warning("INTERNAL_SERVICE_TOKEN is not set; using an insecure development default.")
        return "dev-internal-service-token"
    return token


def sync_interval_hours() -> float:
    return float(env("SYNC_INTERVAL_HOURS", "12") or 12)
