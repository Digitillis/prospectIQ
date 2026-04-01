-- Migration 002: Add tranche and campaign_cluster columns to companies
-- Apply via Supabase SQL editor

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS tranche TEXT CHECK (tranche IN ('T1', 'T2', 'T3')),
    ADD COLUMN IF NOT EXISTS campaign_cluster TEXT;

-- Indexes for routing queries
CREATE INDEX IF NOT EXISTS idx_companies_tranche         ON companies(tranche);
CREATE INDEX IF NOT EXISTS idx_companies_campaign_cluster ON companies(campaign_cluster);
