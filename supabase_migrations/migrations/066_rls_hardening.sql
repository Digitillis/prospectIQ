-- Migration 066: RLS hardening
-- Enables Row Level Security on 17 tables that were publicly accessible via
-- the Supabase REST API (anon key). Service role and direct postgres connections
-- bypass RLS by default and are unaffected.
--
-- Strategy:
--   - All 17 tables: ENABLE ROW LEVEL SECURITY (blocks anon + authenticated REST)
--   - Tables with workspace_id: add authenticated SELECT/INSERT/UPDATE/DELETE
--     policy scoped to the caller's workspace (future dashboard use)
--   - workspace_api_keys + tables without workspace_id: no policy = service-role only
--
-- Security Definer view: v_company_signal_scores is recreated as SECURITY INVOKER
-- so it executes with the querying user's permissions and respects RLS on the
-- underlying company_signals table.

-- ── 1. Tables WITHOUT workspace_id — service role only ────────────────────────
-- No policies added: anon + authenticated = denied; postgres/service_role = allowed.

ALTER TABLE public.apollo_credit_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.downtime_events            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.login_attempts             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.production_lines           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.production_records         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.seed_audit_events          ENABLE ROW LEVEL SECURITY;

-- ── 2. workspace_api_keys — service role only (never expose raw keys via REST) ─

ALTER TABLE public.workspace_api_keys ENABLE ROW LEVEL SECURITY;

-- ── 3. Tables WITH workspace_id — authenticated users see their own workspace ──

ALTER TABLE public.ab_test_events             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytics_snapshots        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_sequence_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.health_snapshots           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_edit_feedback     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_pace_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_send_config       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_state_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_errors            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.suppression_log            ENABLE ROW LEVEL SECURITY;

-- Workspace-scoped policies for authenticated role.
-- auth.jwt() -> 'app_metadata' ->> 'workspace_id' is set by the Supabase auth hook.
-- If that claim is absent (non-dashboard callers), the USING clause evaluates to
-- NULL and access is denied — correct fail-closed behavior.

CREATE POLICY "workspace_isolation" ON public.ab_test_events
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.analytics_snapshots
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.campaign_sequence_definitions
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.health_snapshots
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.outreach_edit_feedback
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.outreach_pace_log
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.outreach_send_config
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.outreach_state_log
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.pipeline_errors
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

CREATE POLICY "workspace_isolation" ON public.suppression_log
    FOR ALL TO authenticated
    USING (workspace_id = (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::uuid);

-- ── 4. Fix Security Definer view ──────────────────────────────────────────────
-- Recreate v_company_signal_scores as SECURITY INVOKER so it executes with the
-- querying user's permissions and respects RLS on company_signals.

DROP VIEW IF EXISTS public.v_company_signal_scores;

CREATE VIEW public.v_company_signal_scores
    WITH (security_invoker = true)
AS
SELECT
    company_id,
    workspace_id,
    signal_type,
    source,
    signal_text,
    observed_at,
    decay_half_life_days,
    power(
        0.5,
        EXTRACT(epoch FROM now() - observed_at) / 86400.0
        / NULLIF(decay_half_life_days, 0)::numeric
    ) AS freshness_weight,
    value
FROM public.company_signals
WHERE observed_at > now() - INTERVAL '365 days';
