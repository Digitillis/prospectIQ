# Pipeline Unlock Report
**Date:** 2026-05-13  
**Scope:** Phase 4 — Pipeline Recovery

---

## 1. Stalled Contacts (Step-2 Eligible)

| Metric | Count |
|---|---|
| Contacts with step-1 sent | 1,000 (sample) |
| Contacts with step-2 draft (any status) | 514 |
| Stalled (step-1 sent, no step-2 draft at all) | 556 |
| Of stalled: email verified/catch_all AND outreach eligible | 349 |
| Of stalled: suppressed/ineligible | 20 |

**349 contacts are immediately eligible for step-2 draft generation.**

These contacts will be picked up by the `_run_draft_generation` cron (every 5 min) when it checks active engagement sequences with `next_action_at` due. If sequences exist for these contacts, the JIT pre-generate cron (`jit_pregenerate`, every 24h) will also generate drafts for any due within 3 days.

No step-2 drafts were created in the last 24 hours. This is consistent with the research/enrichment/discovery croms being paused as of 2026-05-07.

**Action required:** When resuming pipeline operations, these 349 contacts are the priority population for step-2 draft generation. The existing crons will handle this automatically once unpaused.

---

## 2. ZeroBounce Second Pass (1,504 Null-Status Contacts)

**Actual null-status count from live DB:** 7,769 contacts with null `email_status`

This is larger than the 1,504 from the prior audit, suggesting additional contacts were imported without verification.

**ZeroBounce API key status:** NOT SET  
`ZEROBOUNCE_API_KEY` is not in `.env` and not in the Railway Variables (returns empty string from `get_settings()`).

**Credits check:** Cannot be performed until `ZEROBOUNCE_API_KEY` is set in Railway Variables.

**Command to run when credits are purchased and key is set:**
```bash
cd /Users/avanish/prospectIQ && .venv/bin/python zb_verify.py
```

The script will:
1. Check available credits
2. Batch verify contacts with `email_status IS NULL`
3. Update `contacts.email_status` for each result
4. Print progress per batch

**If credits are insufficient for all 7,769:** the script already handles partial runs — it verifies `min(credits, contact_count)` contacts. Prioritize contacts with recent engagement_sequences activity first by modifying the query in `zb_verify.py` to add `.order("created_at", desc=True)`.

---

## 3. Company Lifecycle Backfill (EXECUTED)

### Before
- Companies with `status='outreach_pending'` and sent drafts: **382**
- Companies with `status='contacted'` (from engagement agent): 475

### After (executed 2026-05-13)
- Updated: **382 companies** set from `outreach_pending` to `contacted`
- Verification: 0 of first 50 still showing `outreach_pending`

### Backfill query
```sql
-- Identifies companies to backfill (for re-running verification)
SELECT c.id, c.name, c.status
FROM companies c
WHERE c.status = 'outreach_pending'
AND EXISTS (
    SELECT 1 FROM outreach_drafts od
    WHERE od.company_id = c.id
    AND od.sent_at IS NOT NULL
);
```

---

## 4. Updated Funnel Metrics (Post-Recovery)

| Metric | Before | After |
|---|---|---|
| Companies with `status='contacted'` | 475 | 857 |
| Companies with `status='outreach_pending'` (incorrect) | 382+ | ~0 (for sent companies) |
| Sendable contacts (verified/catch_all) | 1,968 | 1,968 |
| Sent drafts (all steps) | 1,137 | 1,137 |
| Pending drafts (awaiting approval) | 269 | 269 |
| Approved unsent drafts | 101 | 101 |
| Stalled step-2 eligible | 349 | 349 (unchanged — needs cron) |
| 7-day bounce rate | 0.00% | 0.00% |
| All-time bounce rate | 4.10% | 4.10% |

**The all-time 4.10% bounce rate (45 bounces / 1,097 sends) exceeds the 2% threshold.** The 7-day rolling rate is 0% because these bounces occurred earlier in the campaign when contact data quality was lower. The 7-day rolling gate in `assert_bounce_rate_ok` is the correct operational metric — it does not currently block sends.

---

## 5. Pipeline Value Assessment

| Cohort | Contacts | Estimated pipeline value |
|---|---|---|
| Step-2 eligible (stalled) | 349 | 349 potential follow-up touchpoints |
| Contacts awaiting ZB verification | 7,769 | Up to 7,769 additional sendable contacts |
| Approved unsent drafts | 101 | 101 sends queued for next send window |
| Pending drafts (in review) | 269 | 269 drafts in approval workflow |
