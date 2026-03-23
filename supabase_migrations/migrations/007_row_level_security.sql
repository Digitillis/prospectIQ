-- Row Level Security (RLS) Policies
-- Single-tenant app: authenticated users have full access to all tables

-- ============================================================
-- ENABLE RLS ON ALL TABLES
-- ============================================================

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_intelligence ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE engagement_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_archive ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- AUTHENTICATED ACCESS POLICIES
-- Single-tenant: any authenticated user gets full CRUD access
-- ============================================================

CREATE POLICY "authenticated_full_access" ON companies
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON contacts
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON research_intelligence
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON outreach_drafts
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON interactions
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON engagement_sequences
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON api_costs
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON learning_outcomes
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON contact_events
    FOR ALL USING (auth.role() = 'authenticated');

CREATE POLICY "authenticated_full_access" ON content_archive
    FOR ALL USING (auth.role() = 'authenticated');
