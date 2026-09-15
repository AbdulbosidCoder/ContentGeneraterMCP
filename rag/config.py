"""Environment-driven settings for the rag package.

Values are read at call time (not import time) so a process picks up whatever
environment it was started with, and blank values in ``.env`` count as unset.
"""

from __future__ import annotations

import os

MOCK_PREFIX = "[MOCK]"


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, "").strip()
    return value or default


def anthropic_api_key() -> str | None:
    return env("ANTHROPIC_API_KEY")


def anthropic_model() -> str:
    return env("ANTHROPIC_MODEL", "claude-opus-5")  # type: ignore[return-value]


def openai_api_key() -> str | None:
    return env("OPENAI_API_KEY")


def openai_embedding_model() -> str:
    return env("EMBEDDING_MODEL", "text-embedding-3-small")  # type: ignore[return-value]


def local_embedding_model() -> str:
    return env("LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")  # type: ignore[return-value]


def chroma_persist_dir() -> str:
    return env("CHROMA_PERSIST_DIR", "./.chroma")  # type: ignore[return-value]


def chroma_host() -> str | None:
    """When set, connect to a Chroma server (required when several processes share the store)."""
    return env("CHROMA_HOST")


def chroma_port() -> int:
    return int(env("CHROMA_PORT", "8000") or 8000)


def chroma_collection() -> str:
    return env("CHROMA_COLLECTION", "instagram_content")  # type: ignore[return-value]


def mcp_server_url() -> str:
    return env("MCP_SERVER_URL", "http://localhost:8765/mcp")  # type: ignore[return-value]
