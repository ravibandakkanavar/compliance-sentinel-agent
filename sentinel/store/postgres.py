"""Postgres + pgvector store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sentinel.models import Chunk, Document, Finding, NewChunk, Obligation, RawDocument, Run
from sentinel.store.base import SyncResult

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_CHUNK_COLUMNS = """
    c.id, c.document_id, c.regulation, c.section_ref, c.title, c.text, c.text_hash, c.kind,
    c.superseded, (c.processed_at IS NOT NULL) AS processed, d.url, d.retrieved_at
"""

# Reciprocal rank fusion of the vector ranking and the full-text ranking, so an
# exact term match ("Article 17") and a paraphrase both surface.
_HYBRID_SEARCH = f"""
WITH vector_hits AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(embedding)s::vector) AS rank
    FROM chunks
    WHERE NOT superseded AND (%(regulation)s::text IS NULL OR regulation = %(regulation)s)
    ORDER BY embedding <=> %(embedding)s::vector
    LIMIT %(pool)s
),
keyword_hits AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, query) DESC) AS rank
    FROM chunks, websearch_to_tsquery('english', %(query)s) AS query
    WHERE NOT superseded AND tsv @@ query
      AND (%(regulation)s::text IS NULL OR regulation = %(regulation)s)
    ORDER BY ts_rank_cd(tsv, query) DESC
    LIMIT %(pool)s
),
fused AS (
    SELECT id, sum(1.0 / (60 + rank)) AS score
    FROM (SELECT * FROM vector_hits UNION ALL SELECT * FROM keyword_hits) hits
    GROUP BY id
)
SELECT {_CHUNK_COLUMNS}
FROM fused
JOIN chunks c ON c.id = fused.id
JOIN documents d ON d.id = c.document_id
ORDER BY fused.score DESC
LIMIT %(k)s
"""


def migrate(database_url: str) -> list[str]:
    """Apply every SQL file in the migrations folder that has not run yet."""
    applied: list[str] = []
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        self.conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
        register_vector(self.conn)

    def upsert_source(self, name: str, adapter: str, regulation: str, url: str) -> None:
        self.conn.execute(
            """
            INSERT INTO sources (name, adapter, regulation, url) VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
            SET adapter = EXCLUDED.adapter, regulation = EXCLUDED.regulation, url = EXCLUDED.url
            """,
            (name, adapter, regulation, url),
        )

    def mark_source_scraped(self, name: str) -> None:
        self.conn.execute("UPDATE sources SET last_scraped_at = now() WHERE name = %s", (name,))

    def latest_document_hash(self, source: str, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT content_hash FROM documents WHERE source = %s AND key = %s "
            "ORDER BY retrieved_at DESC, id DESC LIMIT 1",
            (source, key),
        ).fetchone()
        return row["content_hash"] if row else None

    def add_document(self, raw: RawDocument, content_hash: str, snapshot_path: str) -> Document:
        row = self.conn.execute(
            """
            INSERT INTO documents
                (source, key, regulation, url, title, content_hash, snapshot_path, retrieved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, key, content_hash)
            DO UPDATE SET retrieved_at = EXCLUDED.retrieved_at
            RETURNING id, source, key, regulation, url, title, content_hash, retrieved_at
            """,
            (
                raw.source,
                raw.key,
                raw.regulation,
                raw.url,
                raw.title,
                content_hash,
                snapshot_path,
                raw.retrieved_at,
            ),
        ).fetchone()
        return Document(**row)

    def sync_chunks(self, document: Document, chunks: list[NewChunk]) -> SyncResult:
        result = SyncResult()
        with self.conn.transaction():
            rows = self.conn.execute(
                "SELECT id, section_ref, text_hash FROM chunks "
                "WHERE source = %s AND doc_key = %s AND NOT superseded FOR UPDATE",
                (document.source, document.key),
            ).fetchall()
            active = {row["section_ref"]: row for row in rows}
            stale: list[int] = []
            for new in chunks:
                old = active.pop(new.section_ref, None)
                if old is not None and old["text_hash"] == new.text_hash:
                    result.unchanged += 1
                    continue
                if old is not None:
                    stale.append(old["id"])
                self.conn.execute(
                    """
                    INSERT INTO chunks (document_id, source, doc_key, regulation, section_ref,
                                        title, text, text_hash, kind, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (
                        document.id,
                        document.source,
                        document.key,
                        new.regulation,
                        new.section_ref,
                        new.title,
                        new.text,
                        new.text_hash,
                        new.kind.value,
                        str(new.embedding),
                    ),
                )
                result.added += 1
            stale.extend(row["id"] for row in active.values())
            if stale:
                self.conn.execute(
                    "UPDATE chunks SET superseded = true WHERE id = ANY(%s)", (stale,)
                )
            result.superseded = len(stale)
        return result

    def _chunks(self, where: str, params: tuple, suffix: str = "") -> list[Chunk]:
        rows = self.conn.execute(
            f"SELECT {_CHUNK_COLUMNS} FROM chunks c JOIN documents d ON d.id = c.document_id "
            f"WHERE {where} {suffix}",
            params,
        ).fetchall()
        return [Chunk(**row) for row in rows]

    def pending_chunks(self, limit: int) -> list[Chunk]:
        return self._chunks(
            "NOT c.superseded AND c.processed_at IS NULL", (limit,), "ORDER BY c.id LIMIT %s"
        )

    def mark_processed(self, chunk_ids: list[int]) -> None:
        if chunk_ids:
            self.conn.execute(
                "UPDATE chunks SET processed_at = now() WHERE id = ANY(%s)", (chunk_ids,)
            )

    def get_chunk(self, chunk_id: int) -> Chunk | None:
        found = self._chunks("c.id = %s", (chunk_id,))
        return found[0] if found else None

    def search_chunks(
        self, embedding: list[float], query_text: str, k: int = 5, regulation: str | None = None
    ) -> list[Chunk]:
        rows = self.conn.execute(
            _HYBRID_SEARCH,
            {
                "embedding": str(embedding),
                "query": query_text,
                "regulation": regulation,
                "pool": max(k * 4, 20),
                "k": k,
            },
        ).fetchall()
        return [Chunk(**row) for row in rows]

    def chunks_created_since(self, since: datetime | None) -> list[Chunk]:
        if since is None:
            return self._chunks("NOT c.superseded", (), "ORDER BY c.id")
        return self._chunks("NOT c.superseded AND c.created_at > %s", (since,), "ORDER BY c.id")

    def add_obligations(self, obligations: list[Obligation]) -> list[Obligation]:
        saved: list[Obligation] = []
        for o in obligations:
            row = self.conn.execute(
                """
                INSERT INTO obligations (chunk_id, regulation, section_ref, title, requirement,
                                         regulation_quote, search_patterns, violation_indicators)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    o.chunk_id,
                    o.regulation,
                    o.section_ref,
                    o.title,
                    o.requirement,
                    o.regulation_quote,
                    Jsonb(o.search_patterns),
                    Jsonb(o.violation_indicators),
                ),
            ).fetchone()
            saved.append(o.model_copy(update={"id": row["id"]}))
        return saved

    def active_obligations(self) -> list[Obligation]:
        rows = self.conn.execute(
            """
            SELECT o.id, o.chunk_id, o.regulation, o.section_ref, o.title, o.requirement,
                   o.regulation_quote, o.search_patterns, o.violation_indicators
            FROM obligations o JOIN chunks c ON c.id = o.chunk_id
            WHERE NOT c.superseded ORDER BY o.id
            """
        ).fetchall()
        return [Obligation(**row) for row in rows]

    def create_run(self, target_repo: str) -> Run:
        row = self.conn.execute(
            "INSERT INTO runs (target_repo) VALUES (%s) RETURNING *", (target_repo,)
        ).fetchone()
        return Run(**row)

    def finish_run(
        self, run_id: int, status: str, input_tokens: int, output_tokens: int, stats: dict
    ) -> Run:
        row = self.conn.execute(
            """
            UPDATE runs SET status = %s, finished_at = now(), input_tokens = %s,
                            output_tokens = %s, stats = %s
            WHERE id = %s RETURNING *
            """,
            (status, input_tokens, output_tokens, Jsonb(stats), run_id),
        ).fetchone()
        return Run(**row)

    def previous_run(self, run_id: int) -> Run | None:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE id < %s AND status = 'completed' ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return Run(**row) if row else None

    def add_findings(self, run_id: int, findings: list[Finding]) -> list[Finding]:
        saved: list[Finding] = []
        for f in findings:
            row = self.conn.execute(
                """
                INSERT INTO findings (run_id, obligation_id, chunk_id, regulation, section_ref,
                    obligation_title, file, line_start, line_end, snippet, severity, confidence,
                    explanation, remediation, regulation_quote, source_url, retrieved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    f.obligation_id,
                    f.chunk_id,
                    f.regulation,
                    f.section_ref,
                    f.obligation_title,
                    f.file,
                    f.line_start,
                    f.line_end,
                    f.snippet,
                    f.severity.value,
                    f.confidence,
                    f.explanation,
                    f.remediation,
                    f.regulation_quote,
                    f.source_url,
                    f.retrieved_at,
                ),
            ).fetchone()
            saved.append(f.model_copy(update={"id": row["id"], "run_id": run_id}))
        return saved

    def findings_for_run(self, run_id: int) -> list[Finding]:
        rows = self.conn.execute(
            "SELECT * FROM findings WHERE run_id = %s ORDER BY id", (run_id,)
        ).fetchall()
        return [Finding(**row) for row in rows]

    def close(self) -> None:
        self.conn.close()
