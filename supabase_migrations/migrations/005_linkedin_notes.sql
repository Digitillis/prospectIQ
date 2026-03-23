-- Add linkedin_notes column to contacts table
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_notes TEXT DEFAULT '';
