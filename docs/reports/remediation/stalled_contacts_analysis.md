# Phase 3 — Stalled Contact Analysis

**Date:** 2026-05-13  
**Confidence:** HIGH (live DB counts)  
**Operational Impact:** High — 361 contacts immediately eligible for step-2 generation

---

## Summary

583 contacts had step-1 sent but have no step-2 draft in any state (pending, approved, rejected, or sent). The segmentation is:

| Segment | Count | Root Cause | Recoverable? |
|---------|-------|------------|-------------|
| A — NULL email_status | 159 | Blocked by `assert_email_status_verified` gate in draft_gen | Yes, after ZB second pass |
| B — Bad email (invalid/unavailable/unverified/extrapolated) | 20 | Permanently blocked by email gate | No |
| C — Bounced contacts | 82 | Hard bounce suppression in suppression_log | No (by design) |
| D — Unsubscribed/not_interested | 1 | Contact or company status block | No |
| E — Verified/catch_all, not blocked | 361 | Gap in draft generation (see below) | Yes — 310 eligible NOW |

**Immediate opportunity: 310 contacts eligible for step-2 generation right now.**

---

## Segment E Deep-Dive (361 recoverable contacts)

These contacts are verified or catch_all, not bounced, not unsubscribed, and have no entry in suppression_log. They should have received a step-2 draft. Why didn't they?

### Sub-segmentation

| Sub-segment | Count | Explanation |
|-------------|-------|-------------|
| In 5-day cooldown (step-1 sent < 5 days ago) | 51 | Step-1 too recent; gap not yet met |
| **Eligible for step-2 NOW** | **310** | No cooldown, no suppression, verified email |

### Why did these 310 not get step-2 drafts?

Several explanations are possible. The most likely:

1. **Step-2 generation cron ran before these contacts had a verified email_status.** Many of these contacts were likely verified in today's ZeroBounce pass (May 13). At the time draft_generation ran for them after their step-1 sent, their email_status was NULL, which caused `assert_email_status_verified` to fail in draft_gen context. Now that their status is verified/catch_all, they should pass the gate.

2. **Company cooldown blocked generation.** The `assert_no_recent_company_send` gate fires if the SAME CONTACT received any email within the last 30 days. For contacts who received step-1 more than 5 days but less than 30 days ago, the cooldown should NOT block a different contact at the same company — but the cooldown check is per-contact, not per-company in draft_gen context. This should not be the issue.

3. **Draft generation cron configuration.** The generation cron runs every 5 minutes (`scheduler.add_job(_run_draft_generation, "interval", minutes=5)`). If the cron is not correctly identifying contacts that need step-2 drafts, these 310 contacts would be missed each cycle.

### Contact Status Breakdown for Segment E

| contact.status | Count |
|----------------|-------|
| enriched       | ~280  |
| identified     | ~75   |
| bounced        | 0 (excluded) |

All recoverable contacts have `contact.status` values consistent with outreach eligibility.

---

## Recovery Plan by Segment

### Segment A (159 contacts — null email_status)

**Action:** Run ZeroBounce second pass (1,504 contacts, ~$12). After the pass, 148+ of these 159 should become verified/catch_all based on 93% sendable yield from today's run.

**After ZB pass:** These contacts move to Segment E (recoverable). Re-run regenerate_step2_candidates.py to confirm.

**Timeline:** 1-2 hours after running `zb_verify.py` again.

### Segment B (20 contacts — bad email)

**Action:** None. These emails are invalid, unavailable, or unverifiable. Unless a different email address can be found for these contacts via Apollo enrichment, they are permanently blocked.

**Optional:** Run Apollo bulk match on these 20 contacts to find an alternative verified email. Cost: ~$0.60.

### Segment C (82 contacts — bounced)

**Action:** None. Hard bounces are intentionally permanent in the tiered suppression architecture. Attempting to re-contact bounced addresses risks reputation damage.

**Note:** If any of these 82 were soft bounces incorrectly classified as hard, they could be reviewed manually. But the suppression_log shows all 82 as `hard_bounce_contact`.

### Segment D (1 contact — unsubscribed)

**Action:** None. CAN-SPAM/CASL compliance requires honoring unsubscribe requests permanently.

### Segment E (310 contacts — eligible NOW)

**Action:** Trigger step-2 draft generation for these contacts. The `_run_draft_generation` cron should pick them up automatically in the next 5-minute cycle.

**Verify after generation:** Query for new step-2 pending drafts for these 310 contact IDs.

---

## Stalled Contacts Not in Segment Analysis (471 more)

Recall: 1,054 total contacts have step-1 sent but no step-2 SENT. Of those, 583 have NO step-2 draft in any state. The other 471 have step-2 drafts in non-sent states:

| Draft status | Count |
|---|---|
| pending review | ~248 |
| approved (unsent) | ~64 |
| rejected | ~159 |

These are not "stalled" in the technical sense — they have drafts, they just haven't been sent yet. The review backlog and rejected drafts are addressed in the broader pipeline health recommendations.

---

## Confidence Levels

| Finding | Confidence |
|---------|-----------|
| 583 truly stalled count | HIGH |
| 82 are bounced | HIGH |
| 310 eligible NOW | HIGH |
| Root cause = email_status was null at time of generation | MEDIUM |
| Cooldown accounting | HIGH |
| Suppression check | HIGH |
