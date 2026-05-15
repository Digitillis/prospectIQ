# Backfill Review Report
## ProspectIQ — outbound_queue Population Analysis

**Date:** 2026-05-15  
**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Status:** ANALYSIS ONLY — No rows written. Awaiting Avanish approval before any execution.  
**Scope:** 51 approved/edited outreach_drafts with sent_at IS NULL and no existing outbound_queue row

---

## A. Executive Summary

The production `outbound_queue` is empty. 51 outreach drafts exist in `outreach_drafts` that predate PR F's `approve_draft_and_enqueue()` function and were never inserted into the queue automatically.

**This analysis finds the 51-draft backfill list is NOT safe to execute as-is.**

- **9 drafts must be excluded** (hard bounces, invalid email, no email)
- **6 drafts require manual review** before inclusion
- **36 drafts are safe** to backfill, subject to company-concentration gating

Even after filtering, **company-concentration risk** and **staleness risk** require that the backfill be executed in controlled batches rather than all 51 at once. The Eos Energy Enterprises situation (3 step-2 follow-ups to the same company) and the Ulbrich/Aluminum Precision/Vicor clustering each require operator decisions.

**Recommended action:** backfill 36 SAFE candidates only, in two batches separated by 24 hours, with company-concentration cap of 1 contact per company per batch.

---

## B. Total Candidate Count

| Dimension | Count |
|-----------|-------|
| Total eligible (approved/edited, sent_at IS NULL, no queue row) | 51 |
| Workspace | 1 (all in workspace `00000000-0000-0000-0000-000000000001`) |
| Sequence names | 1 (`email_value_first` only) |
| Resend message IDs present | 0 — no duplicate-send risk from this field |
| Drafts with sent_at IS NOT NULL | 0 — confirmed |

---

## C. Candidate Segmentation

### C.1 By Sequence Step

| Step | Count | Description |
|------|-------|-------------|
| 1 (initial touch) | 31 | First outreach to contact |
| 2 (follow-up) | 20 | Follow-up; all 20 have confirmed sent step-1 predecessors |

Step-2 coherence check result: **all 20 step-2 drafts have a confirmed sent step-1** for the same contact/sequence. No incoherent follow-ups.

### C.2 By Approval Status

| Status | Count |
|--------|-------|
| `approved` | 51 |
| `edited` | 0 |

### C.3 By Age (staleness)

| Age Bucket | Step 1 Count | Step 2 Count | Total |
|------------|-------------|-------------|-------|
| 30+ days (very stale) | 6 | 0 | 6 |
| 14-30 days (stale) | 5 | 0 | 5 |
| 7-14 days (aging) | 20 | 2 | 22 |
| < 7 days (fresh) | 0 | 18 | 18 |

- Oldest candidate: `2026-04-02` (43 days) — 6 drafts from this date
- Newest candidate: `2026-05-10` (5 days)
- The 43-day-old step-1 drafts are at high staleness risk: the prospect context is cold and the draft content may no longer be timely

### C.4 By Email Status (contact)

| Email Status | Count | Risk Level |
|-------------|-------|------------|
| `verified` | 41 | Safe |
| `unverified` | 2 | Review required |
| `catch_all` | 2 | Review required |
| `invalid` | 1 | DO NOT BACKFILL |
| `null` (no ZeroBounce result) | 3 | Review required |
| No email on contact record | 1 | DO NOT BACKFILL |

### C.5 By has_edited_body

| has_edited_body | Count | Meaning |
|-----------------|-------|---------|
| `true` | 20 | Human-edited body exists — send_assertions will use edited_body |
| `false` | 31 | Original generated body — no edits |

No drafts have edited_body without the corresponding body field. All 51 have subject and body populated.

### C.6 By Company (multi-contact concentration)

| Company | Contacts Queued | Steps | Email Statuses | Risk |
|---------|-----------------|-------|----------------|------|
| Eos Energy Enterprises, Inc. | 3 | 2,2,2 | verified×3 | HIGH — 3 follow-ups to same company |
| Ulbrich Stainless Steels | 3 | 1,1,1 | verified, invalid, verified | HIGH — 1 invalid must be excluded |
| Aluminum Precision Products | 3 | 1,1,2 | verified×3 | MEDIUM — cross-step; space out |
| Vicor | 3 | 1,1,1 | unverified, verified, verified | MEDIUM — 1 REVIEW |
| Fike Corporation | 2 | 1,1 | verified×2 | DO NOT BACKFILL — both hard bounced |
| Potters Industries | 2 | 1,1 | verified×2 | MEDIUM — 2 step-1 to same company |
| Global Advanced Metals | 2 | 1,1 | verified×2 | MEDIUM — 2 step-1 to same company |
| AriensCo | 2 | 1,2 | verified×2 | LOW — different steps, natural timing |
| United Performance Metals | 2 | 1,2 | catch_all, verified | REVIEW for step-1 (catch_all) |

