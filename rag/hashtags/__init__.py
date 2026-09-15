"""Hashtag suggestions for a draft caption, grounded in the user's similar posts."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from rag.generation.llm import ClaudeClient, LLMClient, get_llm_client
from rag.prompts import HASHTAG_SYSTEM, build_hashtag_prompt
from rag.retrieval import extract_hashtags, retrieve_similar_content
from rag.vectorstore import ContentStore, engagement

logger = logging.getLogger("rag.hashtags")

_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "below", "between", "could", "every", "first",
    "from", "have", "here", "into", "just", "like", "more", "most", "much", "only", "other", "over", "really", "some",
    "such", "than", "that", "their", "them", "then", "there", "these", "they", "this", "those", "through", "today",
    "very", "want", "what", "when", "where", "which", "while", "with", "would", "your", "yours", "mock", "link",
    "week", "weekend", "tell", "comments", "save", "later", "only", "join",
}


def caption_keywords(caption: str, limit: int = 8) -> list[str]:
    words = [w.lower() for w in re.findall(r"[^\W\d_]{4,}", re.sub(r"#\w+", " ", caption))]
    seen: dict[str, None] = {}
    for word in words:
        if word not in _STOPWORDS:
            seen.setdefault(word, None)
    keywords = list(seen)
    bigrams = [f"{a}{b}" for a, b in zip(keywords, keywords[1:]) if len(a) + len(b) <= 20]
    return (keywords + bigrams[:3])[:limit]


def suggest_hashtags(
    caption: str,
    user_id: str,
    count: int = 10,
    store: ContentStore | None = None,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Rank hashtags from the user's similar well-performing posts plus caption keywords."""
    already = set(extract_hashtags(caption))
    similar = retrieve_similar_content(caption, 20, user_id, store=store)
    scored = [(item, engagement(item)) for item in similar if item.get("hashtags")]
    max_engagement = max((e for _, e in scored if e), default=0) or 1

    candidates: dict[str, dict[str, Any]] = defaultdict(lambda: {"score": 0.0, "posts": 0, "own": 0})
    for item, score in scored:
        weight = max(item["similarity"], 0.05) * (0.5 + (score or 0) / max_engagement)
        weight *= 1.3 if item["source"] == "own" else 1.0
        for tag in item["hashtags"]:
            entry = candidates[tag]
            entry["score"] += weight
            entry["posts"] += 1
            entry["own"] += item["source"] == "own"

    rows = [
        {"hashtag": tag, "score": round(v["score"], 3),
         "reason": f"used in {v['posts']} similar post(s)" + (f", {v['own']} of yours" if v["own"] else ""),
         "source": "similar_posts"}
        for tag, v in candidates.items() if tag not in already
    ]
    for keyword in caption_keywords(caption):
        if keyword not in candidates and keyword not in already:
            rows.append({"hashtag": keyword, "score": 0.05, "reason": "keyword from your caption", "source": "caption"})
    rows.sort(key=lambda row: row["score"], reverse=True)

    llm = llm or get_llm_client()
    if isinstance(llm, ClaudeClient):
        schema = {
            "type": "object",
            "properties": {"hashtags": {"type": "array", "items": {
                "type": "object",
                "properties": {"hashtag": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["hashtag", "reason"], "additionalProperties": False}}},
            "required": ["hashtags"], "additionalProperties": False,
        }
        try:
            data = llm.structured(HASHTAG_SYSTEM, build_hashtag_prompt(caption, rows, count), schema, max_tokens=4000)
            known = {row["hashtag"]: row for row in rows}
            picks = []
            for pick in data.get("hashtags", [])[:count]:
                tag = re.sub(r"[^\w]", "", pick["hashtag"].lstrip("#").lower())
                if tag and tag not in already:
                    picks.append({"hashtag": tag, "score": known.get(tag, {}).get("score"), "reason": pick["reason"],
                                  "source": known.get(tag, {}).get("source", "ai")})
            return {"suggestions": picks, "similar_posts_used": len(similar), "method": "claude"}
        except Exception:  # noqa: BLE001
            logger.exception("Claude hashtag suggestion failed; using ranking")

    return {"suggestions": rows[:count], "similar_posts_used": len(similar), "method": "ranking"}


__all__ = ["caption_keywords", "suggest_hashtags"]
