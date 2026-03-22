-- Content Archive — preserves posted thought leadership with engagement tracking

CREATE TABLE IF NOT EXISTS content_archive (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Content
    topic TEXT NOT NULL,
    pillar TEXT,               -- food_safety, predictive_maintenance, ops_excellence, leadership
    format TEXT,               -- data_insight, framework, contrarian, benchmark
    post_text TEXT NOT NULL,
    char_count INTEGER,

    -- Verification
    credibility_score INTEGER,  -- 1-10 from 3-round verification
    publish_ready BOOLEAN DEFAULT FALSE,
    intel_report TEXT,          -- Full verification report

    -- Publication
    posted_at TIMESTAMPTZ,
    linkedin_post_url TEXT,     -- URL to the actual LinkedIn post

    -- Engagement metrics (manually entered)
    impressions INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    engagement_rate FLOAT,      -- Computed: (likes+comments+shares) / impressions
    engagement_updated_at TIMESTAMPTZ,

    -- Source tracking
    draft_id UUID,              -- Reference back to the outreach_drafts row
    calendar_id TEXT,           -- If generated via auto-calendar

    -- Dedup
    topic_hash TEXT,            -- SHA-256 of normalized topic for dedup
    last_posted_topic_at TIMESTAMPTZ,  -- When was this topic last posted (for re-post cooldown)

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_archive_pillar ON content_archive(pillar);
CREATE INDEX IF NOT EXISTS idx_content_archive_posted ON content_archive(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_archive_topic_hash ON content_archive(topic_hash);
CREATE INDEX IF NOT EXISTS idx_content_archive_engagement ON content_archive(engagement_rate DESC NULLS LAST);

CREATE TRIGGER content_archive_updated_at
    BEFORE UPDATE ON content_archive
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
