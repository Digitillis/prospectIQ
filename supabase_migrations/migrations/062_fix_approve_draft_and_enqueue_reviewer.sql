-- Migration 062: fix approve_draft_and_enqueue to pass approved_by + reviewed_at.
--
-- Migration 056 added the approval_requires_reviewer constraint
-- (approved_by IS NOT NULL AND reviewed_at IS NOT NULL when approval_status='approved'),
-- but the RPC in migration 054 was not updated to set those columns.
-- Result: enqueue_todays_schedule failed for all drafts without a prior approved_by.
--
-- Fix: add p_approved_by + p_reviewed_at parameters and set them in the UPDATE.

CREATE OR REPLACE FUNCTION approve_draft_and_enqueue(
    p_draft_id      UUID,
    p_workspace_id  UUID,
    p_status        TEXT,
    p_approved_at   TIMESTAMPTZ,
    p_edited_body   TEXT        DEFAULT NULL,
    p_priority      INTEGER     DEFAULT 5,
    p_approved_by   TEXT        DEFAULT NULL,
    p_reviewed_at   TIMESTAMPTZ DEFAULT NULL
)
RETURNS SETOF outreach_drafts
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE outreach_drafts
    SET
        approval_status = p_status::approval_status,
        approved_at     = p_approved_at,
        edited_body     = COALESCE(p_edited_body, edited_body),
        approved_by     = COALESCE(p_approved_by, approved_by),
        reviewed_at     = COALESCE(p_reviewed_at, reviewed_at)
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

COMMENT ON FUNCTION approve_draft_and_enqueue IS
'Atomically approves a draft and inserts it into outbound_queue. '
'p_approved_by + p_reviewed_at satisfy the approval_requires_reviewer constraint (migration 056).';
