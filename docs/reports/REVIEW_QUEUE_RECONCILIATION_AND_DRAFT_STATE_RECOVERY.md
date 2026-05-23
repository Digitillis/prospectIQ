# Review Queue Reconciliation and Draft State Recovery

**Date:** 2026-05-13
**Author:** Avanish Mehrotra & Digitillis Architecture Team
**Scope:** Batches 1-4 (positions 1-64) step-2 draft reconciliation + review queue integrity improvements

---

## Executive Summary

Batches 1-4 of the step-2 outreach draft queue were reviewed and approved by Avanish in prior sessions, but approval writes failed to persist correctly for most records. This report documents the full reconciliation, the root cause of the write failures, and the integrity system now in place to prevent recurrence.

**Total drafts in scope:** 56 (33 pending + 23 rejected in positions 1-64)
**Total approvals restored:** 29 (20 from pending, 9 from rejected)
**Governance blocks:** 26 contacts ineligible (email_status=null/unverified) — quarantined
**Content fixes applied:** 19 drafts had fixable content issues (dashes, diagnostic CTAs, step label leaks)
**Flagged for regeneration:** 2 drafts have fabricated client claims that require full regeneration
**Permanent rejects:** 12 rejected drafts had governance-ineligible contacts

---

## Phase 1: Pending Draft Reconciliation

**Input:** 33 step-2 pending drafts in positions 1-64 (sorted company ASC / last_name ASC)
**Approved:** 20 drafts
**Quarantined (governance):** 13 drafts

### Validation Framework
Each draft was checked against five gates before approval:

| Gate | Check |
|------|-------|
| Content quality | No em/en/double dashes, no dropped-I subjects, Digitillis brand descriptor present, binary curiosity close only, no meeting asks, no diagnostic offers, no "no commitment" language |
| Contact eligibility | email_status IN (verified, catch_all), is_outreach_eligible=true, contact_tier != excluded |
| Suppression | No active suppression_log entry for contact |
| Step gap | Step-1 sent AND at least 5 days elapsed |
| Company cooldown | N/A for step-2 (follow-up, not cold open) |

### Content Issues Found (Systemic)
All 33 pending drafts used an older email template that:
1. Omits "Digitillis, a predictive maintenance platform" brand descriptor on first mention (warning)
2. Uses "2-week diagnostic" as the CTA rather than a binary curiosity close (error)
3. Uses "no cost" / "no commitment" / "no long-term contract" language (error)
4. Some use double-spaced hyphens ( `  -  ` ) as punctuation (error)

These were fixed surgically before approval. The content_hash_before and content_hash_after are recorded in `approval_restoration_audit.json`.

### Governance Blocks (13 drafts)
All 13 blocked drafts have `email_status=null`. These contacts were not ZeroBounce verified. They cannot be sent until email_status is set to `verified` or `catch_all`. These are candidates for the ZeroBounce second-pass run.

| Company | Contact | Block Reason |
|---------|---------|-------------|
| 4C Foods Corp. | Mohamed McDoom | email_status=null |
| 4front Engineered Solutions | Michael Hughes | email_status=null |
| Aalberts Surface Technologies | Robert Zitella | email_status=null |
| Alliance Laundry Systems | Steve Van Gompel | email_status=null |
| ALTEK, Inc. | Kylan Kracher | email_status=null |
| Altera Infrastructure | Lucas Pereira | email_status=null |
| Armstrong Fluid Technology | Michael Cline | email_status=null |
| Ash Grove Cement Company | Obaid Khan | email_status=null |
| Babcock Power | Maggie Guenther | email_status=null |
| Bandit Industries | Saul Villalon | email_status=null |
| Batory Foods | Ravi Somanahally | email_status=null |
| Bergstrom | John Bracey | email_status=null |
| Bw Integrated Systems | Vince Jones | email_status=null |

---

## Phase 2: Rejected Draft Reassessment

