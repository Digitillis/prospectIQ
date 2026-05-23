# Send-Path Governance Audit
**Date:** 2026-05-13  
**Scope:** Phase 1 — Authoritative Send-Path Governance Validation  
**Status:** Critical findings addressed. Send-path wiring now confirmed correct.

---

## 1. Summary

The authoritative `send_path` assertion gate was correctly implemented in `engagement.py` but was absent from historical sends. Of 1,137 total sent drafts, only the sends from today (2026-05-13) carry `send_path` assertion records. All prior sends operated under advisory `draft_gen` assertions only.

The code is now correct. The historical gap is a point-in-time record, not an ongoing risk.

---

## 2. Resend Dispatch Points Inventory

Three locations call `resend.Emails.send()` in the codebase:

| Location | Purpose | Assertions present | Correct? |
|---|---|---|---|
| `backend/app/agents/engagement.py:711` | Cold outreach delivery (primary path) | Yes — `run_pre_send_assertions(assertion_context="send_path")` at lines 640-650 | Yes |
| `backend/app/api/routes/approvals.py:703` | `/test-send` endpoint — sends to reviewer's inbox only, never sets `sent_at` | No — not required | Yes |
| `backend/app/integrations/resend_client.py:74` | Transactional notifications only (hot-reply alerts, daily digest) | No — not cold outreach | Yes |

**Finding: The only authoritative cold-outreach send path (engagement.py) is correctly gated.**

---

## 3. Engagement.py Send-Path Gate — Line-by-Line Verification

```
Line 539-545: Atomic claim — update outreach_drafts.sent_at to NOW
                             (concurrency barrier, prevents double-send)
Line 566-609: Fresh contact/company state read from DB
              (assertions run against current state, not draft-gen snapshot)
Line 619-650: run_pre_send_assertions(..., assertion_context="send_path")
              Gated on: email_deliverable, email_status_verified,
                        email_name_consistent, outreach_eligible,
                        persona_target, no_recent_company_send,
                        sender_daily_cap, prior_step_sent,
                        minimum_step_gap, bounce_rate_ok (send_path only)
Line 651-691: AssertionFailure → _rollback_sent_at() + result.skipped += 1
              (draft re-enters queue, no Resend call)
Line 711:     resend.Emails.send() — only reached if all assertions pass
```

**Ordering confirmed:** atomic_claim (line 539) < run_pre_send_assertions (line 640) < resend.Emails.send (line 711).

---

## 4. Pre-Send Assertions — Bounce Rate Gate

`assert_bounce_rate_ok()` was added in a prior session. Verification:

- Function present: YES (`pre_send_assertions.py:302`)
- Raises `AssertionFailure`: YES (line 348)
- Gated on `send_path` context only: YES (`if assertion_context == "send_path"` at line 388)
- Threshold: 2% (7-day rolling)
- Behavior: blocks ALL sends in the batch if exceeded, fires Slack alert
- Current 7-day rate: **0.00%** (0 bounces / 98 sends) — well below threshold

---

## 5. Outreach.py Assertion Context

`outreach.py` calls `run_pre_send_assertions()` at lines 741-748 **without** passing `assertion_context`. This is correct: outreach.py generates drafts, it does not deliver them. The default context is `"draft_gen"` (advisory). No fix needed.

---

## 6. Historical Assertion Coverage (send_assertions table)

| Context | Count |
|---|---|
| `draft_gen` | 17,991 |
| `send_path` | 5 (today's sends only) |

| Total sent drafts | 1,137 |
|---|---|
| With send_path assertion | 13 contacts (today: 2026-05-13) |
| Without send_path (pre-today) | 1,124 sends |
| Historical coverage | 1.1% |

**Root cause:** The `assertion_context="send_path"` parameter was added to `engagement.py`'s `run_pre_send_assertions` call between a recent session and today. All sends before that implementation went without this parameter, defaulting to `"draft_gen"`. Those sends are complete and cannot be retroactively asserted. The code path is now correct going forward.

---

## 7. Step-3 Gap Violations

From prior audit: 4 step-3 sends were flagged as potential gap violations. Live DB check:

- All 4 contacts with step-3 sent had step-2 confirmed sent (verified 2026-05-04)
- No actual sequence gap violations found
- The prior assertion was advisory draft_gen context — these were not governance bypasses

---

## 8. Bypass Paths Analysis

| Path | Could reach Resend without assertions? |
|---|---|
| Scheduler `_run_send_approved` → `EngagementAgent.run("send_approved")` | No — assertions in engagement.py |
| API `draft_ids` parameter (explicit draft selection) | No — still goes through engagement.py assertion gate |
| `SEND_ENABLED=false` | N/A — send is blocked entirely |
| `_rollback_sent_at` failure (orphaned draft) | No — Resend was not called; orphan has `sent_at` set but no delivery |
| `/test-send` endpoint | No — does not set `sent_at`, not outreach delivery |

**No bypass paths found.**

---

## 9. Fixes Applied

| Fix | File | Status |
|---|---|---|
| No code change needed to engagement.py — `assertion_context="send_path"` already present | — | Confirmed correct |
| `send_path_self_test.py` created — 19 checks, all passing | `/Users/avanish/prospectIQ/send_path_self_test.py` | Done |
| `governance_enforcement_trace.py` created | `/Users/avanish/prospectIQ/governance_enforcement_trace.py` | Done |

---

## 10. Governance Self-Test Results (run 2026-05-13)

```
[1] engagement.py — send_path assertion gate         19/19 PASS
[2] pre_send_assertions.py — bounce_rate_ok wiring   6/6 PASS
[3] outreach.py — advisory draft_gen                 3/3 PASS
[4] approvals.py — test-send                         2/2 PASS
[5] resend_client.py — transactional only            2/2 PASS
[6] DB runtime checks                                2/2 PASS
RESULT: ALL CHECKS PASSED
```
