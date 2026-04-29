-- Migration 008: Supabase RPC functions for memory store vector + text search
-- These functions are called via db.client.rpc() from memory_store.py.
-- Run AFTER migration 005 (pgvector extension must be enabled first).

-- Vector cosine similarity search (used when Voyage AI key is configured)
CREATE OR REPLACE FUNCTION match_memory_nodes(
    query_embedding vector(1024),
    workspace_filter UUID,
    match_count      INT DEFAULT 5
)
RETURNS TABLE (
    id          UUID,
    content     TEXT,
    source_ref  TEXT,
    distance    FLOAT
)
LANGUAGE SQL STABLE
AS $$
    SELECT
        id,
        content,
        source_ref,
        embedding <=> query_embedding AS distance
    FROM memory_nodes
    WHERE
        workspace_id = workspace_filter
        AND embedding IS NOT NULL
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

-- Full-text search fallback (used when no Voyage AI key)
CREATE OR REPLACE FUNCTION match_memory_nodes_text(
    search_query    TEXT,
    workspace_filter UUID,
    match_count     INT DEFAULT 5
)
RETURNS TABLE (
    id         UUID,
    content    TEXT,
    source_ref TEXT,
    rank       FLOAT
)
LANGUAGE SQL STABLE
AS $$
    SELECT
        id,
        content,
        source_ref,
        ts_rank(to_tsvector('english', content), to_tsquery('english', search_query)) AS rank
    FROM memory_nodes
    WHERE
        workspace_id = workspace_filter
        AND to_tsvector('english', content) @@ to_tsquery('english', search_query)
    ORDER BY rank DESC
    LIMIT match_count;
$$;

-- Access count incrementer (called after each retrieval)
CREATE OR REPLACE FUNCTION increment_memory_access(
    node_id     UUID,
    accessed_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS VOID
LANGUAGE SQL
AS $$
    UPDATE memory_nodes
    SET
        access_count     = access_count + 1,
        last_accessed_at = accessed_at
    WHERE id = node_id;
$$;
