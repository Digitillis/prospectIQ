-- Migration 022: Lookalike Discovery runs table
-- Stores each lookalike discovery run with its seed profile and match results.

CREATE TABLE IF NOT EXISTS lookalike_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL,
    seed_company_ids JSONB NOT NULL DEFAULT '[]',
    seed_profile    JSONB NOT NULL DEFAULT '{}',
    matches         JSONB NOT NULL DEFAULT '[]',
    total_scored    INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lookalike_runs_workspace
    ON lookalike_runs(workspace_id, created_at DESC);
