# Phase 4 — Governance Gap Analysis

**Date:** 2026-05-13  
**Confidence:** HIGH for step-3 violations; HIGH for bounce_rate gap  
**Operational Impact:** High — sends may have bypassed a governance gate

---

## Finding 1: Step-3 Gap Violations (CONFIRMED)

All 4 step-3 sends violated the `MIN_STEP_GAP_DAYS = 5` requirement.

| Contact ID (prefix) | Step-2 sent | Step-3 sent | Gap | Status |
|---------------------|-------------|-------------|-----|--------|
| be6a9365 | 2026-05-04 | 2026-05-08 | 3d | VIOLATION |
| a2188dd4 | 2026-05-04 | 2026-05-08 | 3d | VIOLATION |
| 328aa44d | 2026-05-04 | 2026-05-08 | 3d | VIOLATION |
| 1aa01288 | 2026-05-04 | 2026-05-07 | 3d | VIOLATION |

### Root Cause: `send_path` context never ran for step-3

The `assert_minimum_step_gap` function logs to the `send_assertions` table. Investigation shows:

- **Total `send_path` assertions ever in production: 116** (across 16 sends)
- **All 217 assertions on 2026-05-07/08 (the step-3 send window): `draft_gen` context only**
- The step-3 sends occurred on 2026-05-07 and 2026-05-08
- In `draft_gen` context, the minimum_step_gap assertion fires as **advisory** — it logs a failure but does NOT block the send (it only advises the generator)
- The `send_path` context is the **authoritative** gate that actually blocks delivery

**The step-3 drafts were sent through a code path that ran assertions in `draft_gen` context (advisory) rather than `send_path` context (authoritative). The advisory context correctly recorded a gap failure for 3 of 4 contacts — but in draft_gen context, failures do not block the send.**

This is the critical distinction:
- `draft_gen` context: log failure, raise AssertionFailure → caught by draft generator, contact is skipped for THIS generation cycle, but the DRAFT ALREADY EXISTED from a prior cycle
- `send_path` context: log failure, raise AssertionFailure → caught by engagement.py, send is blocked, sent_at is rolled back

If the draft existed before the minimum_step_gap check was added, or if a human-approved draft was delivered directly through the engagement send path without triggering `run_pre_send_assertions(assertion_context="send_path")`, the gap check would not have blocked it.

### Evidence

For contact `328aa44d` — **NO minimum_step_gap assertions found at all** (not even draft_gen context). This contact's step-3 draft was sent without any gap assertion being evaluated, suggesting the draft was created before `assert_minimum_step_gap` was implemented and was sitting in approved state when it was sent.

### Is this an ongoing risk?

The 116 total send_path assertions correspond to approximately 16 contacts (116 / 7 assertions per contact). This is far less than the 1,137 total sends. The `send_path` assertion context is either not wired into the primary send path for most sends, or the assertion function was added to the codebase but the caller (`engagement.py` or similar) does not call `run_pre_send_assertions(assertion_context="send_path")` for all sends.

**Action required:** Verify that `engagement.py`'s send loop calls `run_pre_send_assertions(assertion_context="send_path")` for every send. If it does not, wire it in.

---

## Finding 2: `MAX_BOUNCE_RATE` Was Undefined as Runtime Gate (FIXED)

**Status: FIXED in this session.** `assert_bounce_rate_ok()` has been implemented and wired into `run_pre_send_assertions()`.

### What existed before this session:

```python
MAX_BOUNCE_RATE = 0.02  # Defined at line 29
# No assert_bounce_rate_ok() function existed
# MAX_BOUNCE_RATE was referenced nowhere else in the file
```

The constant existed but had no runtime effect. A bounce spike would not pause the system.

### What was implemented (see pre_send_assertions.py):

```python
def assert_bounce_rate_ok(db, assertion_context="send_path"):
    # Queries interactions for 7-day rolling email_sent and email_bounced counts
    # Raises AssertionFailure if bounce_count / send_count > MAX_BOUNCE_RATE (0.02)
    # Logs to send_assertions table
    # Fires Slack alert on breach
    # Safe to call with empty table (0/0 = pass)
```