---

## D. Risk Analysis

### D.1 Hard Bounce Contacts (BLOCKING)

9 drafts in the backfill list target contacts or companies with suppression entries. The `dispatch_scheduler` runs send_assertions before each Resend call, so these would be caught at dispatch time — but they should be excluded from the queue entirely to avoid unnecessary claim cycles and noise in `send_attempts`.

| Draft ID | Email | Suppression Entry | Date | Classification |
|----------|-------|-------------------|------|----------------|
| `d776e831` | culbrich@ulbrich.com | invalid email_status | — | DO NOT BACKFILL |
| `12be759c` | john.hammerle@ermco-eci.com | hard_bounce_contact | 2026-05-13 | DO NOT BACKFILL |
| `b76e0d26` | ken.michiels@fike.com | hard_bounce_contact | 2026-05-04 | DO NOT BACKFILL |
| `9292af08` | chad.kruger@fike.com | hard_bounce_contact | 2026-05-04 | DO NOT BACKFILL |
| `5f0f6510` | bruce.bratton@flexsteelpipe.com | hard_bounce_contact + hard_bounce_domain | 2026-05-13/14 | DO NOT BACKFILL |
| `8f342cc1` | laurie_barton@crlaurence.com | hard_bounce_contact | 2026-05-13 | DO NOT BACKFILL |
| `82774bf8` | chrichardson@martinsprocket.com | hard_bounce_contact | 2026-05-04 | DO NOT BACKFILL |
| `79153776` | randres@prent.com | hard_bounce_contact | 2026-05-13 | DO NOT BACKFILL |
| `447c9f6f` | (Cincinnati Incorporated) | No contact email on record | — | DO NOT BACKFILL |

Note: `5f0f6510` (flexsteelpipe.com) has both contact-level AND domain-level suppression. The domain-level suppression would also block any future flexsteelpipe.com outreach, not just this contact.

Note: Both Fike Corporation contacts (ken.michiels and chad.kruger) hard bounced in May 2026. Fike should be company-locked in the channel coordinator. No Fike drafts should be backfilled.

### D.2 Staleness Risk

The 6 drafts from 2026-04-02 (43 days old) represent the highest staleness risk:

| Draft ID | Email | Company | Age (days) | Issue |
|----------|-------|---------|------------|-------|
| `dc2832a8` | dplum@ulbrich.com | Ulbrich | 43 | Very stale step-1. Content may be outdated. |
| `ead28407` | hharwood@aluminumprecision.com | Aluminum Precision | 43 | Very stale step-1. |
| `12be759c` | john.hammerle@ermco-eci.com | ERMCO-ECI | 43 | BOUNCED — excluded regardless. |
| `d776e831` | culbrich@ulbrich.com | Ulbrich | 43 | INVALID — excluded regardless. |
| `870b2cfd` | jmondello@vicorpower.com | Vicor | 43 | Stale + unverified — REVIEW. |
| `03ca0c81` | ctodd@aluminumprecision.com | Aluminum Precision | 43 | Very stale step-1. |

A 43-day-old step-1 cold outreach email is problematic: the prospect context is cold, the draft content may reference market signals or company activity that is no longer current, and the implied urgency of a first touch is absent after six weeks. Recommend reviewing and potentially re-generating these 3 surviving drafts (dplum, hharwood, ctodd) before including them in the backfill.

### D.3 Company-Concentration Risk

When multiple drafts targeting the same company are backfilled simultaneously, the dispatch loop may send 2-3 emails to the same company in the same batch window (30-minute tick). This appears as spam to the recipient domain and risks domain reputation damage.

**Eos Energy Enterprises (3 step-2 drafts — highest risk):**
- jmastrangelo@eosenergystorage.com — step 2, 5 days old
- jgreggs@eose.com — step 2, 5 days old
- jmahaz@eose.com — step 2, 5 days old

