#!/usr/bin/env python3
"""One-shot CCS backfill — computes and stores ccs_score for all contacts.

Run after migrating migrations 032-036:
    python -m scripts.backfill_ccs

For each contact:
  1. Counts distinct sources in raw_contacts (raw_source_count)
  2. Calls compute_ccs() with full contact data + raw_source_count
  3. Updates ccs_score and ccs_computed_at on the contacts row

Safe to re-run — it will refresh all scores.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

PAGE_SIZE = 500


def main() -> None:
    from backend.app.core.database import get_supabase_client
    from backend.app.core.contact_filter import compute_ccs

    db = get_supabase_client()
    updated = 0
    errors = 0
    offset = 0

    logger.info("Starting CCS backfill (page_size=%d)...", PAGE_SIZE)

    while True:
        rows = (
            db.table("contacts")
            .select("*")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data or []
        )
        if not rows:
            break

        for contact in rows:
            contact_id = contact["id"]
            try:
                # Count distinct sources for this contact in raw_contacts
                raw_rows = (
                    db.table("raw_contacts")
                    .select("source")
                    .eq("resolved_contact_id", contact_id)
                    .execute()
                    .data or []
                )
                contact["raw_source_count"] = len({r["source"] for r in raw_rows})

                ccs = compute_ccs(contact)
                db.table("contacts").update({
                    "ccs_score": ccs,
                    "ccs_computed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", contact_id).execute()
                updated += 1
            except Exception as exc:
                logger.warning("Failed for contact %s: %s", contact_id, exc)
                errors += 1

        logger.info("offset=%d processed; %d updated so far, %d errors", offset, updated, errors)
        offset += PAGE_SIZE

        if len(rows) < PAGE_SIZE:
            break

        time.sleep(0.05)  # gentle rate limiting

    logger.info("CCS backfill complete: %d updated, %d errors", updated, errors)


if __name__ == "__main__":
    main()
