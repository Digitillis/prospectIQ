"""Seed the 8 named F&B target companies from the FSMA 204 playbook.

These companies are pre-validated against the ICP; seeding them directly avoids
burning Apollo credits on companies we already know are targets.

Run from the prospectIQ root:
    python scripts/seed_fb_named_companies.py

Each company is inserted with:
  - status = "discovered" (enters the normal enrichment pipeline)
  - campaign_name = "fsma204-fb"
  - tier and campaign_cluster per sub-segment
  - fsma_exposure based on FTL coverage
  - enrichment_status = "pending" (enrichment agent will fill Apollo data)
"""

from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
CAMPAIGN = "fsma204-fb"

# Pre-validated F&B targets from the FSMA 204 ICP playbook.
# Revenue estimates from Owler / PitchBook — verify before outreach.
NAMED_COMPANIES = [
    {
        "name": "Crystal Creamery",
        "domain": "crystalcreamery.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Dairy Processing — Fluid Milk",
        "industry": "dairy",
        "hq_state": "CA",
        "employee_count": 500,
        "revenue_range": "$200M-$300M",
        "notes": "Private CA dairy; HTST pasteurizer-heavy; multi-plant",
        "priority": "T1",
    },
    {
        "name": "Stonyfield Organic",
        "domain": "stonyfield.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Dairy Processing — Yogurt",
        "industry": "dairy",
        "hq_state": "NH",
        "employee_count": 350,
        "revenue_range": "$150M-$300M",
        "notes": "Organic; strong food safety culture; FSMA-conscious buyer",
        "priority": "T1",
    },
    {
        "name": "Pacific Coast Producers",
        "domain": "pcpacking.com",
        "tier": "fb_produce",
        "campaign_cluster": "fsma_produce",
        "fsma_exposure": "high",
        "sub_sector": "Fruit and Vegetable Processing — Canned/Cooperative",
        "industry": "food production",
        "hq_state": "CA",
        "employee_count": 600,
        "revenue_range": "$150M-$250M",
        "notes": "FTL exposure (tomatoes, produce); cooperative buying structure",
        "priority": "T1",
    },
    {
        "name": "Bob Evans Farms",
        "domain": "bobevans.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Refrigerated Dairy and Meal Kits",
        "industry": "food production",
        "hq_state": "OH",
        "employee_count": 2500,
        "revenue_range": "$300M-$400M",
        "notes": "Post-acquisition; new ownership = new technology appetite",
        "priority": "T2",
    },
    {
        "name": "Berner Food and Beverage",
        "domain": "bernercheese.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Dairy Processing — Co-manufacturer",
        "industry": "dairy",
        "hq_state": "WI",
        "employee_count": 300,
        "revenue_range": "$75M-$100M",
        "notes": "Private label co-manufacturer; multiple FTL-covered products",
        "priority": "T1",
    },
    {
        "name": "Litehouse Foods",
        "domain": "litehousefoods.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Dairy Processing — Dressings and Dips",
        "industry": "food production",
        "hq_state": "ID",
        "employee_count": 700,
        "revenue_range": "$200M-$300M",
        "notes": "Private family-owned; refrigerated; sustainability-focused buyer",
        "priority": "T1",
    },
    {
        "name": "Inventure Foods",
        "domain": "inventurefoods.com",
        "tier": "fb_bakery",
        "campaign_cluster": "fsma_bakery",
        "fsma_exposure": "low",
        "sub_sector": "Snack Food Manufacturing",
        "industry": "food & beverages",
        "hq_state": "AZ",
        "employee_count": 1200,
        "revenue_range": "$200M-$300M",
        "notes": "Multiple plants; Boulder Canyon, Jamba brands; allergen changeover wedge",
        "priority": "T2",
    },
    {
        "name": "Prairie Farms Dairy",
        "domain": "prairiefarms.com",
        "tier": "fb_dairy",
        "campaign_cluster": "fsma_dairy",
        "fsma_exposure": "high",
        "sub_sector": "Dairy Processing — Regional Cooperative",
        "industry": "dairy",
        "hq_state": "IL",
        "employee_count": 3000,
        "revenue_range": "$2B-$3B",
        "notes": "Regional Dean Foods successor; cooperative; rebuilding post-consolidation",
        "priority": "T2",
    },
]


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    inserted = 0
    skipped = 0

    for co in NAMED_COMPANIES:
        name = co["name"]
        domain = co.get("domain", "")

        # Dedup check — skip if already in DB by domain or name
        existing = None
        if domain:
            r = sb.table("companies").select("id,name").eq("domain", domain).limit(1).execute()
            existing = r.data[0] if r.data else None
        if not existing:
            r = sb.table("companies").select("id,name").ilike("name", f"%{name[:30]}%").limit(1).execute()
            existing = r.data[0] if r.data else None

        if existing:
            logger.info("SKIP  %s — already in DB (%s)", name, existing["id"])
            skipped += 1
            continue

        pqs = _firmographic_score(co)
        row = {
            "workspace_id": WORKSPACE_ID,
            "name": name,
            "domain": domain,
            "tier": co["tier"],
            "campaign_cluster": co["campaign_cluster"],
            "fsma_exposure": co["fsma_exposure"],
            "sub_sector": co.get("sub_sector"),
            "industry": co.get("industry"),
            "state": co.get("hq_state"),
            "employee_count": co.get("employee_count"),
            "revenue_range": co.get("revenue_range"),
            "status": "discovered",
            "campaign_name": CAMPAIGN,
            "outreach_mode": "auto",
            "tranche": co.get("priority", "T1"),
            "custom_tags": {
                "source": "playbook_seed",
                "notes": co.get("notes", ""),
            },
            "pqs_firmographic": pqs,
            "pqs_total": pqs,
        }

        try:
            result = sb.table("companies").insert(row).execute()
            company_id = result.data[0]["id"] if result.data else "?"
            logger.info("INSERT %s → %s (tier=%s, pqs=%d)",
                        name, company_id, co["tier"], row["pqs_firmographic"])
            inserted += 1
        except Exception as e:
            logger.error("FAIL   %s: %s", name, e)

    print(f"\nDone: {inserted} inserted, {skipped} skipped (already in DB)")


def _firmographic_score(co: dict) -> int:
    """Simple firmographic score for seed companies.

    Uses known revenue and FSMA exposure rather than Apollo-derived data.
    Enrichment agent will recompute once Apollo data arrives.
    """
    score = 0
    # Employee count proxy (40 pts max)
    ec = co.get("employee_count", 0)
    if ec >= 500:
        score += 35
    elif ec >= 200:
        score += 28
    elif ec >= 100:
        score += 20
    else:
        score += 12

    # FSMA exposure (15 pts max) — direct FTL coverage = higher score
    fsma = co.get("fsma_exposure", "low")
    if fsma == "high":
        score += 15
    elif fsma == "medium":
        score += 10
    else:
        score += 5

    # Priority tranche (10 pts max)
    if co.get("priority") == "T1":
        score += 10
    else:
        score += 6

    return min(score, 60)


if __name__ == "__main__":
    main()
