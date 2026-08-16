-- 067_claim_outbound_queue_batch_reconcile_live.sql
--
-- Reconciles this function's source-controlled definition with what is
-- actually live in production. Read via
--   SELECT prosrc FROM pg_proc WHERE proname = 'claim_outbound_queue_batch';
-- on 2026-08-16 during the operator-handoff verification for PR #169/#170.
--
-- The version committed in 058_claim_approval_guard.sql has NOT been the
-- live definition for some time. The live function has five conditions
-- that exist in no committed migration:
--
--   1. min_send_at gate (oq2.min_send_at IS NULL OR <= NOW())
--   2. Contact eligibility (c.is_outreach_eligible = true)
--   3. Cluster-routing exclusion (comp.campaign_cluster IS NOT NULL AND
--      != 'other') -- NOTE: the equivalent APPLICATION-level gate was
--      deliberately removed as dead code (see
--      test_cluster_routing_gate_removed.py and PR #160's description,
--      which cites ~5,691 sends destroyed by this exact check against a
--      provider that doesn't send anything). The database still enforces
--      it. Investigated 2026-08-16: does not currently affect any
--      pending draft (0 of 198 companies with real unsent approved/edited
--      drafts have campaign_cluster NULL/'other'), so this migration
--      captures it as-is rather than removing it -- removing a live
--      behavior via an "add missing migration" commit would be a real
--      behavior change dressed up as a documentation fix. Whether this
--      exclusion should be removed to match the app-level decision is a
--      separate, deliberate follow-up, not resolved here.
--   4. Company-lock check: NOT EXISTS a same-company interaction
--      (email_sent/email_replied/linkedin_connection/linkedin_message) at
--      a DIFFERENT contact within the last 8 days. Mirrors
--      channel_coordinator.py's is_company_locked, enforced redundantly
--      here at claim time.
--   5. Hot-suppression check: NOT EXISTS a same-company
--      email_replied/email_clicked interaction within the last 7 days.
--      Mirrors channel_coordinator.py's is_hot_suppressed.
--
-- Items 4 and 5 mean a row matching either condition is silently never
-- claimed by this function -- it never reaches engagement.py's
-- assertion battery, so the explicit company_locked/hot_suppressed
-- park-with-backoff path there (dispatch_scheduler.py, 8-day / 24-hour
-- reschedule with a recorded outcome) may not be reachable for rows this
-- RPC already filtered out. Not resolved here -- recorded so it can be
-- investigated as its own question rather than rediscovered later.
--
-- This migration is a pure reconciliation: CREATE OR REPLACE with the
-- live body, byte-for-byte. It changes nothing about current production
-- behavior -- it only makes that behavior visible in source control.
-- Same pattern as PR #159 adding the already-applied migration 066 to
-- source.

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
    UPDATE outbound_queue oq
    SET locked_by = p_instance_id,
        locked_at = NOW()
    WHERE oq.id IN (
        SELECT oq2.id
        FROM outbound_queue oq2
        JOIN outreach_drafts od ON od.id = oq2.draft_id
        JOIN contacts c ON c.id = od.contact_id
        JOIN companies comp ON comp.id = c.company_id
        WHERE oq2.workspace_id = p_workspace_id
          AND oq2.locked_by IS NULL
          AND (oq2.next_retry_at IS NULL OR oq2.next_retry_at <= NOW())
          AND (oq2.min_send_at IS NULL OR oq2.min_send_at <= NOW())
          AND od.approval_status IN ('approved', 'edited')
          -- Never claim ineligible contacts
          AND c.is_outreach_eligible = true
          -- Never claim rows for unroutable clusters (avoids cluster_routing_skip dead-letters)
          AND comp.campaign_cluster IS NOT NULL
          AND comp.campaign_cluster != 'other'
          -- Never claim rows where another contact at this company was touched in last 8 days
          -- (matches is_company_locked in channel_coordinator.py; applies to ALL steps)
          AND NOT EXISTS (
            SELECT 1 FROM interactions i
            JOIN contacts c2 ON c2.id = i.contact_id
            WHERE c2.company_id = c.company_id
              AND i.type IN ('email_sent','email_replied','linkedin_connection','linkedin_message')
              AND i.created_at > NOW() - INTERVAL '8 days'
              AND i.contact_id IS DISTINCT FROM od.contact_id
          )
          -- Never claim rows where company had a hot reply/click in last 7 days
          -- (avoids hot_suppressed assertion skips; matches is_hot_suppressed in channel_coordinator.py)
          AND NOT EXISTS (
            SELECT 1 FROM interactions i2
            JOIN contacts c3 ON c3.id = i2.contact_id
            WHERE c3.company_id = c.company_id
              AND i2.type IN ('email_replied', 'email_clicked')
              AND i2.created_at > NOW() - INTERVAL '7 days'
          )
        ORDER BY oq2.priority ASC, oq2.enqueued_at ASC
        LIMIT p_batch_size
        FOR UPDATE OF oq2 SKIP LOCKED
    )
    RETURNING oq.*;
END;
$$;
