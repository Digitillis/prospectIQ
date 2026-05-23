# Phase 1 — Estimated Credit Savings Analysis

**Date:** 2026-05-13  
**Confidence:** HIGH

---

## ZeroBounce Credits

### Summary

No ZeroBounce credits were spent during this remediation. The "write-back discrepancy" was a snapshot timing issue, not a script failure. All results from the previous run are preserved in the database.

### Current State (Post-Audit)

| Status         | Count    | Notes                          |
|----------------|----------|-------------------------------|
| verified       | 1,677    | +1,463 since original 214     |
| catch_all      | 291      | All from today's run           |
| **Sendable**   | **1,968**| From 214 at report time        |
| NULL remaining | 1,504    | Not yet submitted to ZB        |

### Credit Impact of Next Pass

| Item                                 | Value          |
|--------------------------------------|----------------|
| Contacts remaining (null status)     | 1,504          |
| ZeroBounce cost per credit           | $0.008         |
| Estimated total cost                 | **$12.03**     |
| Expected sendable yield (~93%)       | ~1,399         |
| Total sendable after pass            | ~3,367         |

### Alternative: Skip ZB, Use Apollo-Verified Status

Apollo email discovery (used to populate most of the 1,677 verified contacts) assigns email_status = "verified" at the time of enrichment. If these contacts' emails were sourced via Apollo, they may already be Apollo-verified. The 1,504 null-status contacts were likely imported via CSV or an earlier pipeline that did not set email_status. Running ZeroBounce on them is the lowest-cost path.

### Credits Saved by Not Re-Calling API

- The remediation plan required exhausing all replay/reconciliation options before making any API call.
- Result: 0 credits spent on reconciliation. The script was analyzed (read-only), the DB was queried directly, and the root cause (timing) was identified without any external API call.
- Credits saved: 1,968 (would have been spent re-verifying already-verified contacts)
- Cost saved: **$15.74** (1,968 credits x $0.008)

---

## Apollo Credits

No Apollo discovery credits were spent during this remediation. The enrichment strategy (Phase 5) identifies the priority population for a future Apollo run but makes no API calls.

### Priority Contact Pool for Next Apollo Run

| Population                              | Count | Est. Apollo Cost     |
|-----------------------------------------|-------|---------------------|
| Target-tier contacts with no email      | 5,851 | ~$175 (at $0.03/ea)  |
| All contacts with no email              | 6,377 | ~$191                |

Recommendation: Run Apollo bulk match for `target`-tier contacts first (5,851) before running on borderline/excluded tiers. This is the single highest-leverage enrichment action available.

---

## Cost Impact Summary

| Action                        | Credits | Cost     | Outcome                          |
|-------------------------------|---------|----------|----------------------------------|
| Reconciliation (this audit)   | 0       | $0.00    | 1,968 sendable confirmed         |
| ZB second pass (recommended)  | 1,504   | $12.03   | ~1,399 more sendable             |
| Apollo bulk discovery         | ~5,851  | ~$175    | ~4,000-5,000 new emails          |
| **Total recommended spend**   |         | **~$187**| ~7,367 total sendable contacts   |

At $0.008/credit, every $1 of ZeroBounce spend unlocks approximately 116 sendable contacts assuming the ~93% sendable yield holds. Apollo discovery at $0.03/contact has a lower density per dollar but operates on the larger 6,377-contact pool.
