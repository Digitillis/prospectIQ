-- Migration 038: Contact email deduplication + unique index
--
-- Problem: The same email address can exist under multiple contact rows when
-- duplicate company records cause the same person to be enriched twice. This
-- leads to multiple outreach drafts for the same real person.
--
-- Fix:
--   1. For each (workspace_id, lower(email)) group, keep the single most
--      advanced contact (prioritise sent > enriched > others; tiebreak: newest).
--      All other duplicates have their email NULLed out — they are not deleted
--      so FK relationships from drafts/interactions remain intact.
--   2. Add a partial unique index that enforces one row per email per workspace
--      going forward (only on non-nulled rows).

BEGIN;

-- Step 1: Null out duplicate email addresses, keeping the canonical contact.
-- Priority: contacts already in an active sequence (touch_N_sent) > enriched > rest
-- Tiebreak: most recently updated row wins.
WITH ranked AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      PARTITION BY workspace_id, lower(email)
      ORDER BY
        CASE
          WHEN outreach_state LIKE 'touch_%' THEN 0
          WHEN outreach_state = 'enriched'   THEN 1
          ELSE 2
        END,
        updated_at DESC NULLS LAST
    ) AS rn
  FROM contacts
  WHERE email IS NOT NULL AND email <> ''
),
dupes AS (
  SELECT id FROM ranked WHERE rn > 1
)
UPDATE contacts
SET
  email        = NULL,
  updated_at   = now()
FROM dupes
WHERE contacts.id = dupes.id;

-- Step 2: Partial unique index — one email per workspace, ignoring NULLed rows.
-- Using lower() for case-insensitive enforcement.
CREATE UNIQUE INDEX IF NOT EXISTS contacts_workspace_email_unique
  ON contacts (workspace_id, lower(email))
  WHERE email IS NOT NULL AND email <> '';

COMMIT;
