#!/usr/bin/env python3
"""Clean up the partial-ID imports so DiscoveryAgent can repopulate cleanly.

Deletes:
  - All contacts with truncated Apollo IDs (< 15 chars) across any company
  - All companies inserted via the tier0 import campaign that have no real
    apollo_id set (DiscoveryAgent will re-create them with real IDs)

The 8 companies that pre-existed (EVS Metal, CraftMark, etc.) keep their
company rows — only their bad contacts are removed.

Run from prospectIQ/backend/:
    python -m scripts.cleanup_tier0_imports
    python -m scripts.cleanup_tier0_imports --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.database import Database

IMPORT_CAMPAIGNS = {"tier0-mfg-pdm-roi", "tier0-fb-fsma"}
REAL_APOLLO_ID_MIN_LEN = 15  # real IDs are 24 chars; our partials are 6


def run_cleanup(dry_run: bool) -> None:
    db = Database()
    client = db.client

    # ------------------------------------------------------------------
    # 1. Find and delete partial-ID contacts
    # ------------------------------------------------------------------
    print("Finding contacts with truncated Apollo IDs...")
    all_contacts = client.table("contacts").select("id, apollo_id, first_name, title, company_id").execute().data
    partial_contacts = [c for c in all_contacts if c.get("apollo_id") and len(c["apollo_id"]) < REAL_APOLLO_ID_MIN_LEN]

    print(f"  Found {len(partial_contacts)} contacts with partial IDs to remove")
    for c in partial_contacts:
        print(f"    🗑  {c['first_name']} — {c['title']} (apollo_id={c['apollo_id']!r})")

    if not dry_run and partial_contacts:
        ids = [c["id"] for c in partial_contacts]
        client.table("contacts").delete().in_("id", ids).execute()
        print(f"  ✅ Deleted {len(partial_contacts)} partial-ID contacts")

    # ------------------------------------------------------------------
    # 2. Find and delete companies inserted by import (no real apollo_id, no domain)
    # ------------------------------------------------------------------
    print("\nFinding import-only companies to remove...")
    import_companies = (
        client.table("companies")
        .select("id, name, apollo_id, domain, campaign_name")
        .in_("campaign_name", list(IMPORT_CAMPAIGNS))
        .execute()
        .data
    )

    # Only delete the ones that have no real apollo_id AND no domain
    # (the 8 pre-existing companies had real apollo_ids from prior DiscoveryAgent runs)
    bad_companies = [
        co for co in import_companies
        if not co.get("apollo_id") and not co.get("domain")
    ]

    print(f"  Found {len(bad_companies)} import-only companies to remove")
    for co in bad_companies:
        print(f"    🗑  {co['name']} (campaign={co['campaign_name']})")

    if not dry_run and bad_companies:
        ids = [co["id"] for co in bad_companies]
        # Delete any remaining contacts for these companies first (safety net)
        client.table("contacts").delete().in_("company_id", ids).execute()
        client.table("companies").delete().in_("id", ids).execute()
        print(f"  ✅ Deleted {len(bad_companies)} import-only companies")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"  {prefix}Cleanup done")
    print(f"  Contacts removed: {len(partial_contacts)}")
    print(f"  Companies removed: {len(bad_companies)}")
    if not dry_run:
        print(f"\n  Next: run DiscoveryAgent to repopulate with real Apollo IDs")
        print(f"  See: backend/scripts/run_discovery.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up partial-ID tier0 imports")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
