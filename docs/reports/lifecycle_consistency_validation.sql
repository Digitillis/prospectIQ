-- Lifecycle Consistency Validation
-- Phase 4 — Company lifecycle backfill queries
-- Date: 2026-05-13

-- ============================================================
-- QUERY 1: Identify companies eligible for 'contacted' backfill
-- Companies with outreach_pending status but at least one sent draft
-- ============================================================
SELECT c.id, c.name, c.status, MIN(od.sent_at) AS first_sent_at
FROM companies c
INNER JOIN outreach_drafts od ON od.company_id = c.id
WHERE c.status = 'outreach_pending'
AND od.sent_at IS NOT NULL
GROUP BY c.id, c.name, c.status
ORDER BY first_sent_at;


-- ============================================================
-- QUERY 2: Backfill update (dry-run: preview with SELECT first)
-- ============================================================
-- DRY-RUN (preview only):
SELECT id, name, status
FROM companies
WHERE status = 'outreach_pending'
AND id IN (
    SELECT DISTINCT company_id
    FROM outreach_drafts
    WHERE sent_at IS NOT NULL
);

-- EXECUTE (run after reviewing dry-run):
-- UPDATE companies
-- SET status = 'contacted'
-- WHERE status = 'outreach_pending'
-- AND id IN (
--     SELECT DISTINCT company_id
--     FROM outreach_drafts
--     WHERE sent_at IS NOT NULL
-- );


-- ============================================================
-- QUERY 3: Verification — confirm backfill complete
-- ============================================================
SELECT COUNT(*) AS remaining_outreach_pending
FROM companies c
WHERE c.status = 'outreach_pending'
AND EXISTS (
    SELECT 1 FROM outreach_drafts od
    WHERE od.company_id = c.id
    AND od.sent_at IS NOT NULL
);
-- Expected: 0 (after backfill)


-- ============================================================
-- QUERY 4: Full company status distribution
-- ============================================================
SELECT status, COUNT(*) AS count
FROM companies
GROUP BY status
ORDER BY count DESC;


-- ============================================================
-- QUERY 5: Companies with sent drafts but not yet 'contacted' or 'engaged'
-- (ongoing monitoring query — run weekly)
-- ============================================================
SELECT c.id, c.name, c.status,
       COUNT(od.id) AS sent_draft_count,
       MAX(od.sent_at) AS last_sent_at
FROM companies c
INNER JOIN outreach_drafts od ON od.company_id = c.id
WHERE od.sent_at IS NOT NULL
AND c.status NOT IN ('contacted', 'engaged', 'bounced', 'cancelled', 'won', 'lost')
GROUP BY c.id, c.name, c.status
ORDER BY last_sent_at DESC;


-- ============================================================
-- QUERY 6: Stalled step-2 contacts
-- (contacts with step-1 sent, no step-2 draft, sendable email)
-- ============================================================
SELECT c.id, c.email, c.full_name, c.email_status,
       od1.sent_at AS step1_sent_at
FROM contacts c
INNER JOIN outreach_drafts od1
    ON od1.contact_id = c.id
    AND od1.sequence_step = 1
    AND od1.sent_at IS NOT NULL
WHERE c.email_status IN ('verified', 'catch_all')
AND c.is_outreach_eligible IS NOT FALSE
AND NOT EXISTS (
    SELECT 1 FROM outreach_drafts od2
    WHERE od2.contact_id = c.id
    AND od2.sequence_step = 2
)
ORDER BY od1.sent_at;
-- This is the 349-contact population ready for step-2
