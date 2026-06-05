-- Migration 050: Schema Hardening — Phase 1
--
-- Three schema-level invariants that close the highest-priority gaps identified
-- in the architectural failure analysis (ARCHITECTURE_FAILURE_ANALYSIS.md):
--
-- 1. workflow_events — immutable audit log for every lifecycle state transition.
--    Replaces scattered UPDATE calls to outreach_drafts.approval_status as the
--    source of truth for "what happened and why." No UPDATE/DELETE allowed.
--
-- 2. provider_events — idempotent webhook intake table.
--    Stops double-counting of opens/clicks by deduplicating on (provider, event_id).
--    Decouples raw webhook ingestion from business-logic projection.
--
-- 3. Duplicate-draft prevention — partial UNIQUE index on outreach_drafts.
--    Prevents two active (non-rejected) drafts existing simultaneously for the
--    same contact+step, closing the scheduler race condition.
--
-- 4. Post-send immutability trigger on outreach_drafts.
--    Once sent_at IS NOT NULL, body and subject are frozen. Closes the audit
--    hole exploited by the operator scripts (now disabled).
--
-- 5. policy_snapshots — point-in-time capture of active send limits and rules.
--    Every approval or auto-decision references a snapshot_id so the exact
--    policy that governed the decision is preserved.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

-- ============================================================
-- 1. WORKFLOW EVENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS workflow_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL,

    -- What transitioned
    entity_type     TEXT        NOT NULL,  -- draft | contact | company | sequence | suppression
    entity_id       UUID        NOT NULL,

    -- The transition
    event_type      TEXT        NOT NULL,  -- e.g. draft.approved, draft.sent, contact.suppressed
    from_state      TEXT,                  -- null for creation events
    to_state        TEXT,

    -- Who or what caused it
    actor_type      TEXT        NOT NULL,  -- system | human | webhook | operator_script
    actor_id        TEXT,                  -- user_id, job name, or 'system'
    triggered_by    TEXT,                  -- endpoint path, job name, or script name

    -- Context at decision time (FK will be added when context_packets table exists)
    context_packet_id   UUID,

    -- Policy snapshot active at decision time
    policy_snapshot_id  UUID,

    -- Arbitrary extra data (reason codes, assertion results, etc.)
    metadata        JSONB       NOT NULL DEFAULT '{}',

    -- Immutable — no updated_at
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- No UPDATE or DELETE on workflow_events — it is an append-only log
CREATE OR REPLACE RULE workflow_events_no_update AS
    ON UPDATE TO workflow_events DO INSTEAD NOTHING;

CREATE OR REPLACE RULE workflow_events_no_delete AS
    ON DELETE TO workflow_events DO INSTEAD NOTHING;

