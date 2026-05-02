-- Migration 039: Per-sender tracking on outreach_drafts
-- Adds sender_email so bounce/complaint rates can be broken down per sending account.
-- Also adds delivery_status for a cleaner unified field (resend_status was Resend-only).

ALTER TABLE outreach_drafts
  ADD COLUMN IF NOT EXISTS sender_email TEXT,
  ADD COLUMN IF NOT EXISTS opened_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS clicked_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS bounced_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS complained_at TIMESTAMPTZ;

-- Index for per-sender analytics queries
CREATE INDEX IF NOT EXISTS idx_outreach_drafts_sender_email
  ON outreach_drafts (sender_email)
  WHERE sender_email IS NOT NULL;

-- Index for bounce rate queries (sender + bounce)
CREATE INDEX IF NOT EXISTS idx_outreach_drafts_sender_bounced
  ON outreach_drafts (sender_email, bounced_at)
  WHERE bounced_at IS NOT NULL;

-- Backfill sender_email from outreach_send_config where possible
-- (only works if instantly_campaign_id or contact linkage exists; most will stay NULL for historical rows)
-- No backfill attempted — new sends will populate going forward.
