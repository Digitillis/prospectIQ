-- Migration 054: Outbound Queue + Send Attempts (PR F — Transactional Outbox)
--
-- Introduces two tables that underpin durable send execution:
--
--   outbound_queue   — one row per draft awaiting dispatch. Written atomically
--                      with the approval status change via approve_draft_and_enqueue().
--                      Consumed and deleted by the dispatch scheduler (PR G).
--
--   send_attempts    — append-only record of every dispatch attempt. Written by
--                      the scheduler before each Resend call (PR G). NOT written
--                      in this migration — table is created here, written in PR G.
--
-- Also creates the approve_draft_and_enqueue() PostgreSQL function, which
-- wraps the outreach_drafts UPDATE and outbound_queue INSERT in a single
-- transaction. Called via Supabase RPC from the approval endpoint so that
-- PgBouncer transaction-mode connections cannot split the two writes.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-15

-- ============================================================
-- 1. OUTBOUND QUEUE
-- ============================================================

CREATE TABLE IF NOT EXISTS outbound_queue (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- One row per draft. UNIQUE enforces idempotency — a double-approval
    -- produces ON CONFLICT DO NOTHING rather than a duplicate queue row.
    draft_id        UUID        NOT NULL UNIQUE REFERENCES outreach_drafts(id) ON DELETE CASCADE,
    workspace_id    UUID        NOT NULL,

    enqueued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Scheduler priority: lower = higher priority. Default 5 = normal.
    priority        INTEGER     NOT NULL DEFAULT 5,

    -- Retry state — written by the scheduler (PR G). Zero until first failure.
    retry_count     INTEGER     NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMPTZ,

    -- Distributed lock — set by the scheduler when it claims a row.
    -- Cleared on successful dispatch. Stale locks (locked_at > N minutes ago)
    -- are reclaimed by the scheduler on the next sweep.
    locked_by       TEXT,
    locked_at       TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Scheduler pickup: find unclaimed rows eligible for dispatch
CREATE INDEX IF NOT EXISTS idx_outbound_queue_pickup
    ON outbound_queue (priority, enqueued_at)
    WHERE locked_at IS NULL AND next_retry_at IS NULL;

-- Retry sweep: find rows with a due next_retry_at
CREATE INDEX IF NOT EXISTS idx_outbound_queue_retry
    ON outbound_queue (next_retry_at)
    WHERE next_retry_at IS NOT NULL;

-- Stale-lock reclaim: find rows locked longer than the timeout
CREATE INDEX IF NOT EXISTS idx_outbound_queue_locked
    ON outbound_queue (locked_at)
    WHERE locked_at IS NOT NULL;

ALTER TABLE outbound_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON outbound_queue
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 2. SEND ATTEMPTS
-- ============================================================

CREATE TABLE IF NOT EXISTS send_attempts (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id                UUID        NOT NULL REFERENCES outreach_drafts(id) ON DELETE CASCADE,
    workspace_id            UUID        NOT NULL,

    attempt_number          INTEGER     NOT NULL DEFAULT 1,
    idempotency_key         TEXT        NOT NULL,

    status                  TEXT        NOT NULL DEFAULT 'DISPATCHED',
    -- DISPATCHED: Resend call issued, awaiting delivery confirmation
    -- DELIVERED:  Resend accepted the message (2xx response)
    -- FAILED:     Resend returned a transient error (5xx, 429) — eligible for retry
    -- PERMANENTLY_FAILED: Resend returned a permanent error (4xx except 429)

    dispatched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,

    -- Provider response
    provider_message_id     TEXT,
    provider_response_body  JSONB,

    -- Failure detail
    failure_code            TEXT,
    failure_reason          TEXT,

    -- Reconciliation timestamp (set when webhook or polling confirms delivery)
    reconciled_at           TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (draft_id, attempt_number),
    CONSTRAINT send_attempts_status_check CHECK (
        status IN ('DISPATCHED', 'DELIVERED', 'FAILED', 'PERMANENTLY_FAILED')
    )
);

-- Reconciliation lookup: given a draft, find all its attempts
CREATE INDEX IF NOT EXISTS idx_send_attempts_draft
    ON send_attempts (draft_id);

-- Stale-dispatch detection: DISPATCHED rows with no resolution after N minutes
CREATE INDEX IF NOT EXISTS idx_send_attempts_stale
    ON send_attempts (dispatched_at)
    WHERE status = 'DISPATCHED';

-- Status-based reporting
CREATE INDEX IF NOT EXISTS idx_send_attempts_status
    ON send_attempts (status, dispatched_at DESC);

ALTER TABLE send_attempts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_access" ON send_attempts
    FOR ALL
    USING (
        workspace_id = current_setting('app.workspace_id', true)::uuid
        OR current_setting('app.workspace_id', true) IS NULL
        OR current_setting('app.workspace_id', true) = ''
    );


-- ============================================================
-- 3. ATOMIC APPROVAL + ENQUEUE FUNCTION
-- ============================================================
-- Called from the approval endpoint via Supabase RPC.
-- Wraps the outreach_drafts UPDATE and outbound_queue INSERT in a single
-- transaction so PgBouncer transaction mode cannot split them.
--
-- Only enqueues for terminal approval states (approved, edited).
-- pending_second_review does NOT produce a queue row.
-- ON CONFLICT DO NOTHING on draft_id ensures idempotency.

CREATE OR REPLACE FUNCTION approve_draft_and_enqueue(
    p_draft_id      UUID,
    p_workspace_id  UUID,
    p_status        TEXT,
    p_approved_at   TIMESTAMPTZ,
    p_edited_body   TEXT    DEFAULT NULL,
    p_priority      INTEGER DEFAULT 5
)
RETURNS SETOF outreach_drafts
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE outreach_drafts
    SET
        approval_status = p_status::approval_status,
        approved_at     = p_approved_at,
        edited_body     = COALESCE(p_edited_body, edited_body)
    WHERE id           = p_draft_id
      AND workspace_id = p_workspace_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'draft_not_found: %', p_draft_id;
    END IF;

    IF p_status IN ('approved', 'edited') THEN
        INSERT INTO outbound_queue (draft_id, workspace_id, priority)
        VALUES (p_draft_id, p_workspace_id, p_priority)
        ON CONFLICT (draft_id) DO NOTHING;
    END IF;

    RETURN QUERY SELECT * FROM outreach_drafts WHERE id = p_draft_id;
END;
$$;
