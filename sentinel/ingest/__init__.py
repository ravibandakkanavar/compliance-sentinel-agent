"""Scrape results into the store: change detection, chunking and embedding."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.ingest.chunking import chunk_sections, content_hash, text_hash
from sentinel.ingest.embeddings import Embedder
from sentinel.models import NewChunk, RawDocument
from sentinel.scrapers.base import SourceAdapter
from sentinel.store.base import Store

log = logging.getLogger(__name__)

_EXTENSIONS = {"text/html": "html", "application/pdf": "pdf", "text/markdown": "md"}


@dataclass
class IngestStats:
    documents_fetched: int = 0
    documents_changed: int = 0
    chunks_added: int = 0
    chunks_superseded: int = 0
    chunks_unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def _save_snapshot(raw: RawDocument, digest: str, snapshots_dir: Path) -> str:
    folder = snapshots_dir / raw.source
    folder.mkdir(parents=True, exist_ok=True)
    extension = _EXTENSIONS.get(raw.content_type, "bin")
    path = folder / f"{raw.key}-{digest[:16]}.{extension}"
    path.write_bytes(raw.content)
    return str(path)


def ingest_source(
    adapter: SourceAdapter, store: Store, embedder: Embedder, snapshots_dir: Path
) -> IngestStats:
    """Fetch one source and store whatever changed since the last scrape."""
    stats = IngestStats()
    store.upsert_source(adapter.name, adapter.adapter_type, adapter.regulation, adapter.url)

    documents = adapter.fetch()
    stats.documents_fetched = len(documents)
    if not documents:
        stats.errors.append(f"{adapter.name}: scrape returned no documents")
        return stats

    for raw in documents:
        digest = content_hash(raw.content)
        if store.latest_document_hash(raw.source, raw.key) == digest:
            log.info("%s/%s unchanged", raw.source, raw.key)
            continue

        sections = chunk_sections(adapter.parse(raw))
        if not sections:
            stats.errors.append(f"{adapter.name}/{raw.key}: document parsed to zero sections")
            continue

        snapshot = _save_snapshot(raw, digest, snapshots_dir)
        document = store.add_document(raw, digest, snapshot)
        embeddings = embedder.embed([f"{s.title}\n{s.text}" for s in sections])
        chunks = [
            NewChunk(
                regulation=raw.regulation,
                section_ref=section.ref,
                title=section.title,
                text=section.text,
                text_hash=text_hash(section.text),
                kind=section.kind,
                embedding=embedding,
            )
            for section, embedding in zip(sections, embeddings, strict=True)
        ]
        result = store.sync_chunks(document, chunks)
        stats.documents_changed += 1
        stats.chunks_added += result.added
        stats.chunks_superseded += result.superseded
        stats.chunks_unchanged += result.unchanged
        log.info(
            "%s/%s: %d added, %d superseded, %d unchanged",
            raw.source,
            raw.key,
            result.added,
            result.superseded,
            result.unchanged,
        )

    store.mark_source_scraped(adapter.name)
    return stats
