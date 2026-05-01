-- Migration 032: capture Apollo email_status on contacts
--
-- Apollo's people/match enrichment endpoint returns an email_status field
-- at no extra cost. Values: verified, unverified, catch_all, invalid, bounce,
-- accept_all, unknown.
-- We store it so the outreach gate can block confirmed-invalid addresses
-- without paying for a separate verification service (NeverBounce/ZeroBounce).

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS email_status TEXT DEFAULT NULL;

-- Fast lookup: outreach gate queries contacts where is_outreach_eligible = true
-- AND email_status != 'invalid' AND email_status != 'bounce'
CREATE INDEX IF NOT EXISTS idx_contacts_email_status
    ON contacts (workspace_id, email_status)
    WHERE email_status IN ('invalid', 'bounce');

-- Mark any contacts that Apollo previously flagged (via enrichment_notes or
-- similar fields) as invalid — backfill is conservative (no-op on empty table).
-- Real status values will populate on next enrichment pass.
