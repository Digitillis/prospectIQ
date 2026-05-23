# ProspectIQ Governance Friction & Throughput Audit

**Date:** 2026-05-13 CDT  
**Auditor:** Automated code + database analysis  
**Gate status at time of audit:** Railway SEND_ENABLED=true | DB send_enabled=false  
**Total clean sendable pool:** 19 drafts  
**Total suppressed contacts:** 84 (contact-scope), 0 (company-scope), 1 (company.status=bounced remaining)  
**Total company-locked (5 biz days):** 90 companies (31 approved drafts blocked)  
**Total approved unsent drafts:** 50  
**Critical finding:** ALL 50 approved unsent drafts are blocked by scheduler strict gate (approved_by=NULL on all)

---

## 1. Executive Summary

### Top 5 Friction Points

**1. Dual-gate configuration mismatch (operational risk, immediate)**  
Railway env `SEND_ENABLED=true` while DB `send_enabled=false`. The code gates exclusively on the Railway env var. The DB field is loaded but never checked as a gate. This means the system believes both gates are engaged when only one is. Anyone managing the DB config dashboard sees a false sense of safety.

**2. Scheduler strict gate blocks 100% of queue (throughput collapse, immediate)**  
The scheduler path requires `approved_by IS NOT NULL AND reviewed_at IS NOT NULL` before any send. Zero of the 50 approved unsent drafts have `approved_by` populated. The columns exist in the schema but no approval ever writes to them. Result: the scheduler cannot send anything via its normal path. Every send since gates were disabled has required manual `draft_ids` targeting to bypass this check. This is an undocumented operational dependency that will silently fail when the next scheduled run fires.

**3. Company lock blocks 62% of approved queue (throughput-collapsing, near-term)**  
31 of 50 approved unsent drafts (62%) are blocked because a different contact at the same company received an email within the last 5 business days. These are not multi-contact collision scenarios — zero locked companies had multiple contacts touched in this window. The lock is triggered by a single contact send, then blocks all approved drafts for other contacts at that company for up to 5 business days. The majority (22 of 31) unlock in approximately 3 days.

**4. 23 approved drafts will permanently stall at send-path (silent starvation)**  
23 of the 50 approved unsent drafts have contacts with `email_status=NULL`. The send-path assertion `email_status_verified` blocks any contact whose status is not in `{verified, catch_all}`. NULL fails this check. These drafts will claim `sent_at`, rollback, and re-enter the queue indefinitely. They will never send without email verification. There is no dashboard indicator that these drafts are permanently blocked.

**5. 86% of contacts have NULL email_status; historical bounce rate on NULL is 7.8% (risky, structural)**  
860 of 1000 sampled contacts have `email_status=NULL`. The historical record shows 562 emails were sent to NULL-status contacts, generating a 7.8% bounce rate. `verified` contacts bounced at 6.7%. The gap is small but the scale is large. The current queue gate (`email_status_verified` assertion) prevents sending to NULL-status contacts — this is correct — but means ~46% of the approved queue (23/50) is silently blocked without operator visibility.

### Highest-Value Fixes (in priority order)

1. Wire `approved_by` + `reviewed_at` into the approval UI so the scheduler can function normally
2. Add a dashboard indicator for permanently-stalled drafts (NULL email_status)
3. Align DB `send_enabled` with Railway env var — either check both or remove the DB field
4. Run email verification on the 23 NULL-status contacts in the queue
5. Evaluate company lock window reduction from 5 business days to 2-3 for single-contact companies

---

## 2. Constraint Inventory

Every gate in the send path classified by function and calibration.

