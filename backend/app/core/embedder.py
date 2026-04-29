"""Embedder — text embedding with Voyage AI and full-text search fallback.

When VOYAGE_API_KEY is set, uses Voyage AI voyage-3-lite (1024 dimensions,
free tier: 200M tokens/month). When not set, falls back to PostgreSQL
tsvector full-text search — zero cost, zero new dependencies.

Cost profile (Voyage AI voyage-3-lite):
  - Free tier: 200M tokens/month (no credit card required)
  - ~2K tokens per typical knowledge item chunk
  - ~100K chunks before hitting free tier limit
  - Batches up to 128 texts per API call

Usage:
    embedder = Embedder()
    vectors = embedder.embed(["text one", "text two"])  # list of float lists or None
    chunks  = embedder.chunk("long document text...")   # list of str
    mode    = embedder.mode   # 'vector' or 'text_search'
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# Voyage AI voyage-3-lite: 1024 dimensions, 32K context window
_VOYAGE_MODEL = "voyage-3-lite"
_VOYAGE_BATCH_SIZE = 128
_CHUNK_TOKENS = 400       # ~400 tokens per chunk (conservative for voyage-3-lite 32K limit)
_CHUNK_OVERLAP_CHARS = 100
_CHARS_PER_TOKEN = 4      # approximate


class Embedder:
    """Embed text with Voyage AI or degrade gracefully to full-text search."""

    def __init__(self) -> None:
        settings = get_settings()
        self._voyage_key = settings.voyage_api_key
        self._client = None

        if self._voyage_key:
            try:
                import voyageai  # type: ignore[import]
                self._client = voyageai.Client(api_key=self._voyage_key)
                logger.info("Embedder: using Voyage AI voyage-3-lite (vector mode)")
            except ImportError:
                logger.warning(
                    "Embedder: voyageai package not installed. "
                    "Run: pip install voyageai. Falling back to text search."
                )
                self._voyage_key = ""
        else:
            logger.info(
                "Embedder: VOYAGE_API_KEY not set — using PostgreSQL full-text search fallback. "
                "To enable semantic search, set VOYAGE_API_KEY in .env (free at voyageai.com)."
            )

    @property
    def mode(self) -> str:
        """Return 'vector' when Voyage AI is configured, else 'text_search'."""
        return "vector" if self._client is not None else "text_search"

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a list of texts into float vectors.

        Args:
            texts: List of strings to embed. Will be batched automatically.

        Returns:
            List of embedding vectors (one per input text), or None if in
            text_search mode or on error.
        """
        if not self._client or not texts:
            return None

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), _VOYAGE_BATCH_SIZE):
            batch = texts[i : i + _VOYAGE_BATCH_SIZE]
            try:
                result = self._client.embed(batch, model=_VOYAGE_MODEL)
                all_embeddings.extend(result.embeddings)
            except Exception as e:
                logger.error(f"Embedder.embed: Voyage AI API error on batch {i}: {e}")
                # Partial failure: pad with None embeddings to keep indexing aligned
                all_embeddings.extend([None] * len(batch))  # type: ignore[arg-type]

        return all_embeddings

    def embed_query(self, query: str) -> list[float] | None:
        """Embed a single query string for similarity search."""
        if not self._client:
            return None
        results = self.embed([query])
        if results and results[0] is not None:
            return results[0]
        return None

    def chunk(self, text: str) -> list[str]:
        """Split text into overlapping chunks for embedding.

        Uses a character-based sliding window. Chunks are sized to fit
        within voyage-3-lite's context window with room to spare.

        Args:
            text: Full document text.

        Returns:
            List of chunk strings.
        """
        max_chars = _CHUNK_TOKENS * _CHARS_PER_TOKEN
        overlap = _CHUNK_OVERLAP_CHARS

        if len(text) <= max_chars:
            return [text.strip()]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            chunk = text[start:end]

            # Try to break on a sentence boundary
            if end < len(text):
                last_period = chunk.rfind(". ")
                if last_period > max_chars // 2:
                    chunk = chunk[: last_period + 1]
                    end = start + last_period + 1

            chunk = chunk.strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap if end < len(text) else end

        return chunks

    @staticmethod
    def content_hash(text: str) -> str:
        """SHA-256 hash of text content — used to skip re-embedding identical chunks."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