The assertion is wired into `run_pre_send_assertions()` as the FIRST check in `send_path` context, so a bounce spike blocks all contacts in that tick before any per-contact processing:

```python
if assertion_context == "send_path":
    assert_bounce_rate_ok(db, assertion_context)
```

It is NOT run in `draft_gen` context to avoid false blocks on advisory-only checks.

### Current bounce rate state

Live DB: 45 bounces / 1,097 sends = **4.1% all-time** — above the 2% MAX_BOUNCE_RATE threshold.

However, this is an all-time rate, not a 7-day rolling rate. The assertion computes a 7-day window. The sends on May 14 will need to check current 7-day rate before proceeding.

**IMPORTANT ACTION BEFORE THURSDAY SEND:**

Run this query manually or via the reconciliation script to check current 7-day bounce rate:

```python
from datetime import datetime, timezone, timedelta
from supabase import create_client

client = create_client(SUPABASE_URL, SUPABASE_KEY)
cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

sends = client.table("interactions").select("id", count="exact").eq("type", "email_sent").gte("created_at", cutoff).execute()
bounces = client.table("interactions").select("id", count="exact").eq("type", "email_bounced").gte("created_at", cutoff).execute()

rate = (bounces.count or 0) / max(sends.count or 1, 1)
print(f"7d rolling: {bounces.count} bounces / {sends.count} sends = {rate:.2%}")
```

If the 7-day rate exceeds 2%, `assert_bounce_rate_ok` will fire and block Thursday's send batch. This is CORRECT behavior — it means the deliverability situation needs attention before sending more.

---

## Finding 3: Peak Day Send Count (2026-05-04: 465 sends)

The operational report flagged 465 sends on 2026-05-04 as potentially exceeding the 125/sender daily cap.

**Assessment:** With 9 active sender accounts in the sender_pool, the theoretical daily capacity is 9 × 125 = 1,125. 465 sends across 9 accounts = ~52/sender, well within per-sender daily cap. No governance violation.

However, if the `assert_sender_under_daily_cap` assertion was checking a single sender email rather than the per-sender pool correctly, it may have been ineffective. This should be confirmed by checking the engagement.py send loop.

---

## Finding 4: send_path Assertion Coverage Gap

**Severity: HIGH**

Only 116 send_path assertions exist across 1,137 total sends. This means approximately 1,021 sends went out WITHOUT the authoritative send_path assertion check. The draft_gen advisory context ran for those sends, but advisory context does not block delivery.

This explains:
- Why step-3 gap violations were possible
- Why the bounce rate gate has not fired (it was never implemented until this session)

**Action required:** Audit `engagement.py` to confirm that `run_pre_send_assertions(assertion_context="send_path")` is called in the send loop. If missing, add it.

---

## Summary of Governance Gaps

| Gap | Severity | Status |
|-----|---------|--------|
| `MAX_BOUNCE_RATE` not enforced | HIGH | FIXED — `assert_bounce_rate_ok()` implemented |
| Step-3 gap violations (4 sends) | HIGH | ROOT CAUSE IDENTIFIED — advisory vs authoritative context |
| `send_path` context missing from ~1,021 sends | HIGH | OPEN — requires engagement.py audit |
| Only draft_gen assertions in step-3 send window | HIGH | OPEN — correlates with send_path gap |

---

## Rollback Considerations

The bounce_rate_ok implementation has one important behavior: if the current 7-day bounce rate exceeds 2% when the Thursday send begins, it will block ALL sends in that tick. This is intentional but should be communicated to Avanish before enabling SEND_ENABLED.

If needed, `assert_bounce_rate_ok` can be disabled by removing the `if assertion_context == "send_path": assert_bounce_rate_ok(...)` call from `run_pre_send_assertions`. This should only be done if the 7-day rate turns out to be above 2% and the bounce data is determined to be stale or incorrect.
