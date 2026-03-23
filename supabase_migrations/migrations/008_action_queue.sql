-- 008: Dynamic Action Queue System
CREATE TABLE IF NOT EXISTS action_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_type TEXT NOT NULL,
    requested_count INT NOT NULL,
    fulfilled_count INT NOT NULL DEFAULT 0,
    filters JSONB DEFAULT '{}',
    from_existing INT DEFAULT 0,
    from_apollo INT DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTz DEFAULT NOW()
);
CREATE INDEX idx_ar_status ON action_requests(status);

CREATE TABLE IF NOT EXISTS action_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_type TEXT NOT NULL,
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'auto',
    request_id UUID REFERENCES action_requests(id) ON DELETE SET NULL,
    priority INT NOT NULL DEFAULT 50,
    pqs_at_queue_time INT,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_date DATE NOT NULL DEFAULT CURRENT_DATE,
    completed_at TIMESTAMPTz,
    skipped_reason TEXT,
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_aq_schedule ON action_queue(scheduled_date, status, priority);
CREATE INDEX idx_aq_type ON action_queue(action_type, scheduled_date, status);
CREATE INDEX idx_aq_contact ON action_queue(contact_id, scheduled_date);

CREATE TABLE IF NOT EXISTS daily_targets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_type TEXT NOT NULL,
    target_count INT NOT NULL,
    effective_date DATE,
    day_of_week INT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(action_type, effective_date, day_of_week)
);
INSERT INTO daily_targets (action_type, target_count) VALUES
    ('connection', 10), ('dm', 5), ('email', 3), ('outcome', 2), ('post', 1)
ON CONFLICT DO NOTHING;

ALTER TABLE action_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_targets ENABLE ROW LEVEL SECURITY;
CREATE POLICY "auth_full" ON action_requests FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "auth_full" ON action_queue FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY "auth_full" ON daily_targets FOR ALL TO authenticated USING (true) WITH CHECK (true);
