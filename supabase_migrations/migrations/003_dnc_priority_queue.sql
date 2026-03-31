-- ProspectIQ Migration 003: DNC Registry + Contact Priority Score
-- Adds: do_not_contact table, priority_score column on contacts.
-- All statements are idempotent.

-- ============================================================
-- 1. Do-Not-Contact registry
-- ============================================================
CREATE TABLE IF NOT EXISTS do_not_contact (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT,                       -- exact email match (nullable)
    domain        TEXT,                       -- whole-domain block (nullable)
    reason        TEXT NOT NULL DEFAULT 'unsubscribed',
    added_by      TEXT,                       -- who added it (user / system / bounce)
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT dnc_email_or_domain CHECK (
        email IS NOT NULL OR domain IS NOT NULL
    )
);

-- Indexes for fast lookup at send time
CREATE INDEX IF NOT EXISTS idx_dnc_email  ON do_not_contact (lower(email))  WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dnc_domain ON do_not_contact (lower(domain)) WHERE domain IS NOT NULL;

-- ============================================================
-- 2. contacts — priority_score column
--    0–100 composite score used by queue_manager to rank send order.
--    Recomputed by queue_manager; stored so dashboard can display it.
-- ============================================================
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS priority_score INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_contacts_priority
    ON contacts (priority_score DESC);
