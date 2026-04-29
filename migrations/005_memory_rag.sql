-- Migration 005: Memory / RAG layer
-- Enables pgvector extension and creates knowledge_items + memory_nodes tables.
-- Phase 3: Memory / RAG Layer
--
-- NOTE: pgvector must be enabled in Supabase dashboard first:
--   Database → Extensions → vector → Enable
-- The CREATE EXTENSION line below is idempotent and safe to run after enabling.

CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge items: documents uploaded by users (ICP docs, case studies, templates, etc.)
CREATE TABLE IF NOT EXISTS knowledge_items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    title        TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('icp', 'template', 'competitor', 'case_study', 'offer', 'general')),
    content      TEXT NOT NULL,
    char_count   INTEGER GENERATED ALWAYS AS (char_length(content)) STORED,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Memory nodes: chunked + embedded fragments of knowledge items
-- Falls back to full-text search when embedding is NULL (no Voyage AI key configured).
CREATE TABLE IF NOT EXISTS memory_nodes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL,
    knowledge_item_id UUID REFERENCES knowledge_items(id) ON DELETE CASCADE,
    content          TEXT NOT NULL,
    content_hash     TEXT NOT NULL,          -- SHA-256 of content; skip re-embedding identical text
    embedding        vector(1024),            -- Voyage AI voyage-3-lite dimension
    source_ref       TEXT,                   -- pointer back to source (item id, chunk index)
    confidence       FLOAT DEFAULT 1.0,
    access_count     INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Full-text search index for fallback when embeddings not available
CREATE INDEX IF NOT EXISTS idx_memory_nodes_fts ON memory_nodes
    USING GIN (to_tsvector('english', content));

-- Vector similarity index (IVFFlat; created when embeddings exist)
-- This index is created separately after first embeddings are inserted:
--   CREATE INDEX idx_memory_nodes_embedding ON memory_nodes
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_memory_nodes_workspace ON memory_nodes(workspace_id);
CREATE INDEX IF NOT EXISTS idx_memory_nodes_hash ON memory_nodes(content_hash, workspace_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_workspace ON knowledge_items(workspace_id, type);

-- Auto-update updated_at on knowledge_items
CREATE OR REPLACE FUNCTION update_knowledge_items_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_knowledge_items_updated_at ON knowledge_items;
CREATE TRIGGER trg_knowledge_items_updated_at
    BEFORE UPDATE ON knowledge_items
    FOR EACH ROW EXECUTE FUNCTION update_knowledge_items_updated_at();
