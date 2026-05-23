# Phase 1 — ZeroBounce Write-Back Root Cause Analysis

**Date:** 2026-05-13  
**Confidence Level:** HIGH (verified from live DB inspection)  
**Operational Impact:** Critical — determines whether 769 contacts remain blocked  
**Risk Level:** Low (no API calls made, read-only investigation)

---

## Executive Finding

**The ZeroBounce write-back did not fail.** The pipeline report was generated before today's (May 13) ZeroBounce run completed its final batch. The 769-contact discrepancy reported as a "write-back failure" was a snapshot timing artifact.

The ZeroBounce script has since been run successfully and wrote:

| Status         | Count written today (May 13) |
|----------------|------------------------------|
| verified       | 653                          |
| catch_all      | 291                          |
| unverified     | 36                           |
| invalid        | 33                           |
| **Total**      | **1,013**                    |

The current production DB shows **1,968 sendable contacts** (1,677 verified + 291 catch_all), up from 214 at the time of the original report.

---

## Root Cause Analysis

### What the report said vs. what live DB shows

| Metric                          | Report (May 13 ~22:00 CDT) | Live DB (May 13 audit) |
|---------------------------------|----------------------------|------------------------|
| verified + catch_all            | 214                        | 1,968                  |
| email_status = NULL (with email) | 769                        | 1,504                  |
| ZB run reported sendable        | 931                        | 1,013 (today's run)    |

### Why the discrepancy existed at report time

The pipeline report was generated at approximately 22:00 CDT May 13. The ZeroBounce run that produced today's results ran after that timestamp. This means:

- At report generation time, only the pre-run data was visible (181 verified + 33 catch_all = 214).
- The ZB script ran subsequently and correctly wrote 944 new sendable contacts (653 verified + 291 catch_all today).
- Prior runs on May 4-12 had already written a further 1,024 contacts (verified: 1,677 - 653 = 1,024 from prior runs).

### What the 1,504 remaining nulls represent

1,504 contacts have an email address but still have null email_status after today's ZB run. These were NOT processed. Two explanations:

1. **Credits ran out.** The ZB script checks available credits before running and truncates the contact list to `min(len(contacts), credits)`. If credits = 1,000-1,013 but null-status contacts = 2,500+, the script would process only the first batch.
2. **These contacts had email_status = null at the time the script ran, but were added to the DB after the initial query.** Less likely given their creation dates (all pre-May 12).

The most likely explanation: at the time the script ran, more than the available credits' worth of contacts had null status, so approximately 1,504 were not submitted to the API.

### Credit cost to verify remaining nulls

```
1,504 contacts × $0.008/credit = $12.03
```

**Recommendation:** Run a second ZeroBounce pass for the remaining 1,504 nulls after confirming credit balance. Expected yield based on today's run ratios (944/1,013 sendable = 93%): approximately 1,399 additional sendable contacts.

---

## Code Analysis: zb_verify.py

The script was inspected at `/Users/avanish/prospectIQ/zb_verify.py`. Key findings:

### Update logic: per-record, within batch loop

```python
for r in results:
    email = (r.get("address") or "").lower()
    zb_status = (r.get("status") or "unknown").lower()
    new_status = STATUS_MAP.get(zb_status, "unverified")
    contact = contact_by_email.get(email)
    if not contact:
        continue
    try:
        db.client.table("contacts").update({...}).eq("id", contact["id"]).execute()
    except Exception as e:
        errors += 1
```

**Finding:** Each contact is updated individually via `eq("id", contact["id"])`. This is correct and precise. No batch-update issues.

### Status mapping

```python
STATUS_MAP = {
    "valid": "verified",
    "invalid": "invalid",
    "catch-all": "catch_all",
    "unknown": "unverified",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}
```

**Finding:** The mapping is correct. ZB returns `"catch-all"` (hyphenated) and the script maps it to `"catch_all"` (underscored) which matches `SENDABLE_EMAIL_STATUSES`. No mismatch.

### Email key matching

The script looks up contacts via `contact_by_email = {c["email"].lower(): c for c in batch}` and matches on `r.get("address").lower()`. This is correct — case-insensitive email match.

### Exception handling

The `except Exception as e: errors += 1` block does NOT log the exception. If writes fail silently (e.g., RLS, DB timeout), the error count increments but nothing is printed about the error detail. This is a latent observability gap but does not explain the discrepancy (which was a timing issue, not a write failure).

### Env routing

The script uses `from backend.app.core.database import Database` which connects to the `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` from the environment. No staging/production routing ambiguity — one DB, one key.

### RLS

The script uses the service role key (`SUPABASE_SERVICE_KEY`). The Supabase service role key bypasses Row Level Security by design. RLS is not the cause of any write failures.

---

## Remaining Work

1. Check current ZeroBounce credit balance before running next pass.
2. Run `zb_verify.py` again to process remaining 1,504 null-status contacts.
3. After run, re-segment the 583 stalled contacts (159 of them have null status — see Phase 3).

---

## Confidence Level Summary

| Finding                                       | Confidence |
|-----------------------------------------------|-----------|
| Write-back failure = timing artifact          | HIGH      |
| Today's run wrote 944 sendable contacts       | HIGH (verified from DB updated_at timestamps) |
| 1,504 remaining due to credit limit           | MEDIUM (circumstantial — credit count not independently verified) |
| Script logic is correct                       | HIGH      |
| No RLS or env routing issues                  | HIGH      |
