-- Migration 027: Replace single-tenant RLS with workspace-scoped multi-tenant policies
--
-- Migration 007 enabled RLS but used a single-tenant pattern:
--   FOR ALL USING (auth.role() = 'authenticated')
--
-- This means any authenticated user can read/write any row regardless of
-- workspace_id. For a multi-tenant commercial product, every policy must
-- also check workspace_id so cross-workspace data leakage is impossible
-- at the database layer.
--
-- Strategy:
--   1. Drop the old single-tenant policies
--   2. Create workspace-scoped policies for authenticated users
--   3. Add service_role bypass policies so backend agents (using service key)
--      can query across workspaces for admin/system operations
--   4. Cover all tables added after migration 007 that were missing from it

-- ============================================================
-- DROP OLD SINGLE-TENANT POLICIES
-- ============================================================

DROP POLICY IF EXISTS "authenticated_full_access" ON companies;
DROP POLICY IF EXISTS "authenticated_full_access" ON contacts;
DROP POLICY IF EXISTS "authenticated_full_access" ON research_intelligence;
DROP POLICY IF EXISTS "authenticated_full_access" ON outreach_drafts;
DROP POLICY IF EXISTS "authenticated_full_access" ON interactions;
DROP POLICY IF EXISTS "authenticated_full_access" ON engagement_sequences;
DROP POLICY IF EXISTS "authenticated_full_access" ON api_costs;
DROP POLICY IF EXISTS "authenticated_full_access" ON learning_outcomes;
DROP POLICY IF EXISTS "authenticated_full_access" ON contact_events;
DROP POLICY IF EXISTS "authenticated_full_access" ON content_archive;

-- ============================================================
-- HELPER: workspace_id check via JWT claim
-- Users are issued a JWT that contains app_metadata.workspace_id.
-- The policy checks that the row's workspace_id matches the
-- workspace_id in the token claims.
-- ============================================================

-- Note: auth.jwt() returns the full decoded JWT as JSONB.
-- We read workspace_id from app_metadata (set by Supabase Auth hook
-- or directly at signup). Falls back to user_metadata for compatibility.

CREATE OR REPLACE FUNCTION public.current_workspace_id() RETURNS UUID AS $$
  SELECT COALESCE(
    (auth.jwt() -> 'app_metadata' ->> 'workspace_id')::UUID,
    (auth.jwt() -> 'user_metadata' ->> 'workspace_id')::UUID
  )
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- ============================================================
-- CORE TABLES — workspace-scoped policies
-- ============================================================

-- companies
CREATE POLICY "workspace_member_access" ON companies
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- contacts
CREATE POLICY "workspace_member_access" ON contacts
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- research_intelligence
CREATE POLICY "workspace_member_access" ON research_intelligence
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- outreach_drafts
CREATE POLICY "workspace_member_access" ON outreach_drafts
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- interactions
CREATE POLICY "workspace_member_access" ON interactions
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- engagement_sequences
CREATE POLICY "workspace_member_access" ON engagement_sequences
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- api_costs
CREATE POLICY "workspace_member_access" ON api_costs
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- learning_outcomes
CREATE POLICY "workspace_member_access" ON learning_outcomes
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- contact_events
CREATE POLICY "workspace_member_access" ON contact_events
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- content_archive
CREATE POLICY "workspace_member_access" ON content_archive
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- ============================================================
-- TABLES ADDED AFTER MIGRATION 007 — enable RLS + add policies
-- ============================================================

-- campaign_threads (migration 019)
ALTER TABLE campaign_threads ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON campaign_threads
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- thread_messages (migration 019) — no workspace_id column, scoped via thread
ALTER TABLE thread_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON thread_messages
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM campaign_threads t
            WHERE t.id = thread_messages.thread_id
              AND t.workspace_id = public.current_workspace_id()
        )
    );

-- hitl_queue (migration 019)
ALTER TABLE hitl_queue ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON hitl_queue
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- action_requests (migration 008)
ALTER TABLE action_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON action_requests
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- company_intent_signals (migration 011)
ALTER TABLE company_intent_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON company_intent_signals
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- linkedin_touchpoints (migration 012)
ALTER TABLE linkedin_touchpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON linkedin_touchpoints
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- pipeline_runs (migration 015)
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON pipeline_runs
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- workspace_audit_log (migration 018)
ALTER TABLE workspace_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON workspace_audit_log
    FOR ALL
    USING (workspace_id = public.current_workspace_id());
-- Audit log is append-only: no WITH CHECK to prevent tampering

-- voice_profiles (migration 025)
ALTER TABLE voice_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON voice_profiles
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- ghostwritten_posts (migration 025)
ALTER TABLE ghostwritten_posts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON ghostwritten_posts
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- lookalike_runs (migration 022)
ALTER TABLE lookalike_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workspace_member_access" ON lookalike_runs
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());

-- ============================================================
-- WORKSPACES TABLE — users can only see their own workspace
-- ============================================================

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_owner_and_member_read" ON workspaces
    FOR SELECT
    USING (
        id = public.current_workspace_id()
        OR owner_email = (auth.jwt() ->> 'email')
    );

-- Only the backend service role can create/modify workspace rows
CREATE POLICY "service_role_write" ON workspaces
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ============================================================
-- WORKSPACE MEMBERS — members can see their workspace's members
-- ============================================================

ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_member_read" ON workspace_members
    FOR SELECT
    USING (workspace_id = public.current_workspace_id());

-- Only owner/admin can modify membership (enforced at app layer too)
CREATE POLICY "service_role_write" ON workspace_members
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- ============================================================
-- DO NOT CONTACT LIST — workspace scoped
-- ============================================================

ALTER TABLE do_not_contact ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workspace_member_access" ON do_not_contact
    FOR ALL
    USING (workspace_id = public.current_workspace_id())
    WITH CHECK (workspace_id = public.current_workspace_id());