All three are step-2 follow-ups, all created on 2026-05-10, all verified. Sending all three on the same batch tick means three simultaneous follow-ups to one company. The channel coordinator's lock logic operates per-contact, not per-company for same-batch scenarios. Backfill these in separate batches, not together.

**Ulbrich (2 safe step-1 drafts + 1 excluded):**
- dplum@ulbrich.com (43 days old)
- dorozco@ulbrich.com (15 days old)
Recommend: send one, let the lock settle (5 business days), then the other.

**Aluminum Precision Products (3 drafts: 2 step-1 stale, 1 step-2 fresh):**
- hharwood@aluminumprecision.com — step 1, 43 days old
- ctodd@aluminumprecision.com — step 1, 43 days old
- gbornman@aluminumprecision.com — step 2, 6 days old
gbornman (step-2) is coherent and fresh. hharwood and ctodd (step-1, 43 days) should be reviewed for staleness.

### D.4 Duplicate-Send Risk

**Zero risk from resend_message_id:** All 51 drafts have null `resend_message_id`. There is no existing Resend email to duplicate.

**Scheduler guard:** `dispatch_loop` checks `SEND_ENABLED` (env=false) before any claim. Even if backfill ran today, zero sends would fire until SEND_ENABLED is set to true.

**`approve_draft_and_enqueue()` guard:** The function uses `ON CONFLICT DO NOTHING` on draft_id. Running backfill `--execute` twice would not create duplicate queue rows.

---

## E. Suppression Analysis

### E.1 Suppression Log Coverage

| Suppression Scope | Count of Affected Candidates |
|-------------------|------------------------------|
| hard_bounce_contact | 7 contacts |
| hard_bounce_domain | 1 domain (flexsteelpipe.com) |
| Total affected drafts | 8 (one draft hits both contact + domain) |

### E.2 Invalid Email Status

| Contact | Status | Drafts Affected |
|---------|--------|-----------------|
| culbrich@ulbrich.com | `invalid` | 1 |
| Cincinnati Incorporated contact | `null` (no email on record) | 1 |

### E.3 Email Status Risk Summary

| Email Status | Backfill Decision |
|-------------|-------------------|
| `verified` | Safe to include |
| `invalid` | Exclude always |
| No email | Exclude always |
| `unverified` | Exclude or manually verify before including |
| `catch_all` | Acceptable risk if content is strong; include with awareness |
| `null` (not verified) | Verify or exclude |

---

## F. Staleness Analysis

The `email_value_first` sequence is a cold outreach sequence. Step-1 relevance degrades significantly after 2 weeks.

| Age Bracket | Step 1 | Recommendation |
|-------------|--------|---------------|
| < 7 days | 0 | — |
| 7-14 days | 20 | Safe — context still warm |
| 14-30 days | 5 | Acceptable but borderline — review content |
| 30+ days | 6 (incl. 3 excluded for bounce/invalid) | Review content or discard; 3 surviving safe |

The 3 surviving very-stale step-1 drafts (dplum, hharwood, ctodd) should have their body content reviewed before enqueue. If the content references outdated signals or context, regenerate before backfilling.

---

## G. Duplicate-Send Risk Analysis

| Risk Vector | Status | Assessment |
|------------|--------|------------|
| resend_message_id already set | 0 of 51 | No risk |
| sent_at already set | 0 of 51 | No risk |
| Draft already in outbound_queue | 0 of 51 | No risk |
| Concurrent backfill run race | mitigated by ON CONFLICT DO NOTHING | Low risk |
| Scheduler dispatch during backfill | mitigated by SEND_ENABLED=false | No risk currently |
| SEND_ENABLED set to true before review | human gate — not an automated risk | Procedural control |

---

## H. Recommended Insertion Strategy

### Step 1 — Exclusion (do not backfill, no further action)

Mark the following 9 drafts as `rejected` with reason `backfill_review_2026_05_15: excluded_[reason]` **or** simply do not include them in the `--execute` backfill. They should never enter outbound_queue.

