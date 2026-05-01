-- Migration 037: F&B FSMA 204 ICP Segment
-- Adds campaign_cluster and fsma_exposure to companies, segment tracking to
-- outreach_pace_log, and extends icp_exclusions with F&B-specific reasons.

-- campaign_cluster already exists with a narrow check constraint — drop it
-- so the new fsma_* cluster values are accepted.
ALTER TABLE companies
  DROP CONSTRAINT IF EXISTS companies_campaign_cluster_check;

-- Add fsma_exposure column (campaign_cluster column already exists)
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS fsma_exposure TEXT
    CHECK (fsma_exposure IN ('high', 'medium', 'low'));

-- Index to support filtering by cluster (e.g., "show all fsma_dairy companies")
CREATE INDEX IF NOT EXISTS idx_companies_campaign_cluster
  ON companies (campaign_cluster)
  WHERE campaign_cluster IS NOT NULL;

-- Backfill campaign_cluster for existing F&B companies using legacy tier codes
UPDATE companies
SET campaign_cluster = CASE tier
  WHEN 'fb1' THEN 'fsma_food'
  WHEN 'fb2' THEN 'fsma_beverage'
  WHEN 'fb3' THEN 'fsma_meat'
  WHEN 'fb4' THEN 'fsma_dairy'
  ELSE campaign_cluster
END
WHERE tier IN ('fb1', 'fb2', 'fb3', 'fb4')
  AND campaign_cluster IS NULL;

-- Add campaign_cluster to outreach_pace_log for per-cluster send tracking
ALTER TABLE outreach_pace_log
  ADD COLUMN IF NOT EXISTS campaign_cluster TEXT;

-- Extend icp_exclusions reason enum to include F&B-specific exclusion reasons
ALTER TABLE icp_exclusions
  DROP CONSTRAINT IF EXISTS icp_exclusions_reason_check;

ALTER TABLE icp_exclusions
  ADD CONSTRAINT icp_exclusions_reason_check
  CHECK (reason IN (
    'hard_bounce',          -- Email bounced — undeliverable address
    'wrong_person_reply',   -- Reply confirms this is the wrong person
    'not_a_fit',            -- Company replied — not in our ICP
    'competitor',           -- Target is a competitor or prospect of a competitor
    'existing_customer',    -- Already a Digitillis customer
    'manual',               -- Manual exclusion by user
    'already_compliant',    -- Has mature traceability system; not an active prospect
    'regulatory_hold',      -- Under active FDA investigation; wrong time to approach
    'wrong_vertical'        -- Misclassified as F&B; actually different sector
  ));

-- ICP version metadata: track which ICP version generated each outreach outcome
-- (already exists via outreach_outcomes.icp_version_id FK — no change needed)

-- Note: title_classifications cache_key is SHA256(title|industry)[:32].
-- Adding segment awareness would require rebuilding the cache. Deferred —
-- the TitleClassifier's food-safety upgrade rule in contact_filter.py handles
-- the most critical case (compliance manager + food safety context → target).
