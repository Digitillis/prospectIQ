# Governance Audit Model
**Date:** 2026-05-13  
**Scope:** Phase 5 — Governance violation definitions, logging, and escalation

---

## 1. What Constitutes a Governance Violation

A **governance violation** is any event where an email was sent (or nearly sent) without the full authoritative send-path assertion suite running and passing.

### Violation Tiers

| Tier | Condition | Response |
|---|---|---|
| **Critical** | Email sent to prospect without ANY assertions | Immediate pause + manual review |
| **High** | Email sent with draft_gen assertions only (no send_path) | Logged, tracked, retroactive review |
| **Medium** | send_path assertion ran but skipped a check | Code fix, no send pause |
| **Low** | assert_bounce_rate_ok ran but bounce rate was 0 sends (vacuous pass) | Monitor |

### Specific Violation Types

1. **No-assertion send** — `outreach_drafts.sent_at` set but no `send_assertions` record for that `contact_id` in `send_path` context  
2. **Rollback failure** — `sent_at` set, assertion failed, but DB rollback also failed (orphaned draft with no delivery)  
3. **Bounce rate override** — bounce rate exceeded 2% but send proceeded  
4. **Step gap violation** — step N sent when step N-1 was not confirmed sent  
5. **Cooldown violation** — same contact emailed within cooldown window (same step)  
6. **Suppressed contact send** — contact was suppressed/DNC but email was sent  

---

## 2. Violation Logging

### Current logging (implemented)

All assertion results are written to `send_assertions` table with:
- `contact_id` — the contact being evaluated
- `company_id` — their company
- `assertion` — the check name
- `passed` — boolean
- `detail` — human-readable detail string
- `assertion_context` — `"draft_gen"` or `"send_path"`
- `evaluated_at` — timestamp

For send-path failures, engagement.py logs:
```
send_path_governance assertion_fail draft_id=... contact_id=... assertion=... detail=...
```

For rollback failures:
```
send_path_governance rollback_failure draft_id=... CRITICAL log — ORPHANED DRAFT
```

### Missing logging (gaps)

1. **No governance violation record distinct from assertion failure** — there is no dedicated `governance_violations` table. Violations must be reconstructed from `send_assertions` + `outreach_drafts` cross-join.  
2. **No alert on no-assertion sends** — the system does not detect when a send occurred without any send_path assertion record. `governance_enforcement_trace.py` must be run manually.

### Recommended: governance_violations table

```sql
CREATE TABLE governance_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    violation_type TEXT NOT NULL,  -- 'no_assertion_send', 'rollback_failure', etc.
    severity TEXT NOT NULL,        -- 'critical', 'high', 'medium', 'low'
    draft_id UUID REFERENCES outreach_drafts(id),
    contact_id UUID,
    company_id UUID,
    detail TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 3. Escalation Behavior

| Violation | Immediate action | Escalation |
|---|---|---|
| Bounce rate > 2% | All sends blocked (assert_bounce_rate_ok raises) | Slack alert |
| Rollback failure (orphaned draft) | CRITICAL log in Railway | Manual review required |
| No-assertion send detected | `governance_enforcement_trace.py` report | Review prior sends |
| Step gap violation | Send blocked, rollback | Slack warning |
| Suppressed contact | Send blocked | Log warning |

---

## 4. Detection Queries

### Detect no-assertion sends (run weekly)
```sql
SELECT od.id, od.contact_id, od.company_id, od.sent_at
FROM outreach_drafts od
WHERE od.sent_at IS NOT NULL
AND od.sent_at >= NOW() - INTERVAL '7 days'
AND NOT EXISTS (
    SELECT 1 FROM send_assertions sa
    WHERE sa.contact_id = od.contact_id
    AND sa.assertion_context = 'send_path'
    AND sa.evaluated_at >= od.sent_at - INTERVAL '5 minutes'
    AND sa.evaluated_at <= od.sent_at + INTERVAL '5 minutes'
);
```

### Detect orphaned drafts
```sql
-- Drafts with sent_at set but no email_sent interaction
SELECT od.id, od.contact_id, od.sent_at
FROM outreach_drafts od
WHERE od.sent_at IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM interactions i
    WHERE i.contact_id = od.contact_id
    AND i.type = 'email_sent'
    AND i.created_at >= od.sent_at - INTERVAL '2 minutes'
    AND i.created_at <= od.sent_at + INTERVAL '2 minutes'
);
```

### Detect rollback failures (CRITICAL logs)
```
Railway log search: "rollback_failure"
```
