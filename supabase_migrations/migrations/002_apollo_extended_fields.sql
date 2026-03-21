-- Extended Apollo fields for richer segmentation and qualification

-- Company fields
ALTER TABLE companies ADD COLUMN IF NOT EXISTS sic_codes JSONB DEFAULT '[]'::jsonb;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS naics_codes JSONB DEFAULT '[]'::jsonb;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS headcount_growth_6m FLOAT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS headcount_growth_12m FLOAT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS headcount_growth_24m FLOAT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS parent_company_id TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS parent_company_name TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS stock_symbol TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS revenue_printed TEXT;

-- Contact fields
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS has_email BOOLEAN DEFAULT FALSE;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS has_direct_phone BOOLEAN DEFAULT FALSE;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_refreshed_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_status TEXT DEFAULT 'not_sent';
