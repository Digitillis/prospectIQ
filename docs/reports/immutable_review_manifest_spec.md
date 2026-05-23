# Immutable Review Manifest Specification

**Version:** 1.0
**Date:** 2026-05-13
**Author:** Avanish Mehrotra & Digitillis Architecture Team

---

## Overview

A review manifest is an immutable snapshot of a pending draft batch created at fetch time. It anchors the exact set of drafts and their content at the moment of review, and validates that neither the record set nor the content has drifted before an approval write is committed.

---

## Data Model

### review_manifests table

| Column | Type | Description |
|--------|------|-------------|
| `manifest_id` | UUID PK | Unique identifier for this manifest |
| `workspace_id` | UUID | Scoped to this workspace |
| `batch_size` | INTEGER | Number of drafts in this batch |
| `batch_offset` | INTEGER | Starting position (0-indexed) in the full queue |
| `sort_key` | TEXT | Sort algorithm: `company_name_asc_last_name_asc` |
| `draft_ids` | JSONB | Ordered array of draft UUIDs (positionally significant) |
| `content_hashes` | JSONB | `{draft_id: sha256(body)}` at fetch time |
| `fetched_at` | TIMESTAMPTZ | When the manifest was created |
| `approved_at` | TIMESTAMPTZ | When approval was committed (null if not yet applied) |
| `approved_by` | TEXT | Who approved (always "avanish" for now) |
| `approval_decisions` | JSONB | Per-draft outcome: approved, hash_mismatch, not_in_manifest, error |
| `status` | TEXT | `open` / `applied` / `applied_with_exceptions` / `expired` / `invalidated` |
| `invalidation_reason` | TEXT | Human-readable explanation (if status=invalidated) |

---

## Lifecycle

```
                    ┌─────────────────┐
                    │   OPEN          │  Created by fetch_review_batch()
                    │ (fetched_at set)│
                    └────────┬────────┘
                             │
               ┌─────────────────────┐
               │                     │
        approve_batch()        (after 24h)
               │                     │
    ┌──────────▼──────────┐  ┌───────▼────────┐
    │ APPLIED             │  │ EXPIRED        │
    │ (all OK)            │  │ (not used)     │
    └─────────────────────┘  └────────────────┘
               │
    (exceptions exist)
               │
    ┌──────────▼──────────────────┐
    │ APPLIED_WITH_EXCEPTIONS     │
    │ (hash mismatches, errors)   │
    └─────────────────────────────┘
```

---

## Canonical Sort Order

All manifests use `company_name ASC / contact last_name ASC` as the canonical sort. This matches the sort order used in all batch review sessions. It is stable and deterministic (company names and last names do not change).

Using `created_at DESC` for queue display is acceptable in the dashboard but must never be used as the position anchor for bulk approvals.

---

## Content Hash Guarantee

Before any approval write, the system:
1. Fetches the current body from `outreach_drafts`
2. Computes `sha256(body)`
3. Compares against `content_hashes[draft_id]` stored in the manifest

If they differ, the approval is rejected with a `hash_mismatch` error. This prevents:
- Parallel session edits silently changing the content that was reviewed
- Quality fix scripts mutating body between review and approval
- Race conditions in bulk approval loops

---

## Usage

```python
from backend.app.core.review_manifest import ReviewManifest

rm = ReviewManifest()

# 1. Fetch batch (creates manifest)
manifest = rm.fetch_review_batch(batch_size=20, offset=0)
manifest_id = manifest["manifest_id"]
drafts = manifest["drafts"]  # ordered list with positions

# 2. Reviewer reads and selects drafts to approve
approved_ids = [d["draft_id"] for d in drafts if passes_review(d)]

# 3. Approve via manifest (validates positions + hashes)
result = rm.approve_batch(manifest_id, approved_ids)

# result.approved   = successfully approved draft_ids
# result.hash_mismatch = draft_ids whose body changed since fetch
# result.not_in_manifest = draft_ids not in this manifest
```

---

## Expiry Policy

Manifests expire after 24 hours if unused (`status=expired`). An expired manifest cannot be used for approvals — a new fetch must be performed. The 24-hour window covers a full review session including overnight work.
