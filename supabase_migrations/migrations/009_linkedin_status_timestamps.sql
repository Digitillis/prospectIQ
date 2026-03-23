-- Add timestamp columns for each LinkedIn status transition
-- Provides full time traceability of the outreach lifecycle
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_connection_sent_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_accepted_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_dm_sent_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_responded_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_meeting_booked_at TIMESTAMPTZ;