**Input:** 23 step-2 rejected drafts in positions 1-64
**Approved:** 9 drafts (after fixes)
**Flagged for regeneration:** 2 drafts (fabricated claims cannot be patched)
**Permanent rejects:** 12 drafts (governance-ineligible contacts)

### Rejection Category Analysis

| Category | Count | Disposition |
|----------|-------|-------------|
| GOVERNANCE_INELIGIBLE (email_status=null/unverified) | 12 | PERMANENT_REJECT |
| FABRICATED_CLAIM (client anecdotes) | 2 | REGENERATE |
| STEP_LABEL_LEAK (fixable) | 4 | APPROVED with fix |
| FABRICATED_CLAIM (governance cleared) | 3 | APPROVED with content fix |
| CONTENT_QUALITY_ONLY | 2 | APPROVED with/without fix |

### System Error Reclassification
The `auto_rejected|step 1 landed` rejection category was a system error — step-2 follow-ups that mention "step 1 landed" in their opener are normal follow-up structure, not a policy violation. These were correctly reclassified and approved (with the literal step-1 label removed from the opener text).

### Drafts Flagged for Regeneration

| Company | Contact | Reason |
|---------|---------|--------|
| American Fuji Seal | Ezra Bowen | `past_customer_claim`: "we've trained our platform on..." + "one aerospace OEM... went from 12-15% to 6-8% scrap" — fabricated performance claim |
| BAUER COMPRESSORS INC. | Domonic Bell | `fabricated_anecdote`: "a manufacturer where" — references a specific unnamed customer |

Both drafts should be regenerated by the personalization engine using clean copy (SMRP-sourced industry benchmarks only, no named or unnamed client anecdotes).

---

## Phase 3: Deterministic Review Queue Guarantees

### Root Cause of Batch 1-4 Drift

**What happened:**
- `get_pending_drafts()` in `database.py` (line 428) orders by `created_at DESC`
- The batch review sessions in batches 1-4 sorted by `company_name ASC / last_name ASC` (canonical)
- These two orderings diverge significantly across the 471-draft step-2 pool
- When bulk approval scripts wrote approval for "positions 1-64", they targeted the canonical sort positions — but the API and any retry scripts that use `created_at DESC` point to a completely different set of 64 records
- No content hash was verified at write time, so stale approvals could silently succeed on the wrong record

**Concrete example:**
- Position 1 in canonical order: 3D Systems / Stefan Leonhardt (rejected)
- Position 1 in created_at DESC order: a different draft entirely
- A bulk approval loop targeting "first 64 by created_at" approves the wrong 64 records

### What is Now Fixed

1. **ReviewManifest class** (`backend/app/core/review_manifest.py`):
   - `fetch_review_batch()`: sorts canonically, assigns manifest UUID, stores ordered draft_ids and content hashes
   - `approve_batch()`: validates draft_id in manifest AND checks current body hash matches stored hash
   - Prevents stale-position writes: if a draft's body changed since fetch, the approval is rejected with `hash_mismatch`

2. **Migration 049** (`supabase_migrations/migrations/049_review_manifests.sql`):
   - `review_manifests` table: manifest_id, draft_ids (JSONB), content_hashes (JSONB), fetched_at, approval_decisions
   - Applied to production DB

3. **`deterministic_review_validator.py`** (`scripts/`):
   - Validates ordering drift, governance eligibility, suppression, assertion coverage, orphan states
   - Should run after every bulk approval session

### `get_pending_drafts()` Ordering Gap

The `get_pending_drafts()` function in `database.py` still uses `created_at DESC` ordering. This affects the dashboard display order but NOT the approval writes (which now go through ReviewManifest). However, this creates a confusing mismatch between what the reviewer sees in the UI and what position they're in the canonical queue.

**Recommendation** (not in scope for this session — send-path changes owned by concurrent agent): update `list_pending_drafts()` in `approvals.py` to accept a `sort` parameter defaulting to `company_name_asc` and pass that through to the DB query.

