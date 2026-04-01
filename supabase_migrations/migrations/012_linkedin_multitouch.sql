-- 012_linkedin_multitouch.sql
-- LinkedIn activity tracking for multi-channel outreach.
-- Logs manual touchpoints noted by the sales team (no scraping).

CREATE TABLE IF NOT EXISTS linkedin_touchpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    touchpoint_type TEXT NOT NULL CHECK (
        touchpoint_type IN (
            'profile_view',
            'connection_accepted',
            'message_sent',
            'post_engagement'
        )
    ),
    viewer_or_actor TEXT,           -- who performed the action (sales rep name)
    notes TEXT,                     -- free-text observation
    post_url TEXT,                  -- for post_engagement type
    engagement_type TEXT,           -- 'like' | 'comment' | 'share' (post_engagement only)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_li_contact
    ON linkedin_touchpoints (contact_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_li_company
    ON linkedin_touchpoints (company_id, created_at DESC);

COMMENT ON TABLE linkedin_touchpoints IS
    'Manual LinkedIn activity log — no scraping. '
    'Company-level post_engagement rows drive an intent signal via IntentEngine.';
