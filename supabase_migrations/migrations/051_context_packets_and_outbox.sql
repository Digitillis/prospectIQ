-- Migration 051: Context Intelligence Foundation + Transactional Outbox
--
-- Phase 2: context_packets
--   Every draft generation, approval, and send consumes a ContextPacket — a
--   point-in-time snapshot of everything the system knew about the contact and
--   company at decision time. Storing this as a row lets us answer "why was
--   this email sent this way?" deterministically, even months later.
--
-- Phase 3: send_attempts + outbound_queue
--   Decouples the claim-lock (reserving a draft for sending) from the delivery
--   state (whether Resend/Instantly accepted the payload). Closes the orphan-
--   draft problem where a crash between "claimed" and "delivered" left a draft
--   stuck with sent_at set but no delivery confirmation.
--
--   outbound_queue is a transactional outbox: the approval write and the queue
--   enqueue happen in the same transaction, so queue items are never lost.
--   The worker claims rows with SELECT FOR UPDATE SKIP LOCKED and writes to
--   send_attempts before calling the provider.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-14

-- ============================================================
-- 1. CONTEXT PACKETS
-- ============================================================

CREATE TABLE IF NOT EXISTS context_packets (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID        NOT NULL,

    -- What this packet was assembled for
    purpose                 TEXT        NOT NULL,  -- draft_generation | approval | send | risk_score
    draft_id                UUID        REFERENCES outreach_drafts(id) ON DELETE SET NULL,
    contact_id              UUID,
    company_id              UUID,

    -- Schema version — increment when ContextPacketBuilder adds/removes fields
    schema_version          INTEGER     NOT NULL DEFAULT 1,

    -- Content hash — SHA256 of the JSON payload, used to detect staleness
    content_hash            TEXT        NOT NULL,

    -- ---- Contact snapshot ----
    contact_snapshot        JSONB       NOT NULL DEFAULT '{}',
    -- keys: full_name, email, linkedin_url, seniority, title, department,
    --       reply_sentiment, linkedin_status, has_email, has_linkedin

    -- ---- Company snapshot ----
    company_snapshot        JSONB       NOT NULL DEFAULT '{}',
    -- keys: name, domain, employee_count, headcount_growth_6m, industry,
    --       tier, status, intent_score, assigned_persona

    -- ---- Outreach history ----
    prior_messages          JSONB       NOT NULL DEFAULT '[]',
    -- array of {step, channel, subject, sent_at, primary_angle}

    sibling_contact_history JSONB       NOT NULL DEFAULT '[]',
    -- other contacts at this company who received outreach; prevents duplicate angles

    reply_history           JSONB       NOT NULL DEFAULT '[]',
    -- {contact_id, sentiment, replied_at, body_excerpt}

    active_conversation     BOOLEAN     NOT NULL DEFAULT false,
    -- true if a reply was received and is unresolved

    -- ---- Governance context ----
    channel_assignment      TEXT,       -- email | linkedin | both | none
    channel_reason          TEXT,
    company_locked          BOOLEAN     NOT NULL DEFAULT false,
    company_lock_reason     TEXT,
    suppression_status      TEXT,       -- none | contact | company | domain | global
    suppression_reason      TEXT,

    -- ---- Content guardrails ----
    prohibited_claims       TEXT[]      NOT NULL DEFAULT '{}',
    -- claims that must not appear (prior step angles, retired proof points, etc.)

    registered_claims       JSONB       NOT NULL DEFAULT '[]',
    -- [{claim_id, claim_text, source, verified_at}] — validated facts available for use

    -- ---- Sequence context ----
    sequence_name           TEXT,
    sequence_step           INTEGER,
    prior_step_angle        TEXT,       -- primary angle used in step N-1; step N must not repeat

    -- ---- Risk indicators (pre-score) ----
    traction_signal         TEXT,       -- none | warm | active_reply | meeting_booked
    is_first_touch          BOOLEAN     NOT NULL DEFAULT true,
    days_since_last_touch   INTEGER,

    -- ---- Meta ----
    assembled_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds             INTEGER     NOT NULL DEFAULT 300,  -- 5 min default; per-field cache in builder
    expired_at              TIMESTAMPTZ GENERATED ALWAYS AS (assembled_at + (ttl_seconds || ' seconds')::interval) STORED,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_context_packets_draft
    ON context_packets (draft_id)
    WHERE draft_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_context_packets_contact_recent
    ON context_packets (contact_id, assembled_at DESC)
    WHERE contact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_context_packets_workspace
    ON context_packets (workspace_id, assembled_at DESC);

-- RLS
ALTER TABLE context_packets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON context_packets
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 2. SEND ATTEMPTS
-- ============================================================

-- One row per attempt to deliver a draft to a provider.
-- Replaces the current pattern of setting sent_at before the provider call,
-- which leaves orphans when the process crashes mid-flight.
--
-- Lifecycle: pending → in_flight → delivered | failed | bounced
CREATE TABLE IF NOT EXISTS send_attempts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID        NOT NULL,
    draft_id            UUID        NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
    outbound_queue_id   UUID,       -- back-reference to the queue row that spawned this attempt

    attempt_number      INTEGER     NOT NULL DEFAULT 1,

    -- Which provider was used
    provider            TEXT        NOT NULL,  -- resend | instantly | linkedin

    -- Provider response
    provider_message_id TEXT,       -- Resend email_id, Instantly lead_id, etc.
    provider_status     TEXT,       -- accepted | queued | failed
    provider_error      TEXT,       -- raw error message if failed

    -- Delivery outcome (populated when we receive a webhook)
    delivery_status     TEXT,       -- pending | delivered | bounced | complained | deferred
    delivery_event_id   UUID        REFERENCES provider_events(id) ON DELETE SET NULL,

    -- State
    status              TEXT        NOT NULL DEFAULT 'pending',
    -- pending | in_flight | delivered | failed | bounced | complained

    -- Timing
    claimed_at          TIMESTAMPTZ,   -- when the worker locked this row
    sent_at             TIMESTAMPTZ,   -- when the provider accepted the payload
    delivered_at        TIMESTAMPTZ,   -- when delivery confirmed via webhook
    failed_at           TIMESTAMPTZ,

    -- Context pinned at send time
    context_packet_id   UUID        REFERENCES context_packets(id) ON DELETE SET NULL,
    policy_snapshot_id  UUID        REFERENCES policy_snapshots(id) ON DELETE SET NULL,

    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only one successful send attempt per draft
CREATE UNIQUE INDEX IF NOT EXISTS idx_send_attempts_delivered_per_draft
    ON send_attempts (draft_id)
    WHERE status = 'delivered';

CREATE INDEX IF NOT EXISTS idx_send_attempts_draft
    ON send_attempts (draft_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_send_attempts_inflight
    ON send_attempts (workspace_id, claimed_at)
    WHERE status = 'in_flight';

CREATE INDEX IF NOT EXISTS idx_send_attempts_pending
    ON send_attempts (workspace_id, created_at ASC)
    WHERE status = 'pending';

-- updated_at
CREATE OR REPLACE FUNCTION update_send_attempts_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_send_attempts_updated_at ON send_attempts;
CREATE TRIGGER trg_send_attempts_updated_at
    BEFORE UPDATE ON send_attempts
    FOR EACH ROW EXECUTE FUNCTION update_send_attempts_updated_at();

-- RLS
ALTER TABLE send_attempts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON send_attempts
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 3. OUTBOUND QUEUE (transactional outbox)
-- ============================================================

-- Queue items are written in the same transaction as the approval write.
-- The worker claims rows with SELECT FOR UPDATE SKIP LOCKED.
-- Once a send_attempt succeeds, the queue row is marked 'completed'.
-- DLQ items (exhausted retries) are moved to status='dead' and never retried.
CREATE TABLE IF NOT EXISTS outbound_queue (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID        NOT NULL,
    draft_id            UUID        NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,

    -- Priority: lower number = higher priority
    -- Step-1 first-touch: 10, Step-2+ follow-up: 20, Re-engagement: 30
    priority            INTEGER     NOT NULL DEFAULT 20,

    -- Scheduled delivery window
    scheduled_after     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Retry tracking
    attempt_count       INTEGER     NOT NULL DEFAULT 0,
    max_attempts        INTEGER     NOT NULL DEFAULT 3,
    last_attempted_at   TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ,

    -- Status: queued | in_flight | completed | failed | dead | cancelled
    status              TEXT        NOT NULL DEFAULT 'queued',

    -- Who enqueued this and why
    enqueued_by         TEXT        NOT NULL DEFAULT 'system',
    enqueue_reason      TEXT,

    -- Error from last failed attempt
    last_error          TEXT,

    -- Context pinned at enqueue time
    context_packet_id   UUID        REFERENCES context_packets(id) ON DELETE SET NULL,
    policy_snapshot_id  UUID        REFERENCES policy_snapshots(id) ON DELETE SET NULL,

    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only one active queue item per draft at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_queue_active_per_draft
    ON outbound_queue (draft_id)
    WHERE status IN ('queued', 'in_flight');

-- Worker claim query: SELECT FOR UPDATE SKIP LOCKED ordered by this index
CREATE INDEX IF NOT EXISTS idx_outbound_queue_worker_claim
    ON outbound_queue (priority ASC, scheduled_after ASC, created_at ASC)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_outbound_queue_workspace
    ON outbound_queue (workspace_id, status, created_at DESC);

-- Retry query
CREATE INDEX IF NOT EXISTS idx_outbound_queue_retry
    ON outbound_queue (next_retry_at ASC)
    WHERE status = 'failed' AND attempt_count < max_attempts;

-- updated_at
CREATE OR REPLACE FUNCTION update_outbound_queue_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_outbound_queue_updated_at ON outbound_queue;
CREATE TRIGGER trg_outbound_queue_updated_at
    BEFORE UPDATE ON outbound_queue
    FOR EACH ROW EXECUTE FUNCTION update_outbound_queue_updated_at();

-- RLS
ALTER TABLE outbound_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON outbound_queue
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- BACK-REFERENCES: add context_packet_id to workflow_events
-- ============================================================

-- Now that context_packets exists, add the FK we intentionally deferred in 050.
ALTER TABLE workflow_events
    ADD COLUMN IF NOT EXISTS context_packet_id_fk UUID
        REFERENCES context_packets(id) ON DELETE SET NULL;

-- Note: the original context_packet_id UUID column in workflow_events (migration 050)
-- remains as a non-FK column for the backfill rows from that migration.
-- New code should write to context_packet_id_fk. The two will be consolidated
-- in migration 052 after the backfill rows have been reviewed.
