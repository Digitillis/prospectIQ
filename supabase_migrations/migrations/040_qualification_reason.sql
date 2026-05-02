-- Migration 040: Add disqualification_reason to companies
-- Captures WHY a company was disqualified or selected, so re-reviews have
-- evidence to work from rather than null fields.

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS disqualification_reason TEXT
    CHECK (disqualification_reason IN (
      'firmographic_score_too_low',   -- Failed pre-filter (no research yet)
      'pqs_score_too_low',            -- Failed full PQS post-research scoring
      'wrong_industry',               -- NAICS not in ICP target list
      'revenue_too_low',              -- Revenue below floor for this segment
      'employees_too_few',            -- Headcount below minimum
      'wrong_country',                -- Not US or Canada
      'low_confidence_research',      -- Research returned nothing useful
      'llm_gate_failed',              -- LLM qualification gates (persona/fit/intent)
      'competitor',
      'existing_customer',
      'manual',                       -- Manually excluded by user
      'other'
    )),
  ADD COLUMN IF NOT EXISTS qualification_decision TEXT
    CHECK (qualification_decision IN (
      'qualified',
      'disqualified',
      'research_needed',
      'outreach_pending',
      'watchlist'
    ));

-- Index for filtering by reason (common in re-review queries)
CREATE INDEX IF NOT EXISTS idx_companies_disqualification_reason
  ON companies (workspace_id, disqualification_reason)
  WHERE disqualification_reason IS NOT NULL;

-- Index for dashboard counts by decision
CREATE INDEX IF NOT EXISTS idx_companies_qualification_decision
  ON companies (workspace_id, qualification_decision)
  WHERE qualification_decision IS NOT NULL;
