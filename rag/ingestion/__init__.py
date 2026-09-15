"""Index posts into the vector store.

Fetching from Facebook/Instagram happens in the application (per-user tokens,
database); this package only receives plain dicts, so it stays usable as a
library without any database or web framework.
"""

from __future__ import annotations

import logging
from typing import Any

from rag.vectorstore import ContentStore

logger = logging.getLogger("rag.ingestion")


def index_items(items: list[dict[str, Any]], store: ContentStore | None = None) -> int:
    """Embed and upsert posts. Each item needs at least ``id``, ``user_id`` and ``caption``."""
    store = store or ContentStore()
    count = 0
    for start in range(0, len(items), 128):
        count += store.upsert_items(items[start:start + 128])
    logger.info("Indexed %d items into %s", count, store.collection_name)
    return count


__all__ = ["index_items"]