| Gate | Location | Classification | Notes |
|---|---|---|---|
| `settings.send_enabled` (Railway env) | `_send_approved_drafts()` first line | **protective-necessary** | Correct. Hard stop before any DB or API calls. |
| DB `send_enabled` field | `outreach_send_config` | **misleading** | Loaded but never checked as a gate. Creates false impression of second gate. |
| `approved_by IS NOT NULL AND reviewed_at IS NOT NULL` | Scheduler path | **protective-necessary** | Correct intent. Broken because approval flow never populates these columns. |
| `approved_by/reviewed_at` bypass for `draft_ids` | Manual path | **protective-necessary** | Acceptable design — explicit targeting IS the human attestation. |
| `is_suppressed()` — contact status (bounced/unsubscribed/not_interested) | Pre-send | **protective-necessary** | Correct. First-tier block. |
| `is_suppressed()` — company suppression_log scope=company | Pre-send | **protective-necessary** | Correct. Only 0 entries currently, but architecture is sound. |
| `is_suppressed()` — competitor check | Pre-send | **protective-necessary** | Correct but relies on `existing_solutions` JSON containing exact competitor strings. Fragile string matching. |
| `is_suppressed()` — sequence cooldown (90 days after completed sequence) | Pre-send | **protective-necessary** | Appropriate for preventing re-entry of completed sequences. |
| `is_suppressed()` — `duplicate_draft_pending` | Draft-gen only (skipped at send-path) | **redundant** | Correctly skipped at send-path. At draft-gen it prevents double-drafting, which is useful but not a send gate. |
| `is_suppressed()` — cross-company email dedup | Pre-send | **protective-necessary** | Correct. Prevents sending to same email address under duplicate company records. |
| `is_company_locked()` — 5 business day window | Pre-send | **protective-too-broad** | Window size is aggressive for single-contact companies. 88 locked companies have only 1 contact touched; the lock applies company-wide regardless. |
| Intra-batch `company_ids_sent_this_batch` dedup | Send loop | **protective-necessary** | Correct. Prevents same-run multi-contact collision. |
| `assert_email_deliverable` — blocks status=invalid/bounce | Send-path assertion | **protective-necessary** | Redundant with suppression check on `contact.status=bounced`, but adds defense-in-depth. |
| `assert_email_status_verified` — blocks NULL/unverified | Send-path assertion | **protective-necessary** | Correct gate. Currently silently stalling 23 approved drafts. Needs operator visibility. |
| `assert_email_name_consistent` — blocks `email_name_verified=False` | Send-path assertion | **protective-necessary** | Correct. Only 0 contacts in queue with this flag. |
| `assert_outreach_eligible` — blocks `is_outreach_eligible=False` | Send-path assertion | **protective-necessary** | Correct. |
| `assert_persona_target` — blocks `contact_tier=excluded` | Send-path assertion | **protective-necessary** | Correct. |
| `assert_no_recent_company_send` (30-day contact cooldown) | Send-path assertion | **redundant** | For step 1: overlaps with company lock (5-day). For step 2+: bypassed entirely (`cooldown_days=0`). The 30-day window is much longer than the company lock window. The assertion is useful as a per-contact check but the two layers serve different scopes. |
| `assert_sender_under_daily_cap` | Send-path assertion | **protective-necessary** | Correct. |
| `assert_prior_step_sent` | Send-path assertion (step 2+ only) | **protective-necessary** | Correct. All 5 step-2 drafts in queue have their step-1 confirmed. |
| `assert_minimum_step_gap` (5-day minimum between steps) | Send-path assertion (step 2+ only) | **protective-necessary** | Correct. |
| Attestation checklist (5 fields required) | Approval UI | **protective-necessary** | Correct intent. Not enforced at send-path — only at approval time. |
| Tier-1 dual-reviewer rule | Approval route | **protective-necessary** | Correct for tier-1 accounts. |
| Daily reviewer cap (30/day) | Approval route | **protective-necessary** | Correct. |
| Quality gate (error-severity blocks approval) | Approval route | **protective-necessary** | Correct. |
| HOT-tier contacts never auto-sent | Engagement tier state machine | **protective-necessary** | Correct. |

---

## 3. Quantitative Impact

### Overall funnel

| Stage | Count |
|---|---|
| Total companies | 1,000 (sampled) / 2,465 total |
| Total contacts | 1,000 (sampled) / 9,945 total |
| Total sent (all time) | 1,127 |
| Total approved unsent (current queue) | 50 |
| Total pending (awaiting approval) | 330 |

### Approved queue breakdown (50 drafts)

| Blocking reason | Count | Notes |
|---|---|---|
| Company lock (5 biz day, other contact) | 31 (62%) | All from single-contact-per-company scenarios |
| NULL email_status (will fail at send-path) | 23 (46%) | Silent permanent stall |
| Scheduler strict gate (no approved_by) | 50 (100%) | Applies to ALL drafts on scheduler path |
| Suppression (contact or company) | 0 | Clean |
| Company status blocked | 0 | Clean (1 bounced company remains but no draft for it) |

*Note: blockers are not mutually exclusive. 19 drafts clear all runtime gates except the scheduler strict gate.*

