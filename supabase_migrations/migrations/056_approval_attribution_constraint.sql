-- Migration 056: enforce reviewer attribution on approved outreach drafts.
--
-- Background: the send-time gate (engagement.py) already filters to
--   approval_status='approved' AND approved_by IS NOT NULL AND reviewed_at IS NOT NULL,
-- but the gate is a query filter, not a write constraint. Approvals made via
-- direct DB writes (scripts, manual SQL) can set approval_status='approved'
-- without populating the reviewer columns, and those drafts are then silently
-- skipped by the scheduler — invisible failure mode.
--
-- This constraint makes the invariant unforgeable at the storage layer:
-- a draft cannot be marked approved unless reviewer attribution is present.

ALTER TABLE outreach_drafts
ADD CONSTRAINT approval_requires_reviewer
CHECK (
    approval_status != 'approved'
    OR (approved_by IS NOT NULL AND reviewed_at IS NOT NULL)
);

-- Index supports the strict send query in engagement.py.
CREATE INDEX IF NOT EXISTS idx_drafts_approved_sendable
ON outreach_drafts (approval_status, sent_at, approved_by, reviewed_at)
WHERE approval_status = 'approved' AND sent_at IS NULL;

COMMENT ON CONSTRAINT approval_requires_reviewer ON outreach_drafts IS
'Approval status=approved requires approved_by + reviewed_at. '
'Prevents silent send-skipping when scripts bypass the approval endpoint.';
