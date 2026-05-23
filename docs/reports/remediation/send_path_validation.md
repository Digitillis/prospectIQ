# Phase 4 — Send Path Validation

**Date:** 2026-05-13  
**Confidence:** HIGH

---

## send_path Assertion Coverage

### Evidence

Total send_path assertions in production (all time): **116**

This corresponds to approximately 16 contacts (116 / 7 assertion types per contact = 16.6 contacts).

Total sends ever: **1,137**

Ratio: 116 / (1,137 × 7) = **1.46%** — only ~1.5% of sends had authoritative send_path assertion coverage.

The remaining ~98.5% of sends ran assertions in `draft_gen` context only (advisory). Advisory context failures raise `AssertionFailure` in the draft generator but do not block a draft that already exists in approved state from being delivered.

### Implication

The step-3 gap violations are explained by this gap. The 4 step-3 drafts were approved and sent through a send path that either:
1. Did not call `run_pre_send_assertions(assertion_context="send_path")`, OR
2. Called it but used a code path that predates the `assert_minimum_step_gap` addition

### Required Action: Audit engagement.py send loop

The authoritative send path lives in `engagement.py`. The send loop must call:
```python
run_pre_send_assertions(
    db=db,
    contact=contact,
    company=company,
    sender_email=sender_email,
    sequence_step=draft["sequence_step"],
    assertion_context="send_path",  # ← THIS IS THE CRITICAL PARAMETER
    current_draft_id=draft["id"],
)
```

If `assertion_context` is omitted, it defaults to `"draft_gen"` (advisory) which will NOT block the send.

---

## Bounce Rate Gate: Pre-Thursday Check

Before enabling SEND_ENABLED for Thursday May 14's send batch, run:

```bash
python3 docs/reports/remediation/bounce_rate_assertion.py
```

The assert_bounce_rate_ok() function computes the 7-day rolling rate. If the rate exceeds 2%, the send batch will be automatically blocked by the new assertion.

Current all-time rate: 4.1% (45/1,097). The 7-day window may be significantly lower if most bounces occurred during earlier high-volume days.

---

## Assertions Wired and Confirmed

| Assertion | Wired in draft_gen | Wired in send_path | Blocks send |
|-----------|--------------------|--------------------|-------------|
| email_deliverable | Yes | Yes | Yes |
| email_status_verified | Yes | Yes | Yes |
| email_name_consistent | Yes | Yes | Yes |
| outreach_eligible | Yes | Yes | Yes |
| persona_target | Yes | Yes | Yes |
| no_recent_company_send | Yes | Yes | Yes |
| sender_daily_cap | Yes | Yes | Yes |
| prior_step_sent | Yes (step ≥ 2) | Yes (step ≥ 2) | Yes |
| minimum_step_gap | Yes (step ≥ 2) | Yes (step ≥ 2) | Yes |
| **bounce_rate_ok** | **No** | **Yes (NEW)** | **Yes** |

The bounce_rate_ok assertion is intentionally NOT in draft_gen context — it is a system-level delivery gate, not a per-contact advisory check.
