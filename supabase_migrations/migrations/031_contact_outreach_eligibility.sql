-- Migration 031: Contact outreach eligibility and title classification
--
-- Adds three columns to contacts:
--   is_outreach_eligible  BOOLEAN — hard gate: false blocks draft generation entirely
--   contact_tier          TEXT    — 'target' | 'borderline' | 'excluded'
--   email_name_verified   BOOLEAN — true = name-to-email consistency check passed
--
-- Backfills:
--   Contacts with status='excluded' → is_outreach_eligible=false, contact_tier='excluded'
--   All others → is_outreach_eligible=true, contact_tier='target' (pending reclassification)

-- 1. Add columns
ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS is_outreach_eligible BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS contact_tier TEXT CHECK (contact_tier IN ('target', 'borderline', 'excluded')) DEFAULT 'target',
  ADD COLUMN IF NOT EXISTS email_name_verified BOOLEAN DEFAULT NULL;

-- 2. Index for fast eligibility queries (outreach agent scans this on every run)
CREATE INDEX IF NOT EXISTS idx_contacts_outreach_eligible
  ON contacts (workspace_id, is_outreach_eligible)
  WHERE is_outreach_eligible = true;

CREATE INDEX IF NOT EXISTS idx_contacts_tier
  ON contacts (workspace_id, contact_tier);

-- 3. Backfill: contacts already marked excluded
UPDATE contacts
SET
  is_outreach_eligible = false,
  contact_tier = 'excluded'
WHERE status = 'excluded';

-- 4. Backfill: contacts whose email failed name consistency (none yet, placeholder)
-- UPDATE contacts SET email_name_verified = false WHERE <condition>;

COMMENT ON COLUMN contacts.is_outreach_eligible IS
  'Hard gate: false blocks draft generation. Set false at import for wrong-function titles, or when email_name_verified=false after manual review.';

COMMENT ON COLUMN contacts.contact_tier IS
  'target = ops buyer, borderline = may be buyer (flag for human review), excluded = non-buyer role';

COMMENT ON COLUMN contacts.email_name_verified IS
  'null = not yet checked, true = name tokens match email local part, false = mismatch detected';
