"""Chroma-backed, user-scoped store of posts (one vector per post, caption embedded).

Every vector carries ``user_id`` metadata and every query filters on it, so one
user's content never leaks into another user's retrieval.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from rag import config
from rag.embeddings import Embedder, get_embedder

logger = logging.getLogger("rag.vectorstore")

_HIDDEN = -1  # Chroma metadata cannot hold None
_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def _chroma_client(path: str):
    """HTTP client when CHROMA_HOST is set, otherwise an embedded client.

    Embedded (PersistentClient) mode is only safe inside ONE process. The backend and
    worker both write vectors, so the Docker setup runs a Chroma server.
    """
    import chromadb
    from chromadb.config import Settings

    settings = Settings(anonymized_telemetry=False)
    host = config.chroma_host()
    key = f"http://{host}:{config.chroma_port()}" if host else str(Path(path).resolve())
    with _clients_lock:
        if key not in _clients:
            if host:
                _clients[key] = chromadb.HttpClient(host=host, port=config.chroma_port(), settings=settings)
            else:
                Path(key).mkdir(parents=True, exist_ok=True)
                _clients[key] = chromadb.PersistentClient(path=key, settings=settings)
        return _clients[key]


def engagement(item: dict[str, Any]) -> int | None:
    """likes + comments + shares + saves; None when likes are hidden."""
    if item.get("like_count") is None:
        return None
    insights = item.get("insights") or {}
    return sum(int(v or 0) for v in (
        item.get("like_count"), item.get("comments_count"), item.get("shares_count"), insights.get("saved")
    ))


def document_text(item: dict[str, Any]) -> str:
    caption = (item.get("caption") or "").replace("[MOCK]", "").strip()
    return caption or f"{item.get('media_type', 'UNKNOWN')} post without a caption"


class ContentStore:
    """Wraps one Chroma collection per embedding model (vectors of different sizes can't mix)."""

    def __init__(
        self, embedder: Embedder | None = None, persist_dir: str | None = None, collection_name: str | None = None
    ) -> None:
        self.embedder = embedder or get_embedder()
        base = collection_name or config.chroma_collection()
        self.collection_name = f"{base}__{self.embedder.slug}"[:120].rstrip("-_.")
        client = _chroma_client(persist_dir or config.chroma_persist_dir())
        self.collection = client.get_or_create_collection(
            name=self.collection_name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    # ------------------------------------------------------------------ writes
    def upsert_items(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        documents = [document_text(item) for item in items]
        embeddings = self.embedder.embed_documents(documents)
        self.collection.upsert(
            ids=[str(item["id"]) for item in items],
            documents=documents,
            embeddings=embeddings,
            metadatas=[self._metadata(item) for item in items],
        )
        return len(items)

    def update_labels(self, labels: dict[str, dict[str, Any]]) -> None:
        """labels: {item_id: {"content_types": [...], "cluster_id": "..."}}"""
        if not labels:
            return
        ids = list(labels)
        existing = self.collection.get(ids=ids, include=["metadatas"])
        metadatas = []
        for item_id, meta in zip(existing["ids"], existing["metadatas"]):
            update = labels[item_id]
            meta = dict(meta or {})
            if "content_types" in update:
                meta["content_types"] = ",".join(update["content_types"])
            if "cluster_id" in update:
                meta["cluster_id"] = update["cluster_id"] or ""
            metadatas.append(meta)
        if existing["ids"]:
            self.collection.update(ids=existing["ids"], metadatas=metadatas)

    def delete_items(self, ids: list[str]) -> None:
        if ids:
            self.collection.delete(ids=[str(i) for i in ids])

    def delete_user(self, user_id: str) -> None:
        self.collection.delete(where={"user_id": str(user_id)})

    # ------------------------------------------------------------------- reads
    def embeddings_for(self, ids: list[str]) -> dict[str, list[float]]:
        if not ids:
            return {}
        result = self.collection.get(ids=[str(i) for i in ids], include=["embeddings"])
        return {item_id: list(vector) for item_id, vector in zip(result["ids"], result["embeddings"])}

    def query_similar(
        self,
        query_text: str,
        n_results: int,
        user_id: str,
        sources: list[str] | None = None,
        platform: str | None = None,
        content_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if n_results < 1:
            return []
        conditions: list[dict[str, Any]] = [{"user_id": str(user_id)}]
        if sources:
            conditions.append({"source": {"$in": list(sources)}})
        if platform:
            conditions.append({"platform": platform})
        where = conditions[0] if len(conditions) == 1 else {"$and": conditions}

        # content_types is a comma-joined string; filter those in Python on a wider pool.
        pool = n_results * 4 if content_type else n_results
        try:
            result = self.collection.query(
                query_embeddings=[self.embedder.embed_query(query_text)],
                n_results=pool,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:  # noqa: BLE001 - an empty filtered set raises in some Chroma versions
            logger.debug("Chroma query returned nothing: %s", exc)
            return []

        rows = [
            self._to_item(item_id, doc, meta, dist)
            for item_id, doc, meta, dist in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
            )
        ]
        if content_type:
            rows = [row for row in rows if content_type in row["content_types"]]
        return rows[:n_results]

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _metadata(item: dict[str, Any]) -> dict[str, Any]:
        insights = item.get("insights") or {}
        return {
            "user_id": str(item["user_id"]),
            "source": item.get("source") or "own",
            "platform": item.get("platform") or "instagram",
            "author": item.get("author") or "",
            "hashtags": ",".join(item.get("hashtags") or []),
            "media_type": item.get("media_type") or "UNKNOWN",
            "like_count": _HIDDEN if item.get("like_count") is None else int(item["like_count"]),
            "comments_count": int(item.get("comments_count") or 0),
            "shares_count": int(item.get("shares_count") or 0),
            "saved": int(insights.get("saved") or 0),
            "reach": int(insights.get("reach") or 0),
            "permalink": item.get("permalink") or "",
            "published_at": str(item.get("published_at") or ""),
            "content_types": ",".join(item.get("content_types") or []),
            "cluster_id": str(item.get("cluster_id") or ""),
            "is_mock": bool(item.get("is_mock", False)),
        }

    @staticmethod
    def _to_item(item_id: str, document: str, meta: dict[str, Any], distance: float) -> dict[str, Any]:
        like_count = meta.get("like_count", _HIDDEN)
        return {
            "id": item_id,
            "user_id": meta.get("user_id"),
            "source": meta.get("source", "own"),
            "platform": meta.get("platform", "instagram"),
            "author": meta.get("author") or None,
            "caption": document,
            "hashtags": [t for t in str(meta.get("hashtags", "")).split(",") if t],
            "media_type": meta.get("media_type", "UNKNOWN"),
            "like_count": None if like_count == _HIDDEN else int(like_count),
            "comments_count": int(meta.get("comments_count", 0)),
            "shares_count": int(meta.get("shares_count", 0)),
            "insights": {"saved": int(meta.get("saved", 0)), "reach": int(meta.get("reach", 0))},
            "permalink": meta.get("permalink", ""),
            "published_at": meta.get("published_at", ""),
            "content_types": [t for t in str(meta.get("content_types", "")).split(",") if t],
            "cluster_id": meta.get("cluster_id") or None,
            "is_mock": bool(meta.get("is_mock", False)),
            "similarity": round(1.0 - float(distance), 4),
        }


__all__ = ["ContentStore", "document_text", "engagement"]
