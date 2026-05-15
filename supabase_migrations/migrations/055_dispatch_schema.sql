-- Migration 055: Dispatch Schema Extensions (PR G)
--
-- Three additive changes:
--
--   1. approval_status enum: adds 'dispatch_failed' terminal value for drafts
--      whose Resend calls permanently failed (4xx or max retries exceeded).
--
--   2. outreach_send_config: adds max_retries column (default 4 attempts total).
--
--   3. claim_outbound_queue_batch() PostgreSQL function: atomically claims up
--      to p_batch_size eligible queue rows using FOR UPDATE SKIP LOCKED.
--      Called via Supabase RPC from the dispatch loop in PR G so PgBouncer
--      transaction mode cannot split the read and the UPDATE.
--
-- Author: Avanish Mehrotra & Digitillis Architecture Team
-- Date: 2026-05-15

-- ============================================================
-- 1. APPROVAL STATUS: dispatch_failed
-- ============================================================
-- Terminal state for drafts that exhausted retries or received a permanent
-- Resend 4xx. Distinct from 'rejected' (human decision) and 'approved'
-- (ready to send). Lets the review UI surface these for triage.

ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'dispatch_failed';


-- ============================================================
-- 2. SEND CONFIG: max_retries
-- ============================================================

ALTER TABLE outreach_send_config
    ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 4;


-- ============================================================
-- 3. ATOMIC BATCH CLAIM FUNCTION
-- ============================================================
-- Called from dispatch_workspace() via db.client.rpc().
-- FOR UPDATE SKIP LOCKED prevents two concurrent dispatcher instances
-- from claiming the same queue row.

CREATE OR REPLACE FUNCTION claim_outbound_queue_batch(
    p_workspace_id  UUID,
    p_instance_id   TEXT,
    p_batch_size    INTEGER
)
RETURNS SETOF outbound_queue
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    UPDATE outbound_queue
    SET
        locked_by = p_instance_id,
        locked_at = NOW()
    WHERE id IN (
        SELECT id
        FROM outbound_queue
        WHERE workspace_id = p_workspace_id
          AND locked_by IS NULL
          AND (next_retry_at IS NULL OR next_retry_at <= NOW())
        ORDER BY priority ASC, enqueued_at ASC
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$;
