#!/usr/bin/env python3
"""Seed ProspectIQ with Tier 0 prospects using REAL 24-char Apollo person IDs.

All IDs in this file were retrieved via Apollo People API (MCP) searches and
verified by confirming the first 6 chars match the truncated IDs in the
prospect markdown files.

Usage (from prospectIQ/backend/):
    python -m scripts.seed_tier0_real_ids
    python -m scripts.seed_tier0_real_ids --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.database import Database


# ---------------------------------------------------------------------------
# MFG Tier 0 — Real Apollo person IDs (24-char)
# Partial IDs in PROSPECT_LIST_MFG.md confirmed to match these full IDs.
# ---------------------------------------------------------------------------

MFG_TIER0_DATA = [
    {
        "company": {
            "name": "GCM",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Michael", "title": "Director of Operations",
             "apollo_id": "6896eafe82027e00018310a3",
             "persona_type": "director_ops", "is_decision_maker": True},
            {"first_name": "Lu", "title": "Director of Operations",
             "apollo_id": "646f46e8908eae0001e4e12c",
             "persona_type": "director_ops", "is_decision_maker": True},
            {"first_name": "David", "title": "Director of Operations",
             "apollo_id": "5f0a34a4ff5ad500019da5d4",
             "persona_type": "director_ops", "is_decision_maker": True},
            {"first_name": "Chad", "title": "Director of Operations",
             "apollo_id": "57d50949a6da98536ee0f61d",
             "persona_type": "director_ops", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Ace Metal Crafts Company",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Chris", "title": "Vice President of Engineering",
             "apollo_id": "5d5f457df6512573f1246913",
             "persona_type": "vp_eng", "is_decision_maker": True},
            {"first_name": "Dale", "title": "VP Engineering",
             "apollo_id": "58bdab66f651251183c42c06",
             "persona_type": "vp_eng", "is_decision_maker": True},
            {"first_name": "Raphael", "title": "VP Operations - Machining",
             "apollo_id": "671121fd8bc9070001162507",
             "persona_type": "vp_ops", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "EVS Metal",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Robert", "title": "VP of Manufacturing",
             "apollo_id": "60fedd6eb727d10001f5dbd4",
             "persona_type": "vp_mfg", "is_decision_maker": True},
            {"first_name": "Keith", "title": "GM / Director of Manufacturing",
             "apollo_id": "60d1bc709d6a6800012cdc65",
             "persona_type": "plant_manager", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Major Tool & Machine",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Brandon", "title": "Director of Manufacturing",
             "apollo_id": "5d60211af651258f69fc5b91",
             "persona_type": "director_mfg", "is_decision_maker": True},
            # Anthony (Dir. Engineering) — not resolved via MCP, skip
        ],
    },
    {
        "company": {
            "name": "Libra Industries",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Troy", "title": "VP of Quality and Engineering",
             "apollo_id": "66f646fb39affd00012a090e",
             "persona_type": "vp_quality", "is_decision_maker": True},
            {"first_name": "Philip", "title": "Director of Manufacturing",
             "apollo_id": "5acd4de0a6da98d9ac911481",
             "persona_type": "director_mfg", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Regal Research & Mfg. Co.",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Peyton", "title": "Vice President of Engineering and Manufacturing",
             "apollo_id": "65bdaf60d0010f00018deb2c",
             "persona_type": "vp_eng", "is_decision_maker": True},
            {"first_name": "Robert", "title": "VP, Engineering, Quality and Reliability, Finance, and Business Mgmt",
             "apollo_id": "618c8fb61bc345000107526b",
             "persona_type": "vp_eng", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Tri-State Fabricators",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Jeff", "title": "VP Engineering",
             "apollo_id": "631662601394b50001ff35ed",
             "persona_type": "vp_eng", "is_decision_maker": True},
            {"first_name": "Joel", "title": "Director of Operations",
             "apollo_id": "57e1c33fa6da9856ff1c957a",
             "persona_type": "director_ops", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "ALTEK, Inc.",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "John", "title": "VP Manufacturing Operations",
             "apollo_id": "5f9de737d4b98400dd89dc6f",
             "persona_type": "vp_mfg", "is_decision_maker": True},
            {"first_name": "Todd", "title": "VP Quality and Productivity",
             "apollo_id": "5f4ca5614ac64100017c77ef",
             "persona_type": "vp_quality", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Kapco Metal Stamping",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Mike", "title": "Vice President of Manufacturing",
             "apollo_id": "60e5b4a9f58d86000145e41f",
             "persona_type": "vp_mfg", "is_decision_maker": True},
            {"first_name": "Timothy", "title": "Director of Manufacturing",
             "apollo_id": "54a515347468692abfcf857b",
             "persona_type": "director_mfg", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Covert Manufacturing, Inc.",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Chris", "title": "Director of Manufacturing Engineering",
             "apollo_id": "54a4a2c174686938ac255657",
             "persona_type": "director_mfg", "is_decision_maker": True},
            {"first_name": "Steve", "title": "Vice President of Engineering",
             "apollo_id": "60948620689f3b000115aaa8",
             "persona_type": "vp_eng", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Advance Turning & Manufacturing, Inc.",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Ron", "title": "Vice President of Quality and Engineering",
             "apollo_id": "66f3d63ddd5d050001e4fe2e",
             "persona_type": "vp_quality", "is_decision_maker": True},
            {"first_name": "Ben", "title": "Vice President of Manufacturing",
             "apollo_id": "6198897ce409f000012aac18",
             "persona_type": "vp_mfg", "is_decision_maker": True},
        ],
    },
    {
        "company": {
            "name": "Midstate Machine",
            "tier": "mfg1",
            "industry": "Discrete Manufacturing",
            "status": "discovered",
            "campaign_name": "tier0-mfg-pdm-roi",
        },
        "contacts": [
            {"first_name": "Richard", "title": "Vice President Operations",
             "apollo_id": "673c1d1915d7560001c7e80d",
             "persona_type": "vp_ops", "is_decision_maker": True},
            {"first_name": "Mark", "title": "Director of Operations",
             "apollo_id": "57da3c02a6da984ab7c28627",
             "persona_type": "director_ops", "is_decision_maker": True},
        ],
    },
    # Companies where no contacts were resolved via Apollo MCP:
    # - Petersen Inc. (Tyler, Matt) — not indexed in free Apollo search
    # - Metalworking Group (Monica, Mark) — not indexed
    # - EK (Dan, Eric) — too generic, not resolved
    # - Primus Aerospace (Christopher, Matt) — not indexed
    # - IBCC Industries (Sean, Douglas) — IBCC on Apollo is a different entity (Indian company)
]


# ---------------------------------------------------------------------------
# F&B Tier 0 — Real Apollo person IDs (24-char)
# ---------------------------------------------------------------------------

FB_TIER0_DATA = [
    {
        "company": {
            "name": "CraftMark Bakery",
            "tier": "fb1",
            "industry": "Food & Beverage",
            "status": "discovered",
            "campaign_name": "tier0-fb-fsma",
        },
        "contacts": [
            {"first_name": "David", "title": "Director Food Safety and Quality",
             "apollo_id": "54c1a7ce7468697af7c70032",
             "persona_type": "director_food_safety", "is_decision_maker": True},
            # Devin (Sr Dir. QA&FS), Dale, Nicholas, Jose — not resolved via MCP
            # These will need enrichment via Apollo UI or credits
        ],
    },
    {
        "company": {
            "name": "Engelman's Bakery",
            "tier": "fb1",
            "industry": "Food & Beverage",
            "status": "discovered",
            "campaign_name": "tier0-fb-fsma",
        },
        "contacts": [
            {"first_name": "Barbara", "title": "Director of Food Safety and Quality",
             "apollo_id": "54ec24477468694311474658",
             "persona_type": "director_food_safety", "is_decision_maker": True},
            # Paul (VP Operational Excellence), Brody (VP Operations) — not resolved
        ],
    },
    {
        "company": {
            "name": "Nelson-Jameson",
            "tier": "fb1",
            "industry": "Food & Beverage",
            "status": "discovered",
            "campaign_name": "tier0-fb-fsma",
        },
        "contacts": [
            {"first_name": "Shawn", "title": "VP of Operations and Logistics",
             "apollo_id": "66f68832e89e940001143500",
             "persona_type": "vp_ops", "is_decision_maker": True},
            {"first_name": "Jessica", "title": "Director of Category Strategy- Food Safety and Quality",
             "apollo_id": "5f5b4783a2ae060001ef5dd6",
             "persona_type": "director_food_safety", "is_decision_maker": True},
            # Brian (Dir. Ops West) — not resolved
        ],
    },
    {
        "company": {
            "name": "Sterling Foods",
            "tier": "fb1",
            "industry": "Food & Beverage",
            "status": "discovered",
            "campaign_name": "tier0-fb-fsma",
        },
        "contacts": [
            {"first_name": "Eric", "title": "Corporate Director of Food Safety & Quality",
             "apollo_id": "64c1cd007ada6f000145408e",
             "persona_type": "director_food_safety", "is_decision_maker": True},
            # Gabriel (VP Operations) — not resolved
        ],
    },
    {
        "company": {
            "name": "Stella & Chewy's",
            "tier": "fb1",
            "industry": "Food & Beverage",
            "status": "discovered",
            "campaign_name": "tier0-fb-fsma",
        },
        "contacts": [
            {"first_name": "Kerry", "title": "Director of Food Safety",
             "apollo_id": "5b0d1a64a3ae618258bd704e",
             "persona_type": "director_food_safety", "is_decision_maker": True},
            # Andy (VP Quality & Food Safety) — not resolved
        ],
    },
    # Companies where no contacts were resolved via Apollo MCP (free API):
    # - Daybreak Foods (Rebecca, Julia)
    # - Godshall's Quality Meats (Joshua, Randy)
    # - ILLES Foods (Kari, Sharon)
    # - WTI Inc. (John, Troy)
    # - BrightPet (Mark, Teki)
    # - Catelli Brothers (Keith, Thomas)
    # - Chesapeake Spice Company (Aleksandra, Eric)
    # - Diversified Foods & Seasonings (Octavio, Joseph)
    # - Carolina Foods (Josh, Kent)
    # These 9 companies need Apollo credits or UI enrichment.
    # Their partial IDs from PROSPECT_LIST_FB.md are real - use Apollo UI to look up by name.
]

ALL_DATA = [("MFG", row) for row in MFG_TIER0_DATA] + \
           [("F&B", row) for row in FB_TIER0_DATA]


# ---------------------------------------------------------------------------
# Insertion logic
# ---------------------------------------------------------------------------

def _get_or_create_company(db: Database, co_data: dict, dry_run: bool) -> dict | None:
    existing = db.get_companies(search=co_data["name"], limit=5)
    for row in existing:
        if row["name"].strip().lower() == co_data["name"].strip().lower():
            print(f"    ↩  {co_data['name']} already exists (id={row['id'][:8]}...)")
            return row

    if dry_run:
        print(f"    [DRY-RUN] would insert: {co_data['name']}")
        return None

    row = db.insert_company(co_data)
    print(f"    ✅ Inserted company: {co_data['name']} (id={row.get('id', '?')[:8]}...)")
    return row


def _get_or_create_contact(db: Database, company_id: str, contact: dict,
                            dry_run: bool) -> bool:
    existing = db.get_contact_by_apollo_id(contact["apollo_id"])
    if existing:
        print(f"      ↩  {contact['first_name']} ({contact['apollo_id'][:8]}...) already exists")
        return False

    if dry_run:
        print(f"      [DRY-RUN] would insert: {contact['first_name']} — {contact['title']}")
        return True

    data = {
        "company_id": company_id,
        "first_name": contact["first_name"],
        "last_name": "",
        "title": contact["title"],
        "apollo_id": contact["apollo_id"],
        "persona_type": contact["persona_type"],
        "is_decision_maker": contact["is_decision_maker"],
    }
    db.insert_contact(data)
    print(f"      ✅ {contact['first_name']} — {contact['title']} ({contact['apollo_id'][:8]}...)")
    return True


def run_seed(dry_run: bool = False) -> None:
    db = Database()
    total_companies = 0
    total_contacts = 0
    skipped_companies = 0

    for vertical, row in ALL_DATA:
        co_data = row["company"]
        contacts = row["contacts"]

        print(f"\n  🏭  [{vertical}] {co_data['name']} ({len(contacts)} contact(s))")
        co_row = _get_or_create_company(db, co_data, dry_run)

        if co_row is None and not dry_run:
            skipped_companies += 1
            continue

        total_companies += 1
        company_id = co_row["id"] if co_row else "dry-run"

        for contact in contacts:
            inserted = _get_or_create_contact(db, company_id, contact, dry_run)
            if inserted or dry_run:
                total_contacts += 1

    print(f"\n{'='*60}")
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"  {prefix}Seeding complete")
    print(f"  Companies processed : {total_companies}")
    print(f"  Contacts inserted   : {total_contacts}")
    if skipped_companies:
        print(f"  Companies skipped   : {skipped_companies} (insert failed)")
    print()
    print("  Unresolved contacts (need Apollo credits / UI enrichment):")
    print("  MFG: Anthony (Major Tool), Petersen Inc. (2), Metalworking Group (2),")
    print("       EK (2), Primus Aerospace (2), IBCC Industries (2)")
    print("  F&B: Devin/Dale/Nicholas/Jose (CraftMark), Paul/Brody (Engelman's),")
    print("       Brian (Nelson-Jameson), Gabriel (Sterling), Andy (Stella & Chewy's),")
    print("       + all 9 remaining F&B companies (29 contacts)")
    print()
    if not dry_run:
        print("  Next: run DiscoveryAgent with corrected icp.yaml to fill the gaps")
        print("  See: backend/scripts/fix_icp_and_discover.py")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Tier 0 prospects with real 24-char Apollo person IDs"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_seed(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
