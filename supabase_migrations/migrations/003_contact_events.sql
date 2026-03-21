-- Contact Event Thread — chronological timeline of every interaction per contact

CREATE TABLE IF NOT EXISTS contact_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id),

    -- What happened
    event_type TEXT NOT NULL,  -- outreach_sent, response_received, connection_accepted,
                               -- status_change, note_added, meeting_scheduled, meeting_held,
                               -- email_opened, link_clicked, profile_viewed, system_action
    channel TEXT,              -- linkedin, email, phone, in_person, system
    direction TEXT,            -- outbound, inbound, internal

    -- Content
    subject TEXT,
    body TEXT,

    -- AI analysis (populated by Claude when logging inbound events)
    sentiment TEXT,            -- positive, neutral, negative
    sentiment_reason TEXT,     -- Why Claude classified it this way
    signals JSONB DEFAULT '[]',  -- Intent signals extracted by Claude
    tags JSONB DEFAULT '[]',     -- User or AI tags

    -- Next action (AI-suggested)
    next_action TEXT,
    next_action_date DATE,
    next_action_status TEXT DEFAULT 'pending',  -- pending, done, skipped
    suggested_message TEXT,    -- AI-drafted follow-up message
    action_reasoning TEXT,     -- Why Claude recommended this

    -- Scoring impact
    pqs_delta INTEGER DEFAULT 0,

    -- Metadata
    created_by TEXT DEFAULT 'user',  -- user, system, agent
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_events_contact ON contact_events(contact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contact_events_company ON contact_events(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contact_events_next_action ON contact_events(next_action_date, next_action_status)
    WHERE next_action_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_contact_events_type ON contact_events(event_type);
