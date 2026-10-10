"""Storage interface. Postgres is the real backend; the memory store backs tests and dry runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sentinel.models import Chunk, Document, Finding, NewChunk, Obligation, RawDocument, Run


@dataclass
class SyncResult:
    added: int = 0
    superseded: int = 0
    unchanged: int = 0


class Store(Protocol):
    def upsert_source(self, name: str, adapter: str, regulation: str, url: str) -> None: ...

    def mark_source_scraped(self, name: str) -> None: ...

    def latest_document_hash(self, source: str, key: str) -> str | None: ...

    def add_document(self, raw: RawDocument, content_hash: str, snapshot_path: str) -> Document: ...

    def sync_chunks(self, document: Document, chunks: list[NewChunk]) -> SyncResult:
        """Make `chunks` the active set for the document's (source, key).

        Sections whose text is unchanged keep their existing row, so they are
        not re-audited. Changed and removed sections are marked superseded.
        """
        ...

    def pending_chunks(self, limit: int) -> list[Chunk]: ...

    def mark_processed(self, chunk_ids: list[int]) -> None: ...

    def get_chunk(self, chunk_id: int) -> Chunk | None: ...

    def search_chunks(
        self, embedding: list[float], query_text: str, k: int = 5, regulation: str | None = None
    ) -> list[Chunk]: ...

    def chunks_created_since(self, since: datetime | None) -> list[Chunk]: ...

    def add_obligations(self, obligations: list[Obligation]) -> list[Obligation]: ...

    def active_obligations(self) -> list[Obligation]: ...

    def create_run(self, target_repo: str) -> Run: ...

    def finish_run(
        self, run_id: int, status: str, input_tokens: int, output_tokens: int, stats: dict
    ) -> Run: ...

    def previous_run(self, run_id: int) -> Run | None: ...

    def add_findings(self, run_id: int, findings: list[Finding]) -> list[Finding]: ...

    def findings_for_run(self, run_id: int) -> list[Finding]: ...

    def close(self) -> None: ...
