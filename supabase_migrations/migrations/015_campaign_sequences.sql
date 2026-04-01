-- Migration 015: Campaign Sequence Definitions + Pipeline Monitoring
-- Run: psql $DATABASE_URL -f supabase_migrations/migrations/015_campaign_sequences.sql
-- Or apply via Supabase dashboard SQL editor.

-- ============================================================
-- 1. Custom sequence definitions (DB-backed, overrides YAML)
-- ============================================================

CREATE TABLE IF NOT EXISTS campaign_sequence_definitions (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,   -- snake_case key matching sequences.yaml names
    display_name TEXT NOT NULL,
    description  TEXT,
    channel      TEXT NOT NULL DEFAULT 'email'
                     CHECK (channel IN ('email', 'linkedin', 'mixed')),
    steps        JSONB NOT NULL DEFAULT '[]',
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_csd_name ON campaign_sequence_definitions (name);
CREATE INDEX IF NOT EXISTS idx_csd_active ON campaign_sequence_definitions (is_active);

-- ============================================================
-- 2. Pipeline monitoring — agent run log
-- Every pipeline script run is recorded here for observability.
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agent        TEXT NOT NULL,        -- 'research', 'qualification', 'enrichment', 'outreach', 'engagement'
    batch_id     TEXT,                 -- Optional batch identifier
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'completed', 'failed', 'partial')),
    processed    INTEGER DEFAULT 0,
    skipped      INTEGER DEFAULT 0,
    errors       INTEGER DEFAULT 0,
    cost_usd     NUMERIC(10, 4),       -- Claude API cost for this run (if applicable)
    error_detail TEXT,                 -- Last error message if status=failed
    meta         JSONB DEFAULT '{}'   -- Extra context (tiers processed, limits, etc.)
);

CREATE INDEX IF NOT EXISTS idx_pr_agent ON pipeline_runs (agent, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pr_status ON pipeline_runs (status);
CREATE INDEX IF NOT EXISTS idx_pr_batch ON pipeline_runs (batch_id) WHERE batch_id IS NOT NULL;

-- ============================================================
-- 3. Error tracking — individual failures during pipeline runs
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_errors (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    run_id       UUID REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    agent        TEXT NOT NULL,
    company_id   UUID REFERENCES companies(id) ON DELETE SET NULL,
    error_type   TEXT,                 -- e.g. 'api_timeout', 'parse_error', 'suppressed'
    error_msg    TEXT,
    stack_trace  TEXT,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved     BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_pe_run ON pipeline_errors (run_id);
CREATE INDEX IF NOT EXISTS idx_pe_agent ON pipeline_errors (agent, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_pe_unresolved ON pipeline_errors (resolved) WHERE resolved = false;

-- ============================================================
-- 4. API cost tracking — extend existing api_costs if present
-- ============================================================

-- api_costs already exists from initial schema; this adds a pipeline_run_id FK
-- so you can tie cost to a specific run. Safe to run even if column already exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_costs')
    AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'api_costs' AND column_name = 'pipeline_run_id'
    ) THEN
        ALTER TABLE api_costs ADD COLUMN pipeline_run_id UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL;
        CREATE INDEX idx_ac_run ON api_costs (pipeline_run_id) WHERE pipeline_run_id IS NOT NULL;
    END IF;
END
$$;

-- ============================================================
-- 5. Health check snapshot — periodic system health summary
-- Written by the monitoring agent every 15 minutes.
-- ============================================================

CREATE TABLE IF NOT EXISTS health_snapshots (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Pipeline state
    companies_total     INTEGER,
    companies_researched INTEGER,
    companies_qualified  INTEGER,
    contacts_enriched   INTEGER,
    drafts_pending      INTEGER,
    drafts_approved     INTEGER,
    drafts_sent         INTEGER,

    -- Cost
    total_cost_usd      NUMERIC(10, 4),

    -- Research pipeline health
    research_running    BOOLEAN,
    last_research_at    TIMESTAMPTZ,
    last_error_at       TIMESTAMPTZ,
    error_count_24h     INTEGER,

    -- Send gate
    send_enabled        BOOLEAN,

    meta                JSONB DEFAULT '{}'
);

-- Keep only the last 7 days of snapshots (older ones auto-delete via cron or manually)
CREATE INDEX IF NOT EXISTS idx_hs_time ON health_snapshots (captured_at DESC);
