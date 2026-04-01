-- CMDB initialization SQL
-- Runs automatically on first postgres container boot via /docker-entrypoint-initdb.d/

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE hosts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname    TEXT        NOT NULL UNIQUE,
    agent_id    TEXT        NOT NULL UNIQUE,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE config_files (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id     UUID        NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    file_path   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (host_id, file_path)
);

-- Content-addressable storage: identical content is stored exactly once
CREATE TABLE file_contents (
    hash        TEXT        PRIMARY KEY,   -- SHA-256 hex (64 chars)
    content     BYTEA       NOT NULL,
    size        BIGINT      NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE snapshots (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    config_file_id  UUID        NOT NULL REFERENCES config_files(id) ON DELETE CASCADE,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    file_hash       TEXT        NOT NULL,   -- SHA-256 from agent (same value as content_hash)
    file_size       BIGINT      NOT NULL,   -- denormalized for fast listing queries
    content_hash    TEXT        NOT NULL REFERENCES file_contents(hash)
);

CREATE INDEX idx_snapshots_config_file_id ON snapshots(config_file_id);
CREATE INDEX idx_snapshots_submitted_at   ON snapshots(submitted_at DESC);
CREATE INDEX idx_snapshots_content_hash   ON snapshots(content_hash);
