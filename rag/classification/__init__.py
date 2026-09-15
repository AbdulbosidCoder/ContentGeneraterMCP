"""Content-type classification (labelled) and unsupervised clustering of posts.

* ``classify_items``: assigns labels from ``CONTENT_TYPES``. With Claude configured it
  uses structured outputs; otherwise zero-shot embedding similarity plus keyword cues.
* ``cluster_items``: KMeans over post embeddings (k chosen by silhouette score), with
  clusters named by Claude or, without a key, by their top TF-IDF terms.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

from rag.embeddings import Embedder, get_embedder
from rag.generation.llm import ClaudeClient, LLMClient, get_llm_client
from rag.prompts import (
    CLASSIFY_SYSTEM,
    CLUSTER_NAMING_SYSTEM,
    build_classify_prompt,
    build_cluster_prompt,
)
from rag.vectorstore import document_text, engagement

logger = logging.getLogger("rag.classification")

CONTENT_TYPES: dict[str, str] = {
    "interactive": "Invites the audience to respond or act: questions, polls, 'comment below', tag a friend, giveaways, contests, challenges.",
    "educational": "Teaches something: tips, how-to steps, tutorials, guides, myth vs. fact, explainers.",
    "promotional": "Sells: discounts, sales, product launches, 'shop now', 'link in bio', limited-time offers.",
    "party_event": "Events and celebrations: parties, launches, pop-ups, meetups, festivals, live sessions, event recaps.",
    "critical_opinion": "Opinion or critique: hot takes, unpopular opinions, calling out problems, honest reviews, debates.",
    "behind_the_scenes": "Shows the process or team: how things are made, a day in the life, the studio, production.",
    "testimonial": "Social proof: customer stories, reviews, results, user-generated content, client quotes.",
    "inspirational": "Motivation or mood: quotes, reflections, lifestyle moments, aspirational imagery.",
    "entertainment": "Humor or fun: memes, jokes, trends, skits, playful content made to amuse.",
    "announcement": "News: updates, openings, changes, milestones, partnerships, new hires.",
}

_KEYWORD_CUES: dict[str, list[str]] = {
    "interactive": [r"\?", r"\bcomment", r"\btag\b", r"\bgiveaway", r"\bpoll\b", r"\bvote\b", r"\bwhich (one|do)"],
    "educational": [r"\bsteps?\b", r"\bhow to\b", r"\bguide\b", r"\btips?\b", r"\bmyth\b", r"\bexplained\b", r"\blearn"],
    "promotional": [r"\d+% off", r"\bshop\b", r"\blink in bio\b", r"\bsale\b", r"\bdiscount", r"\bavailable\b", r"\border\b"],
    "party_event": [r"\bparty\b", r"\bevent\b", r"\bjoin us\b", r"\bpop-up\b", r"\bcelebrat", r"\blive\b", r"\bfestival"],
    "critical_opinion": [r"unpopular opinion", r"\bhonest", r"\boverhyped\b", r"\bwrong\b", r"let's be real", r"\bbroken\b"],
    "behind_the_scenes": [r"behind the scenes", r"\bday in\b", r"\bhow we make\b", r"\bstudio\b", r"\bour team\b"],
    "testimonial": [r"\bcustomer", r"\breview", r"\bresults\b", r"\bsays\b", r"\"[^\"]+\""],
    "inspirational": [r"\bmotivat", r"\binspir", r"\breminder\b", r"\bbreathe?\b", r"\bsmall steps\b"],
    "entertainment": [r"\bmeme\b", r"\blol\b", r"\bfunny\b", r"\btrend\b", r"😂"],
    "announcement": [r"\bannounc", r"\bnew\b.*\bopen", r"\bmilestone\b", r"\bexcited to\b", r"\bpartner"],
}
_KEYWORD_BOOST = 0.15
_MIN_SCORE = 0.2


def _keyword_scores(text: str) -> dict[str, float]:
    lowered = text.lower()
    return {
        label: _KEYWORD_BOOST * min(2, sum(bool(re.search(p, lowered)) for p in patterns))
        for label, patterns in _KEYWORD_CUES.items()
    }


def _classify_by_embeddings(
    items: list[dict[str, Any]], embedder: Embedder, taxonomy: dict[str, str]
) -> dict[str, dict[str, Any]]:
    names = list(taxonomy)
    label_vectors = np.array(embedder.embed_documents([f"A post that is {n.replace('_', ' ')}: {d}" for n, d in taxonomy.items()]))
    post_vectors = np.array(embedder.embed_documents([document_text(item) for item in items]))
    label_vectors /= np.linalg.norm(label_vectors, axis=1, keepdims=True)
    post_vectors /= np.linalg.norm(post_vectors, axis=1, keepdims=True)
    similarity = post_vectors @ label_vectors.T

    results = {}
    for row, item in zip(similarity, items):
        cues = _keyword_scores(item.get("caption") or "")
        scores = {name: float(row[i]) + cues.get(name, 0.0) for i, name in enumerate(names)}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_score = ranked[0][1]
        labels = [name for name, score in ranked[:3] if score >= max(_MIN_SCORE, top_score - 0.05)] or [ranked[0][0]]
        results[str(item["id"])] = {"content_types": labels, "scores": {k: round(v, 3) for k, v in ranked[:5]}}
    return results


def _classify_with_claude(
    items: list[dict[str, Any]], client: ClaudeClient, taxonomy: dict[str, str]
) -> dict[str, dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string", "enum": list(taxonomy)}},
                    },
                    "required": ["id", "labels"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["posts"],
        "additionalProperties": False,
    }
    results: dict[str, dict[str, Any]] = {}
    for start in range(0, len(items), 25):
        batch = items[start:start + 25]
        data = client.structured(CLASSIFY_SYSTEM, build_classify_prompt(batch, taxonomy), schema)
        for post in data.get("posts", []):
            labels = [label for label in post.get("labels", []) if label in taxonomy][:3]
            if labels:
                results[str(post["id"])] = {"content_types": labels, "scores": {"method": "claude"}}
    return results


def classify_items(
    items: list[dict[str, Any]],
    embedder: Embedder | None = None,
    llm: LLMClient | None = None,
    taxonomy: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{item_id: {"content_types": [...], "scores": {...}}}``."""
    if not items:
        return {}
    taxonomy = taxonomy or CONTENT_TYPES
    llm = llm or get_llm_client()
    results: dict[str, dict[str, Any]] = {}
    if isinstance(llm, ClaudeClient):
        try:
            results = _classify_with_claude(items, llm, taxonomy)
        except Exception:  # noqa: BLE001 - fall back to local classification
            logger.exception("Claude classification failed; using embedding classifier")
    missing = [item for item in items if str(item["id"]) not in results]
    if missing:
        results.update(_classify_by_embeddings(missing, embedder or get_embedder(), taxonomy))
    return results