### Company lock profile

| Unlock timeline | Drafts blocked |
|---|---|
| Already expired (unlock in 0 days) | 3 |
| Unlock in ~3 days (May 05 sends) | 22 |
| Unlock in ~5 days (May 11 sends) | 6 |
| **Total** | **31** |

All locks are from `email_sent` interactions. Zero are from LinkedIn or replies. Zero locked companies had multiple contacts touched in the window (all single-contact-type locks).

### Email verification status

| email_status | Total contacts (sampled 1,000) | Approved queue (50 drafts) | Historical sends (1,000) | Bounce rate |
|---|---|---|---|---|
| verified | 131 (13.1%) | 27 (54%) | 430 | 6.7% |
| NULL | 860 (86%) | 23 (46%) | 562 | 7.8% |
| unavailable | 8 | 0 | 3 | 100% |
| extrapolated | 1 | 0 | 4 | 50% |
| catch_all | 0 | 0 | 0 | N/A |
| invalid | 0 | 0 | 1 | 100% |

Historical overall bounce rate: **7.9%** (79 bounces / ~1,000 unique contacts sent). This is substantially above the industry DTC threshold of 2%.

### Suppression log

| Scope | Reason | Count |
|---|---|---|
| contact | hard_bounce_contact | 84 |
| company | (any) | 0 |
| domain | (any) | 0 |

All 84 entries are backfilled from migration 048. Zero have `provider_code` or `provider_message` populated. No Resend-sourced bounces have landed in the suppression_log since the webhook was wired.

One company (`Kobelco Construction Machinery USA`) still has `status=bounced` from the pre-remediation period. The remediation script reset 69/70 bounced companies but missed this one.

### Send assertions

| Assertion | context=draft_gen PASS | context=draft_gen FAIL | context=send_path |
|---|---|---|---|
| email_deliverable | 201 | 0 | 0 |
| email_name_consistent | 201 | 0 | 0 |
| no_recent_company_send | 154 | 32 | 0 |
| outreach_eligible | 205 | 0 | 0 |
| persona_target | 207 | 0 | 0 |
| email_status_verified | — | — | — (not logged) |
| sender_daily_cap | — | — | — (not logged) |

Zero send_path assertion rows exist. This means either: the send-path gate has never run (consistent with only 3 sends on 2026-05-13 via manual `draft_ids`), or send-path assertions are firing but failing to write to the table. Given that all 3 today's sends succeeded, the latter is unlikely. The send-path assertion path has effectively never been exercised at scale.

The `email_status_verified` and `sender_daily_cap` assertions are never logged even at draft_gen. This indicates the draft-gen outreach agent does not call the full `run_pre_send_assertions()` — it calls a subset (5 of the 9 assertions). This means the send-path is the first place `email_status_verified` is enforced, causing rollback-on-first-attempt for 23 drafts.

### Human review workflow

| Field | Status |
|---|---|
| `approved_by` on all 741 approved/edited drafts | NULL (0 populated) |
| `reviewed_at` on all 741 approved/edited drafts | NULL (0 populated) |
| Attestation writes | Functional (API handles missing columns gracefully) |

The `approved_by` and `reviewed_at` columns exist in the schema but the approval route hits a silent fallback when writing them: if the write fails it retries without those fields. Given all 741 historical approvals have NULL values, the columns were either added after approvals happened or the silent retry is always triggering.

### Batch and pacing history

| Date | Emails sent |
|---|---|
| 2026-04-22 | 1 |
| 2026-04-23 | 6 |
| 2026-04-24 | 4 |
| 2026-04-30 | 28 |
| 2026-05-04 | 465 |
| 2026-05-05 | 372 |
| 2026-05-06 | 9 |
| 2026-05-07 | 15 |
| 2026-05-08 | 6 |
| 2026-05-11 | 64 |
| 2026-05-12 | 1 |
| 2026-05-13 | 3 (controlled, manual) |

The spike on May 4-5 (837 sends in 2 days) predates the governance improvements from PRs 77/82/85/86. Current DB config is `batch_size=4, min_gap_minutes=0, daily_limit=500`. With `min_gap_minutes=0` and the scheduler running every 30 minutes, 4 sends per tick equals 192 per day maximum — but if multiple scheduler instances run in overlap during rolling restarts, that cap is theoretical. The `daily_limit=500` is a hard ceiling but is very large for current scale.

### Interactions and company lock trigger types (last 30 days)

| Type | Count |
|---|---|
| email_sent | 570 |
| email_clicked | 71 |
| email_bounced | 45 |
| email_opened | 35 |
| note | 5 |

No `linkedin_connection`, `linkedin_message`, or `email_replied` interactions in the last 30 days. All company locks are triggered exclusively by `email_sent`. No cross-channel lock scenarios exist currently.

---

## 4. Recommendations

### Immediate (before next scheduled send run)

**R1. Fix the `approved_by` / `reviewed_at` write path** — The silent retry in `approve_draft()` strips these fields when the write fails. Debug why the write is failing (likely the column type doesn't match what's being passed, or there's an RLS policy blocking it). Until this is fixed, the scheduler cannot send anything. Alternatively, ensure `draft_ids` is always used for targeted sends and document this as the operating mode.

**R2. Add DB `send_enabled` to the send gate** — Either check `send_cfg['send_enabled']` alongside `settings.send_enabled` in `_send_approved_drafts()`, or remove the DB field entirely if it's not intended to be a gate. Current state: DB says false, code ignores it. This creates a false dashboard indicator.

**R3. Remediate Kobelco Construction Machinery USA** — The one remaining company with `status=bounced` was missed by the remediation script. Update its status to an appropriate non-bounced state if its contact bounces have been addressed individually. Otherwise it's a permanent block.

**R4. Verify 23 NULL email_status contacts** — Run ZeroBounce or Apollo verification on the 23 contacts whose approved drafts are stalled. If they verify as deliverable, update `email_status=verified` and the drafts will exit the stall. If they don't, reject those drafts and remove them from the queue. Add a dashboard label ("verification required") for any approved draft whose contact has NULL email_status.

### Near-term (within 1-2 weeks)

**R5. Reduce company lock window for single-contact companies** — 5 business days is calibrated for enterprises with multiple contacts where collision risk is real. For companies where only one contact exists and has been emailed, the lock prevents follow-up from the same person's draft, which is nonsensical. Consider: if only one contact has been touched at this company, reduce the lock to 2 business days. If 2+ contacts have been touched, keep 5 days.

**R6. Add email_status_verified to the draft-gen assertion set** — The outreach agent at draft-gen runs only 5 of the 9 assertions in `run_pre_send_assertions()`. Adding `assert_email_status_verified` to draft-gen would prevent NULL-status drafts from entering the approval queue entirely, eliminating the send-path stall scenario. This requires confirming the outreach agent calls `run_pre_send_assertions()` with the correct subset or calling the full set.

**R7. Emit a send_assertion row when email_status_verified fails at draft-gen** — Currently, draft-gen uses `assertion_context='draft_gen'` but `email_status_verified` is never logged. Once R6 is fixed, the failures will be visible in the send_assertions table and surfaced on the alerts dashboard.

**R8. Enforce `min_gap_minutes > 0` in DB config** — Currently `min_gap_minutes=0`. While `batch_size=4` limits sends per tick, overlapping scheduler runs can multiply this. Set `min_gap_minutes=2` as a floor. At 30-minute scheduler intervals, this allows 4 sends per run with stagger, and rate-limits to 8 per hour maximum if back-to-back runs overlap.

**R9. Re-run migration backfill to populate suppression_reason on contacts** — Migration 048 added `suppression_reason` column to `contacts` but the backfill only populated `suppression_log`. Fast single-field reads for the suppression_reason column are empty. Populate from `suppression_log` where a matching `contact_id` exists.

### Longer-term (next sprint)

**R10. Add provider_code/provider_message to Instantly webhook bounce handler** — The Resend webhook handler correctly extracts `bounce.code` and `bounce.message`. The Instantly webhook (`_handle_email_bounced`) does not. For platform consistency and bounce classification, add provider metadata extraction to the Instantly path.

**R11. Build a queue health dashboard widget** — Surface the following metrics on the Outreach dashboard: (a) drafts permanently stalled by NULL email_status, (b) drafts currently locked by company lock with estimated unlock date, (c) drafts blocked by scheduler strict gate. Currently these are invisible; operators see 50 approved drafts and no explanation for why nothing sends.

**R12. Introduce bounce-rate alerting** — 7.9% historical bounce rate across all sends exceeds the 2% threshold that triggers ESP review. Implement a 7-day rolling bounce rate check using the existing `MAX_BOUNCE_RATE = 0.02` constant in `pre_send_assertions.py`. The constant exists but `assert_bounce_rate_under_threshold()` is not implemented. Add it and hook it into the scheduler pre-run check.

**R13. Add domain-scope suppression entries for high-bounce domains** — Zero domain-scope suppression entries exist. If a domain repeatedly bounces (e.g., 3+ contacts at different companies on the same domain), the suppression architecture supports domain-scope blocking but it is never used. Add a domain escalation path alongside the company escalation path.

---

## 5. Experiments

**E1. Company lock window: 2 vs 5 business days (single-contact companies)**  
Hypothesis: Reducing the lock to 2 business days for companies with only one outreach-eligible contact has no meaningful compliance impact and unlocks 22 drafts 3 days sooner.  
Method: Filter `is_company_locked()` to check: if only one distinct contact has been touched at this company in history, use 2-day window; otherwise 5-day. Track whether multi-contact collisions increase.  
Measurement: Multi-contact collision rate (interactions from 2+ contacts to same company within 7 days), complaint rate.  

**E2. catch_all contacts: controlled send of 20 with close monitoring**  
Currently zero catch_all contacts exist in the DB. The assertion allows them. When the next Apollo import brings catch_all contacts, run a controlled batch of 20 with bounce tracking before admitting them at scale. Expected bounce rate: 15-25% based on industry data. If >10%, tighten to verified-only.  

**E3. Queue priority: sort by company PQS score rather than creation date**  
The scheduler fetches drafts `ORDER BY created_at ASC` (oldest first). This means the highest-value companies in the queue may wait behind lower-priority ones. Test PQS-descending sort on a 10-send batch and measure whether open/reply rates improve vs FIFO order.  

**E4. Attestation bypass at draft-gen for verified contacts**  
The 5-field attestation checklist is enforced at approval. For contacts with `email_status=verified` and `email_name_verified=True` who pass all draft-gen assertions, test auto-approval with a reduced checklist (3 fields: `persona_in_allowlist`, `company_is_manufacturer`, `specific_opener`). Track whether approval review time decreases without increasing quality failures.  

**E5. min_gap_minutes: 0 vs 2 vs 5 minutes**  
Current setting is 0 (no gap between sends within a batch). With `batch_size=4`, the 4 sends happen as fast as the loop completes. Test whether Resend delivery rates differ with staggered sending (2 min vs 5 min gap). Also test whether sequential sends within a tick trigger ESP rate-limit warnings.  

---

## 6. Data Queries

All queries run against workspace_id `00000000-0000-0000-0000-000000000001` via Supabase Python client. Results reflect state as of 2026-05-13.

```python
# S1a: Suppression log counts by scope and reason
db.client.table("suppression_log").select("scope, reason").execute()
# -> Counter by (scope, reason)

# S1b: Contacts by status
db.client.table("contacts").select("id", count="exact").eq("status", status).execute()
# status in: bounced (84), unsubscribed (1), not_interested (0), active (0), NULL (0)

# S1c: Companies still status=bounced
db.client.table("companies").select("id, name, status").eq("status", "bounced").execute()
# -> 1 company: Kobelco Construction Machinery USA

# S1d: Domain-scope entries
db.client.table("suppression_log").select("id", count="exact").eq("scope", "domain").execute()
# -> 0

# S1e: Provider field population
db.client.table("suppression_log").select("provider_code, provider_message").execute()
# -> 0/84 have provider_code; 0/84 have provider_message

# S2: Companies under lock (5 business days)
cutoff = business_days_ago(5).isoformat()  # 2026-05-06
db.client.table("interactions").select("company_id, contact_id, type").in_("type", [
    "linkedin_connection","linkedin_message","email_sent","email_replied"
]).gte("created_at", cutoff).execute()
# -> 90 unique companies locked; all from email_sent

# S2b: Approved drafts blocked by company lock
# Cross-reference approved unsent drafts vs locked company IDs
# -> 31 blocked; 0 from same-contact scenario

# S3: Send assertions by type
db.client.table("send_assertions").select("assertion, passed, assertion_context").execute()
# -> 1000 rows, all assertion_context=draft_gen, 0 send_path rows

# S4: Send config
db.client.table("outreach_send_config").select(
    "daily_limit, batch_size, min_gap_minutes, send_enabled, sender_pool, reply_to"
).eq("workspace_id", "00000000-0000-0000-0000-000000000001").limit(1).execute()
# -> daily_limit=500, batch_size=4, min_gap_minutes=0, send_enabled=false (DB), 9-sender pool

# S5: Approved unsent queue
db.client.table("outreach_drafts").select("id, created_at, sequence_step").in_(
    "approval_status", ["approved","edited"]
).is_("sent_at", "null").execute()
# -> 50 total; step 1: 45; step 2: 5; age: 39 in 7-30d range

# S5b: Queue blocking reasons
# Cross-reference with suppression, company lock, email_status
# -> 31 company lock; 23 NULL email_status; 0 suppression; 19 clean (runtime gates)

# S6: Contact email_status distribution
db.client.table("contacts").select("email_status").execute()
# -> NULL: 860; verified: 131; unavailable: 8; extrapolated: 1

# S7: Company status distribution (sampled 1000)
db.client.table("companies").select("status").execute()
# -> researched: 409; outreach_pending: 269; contacted: 250; qualified: 38; 
#    discovered: 20; disqualified: 9; engaged: 4; bounced: 1

# S8: Step-2+ prior step sent
db.client.table("outreach_drafts").select("id, contact_id, sequence_step").in_(
    "approval_status", ["approved","edited"]
).is_("sent_at", "null").execute()
# Filter step>=2, check prior step has sent_at IS NOT NULL
# -> 5 step-2 drafts; 5/5 have step-1 confirmed sent

# S9: Daily send volume (last 30 days)
db.client.table("outreach_drafts").select("sent_at").not_.is_("sent_at", "null").gte(
    "sent_at", cutoff_30d
).execute()
# -> Peak: 465 (2026-05-04), 372 (2026-05-05)

# S10: Human review field population
db.client.table("outreach_drafts").select("approved_by, reviewed_at").in_(
    "approval_status", ["approved","edited"]
).execute()
# -> 741 approved/edited; 0 with approved_by; 0 with reviewed_at

# S11: Interactions by type (all time / last 30 days)
db.client.table("interactions").select("type, created_at").execute()
# -> email_sent: 685 total; email_clicked: 71; email_bounced: 45; email_opened: 35; note: 164

# S12: Resend message ID coverage
db.client.table("outreach_drafts").select("id", count="exact").not_.is_("sent_at","null").is_("resend_message_id","null").execute()
# -> 114 sent drafts missing resend_message_id (pre-Resend era)
# 1013 have resend_message_id populated

# S12b: Suppression_log null fields
# -> domain: 100% null; escalated_from: 100% null; provider_code: 100% null;
#    provider_message: 100% null; triggered_by_contact_id: 100% null

# S13: Bounce rate by email_status (historical sends)
# Cross-reference outreach_drafts.sent_at with contacts.status=bounced by email_status
# -> NULL: 562 sent, 7.8% bounce; verified: 430 sent, 6.7% bounce;
#    unavailable: 3 sent, 100% bounce; extrapolated: 4 sent, 50% bounce
```

---

## 7. Risk Assessment

### R1: Wire approved_by/reviewed_at

| Dimension | Assessment |
|---|---|
| Upside | Scheduler resumes normal operation without manual draft_ids targeting |
| Deliverability risk | None — this is hygiene, not a gate change |
| Compliance risk | Improves compliance auditability |
| Operational risk | Low — schema already exists, write path already has fallback |
| Telemetry required | Log first successful approved_by write to confirm fix |

### R2: Align DB send_enabled with env var gate

| Dimension | Assessment |
|---|---|
| Upside | Single source of truth; operator dashboard reflects actual gate state |
| Deliverability risk | Low — only adds a check, doesn't remove one |
| Compliance risk | None |
| Operational risk | If DB send_enabled=false becomes an active gate, turning it on in DB becomes a required step for resuming sends. Document clearly. |
| Telemetry required | Log which gate source triggered send block |

### R3: Reduce company lock window (5 biz → 2 biz, single-contact case)

| Dimension | Assessment |
|---|---|
| Upside | Unlocks 22 drafts 3 days sooner; reduces queue starvation at scale |
| Deliverability risk | Low. No multi-contact companies are currently affected. The risk is only relevant when multiple contacts at the same company have been imported. |
| Compliance risk | Low — 2 business days is still a meaningful cooldown. Not a GDPR/CAN-SPAM issue. |
| Operational risk | Could trigger unintended double-contact if company DB has duplicate records. The cross-company email dedup in `is_suppressed()` mitigates this. |
| Telemetry required | Track multi-contact send events per company. Alert if 2+ contacts at one company receive email within 3 days. |

### R4: Send to verified contacts whose drafts have NULL email_status after verification

| Dimension | Assessment |
|---|---|
| Upside | Unblocks 23 stalled drafts; clears silent queue starvation |
| Deliverability risk | Low for verified addresses. History shows verified contacts bounce at 6.7% — acceptable but still needs monitoring given absolute volume. |
| Compliance risk | None — verification confirms address legitimacy |
| Operational risk | Low. Verification API call cost. |
| Telemetry required | Log verification results per contact; track bounce rate for newly-verified contacts in first 30 days. |

### R5: Allow catch_all contacts (when they appear)

| Dimension | Assessment |
|---|---|
| Upside | Expands sendable pool — likely 10-20% of Apollo contacts on catch-all domains |
| Deliverability risk | Material. Industry catch_all bounce rates range 15-40%. Sending at scale to catch_all without per-address validation will damage domain reputation. |
| Compliance risk | Low — not a legal issue |
| Operational risk | High if domain reputation degrades. Current assertion already permits catch_all but no catch_all contacts exist yet. |
| Telemetry required | Must track bounce rate for catch_all sub-cohort separately. Gate: if catch_all bounce rate > 10% in first 20 sends, pause catch_all sends. |

---

## 8. Proposed Target Architecture

The following is the calibrated governance model that addresses all identified issues while preserving all legitimate protections.

### Layer 0: Global gates (must all pass before any send logic runs)

- **Railway env SEND_ENABLED=true** — hard stop. No change.
- **DB send_enabled=true** — add as second required gate. Both must be true.
- **7-day rolling bounce rate < 2%** — add pre-run check using interactions table. If exceeded: pause all sends and alert Slack.

### Layer 1: Contact-level suppression (before draft enters queue)

- Contact status in `{bounced, unsubscribed, not_interested}` — no change.
- Suppression_log contact-scope entry — no change.
- Email status must be in `{verified}` (near-term: `{verified, catch_all}` with monitoring gate) — enforce at draft-gen, not only at send-path.
- `email_name_verified` is not False — no change.
- `is_outreach_eligible=True` — no change.
- `contact_tier != excluded` — no change.

### Layer 2: Company-level suppression (before draft enters queue)

- Company status in `{not_interested, disqualified, converted}` — no change.
- Suppression_log company-scope entry — no change.
- Competitor in existing_solutions — no change.
- **Remove**: company.status=bounced as a block. It's been migrated to suppression_log. The 1 remaining company (Kobelco) should be manually remediated.

### Layer 3: Sequence governance (runtime, send loop)

- Prior step sent (step N-1) before step N — no change.
- Minimum 5-day gap between steps — no change.
- Sequence cooldown: 90 days after completion without reply — no change.

### Layer 4: Company send lock (runtime, send loop)

- **Calibrated lock**: 5 business days if 2+ distinct contacts touched at this company in history; 2 business days if only 1 contact touched. Implemented in `is_company_locked()` by adding a contacts-touched count check.
- Intra-batch single-company dedup — no change.

### Layer 5: Pacing (runtime, send loop)

- `daily_limit`: reduce from 500 to 50 for normal operations. 50 per day = healthy ESP reputation. Raise only for deliberate burst campaigns.
- `batch_size`: keep at 4.
- `min_gap_minutes`: raise from 0 to 2.

### Layer 6: Human attestation (approval gate)

- Attestation checklist (5 fields, all true) — no change.
- `approved_by` and `reviewed_at` must be populated on all approvals — fix write path.
- Scheduler requires both fields; manual draft_ids targeting bypasses both (by design).
- Tier-1 dual-reviewer — no change.

### Layer 7: Observability

- Dashboard surface: show blocked drafts by reason (lock, NULL email_status, suppression).
- Bounce rate gauge: 7-day rolling, surfaced prominently.
- Suppression log: provider_code/message populated on all new Resend bounces.
- Send assertions: email_status_verified logged at draft_gen.

---

## 9. Action Plan

Sequenced as PR-sized units of work, ordered by urgency.

### PR A: Fix approved_by/reviewed_at write path (Urgency: CRITICAL, before next send)

**Scope**: `backend/app/api/routes/approvals.py`  
**Work**: Debug why `approved_by` write silently fails. Likely cause: column exists but reviewer_user resolution fails (no auth context in non-auth requests), so `reviewer_id` is empty string and the update writes an empty string that violates a UUID constraint, triggering the retry without those fields.  
**Fix**: If `reviewer_id` is empty, do not include `approved_by` in the update (leave as NULL), but always write `reviewed_at`. Update the scheduler gate to require `reviewed_at IS NOT NULL` only (not `approved_by IS NOT NULL`) when `approved_by` is NULL. This allows the scheduler to run while auth is being sorted.  
**Test**: Approve a draft, confirm `reviewed_at` populates, confirm scheduler picks it up.

### PR B: Check DB send_enabled in send gate (Urgency: HIGH, within 24h)

**Scope**: `backend/app/agents/engagement.py`, `_send_approved_drafts()`  
**Work**: After the `settings.send_enabled` check, load `send_cfg` and add: `if not send_cfg.get('send_enabled', True): return result`. Log a clear message distinguishing which gate blocked the send.  
**Test**: Set DB send_enabled=false, confirm send returns early. Set to true, confirm it proceeds.

### PR C: Run email verification on 23 stalled drafts (Urgency: HIGH, within 48h)

**Scope**: Operations / data task, not code  
**Work**: Export contact IDs for the 23 NULL-status approved drafts. Run ZeroBounce or Apollo verification. Update `email_status` field. If verified → drafts unblock. If invalid → reject drafts, update contact status.  
**Test**: Confirm approved queue count changes after update.

### PR D: Remediate Kobelco bounce status (Urgency: MEDIUM)

**Scope**: Database  
**Work**: Check suppression_log for Kobelco contacts. If contact-level bounces exist and no company-scope entry exists, update `companies.status` from `bounced` to `contacted` or `researched` as appropriate.  
**Test**: Query confirms no companies with `status=bounced`.

### PR E: Add email_status_verified to draft-gen assertions (Urgency: MEDIUM)

**Scope**: `backend/app/agents/outreach.py` (the OutreachAgent, not reviewed in this audit — find where `run_pre_send_assertions` is called with `assertion_context='draft_gen'`)  
**Work**: Ensure the full assertion set runs at draft-gen including `email_status_verified`. This prevents NULL-status drafts from entering the queue.  
**Test**: Attempt to generate a draft for a NULL-status contact, confirm it is blocked at draft-gen and logged to send_assertions.

### PR F: Calibrate company lock window (Urgency: MEDIUM)

**Scope**: `backend/app/core/channel_coordinator.py`, `is_company_locked()`  
**Work**: Before returning the 5-day lock, query how many distinct contacts at this company have ever been touched. If 1, use 2-day window. If 2+, use 5-day window.  
**SQL needed**: `SELECT COUNT(DISTINCT contact_id) FROM interactions WHERE company_id = $1 AND type IN ('email_sent', 'email_replied', ...)`.  
**Test**: Company with one contact touched → lock clears after 2 days. Company with two contacts touched → lock clears after 5 days.

### PR G: Reduce daily_limit + add min_gap (Urgency: MEDIUM)

**Scope**: `outreach_send_config` table (DB update, no code change)  
**Work**: Update `daily_limit=50, min_gap_minutes=2` in the config row.  
**Test**: Verify scheduler respects new limits on next run.

### PR H: Build queue health widget (Urgency: LOW)

**Scope**: `dashboard/app/outreach/page.tsx`, new endpoint in `backend/app/api/routes/approvals.py`  
**Work**: Add `GET /api/approvals/queue-health` returning: total approved, blocked by lock (with unlock dates), blocked by NULL email_status, blocked by strict gate, clean sendable. Surface as a status bar in the Send Queue tab.

### PR I: Add bounce rate pre-run check (Urgency: LOW)

**Scope**: `backend/app/core/pre_send_assertions.py` + `backend/app/agents/engagement.py`  
**Work**: Implement `assert_bounce_rate_under_threshold()` using the existing `MAX_BOUNCE_RATE = 0.02` constant. Query interactions for the last 7 days: `email_bounced / email_sent`. Call this once per scheduler run before the send loop, not per draft.  
**Test**: Simulate a bounce rate > 2%, confirm all sends pause and Slack alert fires.

---

*End of audit. All data from live production database as of 2026-05-13 CDT.*
