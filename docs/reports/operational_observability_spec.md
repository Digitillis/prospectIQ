# Operational Observability Spec
**Date:** 2026-05-13  
**Scope:** Phase 5 — Send/approval/bounce/reply/suppression/assertion dashboard

---

## Dashboard Panels

### Panel 1: Send Activity (Daily + Rolling)

**SQL:**
```sql
-- Daily send count (last 14 days)
SELECT DATE(sent_at) AS day, COUNT(*) AS sends
FROM outreach_drafts
WHERE sent_at IS NOT NULL
AND sent_at >= NOW() - INTERVAL '14 days'
GROUP BY day ORDER BY day;

-- 7-day send volume
SELECT COUNT(*) FROM outreach_drafts
WHERE sent_at IS NOT NULL AND sent_at >= NOW() - INTERVAL '7 days';

-- Today's sends vs daily limit
SELECT COUNT(*) AS sent_today
FROM outreach_drafts
WHERE sent_at IS NOT NULL
AND DATE(sent_at) = CURRENT_DATE;
```

### Panel 2: Approval Pipeline

**SQL:**
```sql
-- Pending approvals by age
SELECT approval_status,
       COUNT(*) AS count,
       AVG(EXTRACT(EPOCH FROM (NOW() - created_at))/3600) AS avg_age_hours
FROM outreach_drafts
WHERE sent_at IS NULL
GROUP BY approval_status;

-- Rejection rate (last 30 days)
SELECT
    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) AS approved,
    SUM(CASE WHEN approval_status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) AS pending
FROM outreach_drafts
WHERE created_at >= NOW() - INTERVAL '30 days';

-- Top rejection reasons
SELECT rejection_reason, COUNT(*) AS count
FROM outreach_drafts
WHERE approval_status = 'rejected'
AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY rejection_reason ORDER BY count DESC LIMIT 10;
```

### Panel 3: Bounce Rate (CRITICAL — triggers send halt at 2%)

**SQL:**
```sql
-- 7-day rolling bounce rate
SELECT
    SUM(CASE WHEN type = 'email_sent' THEN 1 ELSE 0 END) AS sends,
    SUM(CASE WHEN type = 'email_bounced' THEN 1 ELSE 0 END) AS bounces,
    ROUND(
        100.0 * SUM(CASE WHEN type = 'email_bounced' THEN 1 ELSE 0 END) /
        NULLIF(SUM(CASE WHEN type = 'email_sent' THEN 1 ELSE 0 END), 0),
        2
    ) AS bounce_rate_pct
FROM interactions
WHERE created_at >= NOW() - INTERVAL '7 days'
AND type IN ('email_sent', 'email_bounced');

-- Bounce by sender (identify problematic senders)
SELECT
    (metadata->>'from') AS sender,
    COUNT(*) AS bounces
FROM interactions
WHERE type = 'email_bounced'
AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY sender ORDER BY bounces DESC;
```

### Panel 4: Reply Pipeline

**SQL:**
```sql
-- Reply volume and intent distribution
SELECT
    metadata->>'intent' AS intent,
    COUNT(*) AS count
FROM interactions
WHERE type = 'email_replied'
AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY intent ORDER BY count DESC;

-- Time-to-first-reply (average days from step-1 send to reply)
SELECT AVG(
    EXTRACT(EPOCH FROM (i.created_at - od.sent_at)) / 86400
) AS avg_days_to_reply
FROM interactions i
INNER JOIN outreach_drafts od ON od.contact_id = i.contact_id
    AND od.sequence_step = 1
WHERE i.type = 'email_replied'
AND od.sent_at IS NOT NULL;

-- HITL queue depth
SELECT classification, COUNT(*) AS count
FROM hitl_queue
WHERE status = 'pending'
GROUP BY classification ORDER BY count DESC;
```

### Panel 5: Suppression + Assertions

**SQL:**
```sql
-- Send-path assertion failures (last 7 days)
SELECT assertion, COUNT(*) AS failures
FROM send_assertions
WHERE passed = FALSE
AND assertion_context = 'send_path'
AND evaluated_at >= NOW() - INTERVAL '7 days'
GROUP BY assertion ORDER BY failures DESC;

-- send_path coverage ratio (last 7 days)
SELECT
    COUNT(DISTINCT od.id) AS total_sends,
    COUNT(DISTINCT sa.contact_id) AS covered_by_send_path,
    ROUND(
        100.0 * COUNT(DISTINCT sa.contact_id) /
        NULLIF(COUNT(DISTINCT od.id), 0),
        1
    ) AS coverage_pct
FROM outreach_drafts od
LEFT JOIN send_assertions sa
    ON sa.contact_id = od.contact_id
    AND sa.assertion_context = 'send_path'
    AND sa.evaluated_at >= NOW() - INTERVAL '7 days'
WHERE od.sent_at IS NOT NULL
AND od.sent_at >= NOW() - INTERVAL '7 days';

-- DNC / suppression hits (last 30 days)
SELECT COUNT(*) AS suppression_hits
FROM interactions
WHERE type = 'suppression_hit'
AND created_at >= NOW() - INTERVAL '30 days';
```

### Panel 6: Sequence Health

**SQL:**
```sql
-- Sequence status distribution
SELECT status, COUNT(*) FROM engagement_sequences
GROUP BY status ORDER BY count DESC;

-- Sequences overdue (next_action_at past due)
SELECT COUNT(*) AS overdue
FROM engagement_sequences
WHERE status = 'active'
AND next_action_at < NOW();

-- Step progression (how many contacts at each step)
SELECT sequence_step, COUNT(*) AS contacts
FROM outreach_drafts
WHERE sent_at IS NOT NULL
GROUP BY sequence_step ORDER BY sequence_step;
```

---

## SLO Definitions (see pipeline_health_metrics.md)

| Panel | SLO |
|---|---|
| Bounce rate | < 2% (7-day rolling) |
| send_path coverage | > 95% of sends |
| HITL queue depth | < 20 interested pending |
| Approval pipeline age | < 48h average |
| Heartbeat gap | < 15 min for gmail_intake |