# ------------------------------------------------------------------ clustering
_STOPWORDS_EXTRA = {"mock", "link", "bio", "ll", "ve", "don", "just", "like", "new", "day", "week", "today"}


def _choose_k(vectors: np.ndarray, max_k: int) -> tuple[int, np.ndarray]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    best: tuple[float, int, np.ndarray] | None = None
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(vectors)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(vectors, labels, metric="cosine")
        if best is None or score > best[0]:
            best = (score, k, labels)
    if best is None:
        return 1, np.zeros(len(vectors), dtype=int)
    return best[1], best[2]


def _keywords_per_cluster(texts: list[str], labels: np.ndarray, top: int = 4) -> dict[int, list[str]]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

    vectorizer = TfidfVectorizer(
        stop_words=list(ENGLISH_STOP_WORDS | _STOPWORDS_EXTRA), token_pattern=r"(?u)\b[^\W\d_]{3,}\b", max_features=2000
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:  # empty vocabulary
        return {int(c): [] for c in set(labels)}
    vocab = np.array(vectorizer.get_feature_names_out())
    keywords = {}
    for cluster in sorted(set(labels)):
        mean = np.asarray(matrix[labels == cluster].mean(axis=0)).ravel()
        keywords[int(cluster)] = [str(vocab[i]) for i in mean.argsort()[::-1][:top] if mean[i] > 0]
    return keywords


def cluster_items(
    items: list[dict[str, Any]], embeddings: dict[str, list[float]], llm: LLMClient | None = None, max_k: int = 8
) -> list[dict[str, Any]]:
    """Group posts by meaning. Returns clusters with label, description, keywords and member ids."""
    usable = [item for item in items if str(item["id"]) in embeddings]
    if len(usable) < 6:
        return []
    vectors = np.array([embeddings[str(item["id"])] for item in usable])
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    k, labels = _choose_k(vectors, max(2, min(max_k, len(usable) // 4)))
    texts = [document_text(item) for item in usable]
    keywords = _keywords_per_cluster(texts, labels)

    names: dict[int, dict[str, str]] = {}
    llm = llm or get_llm_client()
    if isinstance(llm, ClaudeClient):
        samples = {int(c): [texts[i] for i in np.where(labels == c)[0][:8]] for c in set(labels)}
        schema = {
            "type": "object",
            "properties": {"groups": {"type": "array", "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "label": {"type": "string"}, "description": {"type": "string"}},
                "required": ["id", "label", "description"], "additionalProperties": False}}},
            "required": ["groups"], "additionalProperties": False,
        }
        try:
            data = llm.structured(CLUSTER_NAMING_SYSTEM, build_cluster_prompt(samples), schema, max_tokens=4000)
            names = {int(g["id"]): g for g in data.get("groups", [])}
        except Exception:  # noqa: BLE001
            logger.exception("Claude cluster naming failed; using keywords")

    clusters = []
    for cluster in sorted(set(labels)):
        member_idx = np.where(labels == cluster)[0]
        members = [usable[i] for i in member_idx]
        scores = [s for s in (engagement(m) for m in members) if s is not None]
        kw = keywords.get(int(cluster), [])
        named = names.get(int(cluster))
        clusters.append({
            "label": (named or {}).get("label") or (" / ".join(kw[:2]).title() if kw else f"Group {cluster + 1}"),
            "description": (named or {}).get("description") or (f"Posts about {', '.join(kw)}." if kw else None),
            "keywords": kw,
            "member_ids": [str(m["id"]) for m in members],
            "avg_engagement": round(sum(scores) / len(scores)) if scores else None,
        })
    logger.info("Clustered %d posts into %d groups", len(usable), len(clusters))
    return clusters


__all__ = ["CONTENT_TYPES", "classify_items", "cluster_items"]
