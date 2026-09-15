"""Embedding providers, selected at runtime.

``get_embedder()`` returns an ``OpenAIEmbedder`` when ``OPENAI_API_KEY`` is set,
otherwise (or if the OpenAI client cannot be constructed) a ``LocalEmbedder``
backed by sentence-transformers, which needs no key.
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

from rag import config

logger = logging.getLogger("rag.embeddings")


class Embedder(ABC):
    provider: str
    model: str

    @property
    def slug(self) -> str:
        """Stable identifier; vectors from different embedders must not share a collection."""
        return re.sub(r"[^a-z0-9]+", "-", f"{self.provider}-{self.model.split('/')[-1]}".lower()).strip("-")

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class OpenAIEmbedder(Embedder):
    provider = "openai"
    batch_size = 256

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            # The embeddings endpoint rejects empty strings.
            batch = [text if text.strip() else " " for text in texts[start:start + self.batch_size]]
            response = self._client.embeddings.create(model=self.model, input=batch)
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors


class LocalEmbedder(Embedder):
    provider = "local"

    def __init__(self, model: str) -> None:
        self.model = model
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading local sentence-transformers model %s", self.model)
                self._model = SentenceTransformer(self.model, device="cpu")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()


@lru_cache(maxsize=4)
def _build_embedder(openai_key: str | None, openai_model: str, local_model: str) -> Embedder:
    if openai_key:
        try:
            embedder: Embedder = OpenAIEmbedder(openai_key, openai_model)
            logger.info("Embeddings: OpenAI (%s)", openai_model)
            return embedder
        except Exception:  # noqa: BLE001 - any construction failure falls back to local
            logger.exception("OpenAI embedder could not be constructed; falling back to local model")
    else:
        logger.info("Embeddings: OPENAI_API_KEY not set, using local model %s", local_model)
    return LocalEmbedder(local_model)


def get_embedder() -> Embedder:
    return _build_embedder(
        config.openai_api_key(), config.openai_embedding_model(), config.local_embedding_model()
    )


__all__ = ["Embedder", "LocalEmbedder", "OpenAIEmbedder", "get_embedder"]