-- Indexes for the most common access patterns
CREATE INDEX IF NOT EXISTS idx_workflow_events_entity
    ON workflow_events (entity_type, entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_events_workspace_recent
    ON workflow_events (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_events_actor
    ON workflow_events (actor_type, actor_id, created_at DESC)
    WHERE actor_type = 'human';

-- RLS
ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON workflow_events
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 2. PROVIDER EVENTS (idempotent webhook intake)
-- ============================================================

CREATE TABLE IF NOT EXISTS provider_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL,

    -- Deduplication key — (provider, provider_event_id) must be unique
    provider        TEXT        NOT NULL,  -- resend | instantly
    provider_event_id TEXT      NOT NULL,  -- Resend: event.data.email_id + type; Instantly: event_id

    -- What happened
    event_type      TEXT        NOT NULL,  -- email_delivered | email_opened | email_bounced | etc.
    recipient_email TEXT,

    -- Denormalized for fast joins — populated during intake processing
    contact_id      UUID,
    company_id      UUID,

    -- The full raw payload — never truncated
    raw_payload     JSONB       NOT NULL DEFAULT '{}',

    -- Processing lifecycle
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,           -- set when business-logic projection runs
    processing_error TEXT,                 -- set if projection failed; null on success

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The core deduplication constraint
CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_events_dedup
    ON provider_events (provider, provider_event_id);

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_provider_events_contact
    ON provider_events (contact_id, received_at DESC)
    WHERE contact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_provider_events_unprocessed
    ON provider_events (received_at ASC)
    WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_provider_events_workspace
    ON provider_events (workspace_id, received_at DESC);

-- RLS
ALTER TABLE provider_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON provider_events
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 3. DUPLICATE-DRAFT PREVENTION
-- ============================================================

-- Only one non-rejected draft may exist per (workspace, contact, sequence, step).
-- 'rejected' is the only terminal state that allows a replacement draft to be created.
-- This closes the scheduler race condition where two workers could both generate
-- step-2 drafts for the same contact simultaneously.
CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_drafts_unique_active_step
    ON outreach_drafts (workspace_id, contact_id, sequence_name, sequence_step)
    WHERE approval_status NOT IN ('rejected');


-- ============================================================
-- 4. POST-SEND BODY/SUBJECT IMMUTABILITY
-- ============================================================

-- Once a draft has been sent (sent_at IS NOT NULL), body and subject are frozen.
-- Any attempt to modify them raises an exception. This closes the audit hole
-- where operator scripts could silently edit delivered message content.
CREATE OR REPLACE FUNCTION enforce_draft_immutability()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.sent_at IS NOT NULL THEN
        IF NEW.body IS DISTINCT FROM OLD.body THEN
            RAISE EXCEPTION
                'outreach_drafts: body is immutable after send (draft_id=%)', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF NEW.subject IS DISTINCT FROM OLD.subject THEN
            RAISE EXCEPTION
                'outreach_drafts: subject is immutable after send (draft_id=%)', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_immutability ON outreach_drafts;
CREATE TRIGGER trg_draft_immutability
    BEFORE UPDATE ON outreach_drafts
    FOR EACH ROW EXECUTE FUNCTION enforce_draft_immutability();


-- ============================================================
-- 5. POLICY SNAPSHOTS
-- ============================================================

-- Point-in-time capture of the active send limits and governance rules.
-- Every approval decision and every autonomous send references a snapshot_id
-- so the exact policy that governed the action is permanently preserved.
CREATE TABLE IF NOT EXISTS policy_snapshots (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL,

    -- Monotonically increasing within a workspace — used for "latest policy" queries
    version         INTEGER     NOT NULL DEFAULT 1,

    -- Which sources contributed to this snapshot
    sources         TEXT[]      NOT NULL DEFAULT '{}',  -- limits_yaml | db_config | env

    -- The full policy payload at capture time
    payload         JSONB       NOT NULL DEFAULT '{}',

    -- Human note when policy was deliberately changed
    change_reason   TEXT,
    changed_by      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutable
CREATE OR REPLACE RULE policy_snapshots_no_update AS
    ON UPDATE TO policy_snapshots DO INSTEAD NOTHING;

CREATE OR REPLACE RULE policy_snapshots_no_delete AS
    ON DELETE TO policy_snapshots DO INSTEAD NOTHING;

CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_snapshots_version
    ON policy_snapshots (workspace_id, version);

CREATE INDEX IF NOT EXISTS idx_policy_snapshots_latest
    ON policy_snapshots (workspace_id, created_at DESC);

-- RLS
ALTER TABLE policy_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON policy_snapshots
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- BACKFILL: workflow_events for existing sent drafts
-- ============================================================

-- Synthetic events for all already-sent drafts so the audit table starts
-- populated. actor_type='operator_script' marks these as reconstructed.
-- Only inserts if the table is still empty (idempotent).
INSERT INTO workflow_events (
    workspace_id, entity_type, entity_id,
    event_type, from_state, to_state,
    actor_type, actor_id, triggered_by, metadata
)
SELECT
    d.workspace_id,
    'draft',
    d.id,
    'draft.sent',
    'approved',
    'sent',
    'operator_script',
    'backfill_migration_050',
    'migration_050_schema_hardening',
    jsonb_build_object(
        'backfilled', true,
        'sent_at', d.sent_at,
        'contact_id', d.contact_id,
        'company_id', d.company_id,
        'sequence_step', d.sequence_step
    )
FROM outreach_drafts d
WHERE d.sent_at IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM workflow_events we
    WHERE we.entity_id = d.id AND we.event_type = 'draft.sent'
  );

-- Synthetic events for existing approved-but-not-sent drafts
INSERT INTO workflow_events (
    workspace_id, entity_type, entity_id,
    event_type, from_state, to_state,
    actor_type, actor_id, triggered_by, metadata
)
SELECT
    d.workspace_id,
    'draft',
    d.id,
    'draft.approved',
    'pending',
    'approved',
    'operator_script',
    'backfill_migration_050',
    'migration_050_schema_hardening',
    jsonb_build_object(
        'backfilled', true,
        'approved_at', d.approved_at,
        'approved_by', d.approved_by
    )
FROM outreach_drafts d
WHERE d.approval_status = 'approved'
  AND d.sent_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM workflow_events we
    WHERE we.entity_id = d.id AND we.event_type = 'draft.approved'
  );