| Draft ID | Email | Reason |
|----------|-------|--------|
| `d776e831` | culbrich@ulbrich.com | invalid email |
| `12be759c` | john.hammerle@ermco-eci.com | hard bounce |
| `b76e0d26` | ken.michiels@fike.com | hard bounce |
| `9292af08` | chad.kruger@fike.com | hard bounce |
| `5f0f6510` | bruce.bratton@flexsteelpipe.com | hard bounce + domain suppression |
| `8f342cc1` | laurie_barton@crlaurence.com | hard bounce |
| `82774bf8` | chrichardson@martinsprocket.com | hard bounce |
| `79153776` | randres@prent.com | hard bounce |
| `447c9f6f` | (Cincinnati Incorporated) | no email |

The backfill script (`backfill_outbound_queue.py`) does not currently filter for suppression log entries. **The script must not be run with `--execute` until it is modified to skip contacts with hard bounce entries in suppression_log OR until these 9 draft IDs are manually rejected in outreach_drafts before the script runs.**

### Step 2 — Manual Review (Avanish decision required)

| Draft ID | Email | Company | Issue | Options |
|----------|-------|---------|-------|---------|
| `870b2cfd` | jmondello@vicorpower.com | Vicor | unverified, 43 days old | Run ZeroBounce verify, or exclude |
| `73a58bef` | jgondkoff@upmet.com | United Performance Metals | catch_all | Include (accept bounce risk) or exclude |
| `34b43c7d` | kathyw@gwfg.com | Golden West Food Group | catch_all | Include (accept bounce risk) or exclude |
| `8a1d3964` | tzwiebel@rudolphfoods.com | Rudolph Foods | unverified | Run ZeroBounce verify, or exclude |
| `f24e49a0` | ronny.hoff@alterainfra.com | Altera Infrastructure | null email_status | Verify or exclude |
| `33c5604a` | yina.hernandez@richlinegroup.com | Richline Group | null email_status | Verify or exclude |

### Step 3 — SAFE candidates (36 drafts)

All other candidates are classified SAFE after filtering excluded and review groups. These can be backfilled subject to the concentration gating below.

**Concentration gating rule for batch execution:**
- Cap at 1 contact per company per send window (2 tick windows = 1 hour)
- For Eos Energy (3 contacts): backfill 1 per day across 3 days
- For Ulbrich (2 safe contacts): backfill dplum first; wait 5 business days; then dorozco
- For Aluminum Precision (2 stale step-1 + 1 fresh step-2): review stale content first; backfill gbornman (step-2) first as it is fresh and coherent
- For Vicor (2 safe + 1 REVIEW): backfill avogelsang and jaguilar; hold jmondello pending review
- For Potters Industries (2 step-1 verified): backfill one per send window
- For Global Advanced Metals (2 step-1 verified): backfill one per send window

### Delivery Schedule

| Phase | Drafts | Timing | Gate |
|-------|--------|--------|------|
| Pre-backfill | Reject 9 excluded drafts in outreach_drafts | Before any `--execute` | Avanish confirms list |
| Backfill execution | 36 SAFE drafts | After Avanish approval | `--execute` with verified exclusion filter |
| Post-backfill | Verify 36 rows in outbound_queue | Immediately | psql count |
| First send observation | 1 send window (30 min tick) | After SEND_ENABLED=true | Avanish watches logs |
| 6 REVIEW drafts | Decision pending | After first sends confirmed clean | Avanish reviews |

---

## I. Classification Summary

| Classification | Count | Criteria |
|---------------|-------|----------|
| SAFE | 36 | Verified email, no suppression entries, subject/body present |
| REVIEW | 6 | Unverified, catch_all, or null email_status; no suppression entries |
| DO NOT BACKFILL | 9 | Invalid email, no email, or hard bounce in suppression_log |
| **Total** | **51** | |

---

## J. No-Write Confirmation

All data in this report was gathered via SELECT queries only. Verified at time of report generation:

| Metric | Value |
|--------|-------|
| `outbound_queue` rows | **0** |
| `send_attempts` rows | **0** |
| `outbound_queue` locked rows | **0** |
| `send_attempts` DISPATCHED rows | **0** |
| `outreach_drafts` sent in last hour | **0** |
| resend_message_id assigned in last hour | **0** |
| `workflow_events` in last hour | **0** |

No writes occurred as a result of this analysis.

---

**Author:** Avanish Mehrotra & Digitillis Architecture Team  
**Document path:** `docs/operations/BACKFILL_REVIEW_REPORT.md`  
**Next required action:** Avanish reviews Section H and authorizes (or modifies) the insertion strategy
