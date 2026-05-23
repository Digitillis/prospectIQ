-- State Integrity Validation Queries
-- Run these periodically to verify ProspectIQ send-pipeline integrity.
-- Author: Avanish Mehrotra & Digitillis Architecture Team

-- 1. Approved drafts with ineligible email status
SELECT od.id, od.contact_id, c.email_status, c.is_outreach_eligible
FROM outreach_drafts od
JOIN contacts c ON c.id = od.contact_id
WHERE od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND (c.email_status NOT IN ('verified', 'catch_all') OR c.is_outreach_eligible IS NOT TRUE);

-- 2. Approved drafts for contacts suppressed after approval
SELECT od.id, od.contact_id, od.approved_at, sl.created_at as suppressed_at
FROM outreach_drafts od
JOIN suppression_log sl ON sl.contact_id = od.contact_id
WHERE od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND sl.created_at > od.approved_at;

-- 3. Step-2 approved drafts without step-1 sent
SELECT od.id, od.contact_id
FROM outreach_drafts od
WHERE od.sequence_step = 2
  AND od.approval_status = 'approved'
  AND od.sent_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM outreach_drafts s1
      WHERE s1.contact_id = od.contact_id
        AND s1.sequence_step = 1
        AND s1.sent_at IS NOT NULL
  );

-- 4. Sent drafts without send_assertion records
SELECT od.id, od.contact_id, od.sent_at
FROM outreach_drafts od
WHERE od.sent_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM send_assertions sa WHERE sa.contact_id = od.contact_id
  );

-- 5. Queue ordering drift check
-- Compare canonical (company/last_name) vs created_at positions
WITH canonical AS (
    SELECT od.id, ROW_NUMBER() OVER (
        ORDER BY LOWER(co.name), LOWER(COALESCE(ct.last_name, SPLIT_PART(ct.full_name, ' ', -1)))
    ) as canonical_pos
    FROM outreach_drafts od
    JOIN companies co ON co.id = od.company_id
    JOIN contacts ct ON ct.id = od.contact_id
    WHERE od.sequence_step = 2 AND od.sent_at IS NULL
),
by_created AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at DESC) as created_pos
    FROM outreach_drafts
    WHERE sequence_step = 2 AND sent_at IS NULL
)
SELECT c.id, c.canonical_pos, bc.created_pos,
       ABS(c.canonical_pos - bc.created_pos) as position_drift
FROM canonical c
JOIN by_created bc ON bc.id = c.id
WHERE c.canonical_pos <= 64 OR bc.created_pos <= 64
ORDER BY position_drift DESC
LIMIT 20;
