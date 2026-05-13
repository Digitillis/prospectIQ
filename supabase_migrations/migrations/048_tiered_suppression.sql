-- Migration 048: Tiered suppression architecture
--
-- Replaces single-tier company-level bounce suppression with a structured
-- suppression_log that distinguishes contact-scope from company/domain-scope
-- events. A single contact bounce no longer propagates to the company.
--
-- Escalation to company scope is recorded here explicitly, not inferred from
-- companies.status = 'bounced'.

CREATE TABLE IF NOT EXISTS suppression_log (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID        NOT NULL,
    scope                   TEXT        NOT NULL CHECK (scope IN ('contact', 'company', 'domain')),
    reason                  TEXT        NOT NULL CHECK (reason IN (
                                'hard_bounce_contact',
                                'hard_bounce_domain',
                                'soft_bounce',
                                'spam_complaint',
                                'unsubscribe',
                                'manual_block',
                                'legal_hold',
                                'company_opt_out',
                                'competitor',
                                'not_interested',
                                'dnc'
                            )),
    contact_id              UUID        REFERENCES contacts(id) ON DELETE SET NULL,
    company_id              UUID        REFERENCES companies(id) ON DELETE SET NULL,
    email                   TEXT,
    domain                  TEXT,
    bounce_classification   TEXT        CHECK (bounce_classification IN ('hard', 'soft', 'complaint', 'unknown')),
    provider_code           TEXT,
    provider_message        TEXT,
    triggered_by_contact_id UUID        REFERENCES contacts(id) ON DELETE SET NULL,
    escalated_from          UUID        REFERENCES suppression_log(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata                JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_suppression_log_contact
    ON suppression_log (contact_id, created_at DESC)
    WHERE contact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_suppression_log_company
    ON suppression_log (company_id, scope, created_at DESC)
    WHERE company_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_suppression_log_domain
    ON suppression_log (domain, created_at DESC)
    WHERE domain IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_suppression_log_workspace
    ON suppression_log (workspace_id, created_at DESC);

-- Add suppression_reason to contacts for fast single-field reads
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS suppression_reason TEXT;

-- Add suppression_reason to companies for fast single-field reads
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS suppression_reason TEXT;

-- Backfill: migrate existing contact-level bounces into suppression_log.
-- Scope is 'contact' for all — these were individual email bounces; the
-- company-level bounce status that was set from them is incorrect and is
-- remediated by the script in scripts/remediate_company_bounce_status.py.
INSERT INTO suppression_log (
    workspace_id, scope, reason, contact_id, company_id,
    email, bounce_classification, created_at, metadata
)
SELECT DISTINCT ON (c.id)
    COALESCE(c.workspace_id, '00000000-0000-0000-0000-000000000001'),
    'contact',
    'hard_bounce_contact',
    c.id,
    c.company_id,
    c.email,
    'hard',
    COALESCE(i.created_at, NOW()),
    jsonb_build_object('migrated_from', 'contacts.status', 'original_status', c.status)
FROM contacts c
LEFT JOIN interactions i
    ON i.contact_id = c.id AND i.type = 'email_bounced'
WHERE c.status = 'bounced'
ON CONFLICT DO NOTHING;
