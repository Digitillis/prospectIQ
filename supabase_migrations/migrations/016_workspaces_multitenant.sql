-- Migration 016: Multi-tenancy foundation
-- Adds workspaces table and workspace_id to all core tables
-- SAFE: workspace_id is nullable so existing pipeline keeps running
-- After backfill completes, enforce NOT NULL in migration 017

-- ============================================================
-- WORKSPACES TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,  -- URL-safe identifier, e.g. "digitillis"
    owner_email TEXT NOT NULL,

    -- Tier controls feature access
    tier TEXT NOT NULL DEFAULT 'starter',  -- starter | growth | scale | api
    tier_changed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Billing
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    subscription_status TEXT DEFAULT 'trialing',  -- trialing | active | past_due | canceled
    trial_ends_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '14 days'),

    -- Settings
    settings JSONB DEFAULT '{}'::jsonb,

    -- Limits (tier-based, can override per workspace)
    monthly_research_limit INTEGER DEFAULT 500,
    monthly_outreach_limit INTEGER DEFAULT 1000,
    seats_limit INTEGER DEFAULT 1,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- WORKSPACE MEMBERS
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,           -- Supabase auth.users.id
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',  -- owner | admin | member | viewer
    invited_by UUID,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace ON workspace_members(workspace_id);

-- ============================================================
-- WORKSPACE API KEYS (for pipeline scripts)
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace_api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,              -- e.g. "Pipeline Key", "CI Key"
    key_hash TEXT NOT NULL UNIQUE,  -- SHA-256 of the actual key (never stored raw)
    key_prefix TEXT NOT NULL,       -- First 8 chars shown in UI, e.g. "piq_live"
    scopes TEXT[] DEFAULT ARRAY['read', 'write'],
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ          -- NULL = active
);

CREATE INDEX IF NOT EXISTS idx_api_keys_workspace ON workspace_api_keys(workspace_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON workspace_api_keys(key_hash);

-- ============================================================
-- ADD workspace_id TO ALL CORE TABLES (nullable for safety)
-- ============================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE outreach_drafts
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE interactions
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE engagement_sequences
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE action_queue
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE api_costs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE do_not_contact
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE learning_outcomes
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE company_intent_signals
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE content_archive
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

-- Tables that may not exist in all deployments — use conditional approach
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'research_intelligence') THEN
        ALTER TABLE research_intelligence
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'contact_events') THEN
        ALTER TABLE contact_events
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'outreach_state_log') THEN
        ALTER TABLE outreach_state_log
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'action_requests') THEN
        ALTER TABLE action_requests
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'health_snapshots') THEN
        ALTER TABLE health_snapshots
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_runs') THEN
        ALTER TABLE pipeline_runs
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_errors') THEN
        ALTER TABLE pipeline_errors
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'campaign_sequence_definitions') THEN
        ALTER TABLE campaign_sequence_definitions
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'daily_targets') THEN
        ALTER TABLE daily_targets
            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ============================================================
-- INDEXES ON workspace_id (for query performance)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_companies_workspace ON companies(workspace_id);
CREATE INDEX IF NOT EXISTS idx_contacts_workspace ON contacts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_outreach_drafts_workspace ON outreach_drafts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_interactions_workspace ON interactions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_api_costs_workspace ON api_costs(workspace_id);

-- ============================================================
-- DEFAULT WORKSPACE — backfill for existing single-tenant data
-- ============================================================

-- Insert the default workspace (Digitillis / Avanish's workspace)
INSERT INTO workspaces (id, name, slug, owner_email, tier, subscription_status, settings)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Digitillis',
    'digitillis',
    'avi@digitillis.com',
    'scale',
    'active',
    '{"is_default": true}'::jsonb
)
ON CONFLICT (id) DO NOTHING;

-- Backfill all existing rows with the default workspace ID
UPDATE companies    SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE contacts     SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE outreach_drafts SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE interactions SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE api_costs    SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE do_not_contact SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'research_intelligence') THEN
        UPDATE research_intelligence SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'content_archive') THEN
        UPDATE content_archive SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'engagement_sequences') THEN
        UPDATE engagement_sequences SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'action_queue') THEN
        UPDATE action_queue SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'learning_outcomes') THEN
        UPDATE learning_outcomes SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'company_intent_signals') THEN
        UPDATE company_intent_signals SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'health_snapshots') THEN
        UPDATE health_snapshots SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_runs') THEN
        UPDATE pipeline_runs SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'daily_targets') THEN
        UPDATE daily_targets SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
END $$;

-- ============================================================
-- updated_at trigger for workspaces
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS workspaces_updated_at ON workspaces;
CREATE TRIGGER workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
