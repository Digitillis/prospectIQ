# Review Queue Drift Analysis

**Date:** 2026-05-13
**Author:** Avanish Mehrotra & Digitillis Architecture Team

---

## Root Cause of Batch 1-4 Drift

### Timeline of Events

**Sessions 1-4 (pre-2026-05-13):**
- Avanish reviews batches 1-4 (64 drafts total) using a bulk review script
- Script fetches queue sorted by `company_name ASC / last_name ASC`
- Script approves the selected draft_ids in batch
- DB writes succeed for some records; fail silently for others

**2026-05-13 (this session):**
- Inspection reveals 33 of those 64 drafts are still `pending`, 23 still `rejected`
- Only some records (those already in `approved` state) had the writes land

### Why Writes Silently Failed

Investigation points to three likely failure modes:

**1. API rejection without error propagation:**
The approval API (`POST /api/approvals/{draft_id}/approve`) requires:
- Attestation object with all 5 keys set to `true`
- Reviewer role (`member` or above)
- No quality errors in the draft body (unless `?force=true`)

Batch 1-4 review scripts that called the API without an attestation object would have received `400 attestation_incomplete` responses. If the script logged but continued rather than halting, it would produce a misleading "33 approved" output while the database remained unchanged.

**2. Quality gate blocking approval:**
The drafts contain policy violations (diagnostic CTAs, dashes, "no cost" language). The API quality gate (`validate_draft()`) returns `422` for drafts with error-severity issues. A bulk script suppressing errors would silently skip these.

**3. Ordering mismatch causing wrong draft_ids to be targeted:**
If the retry sessions used `created_at DESC` ordering to rebuild the list of "pending in positions 1-64," they would produce a different set of 64 records from the canonical sort. Approving that set marks different records as approved — leaving the original 33 still pending.

### Confirmation Evidence

After this session's reconciliation, the exact 33 pending drafts from positions 1-64 of the canonical sort are now approved (where governance allows). The 13 governance-blocked contacts have `email_status=null` — their write failures were governance-correct.

### Why This Specific Pattern: 33 Pending, 23 Rejected

- **33 pending:** approval writes failed without transitioning the record
- **23 rejected:** system auto-rejection ran against these drafts and marked them `rejected` with reasons like `auto_rejected|step_label_leak` or `fabricated_anecdote`. The auto-rejection is a separate process from manual approval and does not require an attestation. It persisted correctly.

---

## What Prevents Recurrence

1. **ReviewManifest** anchors batch fetch to exact draft_ids with content hashes. No approval can land on an un-reviewed draft.

2. **Dry-run first** rule: every bulk operation now runs with `--dry-run` before committing, printing the exact before/after state.

3. **`deterministic_review_validator.py`** should run after every approval session to confirm state consistency.

4. **API attestation requirement** is enforced on the approval endpoint. Bulk scripts must construct the attestation object or use `?force=true` (admin only).

---

## Ordering Drift Magnitude

Sampling the first 64 positions:

| Sort | Positions 1-5 |
|------|---------------|
| company_name ASC / last_name ASC | 3D Systems, 3D Systems, 4C Foods, 4front, A.M. Castle |
| created_at DESC | Recent drafts (last added to queue) |

The two orderings are essentially unrelated — `created_at` reflects when the draft was generated (pipeline run order), not any attribute of the target company. A bulk approval using `created_at DESC` positions would approve random recent drafts, not the intended review targets.
