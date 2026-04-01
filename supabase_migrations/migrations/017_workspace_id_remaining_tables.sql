-- Migration 017: workspace_id for remaining tables + NOT NULL enforcement
-- Covers tables missed in migration 016:
--   ab_test_events, analytics_snapshots, linkedin_touchpoints, outreach_pace_log
-- Also enforces NOT NULL on the tables backfilled in migration 016.
-- SAFE: all ALTER COLUMN ... SET NOT NULL run after confirming no NULL rows.

-- ============================================================
-- 1. ADD workspace_id TO REMAINING TABLES
-- ============================================================

ALTER TABLE ab_test_events
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE analytics_snapshots
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE linkedin_touchpoints
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

ALTER TABLE outreach_pace_log
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

-- ============================================================
-- 2. BACKFILL NEW COLUMNS WITH DEFAULT WORKSPACE
-- ============================================================

UPDATE ab_test_events
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;

UPDATE analytics_snapshots
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;

UPDATE linkedin_touchpoints
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;

UPDATE outreach_pace_log
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;

-- ============================================================
-- 3. BACKFILL ANY REMAINING NULLS FROM MIGRATION 016
--    (safety net in case 016 ran before rows were inserted)
-- ============================================================

UPDATE companies              SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE contacts               SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE outreach_drafts        SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE interactions           SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE api_costs              SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE do_not_contact         SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE engagement_sequences   SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE action_queue           SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE learning_outcomes      SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE company_intent_signals SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
UPDATE content_archive        SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'research_intelligence') THEN
        UPDATE research_intelligence SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'contact_events') THEN
        UPDATE contact_events SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'outreach_state_log') THEN
        UPDATE outreach_state_log SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'action_requests') THEN
        UPDATE action_requests SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'health_snapshots') THEN
        UPDATE health_snapshots SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_runs') THEN
        UPDATE pipeline_runs SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_errors') THEN
        UPDATE pipeline_errors SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'campaign_sequence_definitions') THEN
        UPDATE campaign_sequence_definitions SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'daily_targets') THEN
        UPDATE daily_targets SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
    END IF;
END $$;

-- ============================================================
-- 4. ENFORCE NOT NULL ON CORE TABLES
--    (safe now that all rows have been backfilled)
-- ============================================================

ALTER TABLE companies              ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE contacts               ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE outreach_drafts        ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE interactions           ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE api_costs              ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE do_not_contact         ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE engagement_sequences   ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE action_queue           ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE learning_outcomes      ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE company_intent_signals ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE content_archive        ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE ab_test_events         ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE analytics_snapshots    ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE linkedin_touchpoints   ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE outreach_pace_log      ALTER COLUMN workspace_id SET NOT NULL;

-- Conditional NOT NULL for tables that may not exist in all deployments
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'research_intelligence') THEN
        ALTER TABLE research_intelligence ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'contact_events') THEN
        ALTER TABLE contact_events ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'outreach_state_log') THEN
        ALTER TABLE outreach_state_log ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'action_requests') THEN
        ALTER TABLE action_requests ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'health_snapshots') THEN
        ALTER TABLE health_snapshots ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_runs') THEN
        ALTER TABLE pipeline_runs ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pipeline_errors') THEN
        ALTER TABLE pipeline_errors ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'campaign_sequence_definitions') THEN
        ALTER TABLE campaign_sequence_definitions ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'daily_targets') THEN
        ALTER TABLE daily_targets ALTER COLUMN workspace_id SET NOT NULL;
    END IF;
END $$;

-- ============================================================
-- 5. INDEXES ON NEW workspace_id COLUMNS
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_ab_test_events_workspace      ON ab_test_events (workspace_id);
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_workspace  ON analytics_snapshots (workspace_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_touchpoints_workspace ON linkedin_touchpoints (workspace_id);
CREATE INDEX IF NOT EXISTS idx_outreach_pace_log_workspace    ON outreach_pace_log (workspace_id);
