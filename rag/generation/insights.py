"""Engagement statistics over retrieved examples, used to ground the prompts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rag.vectorstore import engagement


def _ranked(buckets: dict[str, list[int]], key: str, top: int) -> list[dict[str, Any]]:
    rows = [
        {key: name, "avg_engagement": round(sum(values) / len(values)), "posts": len(values)}
        for name, values in buckets.items()
    ]
    rows.sort(key=lambda row: (row["avg_engagement"], row["posts"]), reverse=True)
    return rows[:top]


def summarize_performance(examples: list[dict[str, Any]], top_hashtags: int = 12) -> dict[str, Any]:
    by_hashtag: dict[str, list[int]] = defaultdict(list)
    by_format: dict[str, list[int]] = defaultdict(list)
    by_type: dict[str, list[int]] = defaultdict(list)
    for item in examples:
        score = engagement(item)
        if score is None:
            continue
        by_format[item["media_type"]].append(score)
        for tag in item.get("hashtags") or []:
            by_hashtag[tag].append(score)
        for ctype in item.get("content_types") or []:
            by_type[ctype].append(score)
    return {
        "hashtags": _ranked(by_hashtag, "hashtag", top_hashtags),
        "formats": _ranked(by_format, "media_type", len(by_format)),
        "content_types": _ranked(by_type, "content_type", len(by_type)),
    }
