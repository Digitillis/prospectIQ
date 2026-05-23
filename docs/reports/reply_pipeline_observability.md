# Reply Pipeline Observability Spec
**Date:** 2026-05-13  
**Scope:** Phase 3 — Ongoing telemetry for Gmail IMAP reply ingestion

---

## 1. Metrics to Collect

### Heartbeat (already implemented)
- **Event:** `gmail_intake_heartbeat` — logged at start of every 15-min tick
- **Event:** `gmail_intake_complete` — logged at end of every 15-min tick
- **Alert:** >15 min gap in heartbeat events = cron stopped

### Per-tick counters (already implemented via `logger.info`)
```
gmail_intake [{ws_name}]: {processed} processed, {skipped} skipped
```

**Enhancement needed:** add structured keys so these can be queried:
```python
logger.info("gmail_intake_tick_summary workspace=%s processed=%d skipped=%d accounts=%d",
            ws_name, processed, skipped, len(accounts_to_poll),
            extra={"event": "gmail_intake_tick_summary", "workspace": ws_name,
                   "processed": processed, "skipped": skipped})
```

---

## 2. Dashboard Queries

### Active reply pipeline
```sql
SELECT COUNT(*) FROM interactions
WHERE type = 'email_replied' AND source = 'gmail_imap'
AND created_at >= NOW() - INTERVAL '7 days';
```

### Reply intent breakdown (last 30 days)
```sql
SELECT metadata->>'intent' AS intent, COUNT(*) AS count
FROM interactions
WHERE type = 'email_replied'
AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY metadata->>'intent'
ORDER BY count DESC;
```

### Thread messages written vs interactions
```sql
-- Inbound thread_messages (check thread_id joins)
SELECT COUNT(*) FROM thread_messages
WHERE direction = 'inbound'
AND source = 'gmail_imap'
AND created_at >= NOW() - INTERVAL '7 days';
```

### HITL queue from replies
```sql
SELECT classification, COUNT(*) FROM hitl_queue
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY classification ORDER BY count DESC;
```

### Reply-to-sequence update coverage
```sql
-- Sequences paused due to not_interested replies
SELECT COUNT(*) FROM engagement_sequences
WHERE status = 'paused';

-- Sequences expedited due to interested replies
SELECT COUNT(*) FROM engagement_sequences
WHERE status = 'active'
AND next_action_at < NOW() + INTERVAL '2 days';
```

---

## 3. Alerting Thresholds

| Metric | Warning | Critical |
|---|---|---|
| Heartbeat gap | > 15 min | > 30 min |
| Skipped replies (no match) | > 80% of fetched | > 95% |
| thread_message insert failures | Any | Any |
| interaction write failures | Any | Any |
| HITL queue depth (interested) | > 10 unactioned | > 20 unactioned |

---

## 4. Health Check Endpoint Spec

Add to `/api/monitoring/health` or `/api/approvals/status`:

```json
{
  "gmail_intake": {
    "last_heartbeat_at": "2026-05-13T14:30:00Z",
    "minutes_since_last_tick": 4,
    "replies_7d": 0,
    "replies_30d": 0,
    "hitl_pending": 0,
    "status": "healthy"
  }
}
```

---

## 5. Log Parsing (Railway)

Search Railway logs for:
- `gmail_intake_heartbeat` — confirms cron is alive
- `gmail_intake [{ws}]: N processed` — confirms reply volume
- `thread_message insert failed` — catch schema errors
- `Gmail intake [{ws}]: account {email} failed` — catch credential errors

---

## 6. Missing Observability Items (Priority Order)

| Priority | Item | Implementation |
|---|---|---|
| P0 | Railway env var verification — `GMAIL_APP_PASSWORD` | Avanish action |
| P0 | Structured log per tick with `processed`/`skipped` counts | 1-line code change |
| P1 | Alert on > 30-min heartbeat gap | Railway alerting or external monitor |
| P1 | Dashboard panel: interactions by source (gmail_imap vs instantly_webhook) | SQL query above |
| P2 | Store IMAP last-run timestamp in DB for gap detection | New table row |
| P3 | Move from UNSEEN to Gmail API label-based polling | Larger refactor |
