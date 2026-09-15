"""User-scoped similarity retrieval."""

from __future__ import annotations

import re
from typing import Any

from rag.vectorstore import ContentStore

_HASHTAG_RE = re.compile(r"(?<![\w#])#(\w*[^\W\d]\w*)")


def extract_hashtags(text: str | None) -> list[str]:
    seen: dict[str, None] = {}
    for tag in _HASHTAG_RE.findall(text or ""):
        seen.setdefault(tag.lower(), None)
    return list(seen)


def retrieve_similar_content(
    query: str,
    n_results: int,
    user_id: str,
    sources: list[str] | None = None,
    content_type: str | None = None,
    store: ContentStore | None = None,
) -> list[dict[str, Any]]:
    return (store or ContentStore()).query_similar(
        query, n_results, user_id, sources=sources, content_type=content_type
    )


def retrieve_by_hashtags(
    hashtags: list[str],
    n_results: int,
    user_id: str,
    query: str | None = None,
    sources: list[str] | None = None,
    store: ContentStore | None = None,
) -> list[dict[str, Any]]:
    """Semantic retrieval re-ranked so posts using the requested hashtags come first."""
    wanted = {tag.lstrip("#").lower() for tag in hashtags if tag.strip("# ")}
    query_text = query or " ".join(f"#{tag}" for tag in sorted(wanted))
    candidates = retrieve_similar_content(query_text, max(n_results * 4, 20), user_id, sources, store=store)
    for item in candidates:
        item["matched_hashtags"] = sorted(wanted.intersection(item["hashtags"]))
    candidates.sort(key=lambda item: (len(item["matched_hashtags"]), item["similarity"]), reverse=True)
    return candidates[:n_results]


def retrieve_for_query(
    query: str, n_results: int, user_id: str, sources: list[str] | None = None, store: ContentStore | None = None
) -> list[dict[str, Any]]:
    hashtags = extract_hashtags(query)
    if hashtags:
        return retrieve_by_hashtags(hashtags, n_results, user_id, query=query, sources=sources, store=store)
    return retrieve_similar_content(query, n_results, user_id, sources, store=store)


__all__ = ["extract_hashtags", "retrieve_by_hashtags", "retrieve_for_query", "retrieve_similar_content"]
