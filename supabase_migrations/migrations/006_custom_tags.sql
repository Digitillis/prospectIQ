-- Add custom_tags column to companies table for tag management
ALTER TABLE companies ADD COLUMN IF NOT EXISTS custom_tags JSONB DEFAULT '[]'::jsonb;
