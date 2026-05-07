-- Track which model generated each draft.
-- Used by the model router to escalate from Haiku → Sonnet on rejection.
ALTER TABLE outreach_drafts
  ADD COLUMN IF NOT EXISTS model TEXT;

-- Index for fast lookup of rejected drafts by contact + step
CREATE INDEX IF NOT EXISTS idx_outreach_drafts_rejection_lookup
  ON outreach_drafts (contact_id, sequence_name, sequence_step, approval_status)
  WHERE approval_status = 'rejected';
