"""Persona eligibility audit (P1.2).

Reports the count of contacts in each persona_classification bucket and
asserts that no company in `outreach_pending` carries a contact whose
classification is outside the persona allowlist.

Usage:
    python -m backend.scripts.audit_persona_eligibility
"""

from __future__ import annotations

import os
import sys
from collections import Counter

from backend.app.core.contact_filter import (
    _ALLOWED_PERSONAS,
    is_eligible,
    normalize_persona_classification,
)
from backend.app.core.database import Database


def _load_workspace_id() -> str:
    return os.environ.get("WORKSPACE_ID") or "00000000-0000-0000-0000-000000000001"


def main() -> int:
    db = Database(workspace_id=_load_workspace_id())

    # Pull every contact in this workspace with the relevant fields
    rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        page = (
            db.client.table("contacts")
            .select(
                "id, persona_type, persona_classification, persona_confidence, "
                "persona_source, company_id"
            )
            .eq("workspace_id", db.workspace_id)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    # Bucket by canonical classification
    bucket_counter: Counter = Counter()
    for r in rows:
        cls = (
            r.get("persona_classification")
            or normalize_persona_classification(r.get("persona_type"))
            or "(unmapped)"
        )
        bucket_counter[cls] += 1

    print("\n== Contact counts by persona_classification ==")
    print(f"{'classification':<32} {'count':>8} {'allowlisted':>14}")
    print("-" * 58)
    for cls, n in sorted(bucket_counter.items(), key=lambda kv: -kv[1]):
        flag = "yes" if cls in _ALLOWED_PERSONAS else "no"
        print(f"{cls:<32} {n:>8} {flag:>14}")

    # Pull companies in outreach_pending
    pending_companies = (
        db.client.table("companies")
        .select("id")
        .eq("workspace_id", db.workspace_id)
        .eq("status", "outreach_pending")
        .limit(10000)
        .execute()
        .data
        or []
    )
    pending_ids = {c["id"] for c in pending_companies}

    pending_contacts = [r for r in rows if r.get("company_id") in pending_ids]

    out_of_allowlist: list[dict] = []
    for c in pending_contacts:
        cls = c.get("persona_classification") or normalize_persona_classification(
            c.get("persona_type")
        )
        if cls not in _ALLOWED_PERSONAS:
            out_of_allowlist.append(c)

    print(
        f"\n== outreach_pending audit =="
        f"\n  pending companies:               {len(pending_ids)}"
        f"\n  contacts at pending companies:   {len(pending_contacts)}"
        f"\n  contacts outside allowlist:      {len(out_of_allowlist)}"
    )

    if out_of_allowlist:
        print("\nFAIL — outreach_pending contains contacts outside the persona allowlist:")
        for c in out_of_allowlist[:20]:
            print(
                f"  contact_id={c['id']} "
                f"persona_type={c.get('persona_type')} "
                f"classification={c.get('persona_classification')} "
                f"confidence={c.get('persona_confidence')}"
            )
        return 1

    # Spot-check eligibility on first 5 pending contacts
    print("\n== eligibility spot check (first 5 pending) ==")
    for c in pending_contacts[:5]:
        ok = is_eligible(c)
        print(f"  contact_id={c['id']}  is_eligible={ok}  persona_type={c.get('persona_type')}")

    print("\nOK — every pending contact is in the persona allowlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
