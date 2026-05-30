-- 058_claim_approval_guard.sql
-- Replace claim_outbound_queue_batch() to skip rows whose outreach_draft has
-- been rejected or permanently failed.  Previously the claim RPC selected from
-- outbound_queue without joining outreach_drafts, so a rejected draft could
-- still be claimed and sent (R2 remediation).

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
    SET
        locked_by = p_instance_id,
        locked_at = NOW()
    WHERE oq.id IN (
        SELECT oq2.id
        FROM outbound_queue oq2
        JOIN outreach_drafts od ON od.id = oq2.draft_id
        WHERE oq2.workspace_id = p_workspace_id
          AND oq2.locked_by IS NULL
          AND (oq2.next_retry_at IS NULL OR oq2.next_retry_at <= NOW())
          -- Only claim drafts that are in an approvable state.
          -- 'rejected' and 'dispatch_failed' are terminal — never dispatch them.
          AND od.approval_status IN ('approved', 'edited')
        ORDER BY oq2.priority ASC, oq2.enqueued_at ASC
        LIMIT p_batch_size
        FOR UPDATE OF oq2 SKIP LOCKED
    )
    RETURNING oq.*;
END;
$$;
