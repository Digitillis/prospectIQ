-- Migration 014: Add tranche and campaign_cluster columns
-- Supports three-tranche ICP segmentation ($100M-$400M / $400M-$1B / $1B-$2B)
-- and vertical campaign cluster routing (machinery / auto / chemicals / metals / process / fb)

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS tranche TEXT
    CHECK (tranche IN ('T1', 'T2', 'T3', 'watchlist') OR tranche IS NULL),
  ADD COLUMN IF NOT EXISTS campaign_cluster TEXT
    CHECK (campaign_cluster IN ('machinery', 'auto', 'chemicals', 'metals', 'process', 'fb', 'other') OR campaign_cluster IS NULL),
  ADD COLUMN IF NOT EXISTS outreach_mode TEXT
    CHECK (outreach_mode IN ('auto', 'manual') OR outreach_mode IS NULL) DEFAULT 'auto';

-- Index for efficient routing queries
CREATE INDEX IF NOT EXISTS idx_companies_tranche ON companies(tranche);
CREATE INDEX IF NOT EXISTS idx_companies_campaign_cluster ON companies(campaign_cluster);
CREATE INDEX IF NOT EXISTS idx_companies_outreach_mode ON companies(outreach_mode);

-- Comments
COMMENT ON COLUMN companies.tranche IS 'Revenue tranche: T1=$100M-400M, T2=$400M-1B, T3=$1B-2B, watchlist=excluded from auto outreach';
COMMENT ON COLUMN companies.campaign_cluster IS 'Vertical campaign cluster for Instantly sequence routing';
COMMENT ON COLUMN companies.outreach_mode IS 'auto=push to Instantly automatically, manual=flag for human review before outreach';
