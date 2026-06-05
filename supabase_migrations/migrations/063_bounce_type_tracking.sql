-- Migration 063: add bounce_type + bounce_smtp_code to outreach_drafts.
--
-- Context (discovered 2026-06-05):
--   The Resend webhook delivers two distinct bounce classes:
--     Permanent — hard bounce (dead address, Exchange block). DNC forever.
--     Transient  — soft bounce (auth failure, temp reject). Do not DNC; may retry.
--   The webhook handler was treating both as hard bounces, permanently suppressing
--   contacts that may still be reachable. These columns let the handler branch
--   correctly and give the bounce_rate gate a clean hard-only numerator.
--
-- Also: resend_status was never updated when email.bounced fired after
-- email.delivered, leaving contradictory state (resend_status='delivered' AND
-- bounced_at IS NOT NULL). The webhook fix writes resend_status='bounced' on
-- email.bounced; no schema change needed for that.

ALTER TABLE outreach_drafts
    ADD COLUMN IF NOT EXISTS bounce_type      TEXT
        CHECK (bounce_type IN ('hard', 'soft', 'complaint')),
    ADD COLUMN IF NOT EXISTS bounce_smtp_code TEXT;

COMMENT ON COLUMN outreach_drafts.bounce_type IS
    'Resend bounce classification at webhook time: hard (Permanent), soft (Transient), complaint.
     NULL when no bounce has been received. Used by the 7-day bounce-rate gate to count
     only hard bounces, and by suppression logic to skip DNC for soft bounces.';

COMMENT ON COLUMN outreach_drafts.bounce_smtp_code IS
    'First SMTP diagnostic code from Resend bounce.diagnosticCode[0], e.g.
     "smtp;550 5.1.10 RESOLVER.ADR.RecipientNotFound". Max 200 chars.
     Aids triage: 5.1.10 = dead address; 5.4.1 = Exchange access denied; 5.7.134 = auth.';

CREATE INDEX IF NOT EXISTS idx_drafts_bounce_type
    ON outreach_drafts (bounce_type)
    WHERE bounce_type IS NOT NULL;
