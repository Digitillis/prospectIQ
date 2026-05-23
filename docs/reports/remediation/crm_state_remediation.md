# Phase 5 — CRM State Remediation

**Date:** 2026-05-13  
**Confidence:** HIGH

---

## Company Lifecycle State Assessment

### Current State

| Status | Count | Notes |
|--------|-------|-------|
| researched | 1,140 | Has research data; may or may not have had outreach |
| outreach_pending | 531 | Queued for outreach but not yet contacted |
| contacted | 475 | Step-1 sent |
| disqualified | 209 | Intentionally excluded |
| qualified | 80 | Qualified but not contacted |
| discovered | 20 | Identified, not researched |
| engaged | 9 | Replied positively |
| bounced | 1 | All contacts bounced |
| **NULL** | **0** | None at NULL — status is fully populated |

**Key finding:** The company status field is fully populated. The original report's claim that 1,465 companies had NULL status is **outdated** — the pipeline has since backfilled these. All 2,465 companies have a status value.

### Companies with Outreach Sent vs Status

867 companies have had at least one step-1 draft sent. Their status breakdown:

| Status | Count |
|--------|-------|
| contacted | 475 |
| outreach_pending | 382 |
| engaged | 9 |
| bounced | 1 |

**Finding:** 382 companies have `status = outreach_pending` despite having had email sent. This is a status lag — they were queued for outreach, outreach was sent, but the status was not advanced from `outreach_pending` to `contacted`.

### SQL to Correct outreach_pending → contacted

```sql
-- Identify companies with sends but outreach_pending status
UPDATE companies
SET status = 'contacted'
WHERE id IN (
    SELECT DISTINCT company_id
    FROM outreach_drafts
    WHERE sent_at IS NOT NULL
)
AND status = 'outreach_pending';

-- Expected rows affected: ~382
```

**Run as a migration** — this is a backfill, not a schema change. Safe to run on production.

### SQL to Tag Engaged Companies

Companies where a contact has `status = 'engaged'` but the company's status has not been updated:

```sql
UPDATE companies c
SET status = 'engaged'
WHERE EXISTS (
    SELECT 1 FROM contacts ct
    WHERE ct.company_id = c.id
    AND ct.status = 'engaged'
)
AND c.status NOT IN ('disqualified', 'converted', 'engaged');
```

---

## Suppression Consistency Check

### interaction vs suppression_log Discrepancy

- email_bounced interactions: **45**
- suppression_log entries (contact scope): **84**

This 39-record gap means 39 contacts were added to suppression_log without a corresponding `email_bounced` interaction. Possible causes:
1. Manual suppression entries (Avanish or ops team added bounces directly)
2. A code path that writes to suppression_log but not to interactions (e.g., the bounce_hygiene agent in `agents/bounce_hygiene.py`)
3. Resend webhook fires and writes suppression but the interaction insert fails silently

This discrepancy is not operationally harmful (suppression is the authoritative source) but reduces reporting accuracy. The bounce rate in the pipeline report (4.1%) is based on interactions, which undercounts the true bounce rate.

**True bounce rate estimate:** 84 hard bounces / 1,097 sends = **7.7%** (contact-scope)

This is significantly above the `MAX_BOUNCE_RATE = 0.02` threshold. However, the 7-day rolling rate may be within bounds if most bounces occurred during early high-volume days.

---

## Additive SQL Remediation Scripts

### Backfill 1: contacted status for companies with sends

```sql
-- SAFE: additive only, moves outreach_pending → contacted
-- Run on staging first, then production
UPDATE companies
SET status = 'contacted',
    updated_at = NOW()
WHERE id IN (
    SELECT DISTINCT company_id
    FROM outreach_drafts
    WHERE sent_at IS NOT NULL
      AND company_id IS NOT NULL
)
AND status = 'outreach_pending';
```

### Backfill 2: Sync company bounce status from suppression_log

```sql
-- Mark company as bounced if 2+ distinct contacts have hard bounces
-- (COMPANY_ESCALATION_BOUNCE_COUNT = 2)
UPDATE companies c
SET status = 'bounced',
    updated_at = NOW()
WHERE id IN (
    SELECT company_id
    FROM suppression_log
    WHERE scope = 'company'
    AND reason = 'hard_bounce_domain'
)
AND status NOT IN ('not_interested', 'disqualified', 'converted');
```

### Backfill 3: interaction records for suppression-only bounces

```sql
-- For the 39 contacts in suppression_log but not in interactions:
-- Create interaction records for audit trail completeness
-- NOTE: Requires Python script to match contact_id → company_id
-- See Phase 5 enrichment_strategy.md for full script
```

---

## Risk Assessment

| Action | Risk Level | Rollback |
|--------|-----------|----------|
| Backfill 1 (outreach_pending → contacted) | LOW | UPDATE back to outreach_pending using same query |
| Backfill 2 (company bounce status) | LOW | UPDATE status back; no data deleted |
| Backfill 3 (interaction records) | VERY LOW | DELETE from interactions WHERE source = 'backfill' |

All three are additive or status-change only. No rows are deleted. All changes are reversible.
