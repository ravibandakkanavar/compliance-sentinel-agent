"""In-memory store with the same behaviour as the Postgres store, minus durability."""

from __future__ import annotations

import math
import re
from datetime import datetime

from sentinel.models import (
    Chunk,
    Document,
    Finding,
    NewChunk,
    Obligation,
    RawDocument,
    Run,
    utcnow,
)
from sentinel.store.base import SyncResult


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


class MemoryStore:
    def __init__(self) -> None:
        self.sources: dict[str, dict] = {}
        self.documents: list[Document] = []
        self.chunks: dict[int, Chunk] = {}
        self._chunk_keys: dict[int, tuple[str, str]] = {}
        self._embeddings: dict[int, list[float]] = {}
        self._created: dict[int, datetime] = {}
        self.obligations: list[Obligation] = []
        self.runs: dict[int, Run] = {}
        self.findings: list[Finding] = []
        self._next_id = 0

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def upsert_source(self, name: str, adapter: str, regulation: str, url: str) -> None:
        existing = self.sources.get(name, {})
        self.sources[name] = {
            "adapter": adapter,
            "regulation": regulation,
            "url": url,
            "last_scraped_at": existing.get("last_scraped_at"),
        }

    def mark_source_scraped(self, name: str) -> None:
        self.sources[name]["last_scraped_at"] = utcnow()

    def latest_document_hash(self, source: str, key: str) -> str | None:
        matches = [d for d in self.documents if d.source == source and d.key == key]
        return matches[-1].content_hash if matches else None

    def add_document(self, raw: RawDocument, content_hash: str, snapshot_path: str) -> Document:
        doc = Document(
            id=self._id(),
            source=raw.source,
            key=raw.key,
            regulation=raw.regulation,
            url=raw.url,
            title=raw.title,
            content_hash=content_hash,
            retrieved_at=raw.retrieved_at,
        )
        self.documents.append(doc)
        return doc

    def sync_chunks(self, document: Document, chunks: list[NewChunk]) -> SyncResult:
        result = SyncResult()
        doc_key = (document.source, document.key)
        active = {
            c.section_ref: c
            for cid, c in self.chunks.items()
            if self._chunk_keys[cid] == doc_key and not c.superseded
        }
        for new in chunks:
            old = active.pop(new.section_ref, None)
            if old is not None and old.text_hash == new.text_hash:
                result.unchanged += 1
                continue
            if old is not None:
                old.superseded = True
                result.superseded += 1
            chunk = Chunk(
                id=self._id(),
                document_id=document.id,
                regulation=new.regulation,
                section_ref=new.section_ref,
                title=new.title,
                text=new.text,
                text_hash=new.text_hash,
                kind=new.kind,
                url=document.url,
                retrieved_at=document.retrieved_at,
            )
            self.chunks[chunk.id] = chunk
            self._chunk_keys[chunk.id] = doc_key
            self._embeddings[chunk.id] = new.embedding
            self._created[chunk.id] = utcnow()
            result.added += 1
        for removed in active.values():
            removed.superseded = True
            result.superseded += 1
        return result

    def pending_chunks(self, limit: int) -> list[Chunk]:
        pending = [c for c in self.chunks.values() if not c.superseded and not c.processed]
        return sorted(pending, key=lambda c: c.id)[:limit]

    def mark_processed(self, chunk_ids: list[int]) -> None:
        for cid in chunk_ids:
            self.chunks[cid].processed = True

    def get_chunk(self, chunk_id: int) -> Chunk | None:
        return self.chunks.get(chunk_id)

    def search_chunks(
        self, embedding: list[float], query_text: str, k: int = 5, regulation: str | None = None
    ) -> list[Chunk]:
        candidates = [
            c
            for c in self.chunks.values()
            if not c.superseded and (regulation is None or c.regulation == regulation)
        ]
        query_terms = _terms(query_text)
        by_vector = sorted(
            candidates, key=lambda c: _cosine(embedding, self._embeddings[c.id]), reverse=True
        )
        by_keyword = sorted(
            candidates,
            key=lambda c: len(query_terms & _terms(f"{c.title} {c.text}")),
            reverse=True,
        )
        scores: dict[int, float] = {}
        for ranking in (by_vector, by_keyword):
            for rank, chunk in enumerate(ranking, start=1):
                scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (60 + rank)
        ranked = sorted(candidates, key=lambda c: scores[c.id], reverse=True)
        return ranked[:k]

    def chunks_created_since(self, since: datetime | None) -> list[Chunk]:
        return [
            c
            for cid, c in sorted(self.chunks.items())
            if not c.superseded and (since is None or self._created[cid] > since)
        ]

    def add_obligations(self, obligations: list[Obligation]) -> list[Obligation]:
        saved = [o.model_copy(update={"id": self._id()}) for o in obligations]
        self.obligations.extend(saved)
        return saved

    def active_obligations(self) -> list[Obligation]:
        return [o for o in self.obligations if not self.chunks[o.chunk_id].superseded]

    def create_run(self, target_repo: str) -> Run:
        run = Run(id=self._id(), started_at=utcnow(), target_repo=target_repo)
        self.runs[run.id] = run
        return run

    def finish_run(
        self, run_id: int, status: str, input_tokens: int, output_tokens: int, stats: dict
    ) -> Run:
        run = self.runs[run_id]
        run.status = status
        run.finished_at = utcnow()
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.stats = stats
        return run

    def previous_run(self, run_id: int) -> Run | None:
        earlier = [r for r in self.runs.values() if r.id < run_id and r.status == "completed"]
        return max(earlier, key=lambda r: r.id) if earlier else None

    def add_findings(self, run_id: int, findings: list[Finding]) -> list[Finding]:
        saved = [f.model_copy(update={"id": self._id(), "run_id": run_id}) for f in findings]
        self.findings.extend(saved)
        return saved

    def findings_for_run(self, run_id: int) -> list[Finding]:
        return [f for f in self.findings if f.run_id == run_id]

    def close(self) -> None:
        pass
