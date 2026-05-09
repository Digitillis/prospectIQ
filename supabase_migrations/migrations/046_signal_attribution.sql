-- Link outreach drafts to the top company signal used for personalization
ALTER TABLE outreach_drafts
  ADD COLUMN IF NOT EXISTS top_signal_id  UUID,
  ADD COLUMN IF NOT EXISTS top_signal_type TEXT;

COMMENT ON COLUMN outreach_drafts.top_signal_id IS 'ID of the primary company_signals row used for this draft';
COMMENT ON COLUMN outreach_drafts.top_signal_type IS 'Denormalized signal_type for fast analytics queries';
