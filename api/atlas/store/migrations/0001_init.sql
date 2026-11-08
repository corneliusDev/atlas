-- Atlas schema v1. Applied by atlas/store/migrate.py (one transaction per file).
-- Single-writer rule (PRD Output 4):
--   documents, chunks, topics, document_topics, wiki_links, semantic_links, clusters
--       -> IngestPipeline via DocumentRepository / ClusterRepository
--   jobs          -> JobQueue
--   link_feedback -> LinkFeedbackRepository
-- save_document must UPSERT the documents row (ON CONFLICT (vault_id, path) DO UPDATE), never
-- delete+insert, or the ON DELETE CASCADE would wipe link_feedback for that document.

CREATE EXTENSION IF NOT EXISTS vector;

-- Workspace entity of the data model. One row per indexed folder ("vault").
CREATE TABLE vaults (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    root_path   text NOT NULL,                    -- container path, e.g. /vault
    settings    jsonb NOT NULL DEFAULT '{}'::jsonb, -- {"link_threshold": 0.55, "link_top_k": 8}
    created_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO vaults (id, name, root_path)
VALUES ('00000000-0000-0000-0000-000000000001', 'Default vault', '/vault');

CREATE TABLE clusters (
    id          uuid PRIMARY KEY,
    vault_id    uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    label       text,                             -- NULL until label_clusters succeeds
    centroid    vector(768) NOT NULL,
    color       text NOT NULL,                    -- "#rrggbb"
    size        integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX clusters_vault_idx ON clusters (vault_id);

CREATE TABLE documents (
    id             uuid PRIMARY KEY,              -- deterministic: types.document_id_for(vault, path)
    vault_id       uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    path           text NOT NULL,                 -- VaultPath, relative POSIX
    origin         text NOT NULL CHECK (origin IN ('vault', 'upload')),
    content_hash   text NOT NULL,                 -- sha256 hex of file bytes
    version        integer NOT NULL DEFAULT 1,    -- +1 on every successful re-index
    title          text NOT NULL,
    frontmatter    jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary        text,                          -- NULL when LLM failed / embeddings-only
    tags           text[] NOT NULL DEFAULT '{}',
    doc_embedding  vector(768) NOT NULL,
    cluster_id     uuid REFERENCES clusters(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    indexed_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT documents_vault_path_uq UNIQUE (vault_id, path)
);
CREATE INDEX documents_embedding_hnsw ON documents USING hnsw (doc_embedding vector_cosine_ops);
CREATE INDEX documents_tags_gin ON documents USING gin (tags);
CREATE INDEX documents_cluster_idx ON documents (cluster_id);
-- Wikilink resolution: lower(file stem) and lower(title)
CREATE INDEX documents_title_lower_idx ON documents (vault_id, lower(title));

CREATE TABLE chunks (
    id            uuid PRIMARY KEY,               -- deterministic: types.chunk_id_for(doc, ordinal)
    document_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       integer NOT NULL,
    heading_path  text[] NOT NULL DEFAULT '{}',
    heading_text  text NOT NULL DEFAULT '',       -- array_to_string(heading_path, ' > '), for tsv
    text          text NOT NULL,
    embedding     vector(768) NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (
                      setweight(to_tsvector('english', heading_text), 'A') ||
                      setweight(to_tsvector('english', text), 'B')
                  ) STORED,
    CONSTRAINT chunks_doc_ordinal_uq UNIQUE (document_id, ordinal)
);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE topics (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id        uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    canonical_name  text NOT NULL,
    name_key        text NOT NULL,                -- lower(trim(canonical_name)), dedup key
    aliases         text[] NOT NULL DEFAULT '{}', -- lowercased
    kind            text NOT NULL CHECK (kind IN ('concept', 'person', 'org', 'tag')),
    embedding       vector(768),                  -- NULL for kind='tag'
    cluster_id      uuid REFERENCES clusters(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT topics_vault_kind_name_uq UNIQUE (vault_id, kind, name_key)
);
CREATE INDEX topics_embedding_hnsw ON topics USING hnsw (embedding vector_cosine_ops);
CREATE INDEX topics_aliases_gin ON topics USING gin (aliases);

CREATE TABLE document_topics (
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    topic_id     uuid NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    salience     real NOT NULL CHECK (salience >= 0 AND salience <= 1),
    PRIMARY KEY (document_id, topic_id)
);
CREATE INDEX document_topics_topic_idx ON document_topics (topic_id);

-- Explicit [[wikilinks]], stored by target name; resolved at read time (ghost if unresolved).
CREATE TABLE wiki_links (
    id              bigserial PRIMARY KEY,
    source_doc_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_name     text NOT NULL,                -- as written, without .md
    target_key      text NOT NULL,                -- lower(trim(target_name)), for resolution
    anchor          text,                         -- [[Note#Heading]]
    alias           text,                         -- [[Note|alias]]
    ordinal         integer NOT NULL,
    CONSTRAINT wiki_links_src_ord_uq UNIQUE (source_doc_id, ordinal)
);
CREATE INDEX wiki_links_target_idx ON wiki_links (target_key);

-- Semantic doc-doc links. Ordered pair (doc_a < doc_b) = one row per pair.
CREATE TABLE semantic_links (
    vault_id            uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    doc_a               uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    doc_b               uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    score               real NOT NULL CHECK (score >= 0 AND score <= 1),
    reason              text,                     -- NULL until the LLM explains it
    evidence_chunk_ids  uuid[] NOT NULL CHECK (cardinality(evidence_chunk_ids) = 2), -- {chunk of a, chunk of b}; no FK
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_a, doc_b),
    CHECK (doc_a < doc_b)
);
CREATE INDEX semantic_links_b_idx ON semantic_links (doc_b);
CREATE INDEX semantic_links_vault_idx ON semantic_links (vault_id);

-- User verdicts. Written only by LinkFeedbackRepository; re-index never touches it.
CREATE TABLE link_feedback (
    vault_id    uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    doc_a       uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    doc_b       uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    verdict     text NOT NULL CHECK (verdict IN ('confirmed', 'hidden', 'added')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_a, doc_b),
    CHECK (doc_a < doc_b)
);

-- Job queue (FOR UPDATE SKIP LOCKED). payload = IngestJob JSON (types.IngestJob).
CREATE TABLE jobs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id     uuid NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('upsert', 'remove', 'recluster')),
    path         text,                            -- NULL for recluster
    dedup_key    text NOT NULL,                   -- path for file jobs, '__recluster__' for recluster
    payload      jsonb NOT NULL,
    state        text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'done', 'failed')),
    attempts     integer NOT NULL DEFAULT 0,      -- incremented on claim
    run_after    timestamptz NOT NULL DEFAULT now(),
    lease_until  timestamptz,                     -- set while running; expired lease = reclaimable
    outcome      jsonb,                           -- types.IngestOutcome on done
    last_error   jsonb,                           -- types.IngestError on last failure
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    CHECK ((kind = 'recluster') = (path IS NULL))
);
-- At most one pending AND at most one running job per (vault, dedup_key).
-- enqueue: INSERT ... ON CONFLICT (vault_id, dedup_key) WHERE state = 'pending'
--          DO UPDATE SET payload = EXCLUDED.payload, kind = EXCLUDED.kind, run_after = now(), attempts = 0
-- claim:   pick pending rows with run_after <= now() whose dedup_key has no running row
--          (or whose running row's lease expired), FOR UPDATE SKIP LOCKED.
CREATE UNIQUE INDEX jobs_one_pending_uq ON jobs (vault_id, dedup_key) WHERE state = 'pending';
CREATE UNIQUE INDEX jobs_one_running_uq ON jobs (vault_id, dedup_key) WHERE state = 'running';
CREATE INDEX jobs_claim_idx ON jobs (run_after) WHERE state = 'pending';
CREATE INDEX jobs_state_updated_idx ON jobs (state, updated_at DESC);
CREATE INDEX jobs_vault_path_idx ON jobs (vault_id, path, created_at DESC);
