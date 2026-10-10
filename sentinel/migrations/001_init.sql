CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    name            text PRIMARY KEY,
    adapter         text NOT NULL,
    regulation      text NOT NULL,
    url             text NOT NULL,
    last_scraped_at timestamptz
);

-- One row per fetched version of a source document. A re-scrape that returns
-- identical bytes matches on content_hash and inserts nothing.
CREATE TABLE IF NOT EXISTS documents (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text NOT NULL REFERENCES sources (name),
    key           text NOT NULL,
    regulation    text NOT NULL,
    url           text NOT NULL,
    title         text NOT NULL,
    content_hash  text NOT NULL,
    snapshot_path text NOT NULL DEFAULT '',
    retrieved_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, key, content_hash)
);
CREATE INDEX IF NOT EXISTS documents_source_key_idx ON documents (source, key, retrieved_at DESC);

CREATE TABLE IF NOT EXISTS chunks (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  bigint NOT NULL REFERENCES documents (id),
    source       text NOT NULL,
    doc_key      text NOT NULL,
    regulation   text NOT NULL,
    section_ref  text NOT NULL,
    title        text NOT NULL DEFAULT '',
    text         text NOT NULL,
    text_hash    text NOT NULL,
    kind         text NOT NULL DEFAULT 'rule',
    embedding    vector(384) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED,
    superseded   boolean NOT NULL DEFAULT false,
    processed_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_active_idx ON chunks (source, doc_key, section_ref) WHERE NOT superseded;
CREATE INDEX IF NOT EXISTS chunks_pending_idx ON chunks (id) WHERE NOT superseded AND processed_at IS NULL;

CREATE TABLE IF NOT EXISTS obligations (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id             bigint NOT NULL REFERENCES chunks (id),
    regulation           text NOT NULL,
    section_ref          text NOT NULL,
    title                text NOT NULL,
    requirement          text NOT NULL,
    regulation_quote     text NOT NULL,
    search_patterns      jsonb NOT NULL DEFAULT '[]',
    violation_indicators jsonb NOT NULL DEFAULT '[]',
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS obligations_chunk_idx ON obligations (chunk_id);

CREATE TABLE IF NOT EXISTS runs (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text NOT NULL DEFAULT 'running',
    target_repo   text NOT NULL DEFAULT '',
    input_tokens  bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    stats         jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS findings (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           bigint NOT NULL REFERENCES runs (id),
    obligation_id    bigint NOT NULL REFERENCES obligations (id),
    chunk_id         bigint NOT NULL REFERENCES chunks (id),
    regulation       text NOT NULL,
    section_ref      text NOT NULL,
    obligation_title text NOT NULL,
    file             text NOT NULL,
    line_start       integer NOT NULL,
    line_end         integer NOT NULL,
    snippet          text NOT NULL,
    severity         text NOT NULL,
    confidence       numeric(3, 2) NOT NULL,
    explanation      text NOT NULL,
    remediation      text NOT NULL,
    regulation_quote text NOT NULL,
    source_url       text NOT NULL DEFAULT '',
    retrieved_at     timestamptz
);
CREATE INDEX IF NOT EXISTS findings_run_idx ON findings (run_id);
