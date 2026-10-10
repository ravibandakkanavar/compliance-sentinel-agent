"""Postgres store checks. Skipped unless TEST_DATABASE_URL points at a pgvector database."""

from __future__ import annotations

import os

import pytest

from sentinel.ingest import ingest_source
from sentinel.models import Finding, Obligation, Severity
from sentinel.scrapers import demo_source

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
]


@pytest.fixture
def pg_store():
    import psycopg

    from sentinel.store.postgres import PostgresStore, migrate

    migrate(DATABASE_URL)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE findings, obligations, chunks, documents, runs, sources CASCADE")
    store = PostgresStore(DATABASE_URL)
    yield store
    store.close()


def test_migrations_are_idempotent():
    from sentinel.store.postgres import migrate

    migrate(DATABASE_URL)
    assert migrate(DATABASE_URL) == []


def test_change_detection_matches_the_memory_store(pg_store, embedder, settings):
    first = ingest_source(demo_source(), pg_store, embedder, settings.snapshots_dir)
    again = ingest_source(demo_source(), pg_store, embedder, settings.snapshots_dir)
    pg_store.mark_processed([c.id for c in pg_store.pending_chunks(100)])
    amended = ingest_source(demo_source(amended=True), pg_store, embedder, settings.snapshots_dir)

    assert (first.chunks_added, again.chunks_added) == (5, 0)
    assert (amended.chunks_added, amended.chunks_superseded, amended.chunks_unchanged) == (3, 1, 4)
    pending = {c.section_ref for c in pg_store.pending_chunks(100)}
    assert pending == {"Section 2", "Section 6", "Section 7"}


def test_hybrid_search_returns_active_chunks_with_citation_fields(pg_store, embedder, settings):
    ingest_source(demo_source(), pg_store, embedder, settings.snapshots_dir)
    ingest_source(demo_source(amended=True), pg_store, embedder, settings.snapshots_dir)

    query = "email addresses in application logs"
    hits = pg_store.search_chunks(embedder.embed([query])[0], query, k=3)

    assert hits[0].section_ref == "Section 2"
    assert "internal account identifier" in hits[0].text
    assert hits[0].url and hits[0].retrieved_at is not None
    only = pg_store.search_chunks(embedder.embed([query])[0], query, k=3, regulation="Nope")
    assert only == []


def test_obligations_runs_and_findings_round_trip(pg_store, embedder, settings):
    ingest_source(demo_source(), pg_store, embedder, settings.snapshots_dir)
    chunk = pg_store.pending_chunks(1)[0]
    [obligation] = pg_store.add_obligations(
        [
            Obligation(
                chunk_id=chunk.id,
                regulation=chunk.regulation,
                section_ref=chunk.section_ref,
                title="Hash passwords",
                requirement="r",
                regulation_quote="q",
                search_patterns=["password"],
                violation_indicators=["plain text"],
            )  # fmt: skip
        ]
    )
    assert pg_store.active_obligations()[0].search_patterns == ["password"]

    run = pg_store.create_run("/repo")
    pg_store.add_findings(
        run.id,
        [
            Finding(
                obligation_id=obligation.id,
                chunk_id=chunk.id,
                regulation=chunk.regulation,
                section_ref=chunk.section_ref,
                obligation_title="Hash passwords",
                file="db.py",
                line_start=3,
                line_end=4,
                snippet="x",
                severity=Severity.CRITICAL,
                confidence=0.85,
                explanation="e",
                remediation="m",
                regulation_quote="q",
                source_url=chunk.url,
                retrieved_at=chunk.retrieved_at,
            )  # fmt: skip
        ],
    )
    finished = pg_store.finish_run(run.id, "completed", 10, 20, {"findings_verified": 1})

    [stored] = pg_store.findings_for_run(run.id)
    assert (stored.file, stored.severity, stored.confidence) == ("db.py", Severity.CRITICAL, 0.85)
    assert finished.stats == {"findings_verified": 1} and finished.finished_at is not None
    assert pg_store.previous_run(run.id) is None
    later = pg_store.create_run("/repo")
    assert pg_store.previous_run(later.id).id == run.id
    assert [c.id for c in pg_store.chunks_created_since(finished.finished_at)] == []
