-- Migration 050: Workflow Events Foundation
--
-- Establishes the append-only workflow_events table.
-- Every significant lifecycle state transition — draft approval, rejection,
-- send, suppression — gets a row here so we can answer "what happened
-- and why?" deterministically, even months later.
--
-- Intentionally minimal:
--   * No context_packet_id or policy_snapshot_id columns — those reference
--     tables created in later migrations (PR E, PR F). They will be added
--     via ALTER TABLE once those tables exist, avoiding the dual-column
--     confusion introduced in the PR #99 draft.
--   * No backfill — historical events before this migration are absent from
--     the table; that is acceptable and expected.
--   * Append-only enforced at the DB level via PostgreSQL RULE so no UPDATE
--     or DELETE can silently corrupt the audit trail from Python or SQL.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

CREATE TABLE IF NOT EXISTS workflow_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL,

    -- What entity transitioned
    -- Values: draft | contact | company | sequence | suppression
    entity_type     TEXT        NOT NULL,
    entity_id       UUID        NOT NULL,

    -- The transition itself
    -- Values: draft.approved | draft.edited | draft.rejected | draft.sent |
    --         contact.suppressed | company.suppressed | sequence.paused | etc.
    event_type      TEXT        NOT NULL,
    from_state      TEXT,                  -- null for creation events
    to_state        TEXT,

    -- Who or what triggered this transition
    -- actor_type values: system | human | webhook | operator_script
    actor_type      TEXT        NOT NULL DEFAULT 'system',
    actor_id        TEXT,                  -- user_id UUID string, job name, or 'system'
    triggered_by    TEXT,                  -- endpoint path, job name, or script name

    -- Arbitrary context (rejection reason, attestation flags, assertion results, etc.)
    metadata        JSONB       NOT NULL DEFAULT '{}',

    -- Immutable — no updated_at column intentionally
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- APPEND-ONLY RULES
-- These fire at the Postgres level so no UPDATE or DELETE can
-- reach workflow_events regardless of which client issued them.
-- ============================================================

CREATE OR REPLACE RULE workflow_events_no_update AS
    ON UPDATE TO workflow_events DO INSTEAD NOTHING;

CREATE OR REPLACE RULE workflow_events_no_delete AS
    ON DELETE TO workflow_events DO INSTEAD NOTHING;

-- ============================================================
-- INDEXES
-- ============================================================

-- Primary access pattern: "show me all events for draft X"
CREATE INDEX IF NOT EXISTS idx_workflow_events_entity
    ON workflow_events (entity_type, entity_id, created_at DESC);

-- Dashboard / ops: "show me all recent events in this workspace"
CREATE INDEX IF NOT EXISTS idx_workflow_events_workspace_recent
    ON workflow_events (workspace_id, created_at DESC);

-- Reviewer audit: "show me everything a specific human did"
CREATE INDEX IF NOT EXISTS idx_workflow_events_actor_human
    ON workflow_events (actor_id, created_at DESC)
    WHERE actor_type = 'human';

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON workflow_events
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );
