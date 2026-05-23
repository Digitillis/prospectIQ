# Priority Stabilization and Governance Hardening — Master Report
**Date:** 2026-05-13  
**Scope:** Phases 1, 3, 4, 5 of the ProspectIQ Outbound Pipeline Governance Program  
**Phase 2 (approval workflow, rejected drafts):** handled by concurrent agent — not modified here

---

## Executive Summary

Four production issues were identified and three were resolved. The most critical finding is a **silent failure in reply ingestion**: every IMAP-sourced reply that reached `thread_messages` write was silently dropped due to a schema mismatch (columns that do not exist). This was fixed. The send-path governance gate was confirmed correct and all 19 self-test checks pass. 382 companies were backfilled from `outreach_pending` to `contacted`. Two items require Avanish action: Railway env var verification for `GMAIL_APP_PASSWORD`, and ZeroBounce API key setup.

---

## Phase 1: Send-Path Governance Validation

### Findings

**Finding P1-1: send_path wiring is correct going forward**
- Severity: Resolved (was High)
- Confidence: High
- engagement.py correctly calls `run_pre_send_assertions(assertion_context="send_path")` at line 640, after the atomic `sent_at` claim (line 539) and before `resend.Emails.send()` (line 711)
- `assert_bounce_rate_ok` is correctly wired: runs only in `send_path` context, 7-day rolling 2% threshold
- Rollback (`_rollback_sent_at`) fires on any AssertionFailure or unexpected exception, preventing orphaned drafts
- No bypass paths to Resend exist

**Finding P1-2: Historical 97.7% of sends lacked send_path assertions**
- Severity: Medium (informational — historical, not ongoing)
- Impact: Prior 1,124 sends had advisory draft_gen assertions only, not authoritative send_path assertions
- Confidence: High (confirmed via DB query)
- Root cause: `assertion_context="send_path"` was added to engagement.py between a prior session and today
- Blast radius: Those sends are complete. No current risk.
- Rollback: N/A (historical)

**Finding P1-3: 3 send_path assertion failures today (governance working)**
- Severity: Informational (system functioning correctly)
- All 3 were `no_recent_company_send` violations: drafts that were approved but whose contact was already within cooldown
- All 3 were blocked and rolled back — Resend was not called

### Fixes Applied

| Fix | File | Lines |
|---|---|---|
| No code change needed — engagement.py already correct | — | — |
| `send_path_self_test.py` created — 19 checks, all passing | `/Users/avanish/prospectIQ/send_path_self_test.py` | New file |
| `governance_enforcement_trace.py` created | `/Users/avanish/prospectIQ/governance_enforcement_trace.py` | New file |
| `send_path_governance_audit.md` | `/Users/avanish/prospectIQ/docs/reports/` | New file |
| `authoritative_assertion_coverage_report.md` | `/Users/avanish/prospectIQ/docs/reports/` | New file |

### Avanish Actions
- None required for Phase 1

---

## Phase 3: Reply Ingestion Hardening

### Findings

**Finding P3-1: CRITICAL — thread_messages writes silently failing**
- Severity: Critical
- Impact: Every IMAP-sourced inbound reply is dropped from `thread_messages`. The `interactions` write still succeeds, but `_get_latest_reply_context()` reads from `thread_messages` to inject reply context into follow-up drafts — this function returns `None` for all IMAP replies, meaning follow-up drafts are generated without reply awareness.
- Confidence: Confirmed — live test of insert with `company_id` column returns PGRST204 error
- Root cause: `_gmail_intake_workspace` inserts `company_id`, `contact_id`, `workspace_id` into `thread_messages`, but those columns do not exist in the table
- Blast radius: All IMAP reply context has been silently dropped since this function was deployed
- Rollback: Revert edit to `main.py` lines 489-500

**Fix applied:** Remove non-existent columns from the `thread_messages` insert. Now only writes `direction`, `body`, `subject`, `classification`, `source`, and `thread_id` (all verified present in schema).

**Finding P3-2: IMAP UNSEEN-only polling misses manually-read replies**
- Severity: High
- Impact: If Avanish reads a reply in Gmail before the 15-min cron runs, that reply is permanently missed
- Confidence: High (confirmed by IMAP flag behavior documentation)
- Blast radius: Unknown number of missed replies
- Resolution: No code fix applied — requires product decision. Options: Gmail API, SINCE date fallback, dedicated label
- Avanish action: Decide on mitigation approach

**Finding P3-3: GMAIL_APP_PASSWORD may not be in Railway**
- Severity: High
- Impact: If not set, all reply ingestion is silently skipped (accounts_to_poll is empty)
- Confidence: Confirmed set locally (.env), Railway status unknown
- Avanish action required: Verify in Railway Dashboard → Service → Variables

**Finding P3-4: 0 email_replied interaction records**
- Severity: High
- Impact: No replies have been ingested via IMAP, or Railway env var is missing
- Confidence: Confirmed (0 records with source='gmail_imap' in interactions)

**Finding P3-5: No heartbeat logging**
- Severity: Medium
- Fixed: `_run_gmail_intake()` now logs `gmail_intake_heartbeat` at start and end of each tick

### Fixes Applied

| Fix | File | Lines |
|---|---|---|
| thread_messages insert: removed non-existent company_id, contact_id, workspace_id columns | `backend/app/api/main.py` | 489-500 |
| Heartbeat logging added to `_run_gmail_intake()` | `backend/app/api/main.py` | 598-612 |
| `reply_ingestion_operational_validation.md` | `docs/reports/` | New file |
| `reply_pipeline_observability.md` | `docs/reports/` | New file |
| `synthetic_reply_end_to_end_test.py` | `/Users/avanish/prospectIQ/` | New file — 26 checks, all passing |

### Avanish Actions (REQUIRED)

1. **Verify `GMAIL_APP_PASSWORD` in Railway Variables** — if not present, add it
   - Value from .env: `uoto laih khpf cvib`
   - Railway Dashboard → Service → Variables → add `GMAIL_APP_PASSWORD`
2. **Decide on UNSEEN vs Gmail API polling** — currently any reply read manually in Gmail will be permanently missed

---

## Phase 4: Pipeline Recovery

### Findings

**Finding P4-1: 349 stalled step-2-eligible contacts**
- Contacts with step-1 sent, no step-2 draft, verified/catch_all email, outreach eligible
- Status: Identified. Will be picked up automatically when croms are unpaused.
- No step-2 drafts created in last 24h (consistent with croms paused since 2026-05-07)

**Finding P4-2: ZeroBounce API key not configured**
- `ZEROBOUNCE_API_KEY` is empty in both local .env and Railway (returns blank from settings)
- 7,769 contacts have null email_status (larger than prior 1,504 estimate — additional contacts imported without verification)
- Cannot verify credits or run second pass without the API key

**Finding P4-3: 382 companies stuck at outreach_pending despite sent drafts (RESOLVED)**
- These companies had emails sent but status never updated to `contacted`
- Root cause: likely a database update failure in the company status update code path (non-fatal, does not block sends)

**Finding P4-4: All-time bounce rate 4.10% (historical data quality)**
- 45 bounces / 1,097 sends
- 7-day rolling rate: 0.00% — no recent bounces
- The all-time rate reflects early campaign sends with lower contact data quality
- `assert_bounce_rate_ok` uses 7-day rolling rate, not all-time — not currently blocking sends

### Actions Taken

| Action | Method | Result |
|---|---|---|
| Company lifecycle backfill | Direct DB update via Supabase client | 382 companies updated to 'contacted' |
| Dry-run confirmed before execute | Sample of 10 companies reviewed | Safe |

### Avanish Actions (REQUIRED)

1. **Purchase ZeroBounce credits and set `ZEROBOUNCE_API_KEY`** in Railway Variables
2. **Run ZeroBounce second pass**: `python zb_verify.py` (verifies up to credits limit of null-status contacts)
3. **Unpause croms** when GTM assessment is complete: research, enrichment, discovery in main.py scheduler

---

## Phase 5: Operational Observability

### Documents Created

| Document | Location |
|---|---|
| `operational_observability_spec.md` — 6 dashboard panels with exact SQL queries | `docs/reports/` |
| `governance_audit_model.md` — violation types, logging gaps, escalation behavior | `docs/reports/` |
| `pipeline_health_metrics.md` — SLOs, thresholds, breach conditions, current state | `docs/reports/` |

---

## Prioritized Action List

### System Actions (automatic, no Avanish needed)
- send_path assertions now run on every send — forward coverage is 100%
- 382 companies now show `contacted` status — lifecycle is consistent
- Heartbeat logging active on gmail_intake
- thread_messages writes now use correct schema — future reply ingestion will work

### Avanish Actions (ordered by priority)

| Priority | Action | Impact |
|---|---|---|
| P0 | Verify `GMAIL_APP_PASSWORD` in Railway Variables | Reply ingestion either working or needs this |
| P0 | Decide on UNSEEN-only vs Gmail API reply polling | Determines if manually-read replies are recoverable |
| P1 | Set `ZEROBOUNCE_API_KEY` in Railway, run `zb_verify.py` | Unlocks 7,769 contacts for potential outreach |
| P1 | Unpause research/enrichment/discovery croms when ready | Resumes top-of-funnel growth |
| P2 | Review and approve 269 pending drafts | 269 sends ready to go |
| P3 | Add `GMAIL_APP_PASSWORD` for any secondary sender_pool addresses | Multi-sender reply capture |

---

## Credit Impact Summary

| Service | Credits Used This Session | Notes |
|---|---|---|
| ZeroBounce | 0 | API key not configured; no calls made |
| Apollo | 0 | Enrichment paused; no calls made |
| Anthropic | N/A | Draft generation not run this session |
| Resend | 0 | No sends triggered this session |

---

## Artifacts Produced

| File | Description |
|---|---|
| `governance_enforcement_trace.py` | Query send_assertions for per-send governance coverage |
| `send_path_self_test.py` | 19-check wiring validation (all passing) |
| `synthetic_reply_end_to_end_test.py` | 26-check reply ingestion dry-run test (all passing) |
| `docs/reports/send_path_governance_audit.md` | Phase 1 audit findings |
| `docs/reports/authoritative_assertion_coverage_report.md` | Coverage metrics |
| `docs/reports/reply_ingestion_operational_validation.md` | Phase 3 findings and fixes |
| `docs/reports/reply_pipeline_observability.md` | Telemetry spec |
| `docs/reports/pipeline_unlock_report.md` | Phase 4 before/after counts |
| `docs/reports/post_recovery_funnel_metrics.md` | Updated funnel state |
| `docs/reports/lifecycle_consistency_validation.sql` | Backfill queries |
| `docs/reports/operational_observability_spec.md` | Dashboard panel specs |
| `docs/reports/governance_audit_model.md` | Violation model and escalation |
| `docs/reports/pipeline_health_metrics.md` | SLOs and thresholds |
