-- Migration 042: Add enrichment_attempts counter to contacts
-- Tracks how many times Apollo returned no email for a contact.
-- After 3 failed attempts the enrichment agent flips status to 'failed'
-- so the contact stops consuming credits each cycle.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS enrichment_attempts INTEGER NOT NULL DEFAULT 0;

-- Index for the enrichment agent pool query: quickly find contacts that
-- still need enrichment and haven't exhausted their attempt budget.
CREATE INDEX IF NOT EXISTS idx_contacts_enrichment_attempts
    ON contacts (enrichment_attempts)
    WHERE enrichment_status IN ('needs_enrichment', 'stale');