---

## Phase 4: State Consistency Validation

### Results

| Check | Result |
|-------|--------|
| Ordering stability (canonical vs created_at) | MISMATCH — expected, by design |
| Approved drafts with governance violations | 29 (pre-existing, batches 5+) |
| Post-approval suppressions | 0 |
| Send assertion coverage | 80.2% (401/500 contacts) |
| Orphan step-2 (no step-1 sent) | 0 |
| review_manifests table | EXISTS |

### Approved Drafts with Governance Violations (29)
These are pre-existing approvals from batches 5+ for contacts where `email_status=null`. They are NOT from the batch 1-4 reconciliation (all 13 governance-blocked contacts in batch 1-4 were quarantined before this session's approvals ran).

The 29 violations break down: 11 step-1 drafts, 18 step-2 drafts. All have `email_status=null` (28) or `email_status=invalid` (1). These are candidates for the ZeroBounce second-pass run owned by the concurrent agent.

**These drafts will NOT send** — the pre-send assertions include an email_status gate (`verified`/`catch_all`) that blocks sends for unverified addresses.

### Send Assertion Coverage (80.2%)
100 out of 500 sampled sent contacts have no send_assertion record. This is below the 95%+ expected for a hardened pipeline. Investigation and remediation is scoped to the concurrent send-path agent.

### Orphan States
Zero step-2 approved drafts without a step-1 sent. Zero step-3 orphans. No impossible `approved_at < created_at` records found.

---

## Artifacts Produced

| File | Description |
|------|-------------|
| `docs/reports/reconciled_pending_drafts.md` | Phase 1 draft-by-draft results |
| `docs/reports/approval_restoration_audit.json` | Machine-readable Phase 1 audit |
| `docs/reports/rejected_draft_disposition_report.md` | Phase 2 draft-by-draft results |
| `docs/reports/rejected_draft_reassessment.json` | Machine-readable Phase 2 audit |
| `docs/reports/regenerate_rejected_candidates.py` | Draft IDs needing regeneration |
| `docs/reports/operational_state_consistency_report.md` | Phase 4 consistency check |
| `docs/reports/state_integrity_validation.sql` | SQL queries for ongoing validation |
| `backend/app/core/review_manifest.py` | ReviewManifest class |
| `supabase_migrations/migrations/049_review_manifests.sql` | Migration 049 |
| `scripts/pending_draft_reconciliation.py` | Reusable Phase 1 reconciliation script |
| `scripts/rejected_draft_reassessment.py` | Reusable Phase 2 reassessment script |
| `scripts/deterministic_review_validator.py` | Queue state validator |

---

## Before/After Counts

| Metric | Before | After |
|--------|--------|-------|
| Step-2 unsent pending | 217 | 197 |
| Step-2 unsent approved | 65 | 85 |
| Step-2 unsent rejected | 198 | 189 |
| Total approvals restored (batch 1-4) | 0 | 29 |
| Governance blocks quarantined | 0 | 26 |
| Content fixes applied | 0 | 19 |

---

## Governance Violations Requiring Follow-Up

### Immediate (before next send run)
1. **ZeroBounce second-pass**: 26 blocked contacts (batch 1-4) + 29 pre-existing approved contacts all have `email_status=null`. Run ZeroBounce verification before next approval session.
2. **Regenerate 2 drafts**: American Fuji Seal (Ezra Bowen), BAUER COMPRESSORS (Domonic Bell) — fabricated claims, need fresh copy.

### Ongoing
3. **Fix `get_pending_drafts()` ordering**: Update to canonical sort to match manifest ordering in dashboard display.
4. **Assert coverage**: Investigate the 100 sent contacts with no send_assertion records — likely a pre-July 2026 gap before the assertion engine was enabled.

---

**Copyright 2026 Digitillis. All rights reserved.**
**Author: Avanish Mehrotra & Digitillis Architecture Team**
