"""Deterministic Review Queue Manifest System.

Solves the batch 1-4 approval drift problem by generating an immutable manifest
at fetch time and validating content hashes before any approval write.

Root cause of batch 1-4 drift:
  - `get_pending_drafts()` in database.py sorted by `created_at DESC`
  - The review session sorted by company_name ASC / last_name ASC
  - These two sort orders produce different position sequences
  - When a bulk approval wrote positions 1-64, the wrong records were targeted
  - No content hash was checked, so silent body mutations could corrupt the queue

What the manifest fixes:
  - Fetch time: sort by canonical key (company_name ASC / last_name ASC)
  - Each manifest is assigned a UUID and records the draft_id at each position
  - Content hash (sha256 of body at fetch time) is stored per draft
  - Approval validates: draft_id in manifest AND current body hash matches stored hash
  - If body was mutated since manifest was fetched, the approval is rejected

Usage:
    from backend.app.core.review_manifest import ReviewManifest

    rm = ReviewManifest()
    manifest = rm.fetch_review_batch(batch_size=20, offset=0)
    # ... user reviews drafts ...
    result = rm.approve_batch(manifest["manifest_id"], draft_ids=["abc...", "def..."])

Author: Avanish Mehrotra & Digitillis Architecture Team
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
APPROVED_BY = "avanish"


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewManifest:
    """Deterministic, hash-validated batch review queue for outreach drafts.

    Provides:
      - Canonical ordering (company_name ASC / contact last_name ASC)
      - Immutable position anchoring via manifest UUID
      - Body content hash validation before approval write
      - Full audit trail in review_manifests table
    """

    def __init__(self, supabase_client=None, workspace_id: str = WORKSPACE_ID):
        if supabase_client is None:
            import os
            from supabase import create_client
            from dotenv import load_dotenv
            from pathlib import Path

            load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
            supabase_client = create_client(
                os.environ["SUPABASE_URL"],
                os.environ["SUPABASE_SERVICE_KEY"],
            )
        self.sb = supabase_client
        self.workspace_id = workspace_id

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def fetch_review_batch(
        self,
        batch_size: int = 20,
        offset: int = 0,
        sequence_step: int | None = None,
    ) -> dict[str, Any]:
        """Fetch a deterministically ordered review batch and record a manifest.

        Returns a manifest dict containing:
          - manifest_id: UUID to pass back to approve_batch()
          - drafts: ordered list of draft records (draft_id, contact_name, company_name,
                    subject, body, content_hash, position)
          - batch_size, offset, fetched_at

        Args:
            batch_size: Number of drafts to include in this batch.
            offset: Starting position (0-indexed).
            sequence_step: If set, only include drafts for this step (default: all steps).
        """
        # Fetch all unsent pending drafts
        query = (
            self.sb.table("outreach_drafts")
            .select(
                "id, approval_status, body, subject, sequence_step, contact_id, company_id, "
                "created_at, updated_at"
            )
            .eq("approval_status", "pending")
            .eq("workspace_id", self.workspace_id)
            .is_("sent_at", "null")
        )
        if sequence_step is not None:
            query = query.eq("sequence_step", sequence_step)

        raw = query.execute().data or []

        # Batch-fetch company and contact names for sorting
        company_ids = list({r["company_id"] for r in raw if r.get("company_id")})
        contact_ids = list({r["contact_id"] for r in raw if r.get("contact_id")})

        companies: dict[str, dict] = {}
        for i in range(0, len(company_ids), 100):
            chunk = company_ids[i : i + 100]
            result = (
                self.sb.table("companies")
                .select("id, name")
                .in_("id", chunk)
                .execute()
            )
            for c in result.data or []:
                companies[c["id"]] = c

        contacts: dict[str, dict] = {}
        for i in range(0, len(contact_ids), 100):
            chunk = contact_ids[i : i + 100]
            result = (
                self.sb.table("contacts")
                .select("id, full_name, last_name, first_name")
                .in_("id", chunk)
                .execute()
            )
            for c in result.data or []:
                contacts[c["id"]] = c

        # Canonical sort: company_name ASC, last_name ASC
        def sort_key(r: dict) -> tuple[str, str]:
            co = companies.get(r.get("company_id", ""), {})
            ct = contacts.get(r.get("contact_id", ""), {})
            company_name = (co.get("name") or "").lower()
            fn = ct.get("full_name") or ""
            last_name = (ct.get("last_name") or (fn.split()[-1] if fn else "")).lower()
            return (company_name, last_name)

        raw.sort(key=sort_key)

        # Apply offset + batch_size window
        page = raw[offset : offset + batch_size]

        # Build manifest entries
        draft_ids: list[str] = []
        content_hashes: dict[str, str] = {}
        drafts_out: list[dict] = []

        for pos, draft in enumerate(page, start=offset + 1):
            draft_id = draft["id"]
            body = draft.get("body") or ""
            body_hash = _sha256(body)

            co = companies.get(draft.get("company_id", ""), {})
            ct = contacts.get(draft.get("contact_id", ""), {})
            contact_name = ct.get("full_name") or ct.get("first_name", "Unknown")
            company_name = co.get("name", "Unknown")

            draft_ids.append(draft_id)
            content_hashes[draft_id] = body_hash

            drafts_out.append({
                "position": pos,
                "draft_id": draft_id,
                "contact_name": contact_name,
                "company_name": company_name,
                "subject": draft.get("subject", ""),
                "body": body,
                "sequence_step": draft.get("sequence_step"),
                "content_hash": body_hash,
            })

        # Persist manifest
        manifest_id = str(uuid.uuid4())
        manifest_row = {
            "manifest_id": manifest_id,
            "workspace_id": self.workspace_id,
            "batch_size": batch_size,
            "batch_offset": offset,
            "sort_key": "company_name_asc_last_name_asc",
            "draft_ids": json.dumps(draft_ids),
            "content_hashes": json.dumps(content_hashes),
            "fetched_at": _now_iso(),
            "status": "open",
        }
        try:
            self.sb.table("review_manifests").insert(manifest_row).execute()
            logger.info("[manifest] Created manifest %s with %d drafts", manifest_id[:8], len(draft_ids))
        except Exception as exc:
            logger.warning("[manifest] Failed to persist manifest (non-fatal): %s", exc)

        return {
            "manifest_id": manifest_id,
            "batch_size": batch_size,
            "offset": offset,
            "total_in_queue": len(raw),
            "fetched_at": manifest_row["fetched_at"],
            "drafts": drafts_out,
        }

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def approve_batch(
        self,
        manifest_id: str,
        draft_ids: list[str],
        approved_by: str = APPROVED_BY,
    ) -> dict[str, Any]:
        """Approve a list of drafts, validating against the manifest.

        Validation:
          1. Every draft_id must be in the manifest
          2. Current body hash must match the hash stored at fetch time

        Returns:
          {
            "approved": [...],          # draft_ids successfully approved
            "hash_mismatch": [...],     # draft_ids whose body changed since fetch
            "not_in_manifest": [...],   # draft_ids not in the manifest
            "errors": [...],            # draft_ids that hit DB errors
          }
        """
        # Fetch manifest row
        manifest_row: dict | None = None
        try:
            result = (
                self.sb.table("review_manifests")
                .select("*")
                .eq("manifest_id", manifest_id)
                .limit(1)
                .execute()
            )
            if result.data:
                manifest_row = result.data[0]
        except Exception as exc:
            logger.error("[manifest] Failed to fetch manifest %s: %s", manifest_id[:8], exc)
            return {"error": f"Manifest fetch failed: {exc}"}

        if not manifest_row:
            return {"error": f"Manifest {manifest_id[:8]} not found"}

        stored_draft_ids: list[str] = json.loads(manifest_row.get("draft_ids") or "[]")
        stored_hashes: dict[str, str] = json.loads(manifest_row.get("content_hashes") or "{}")
        manifest_set = set(stored_draft_ids)

        approved: list[str] = []
        hash_mismatch: list[dict] = []
        not_in_manifest: list[str] = []
        errors: list[dict] = []
        decisions: dict[str, dict] = {}

        now_iso = _now_iso()

        for draft_id in draft_ids:
            if draft_id not in manifest_set:
                not_in_manifest.append(draft_id)
                decisions[draft_id] = {"status": "not_in_manifest", "timestamp": now_iso}
                continue

            # Fetch current body to check hash
            try:
                current = (
                    self.sb.table("outreach_drafts")
                    .select("id, body, approval_status")
                    .eq("id", draft_id)
                    .limit(1)
                    .execute()
                )
                if not current.data:
                    errors.append({"draft_id": draft_id, "error": "Draft not found"})
                    decisions[draft_id] = {"status": "draft_not_found", "timestamp": now_iso}
                    continue

                current_body = current.data[0].get("body") or ""
                current_hash = _sha256(current_body)
                stored_hash = stored_hashes.get(draft_id, "")

                if current_hash != stored_hash:
                    hash_mismatch.append({
                        "draft_id": draft_id,
                        "stored_hash": stored_hash[:16],
                        "current_hash": current_hash[:16],
                    })
                    decisions[draft_id] = {
                        "status": "hash_mismatch",
                        "stored_hash": stored_hash[:16],
                        "current_hash": current_hash[:16],
                        "timestamp": now_iso,
                    }
                    logger.warning(
                        "[manifest] Hash mismatch for %s: body changed since manifest fetch", draft_id[:8]
                    )
                    continue

            except Exception as exc:
                errors.append({"draft_id": draft_id, "error": str(exc)})
                decisions[draft_id] = {"status": "error", "detail": str(exc), "timestamp": now_iso}
                continue

            # Write approval
            try:
                self.sb.table("outreach_drafts").update({
                    "approval_status": "approved",
                    "approved_at": now_iso,
                    "approved_by": approved_by,
                }).eq("id", draft_id).execute()
                approved.append(draft_id)
                decisions[draft_id] = {"status": "approved", "timestamp": now_iso, "approved_by": approved_by}
                logger.info("[manifest] Approved %s", draft_id[:8])
            except Exception as exc:
                errors.append({"draft_id": draft_id, "error": str(exc)})
                decisions[draft_id] = {"status": "db_error", "detail": str(exc), "timestamp": now_iso}

        # Update manifest record
        new_status = "applied" if not errors and not hash_mismatch and not not_in_manifest else "applied_with_exceptions"
        try:
            self.sb.table("review_manifests").update({
                "approved_at": now_iso,
                "approved_by": approved_by,
                "approval_decisions": json.dumps(decisions),
                "status": new_status,
            }).eq("manifest_id", manifest_id).execute()
        except Exception as exc:
            logger.warning("[manifest] Failed to update manifest status: %s", exc)

        return {
            "manifest_id": manifest_id,
            "approved": approved,
            "hash_mismatch": hash_mismatch,
            "not_in_manifest": not_in_manifest,
            "errors": errors,
            "total_submitted": len(draft_ids),
            "total_approved": len(approved),
        }

    # ------------------------------------------------------------------
    # Expiry / housekeeping
    # ------------------------------------------------------------------

    def expire_old_manifests(self, max_age_hours: int = 24) -> int:
        """Mark manifests older than max_age_hours as expired. Returns count expired."""
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        try:
            result = (
                self.sb.table("review_manifests")
                .update({"status": "expired"})
                .eq("workspace_id", self.workspace_id)
                .eq("status", "open")
                .lt("fetched_at", cutoff)
                .execute()
            )
            count = len(result.data or [])
            if count:
                logger.info("[manifest] Expired %d old manifests", count)
            return count
        except Exception as exc:
            logger.warning("[manifest] expire_old_manifests failed: %s", exc)
            return 0
