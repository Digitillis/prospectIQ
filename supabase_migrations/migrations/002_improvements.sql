-- ProspectIQ Migration 002: Data Quality & Pipeline Improvements
-- Adds: enrichment lifecycle states, completeness scoring, apollo_id validation,
--        credit tracking, audit log, outreach pace limiting, domain dedup index.
-- All statements are idempotent (IF NOT EXISTS / IF EXISTS guards throughout).

-- ============================================================
-- 1. Enrichment status enum
-- ============================================================
DO $$ BEGIN
    CREATE TYPE enrichment_status AS ENUM (
        'needs_enrichment',
        'pending',
        'enriched',
        'failed',
        'stale'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 2. contacts — new columns
-- ============================================================

-- Enrichment lifecycle state
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS enrichment_status enrichment_status NOT NULL DEFAULT 'needs_enrichment';

-- When the contact was last successfully enriched
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

-- 0–100 score: email(25) + phone(15) + last_name(10) + full_apollo_id(25) + title(25)
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS completeness_score INTEGER NOT NULL DEFAULT 0;

-- Source of the enrichment (apollo | hunter | manual)
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS enrichment_source TEXT;

-- Primary target role for coverage matrix (vp_ops | plant_manager | coo | cio | digital_transformation | director_ops | vp_supply_chain)
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS role TEXT;

-- ============================================================
-- 3. contacts — apollo_id length check (must be 24 chars when present)
-- ============================================================
DO $$ BEGIN
    ALTER TABLE contacts
        ADD CONSTRAINT contacts_apollo_id_min_length
        CHECK (apollo_id IS NULL OR length(apollo_id) >= 24);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 4. companies — domain dedup index
-- ============================================================
CREATE UNIQUE INDEX IF NOT EXISTS companies_domain_unique
    ON companies (domain)
    WHERE domain IS NOT NULL AND domain <> '';

-- ============================================================
-- 5. apollo_credit_events — track every Apollo API credit spend
-- ============================================================
CREATE TABLE IF NOT EXISTS apollo_credit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operation       TEXT NOT NULL,              -- people_match | people_bulk_match | org_enrich | people_search
    credits_used    INTEGER NOT NULL DEFAULT 1,
    contact_id      UUID REFERENCES contacts(id) ON DELETE SET NULL,
    company_id      UUID REFERENCES companies(id) ON DELETE SET NULL,
    batch_id        TEXT,
    campaign_name   TEXT,
    response_status TEXT,                        -- success | failed | no_match
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_credit_events_created   ON apollo_credit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credit_events_campaign  ON apollo_credit_events (campaign_name);
CREATE INDEX IF NOT EXISTS idx_credit_events_contact   ON apollo_credit_events (contact_id);

-- ============================================================
-- 6. seed_audit_events — idempotent script audit trail
-- ============================================================
CREATE TABLE IF NOT EXISTS seed_audit_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    script_name  TEXT NOT NULL,
    entity_type  TEXT NOT NULL,    -- company | contact
    entity_id    UUID,
    entity_name  TEXT,
    action       TEXT NOT NULL,    -- created | skipped | updated | deleted | failed
    source       TEXT,             -- apollo_mcp | csv | manual | api
    details      TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created  ON seed_audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_script   ON seed_audit_events (script_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity   ON seed_audit_events (entity_type, entity_id);

-- ============================================================
-- 7. outreach_pace_log — enforce daily send cap per campaign
-- ============================================================
CREATE TABLE IF NOT EXISTS outreach_pace_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    campaign_name TEXT NOT NULL,
    contact_id    UUID REFERENCES contacts(id) ON DELETE SET NULL,
    company_id    UUID REFERENCES companies(id) ON DELETE SET NULL,
    channel       TEXT NOT NULL DEFAULT 'email',   -- email | linkedin
    status        TEXT NOT NULL DEFAULT 'sent'     -- sent | blocked | bounced
);

CREATE UNIQUE INDEX IF NOT EXISTS outreach_pace_log_unique_contact_day
    ON outreach_pace_log (contact_id, send_date)
    WHERE contact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pace_log_date_campaign
    ON outreach_pace_log (send_date, campaign_name);

-- ============================================================
-- 8. Function: compute_completeness_score(contact_row)
--    Called by trigger to keep completeness_score up to date.
-- ============================================================
CREATE OR REPLACE FUNCTION compute_contact_completeness()
RETURNS TRIGGER AS $$
DECLARE
    score INTEGER := 0;
BEGIN
    -- email: 25 pts
    IF NEW.email IS NOT NULL AND NEW.email <> '' THEN score := score + 25; END IF;
    -- phone: 15 pts
    IF NEW.phone IS NOT NULL AND NEW.phone <> '' THEN score := score + 15; END IF;
    -- last_name: 10 pts
    IF NEW.last_name IS NOT NULL AND NEW.last_name <> '' THEN score := score + 10; END IF;
    -- full 24-char apollo_id: 25 pts
    IF NEW.apollo_id IS NOT NULL AND length(NEW.apollo_id) >= 24 THEN score := score + 25; END IF;
    -- title: 25 pts
    IF NEW.title IS NOT NULL AND NEW.title <> '' THEN score := score + 25; END IF;

    NEW.completeness_score := score;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contact_completeness ON contacts;
CREATE TRIGGER trg_contact_completeness
    BEFORE INSERT OR UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION compute_contact_completeness();

-- ============================================================
-- 9. Backfill completeness_score for existing contacts
-- ============================================================
UPDATE contacts SET
    completeness_score = (
        CASE WHEN email IS NOT NULL AND email <> '' THEN 25 ELSE 0 END +
        CASE WHEN phone IS NOT NULL AND phone <> '' THEN 15 ELSE 0 END +
        CASE WHEN last_name IS NOT NULL AND last_name <> '' THEN 10 ELSE 0 END +
        CASE WHEN apollo_id IS NOT NULL AND length(apollo_id) >= 24 THEN 25 ELSE 0 END +
        CASE WHEN title IS NOT NULL AND title <> '' THEN 25 ELSE 0 END
    ),
    enrichment_status = CASE
        WHEN email IS NOT NULL AND email <> '' THEN 'enriched'::enrichment_status
        ELSE 'needs_enrichment'::enrichment_status
    END;
