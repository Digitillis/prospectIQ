#!/usr/bin/env python3
"""ICP Pre-filter — Stage 0 of the gated linear pipeline.

Two jobs:
  1. Disqualify ghost-duplicate shells (custom_tags.is_duplicate=true, status=discovered).
     These are safe to bulk-disqualify: the real record lives elsewhere.

  2. Name-based ICP sanity check on 'unknown' cluster companies.
     Flags obvious non-manufacturers (law firms, banks, staffing, retail, etc.)
     that slipped through Apollo's manufacturing search.

Usage:
    python3 scripts/icp_prefilter.py --dry-run        # show what would change
    python3 scripts/icp_prefilter.py --ghosts-only    # clean ghosts, skip name filter
    python3 scripts/icp_prefilter.py                  # full run (ghosts + name filter)
    python3 scripts/icp_prefilter.py --sample 100     # name-filter sample only (no writes)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import get_supabase_client

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_SIZE = 1000

# ---------------------------------------------------------
# Non-manufacturer signal patterns (case-insensitive)
# ---------------------------------------------------------
DISQUALIFY_PATTERNS = [
    # Legal
    " law ", " law,", "law firm", " llp", " llp.", " llp,", "attorneys",
    "legal services", "solicitors",
    # Finance & investment
    "capital partners", "capital management", "investment management",
    "private equity", "venture capital", "hedge fund", "asset management",
    "financial services", "wealth management", "securities",
    " bank ", " banking", "credit union", "insurance company",
    "insurance agency", "mortgage",
    # Real estate
    "real estate", " realty", "property management", "commercial properties",
    "residential properties",
    # Healthcare provider (not device/equipment)
    "hospital system", "health system", "medical center", "health network",
    "physician group", "dental practice", "urgent care", "hospice",
    # Staffing & HR
    "staffing solutions", "staffing agency", "talent acquisition",
    "executive search", "hr consulting", "human resources consulting",
    # Marketing & media
    "marketing agency", "advertising agency", "media agency",
    "public relations", "digital marketing", "creative agency",
    # Retail (non-industrial)
    "retail store", "e-commerce", "online retailer",
    # Restaurant / hospitality
    " restaurant", " restaurants", "food service", "catering company",
    "hotel group", "hospitality management",
    # Education / nonprofit (not vocational)
    "school district", "community college", "charitable foundation",
    "trade association", " church", " churches",
    # Consulting (management, not engineering/ops)
    "management consulting", "strategy consulting", "business consulting",
]

# Signals that PROTECT a company from disqualification even if a
# disqualify pattern matches (e.g., "capital" in "Capital Equipment Corp")
PROTECT_PATTERNS = [
    "manufacturing", "mfg", "industrial", " industries",
    "products", "fabricat", "machin", "casting", "forging",
    "metal", "steel", "plastics", "precision", "tooling",
    "equipment", "components", "systems", "engineering",
    "automation", "electronics", "semiconductor", "chemicals",
    "packaging", "printing", "aerospace", "defense", "automotive",
    "food processing", "beverage", "pharma",
]


def _is_non_manufacturer(name: str) -> tuple[bool, str]:
    """Return (should_disqualify, matched_pattern)."""
    lower = name.lower()

    # If any protect pattern hits, never disqualify on name alone
    for p in PROTECT_PATTERNS:
        if p in lower:
            return False, ""

    for p in DISQUALIFY_PATTERNS:
        if p in lower:
            return True, p

    return False, ""


def _fetch_all_discovered(client) -> list[dict]:
    all_rows = []
    offset = 0
    while True:
        result = (
            client.table("companies")
            .select("id,name,custom_tags,tier,campaign_name,status")
            .eq("workspace_id", WORKSPACE_ID)
            .eq("status", "discovered")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = result.data or []
        all_rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_rows


def _parse_tags(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def run(dry_run: bool, ghosts_only: bool, sample: int | None) -> None:
    client = get_supabase_client()
    prefix = "[DRY-RUN] " if dry_run else ""

    print(f"{prefix}Fetching all discovered companies...")
    all_rows = _fetch_all_discovered(client)
    print(f"  Total discovered: {len(all_rows)}")

    # Separate ghosts from real
    ghosts = []
    real_rows = []
    for c in all_rows:
        tags = _parse_tags(c.get("custom_tags"))
        if tags.get("is_duplicate"):
            ghosts.append(c)
        else:
            real_rows.append(c)

    print(f"  Ghost duplicates (is_duplicate=true): {len(ghosts)}")
    print(f"  Real companies: {len(real_rows)}")
    print()

    # --- Step 1: Disqualify ghost duplicates ---
    ghost_ids = [g["id"] for g in ghosts]
    print(f"{prefix}Step 1: Disqualify {len(ghost_ids)} ghost duplicates")
    if ghost_ids and not dry_run and not sample:
        # Batch deletes in groups of 500 (Supabase limit on IN clause)
        disqualified = 0
        for i in range(0, len(ghost_ids), 500):
            chunk = ghost_ids[i:i+500]
            client.table("companies").update({"status": "disqualified"}).in_("id", chunk).execute()
            disqualified += len(chunk)
        print(f"  Disqualified: {disqualified}")
    else:
        print(f"  Would disqualify: {len(ghost_ids)} (skipped in {'sample' if sample else 'dry-run'} mode)")
    print()

    if ghosts_only:
        print("--ghosts-only flag set. Skipping name-based ICP filter.")
        return

    # --- Step 2: Name-based ICP filter on unclassified companies ---
    # "unknown" in earlier analysis = campaign_cluster key is missing (not string "unknown")
    KNOWN_MFG_CLUSTERS = {"machinery", "process", "auto", "chemicals", "fb", "metals", "electronics"}
    unknown = [
        c for c in real_rows
        if _parse_tags(c.get("custom_tags")).get("campaign_cluster") not in KNOWN_MFG_CLUSTERS
    ]
    print(f"Step 2: Name-based ICP filter on {len(unknown)} unclassified companies")

    if sample:
        # Sample-only mode: show what the filter would flag without writing
        target = unknown[:sample]
        print(f"  (sample mode: reviewing first {len(target)})")
        flagged = []
        kept = []
        for c in target:
            disqualify, pattern = _is_non_manufacturer(c["name"])
            if disqualify:
                flagged.append((c["name"], pattern))
            else:
                kept.append(c["name"])

        print(f"\n  Would DISQUALIFY ({len(flagged)}):")
        for name, pat in flagged:
            print(f"    [{pat}]  {name}")
        print(f"\n  Would KEEP ({len(kept)}):")
        for name in kept[:30]:
            print(f"    {name}")
        if len(kept) > 30:
            print(f"    ... and {len(kept)-30} more")
        return

    # Full run
    to_disqualify = []
    for c in unknown:
        disqualify, pattern = _is_non_manufacturer(c["name"])
        if disqualify:
            to_disqualify.append((c["id"], c["name"], pattern))

    print(f"  ICP filter would disqualify: {len(to_disqualify)} of {len(unknown)}")
    print(f"  ICP filter would keep:       {len(unknown) - len(to_disqualify)}")

    if to_disqualify:
        print(f"\n  Companies flagged by name filter:")
        for _, name, pat in to_disqualify[:50]:
            print(f"    [{pat}]  {name}")
        if len(to_disqualify) > 50:
            print(f"    ... and {len(to_disqualify)-50} more")

    if to_disqualify and not dry_run:
        ids = [r[0] for r in to_disqualify]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i+500]
            client.table("companies").update({"status": "disqualified"}).in_("id", chunk).execute()
        print(f"\n  Disqualified {len(to_disqualify)} non-ICP companies.")
    elif to_disqualify:
        print(f"\n  {prefix}Would disqualify {len(to_disqualify)} companies.")

    print()
    print(f"{prefix}Done.")
    print(f"  Ghost duplicates action: {len(ghosts)}")
    print(f"  Name-filter disqualified: {len(to_disqualify)}")
    remaining = len(real_rows) - len(to_disqualify)
    print(f"  Remaining real discovered: {remaining}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--ghosts-only", action="store_true", help="Only clean ghost duplicates")
    parser.add_argument("--sample", type=int, default=None, help="Sample N unknown companies for review (no writes)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, ghosts_only=args.ghosts_only, sample=args.sample)
