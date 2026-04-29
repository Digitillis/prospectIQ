-- Migration 007: LinkedIn provider rate limit tracking
-- DB-backed token bucket for per-workspace, per-provider daily limits.
-- Phase 1: LinkedIn outreach completion

CREATE TABLE IF NOT EXISTS provider_rate_limits (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL,
    provider         TEXT NOT NULL CHECK (provider IN ('linkedin_connect', 'linkedin_dm', 'email')),
    tokens_used      INTEGER DEFAULT 0,
    daily_limit      INTEGER NOT NULL,
    window_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (workspace_id, provider, window_date)
);

CREATE INDEX IF NOT EXISTS idx_provider_rate_limits_lookup
    ON provider_rate_limits(workspace_id, provider, window_date);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_provider_rate_limits_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_provider_rate_limits_updated_at ON provider_rate_limits;
CREATE TRIGGER trg_provider_rate_limits_updated_at
    BEFORE UPDATE ON provider_rate_limits
    FOR EACH ROW EXECUTE FUNCTION update_provider_rate_limits_updated_at();
