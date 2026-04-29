-- Migration 006: LLM-enhanced qualification results
-- Adds a JSONB column to companies for storing 7-gate LLM qualification results.
-- Phase 4: LLM-Enhanced Qualification

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS llm_qualification_result JSONB,
    ADD COLUMN IF NOT EXISTS llm_qualified_at         TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_companies_llm_qualified
    ON companies(workspace_id, llm_qualified_at DESC NULLS LAST)
    WHERE llm_qualification_result IS NOT NULL;
