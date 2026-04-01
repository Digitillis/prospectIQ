-- ProspectIQ Migration 013: Analytics Layer
-- Adds A/B test event tracking and analytics snapshot cache.
-- All statements are idempotent (IF NOT EXISTS guards throughout).

-- ============================================================
-- 1. ab_test_events — email A/B test event tracking
-- ============================================================

CREATE TABLE IF NOT EXISTS ab_test_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id    UUID REFERENCES contacts(id) ON DELETE CASCADE,
    sequence_id   TEXT NOT NULL,
    variant       TEXT NOT NULL CHECK (variant IN ('a', 'b')),
    subject_line  TEXT,
    event_type    TEXT NOT NULL CHECK (event_type IN ('sent', 'opened', 'replied')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Lookup by sequence + variant + event for stats aggregation
CREATE INDEX IF NOT EXISTS idx_ab_sequence
    ON ab_test_events (sequence_id, variant, event_type);

-- Lookup by contact for reply/open attribution
CREATE INDEX IF NOT EXISTS idx_ab_contact
    ON ab_test_events (contact_id, event_type, created_at DESC);

-- ============================================================
-- 2. analytics_snapshots — cached analytics results
-- ============================================================
-- Stores pre-computed analytics payloads (weekly reports, funnel snapshots,
-- hot account lists) so the dashboard can load instantly without re-querying.

CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_type  TEXT NOT NULL,    -- 'weekly_report' | 'funnel' | 'hot_accounts'
    campaign_name  TEXT,
    data           JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Most-recent snapshot retrieval per type + campaign
CREATE INDEX IF NOT EXISTS idx_snapshots_type
    ON analytics_snapshots (snapshot_type, campaign_name, created_at DESC);
