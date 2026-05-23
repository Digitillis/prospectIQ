# Deterministic Review Integrity Report

**Date:** 2026-05-13
**Author:** Avanish Mehrotra & Digitillis Architecture Team

---

## What Was Broken

### Problem 1: Ordering Mismatch Between Review and Approval

`get_pending_drafts()` in `database.py` orders by `created_at DESC`. The batch review sessions in sessions 1-4 sorted by `company_name ASC / contact last_name ASC` (canonical). These two orderings diverge significantly.

When session scripts iterated over "positions 1-64 of the sorted queue" and approved them, the DB write targeted records by draft_id — but when the session later tried to verify or retry, it could re-fetch using `created_at DESC` ordering and compute wrong positions. Additionally, any later approval script that used `created_at` ordering would approve the wrong 64 records.

**Impact:** Up to 64 approvals wrote to the correct draft_ids in isolation (if using the canonical sort), but subsequent sessions using a different sort order could not deterministically reproduce position 1 = draft X.

### Problem 2: No Content Hash Validation

Approval writes had no mechanism to detect if a draft's body was mutated between when the reviewer read it and when the approval was committed. A draft could be:
- Edited by another session in parallel
- Modified by a content quality fixer between review and approval

Without a content hash, an approval could validly write to a draft whose content had changed to contain a policy violation.

### Problem 3: No Manifest Linking Fetch to Write

There was no atomic linkage between "I fetched these 20 drafts" and "I am now approving these specific 20 drafts." Each approval call was independent and could be applied to any draft_id with any body content.

---

## What Is Now Fixed

### ReviewManifest System (`backend/app/core/review_manifest.py`)

```
fetch_review_batch(batch_size, offset)
  → Returns manifest_id + ordered list of drafts
  → Stores (manifest_id, draft_ids, content_hashes) in review_manifests table
  → Sort: company_name ASC / last_name ASC (canonical, deterministic)

approve_batch(manifest_id, draft_ids)
  → Validates: every draft_id is in the manifest
  → Validates: current body hash == stored hash at fetch time
  → On hash mismatch: rejects the approval, returns hash_mismatch error
  → On success: writes approval_status=approved + full audit record
```

### Migration 049: review_manifests table

Stores all manifests with:
- `manifest_id` (UUID PK)
- `draft_ids` (JSONB ordered array)
- `content_hashes` (JSONB keyed by draft_id)
- `fetched_at`, `approved_at`, `approved_by`
- `approval_decisions` (JSONB per-draft decisions)
- `status` (open | applied | applied_with_exceptions | expired | invalidated)

### Remaining Gap: Dashboard Sort Order

`list_pending_drafts()` in `approvals.py` still uses `get_pending_drafts()` which sorts by `created_at DESC`. The dashboard display order will differ from the manifest canonical order. This is a cosmetic issue now (approvals always go through manifest) but should be addressed for reviewer clarity.

---

## Severity and Rollback

**Severity of original bug:** HIGH — caused 33 approved-writes to fail silently over 4 sessions.

**Rollback strategy for ReviewManifest:** If manifest-based approvals cause issues, disable by calling `approve_batch()` without a manifest_id check (skip the manifest lookup). The underlying approval write logic is unchanged; the manifest adds a validation layer on top.
