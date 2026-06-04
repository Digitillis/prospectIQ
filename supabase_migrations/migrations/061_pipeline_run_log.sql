-- Migration 061: Pipeline run log
--
-- One row per stage execution per run. Append-only: no UPDATE or DELETE.
-- Purpose: operators can see what ran, what was filtered out and why, and
-- what failed — without tailing logs. Instrumented at the two highest-value
-- filter/transform points in the send pipeline (load_state, enqueue).
--
-- workspace_id is plain UUID NOT NULL (no FK), matching the convention used
-- by 060_send_schedule.sql and the rest of the send-pipeline tables.
--
-- Author: Avanish Mehrotra & Digitillis Technical Team
-- Date: 2026-06-04

CREATE TABLE IF NOT EXISTS pipeline_run_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL,                 -- shared across all stages of one run
    workspace_id    UUID NOT NULL,
    stage           TEXT NOT NULL,                 -- e.g. 'load_state_filter', 'enqueue_todays_schedule'
    input_count     INTEGER,
    output_count    INTEGER,
    filtered_count  INTEGER,
    filter_reason   TEXT,                          -- why items were filtered (e.g. 'model_tag_mismatch')
    duration_ms     INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only — no UPDATE or DELETE permitted
CREATE OR REPLACE RULE pipeline_run_log_no_update AS
    ON UPDATE TO pipeline_run_log DO INSTEAD NOTHING;

CREATE OR REPLACE RULE pipeline_run_log_no_delete AS
    ON DELETE TO pipeline_run_log DO INSTEAD NOTHING;

CREATE INDEX IF NOT EXISTS idx_pipeline_run_log_workspace_recent
    ON pipeline_run_log (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_log_run
    ON pipeline_run_log (run_id);
