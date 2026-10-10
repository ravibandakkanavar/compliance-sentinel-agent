"""Retrieval over the stored regulation text."""

from __future__ import annotations

from sentinel.ingest.embeddings import Embedder
from sentinel.models import Chunk
from sentinel.store.base import Store


def retrieve(
    store: Store, embedder: Embedder, query: str, k: int = 5, regulation: str | None = None
) -> list[Chunk]:
    """Hybrid vector and keyword search; returns active chunks, best first."""
    embedding = embedder.embed([query])[0]
    return store.search_chunks(embedding, query, k=k, regulation=regulation)


def format_citation(chunk: Chunk) -> str:
    retrieved = chunk.retrieved_at.date().isoformat() if chunk.retrieved_at else "unknown date"
    return f"{chunk.regulation}, {chunk.section_ref} ({chunk.url}, retrieved {retrieved})"
