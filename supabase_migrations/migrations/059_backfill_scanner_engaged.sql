-- 059_backfill_scanner_engaged.sql
-- One-time backfill: reset companies that were promoted to 'engaged' solely
-- on scanner/bot click events (no genuine reply, no human open signal).
--
-- Criteria for reverting: status='engaged' AND no row in outreach_outcomes
-- with replied_at IS NOT NULL for any of their contacts.  These are companies
-- whose "engagement" was entirely click-pixel artefacts.
--
-- The canonical status for a company that was contacted but never replied is
-- 'qualified' (already in outreach).  We do not touch companies that have a
-- genuine reply (outreach_outcomes.replied_at is set).

UPDATE companies
SET status = 'qualified'
WHERE status = 'engaged'
  AND id NOT IN (
      SELECT DISTINCT c2.company_id
      FROM contacts c2
      JOIN outreach_outcomes oo ON oo.contact_id = c2.id
      WHERE oo.replied_at IS NOT NULL
  )
  AND id NOT IN (
      -- Also preserve companies that have a positive interaction of type email_replied
      SELECT DISTINCT company_id
      FROM interactions
      WHERE type = 'email_replied'
  );
