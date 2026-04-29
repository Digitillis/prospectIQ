-- Migration 004: Intelligence confidence lifecycle
-- Adds confidence scoring + evidence tracking to learning_outcomes,
-- and creates the intelligence_evidence table for evidence accumulation.
-- Phase 2: Intelligence Confidence Lifecycle

-- Add confidence lifecycle columns to learning_outcomes
ALTER TABLE learning_outcomes
    ADD COLUMN IF NOT EXISTS confidence_level TEXT DEFAULT 'hypothesis'
        CHECK (confidence_level IN ('hypothesis', 'validated', 'proven')),
    ADD COLUMN IF NOT EXISTS evidence_count    INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_count     INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_evidence_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS segment          TEXT,
    ADD COLUMN IF NOT EXISTS channel          TEXT CHECK (channel IN ('email', 'linkedin', 'both', NULL)),
    ADD COLUMN IF NOT EXISTS insight_summary  TEXT,
    ADD COLUMN IF NOT EXISTS bias_flagged     BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS promoted_at      TIMESTAMPTZ;

-- Evidence trail for each learning outcome
CREATE TABLE IF NOT EXISTS intelligence_evidence (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outcome_id     UUID NOT NULL REFERENCES learning_outcomes(id) ON DELETE CASCADE,
    source_type    TEXT NOT NULL CHECK (source_type IN ('ab_winner', 'reply_positive', 'reply_converted', 'meeting_booked', 'manual')),
    source_ref     TEXT,       -- e.g. sequence_id, thread_id, contact_id
    signal_text    TEXT,       -- human-readable description of the signal
    workspace_id   UUID,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intelligence_evidence_outcome ON intelligence_evidence(outcome_id);
CREATE INDEX IF NOT EXISTS idx_intelligence_evidence_workspace ON intelligence_evidence(workspace_id);
CREATE INDEX IF NOT EXISTS idx_learning_outcomes_confidence ON learning_outcomes(confidence_level, workspace_id);
CREATE INDEX IF NOT EXISTS idx_learning_outcomes_channel ON learning_outcomes(channel, workspace_id);
