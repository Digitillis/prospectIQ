-- Migration 049: Review Manifests
-- Implements the deterministic review queue guarantee system.
-- Every batch fetch creates an immutable manifest; approvals are validated
-- against that manifest before writing to prevent stale-position writes.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-13

-- Review manifests table
CREATE TABLE IF NOT EXISTS review_manifests (
    manifest_id         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID            NOT NULL,
    batch_size          INTEGER         NOT NULL,
    batch_offset        INTEGER         NOT NULL DEFAULT 0,
    sort_key            TEXT            NOT NULL DEFAULT 'company_name_asc_last_name_asc',

    -- Ordered list of draft IDs at fetch time (positionally significant)
    draft_ids           JSONB           NOT NULL,

    -- sha256 hash of each draft's body at fetch time, keyed by draft_id
    content_hashes      JSONB           NOT NULL,

    -- Lifecycle timestamps
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    approved_at         TIMESTAMPTZ,
    approved_by         TEXT,

    -- Per-draft approval decisions and actions
    approval_decisions  JSONB,

    -- Status: open | applied | expired | invalidated
    status              TEXT            NOT NULL DEFAULT 'open',

    -- Human-readable description of invalidation reason (if status=invalidated)
    invalidation_reason TEXT,

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_review_manifests_workspace
    ON review_manifests (workspace_id, fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_manifests_status
    ON review_manifests (workspace_id, status)
    WHERE status = 'open';

-- RLS: workspace-scoped access
ALTER TABLE review_manifests ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON review_manifests
    FOR ALL
    USING (workspace_id = current_setting('app.workspace_id', true)::uuid OR
           current_setting('app.workspace_id', true) IS NULL OR
           current_setting('app.workspace_id', true) = '');

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_review_manifests_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER review_manifests_updated_at
    BEFORE UPDATE ON review_manifests
    FOR EACH ROW EXECUTE FUNCTION update_review_manifests_updated_at();
