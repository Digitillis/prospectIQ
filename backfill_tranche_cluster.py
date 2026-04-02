"""Backfill tranche, campaign_cluster, and outreach_mode for all existing companies.

Run AFTER applying supabase_migrations/migrations/014_tranche_campaign_cluster.sql.

Logic mirrors backend/app/agents/discovery.py.
"""
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(".env"))

from typing import Optional
from backend.app.core.database import Database

# ---------------------------------------------------------------------------
# Cluster mapping (mirrors _TIER_TO_CLUSTER in discovery.py)
# ---------------------------------------------------------------------------
_TIER_TO_CLUSTER: dict[str, str] = {
    "mfg1": "machinery",
    "mfg2": "machinery",
    "mfg4": "machinery",
    "mfg5": "machinery",
    "mfg8": "machinery",
    "mfg3": "auto",
    "mfg7": "metals",
    "mfg6": "other",    # Aerospace — watchlist (excluded from auto outreach)
    "pmfg1": "chemicals",
    "pmfg3": "process",
    "pmfg4": "process",
    "pmfg7": "process",
    "pmfg8": "process",
    "pmfg2": "other",   # Oil & Gas — watchlist
    "pmfg5": "other",   # Utilities — watchlist
    "pmfg6": "other",   # Pharma — watchlist
    "fb1": "fb",
    "fb2": "fb",
    "fb3": "fb",
    "fb4": "fb",
    "fb5": "fb",
}


def _assign_tranche(employee_count: Optional[int], revenue: Optional[float] = None) -> Optional[str]:
    if revenue:
        if revenue < 400_000_000:
            return "T1"
        elif revenue < 1_000_000_000:
            return "T2"
        else:
            return "T3"
    if employee_count:
        if employee_count <= 1000:
            return "T1"
        elif employee_count <= 3000:
            return "T2"
        else:
            return "T3"
    return None


def main():
    db = Database()

    PAGE = 1000
    offset = 0
    total_fetched = 0
    updated = 0
    skipped = 0

    print("Starting tranche + campaign_cluster + outreach_mode backfill...")

    while True:
        result = (
            db.client.table("companies")
            .select("id, tier, employee_count, estimated_revenue, tranche, campaign_cluster, outreach_mode")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        rows = result.data
        if not rows:
            break

        total_fetched += len(rows)

        for row in rows:
            company_id = row["id"]
            tier = row.get("tier")
            employee_count = row.get("employee_count")
            estimated_revenue = row.get("estimated_revenue")

            new_cluster = _TIER_TO_CLUSTER.get(tier) if tier else None

            # "other" cluster = watchlist tier — manual review, no auto outreach
            if new_cluster == "other":
                new_tranche = "watchlist"
                new_outreach_mode = "manual"
            else:
                new_tranche = _assign_tranche(employee_count, estimated_revenue)
                new_outreach_mode = "auto"

            # Skip if nothing to update
            patch: dict = {}
            if new_tranche is not None and row.get("tranche") != new_tranche:
                patch["tranche"] = new_tranche
            if new_cluster is not None and row.get("campaign_cluster") != new_cluster:
                patch["campaign_cluster"] = new_cluster
            if row.get("outreach_mode") != new_outreach_mode:
                patch["outreach_mode"] = new_outreach_mode

            if not patch:
                skipped += 1
                continue

            db.client.table("companies").update(patch).eq("id", company_id).execute()
            updated += 1

        if len(rows) < PAGE:
            break
        offset += PAGE

    print(f"\nDone.")
    print(f"  Fetched:  {total_fetched}")
    print(f"  Updated:  {updated}")
    print(f"  Skipped:  {skipped}")

    # Distribution summary
    tranche_counts: dict[str, int] = {}
    cluster_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    offset = 0
    while True:
        result = (
            db.client.table("companies")
            .select("tranche, campaign_cluster, outreach_mode")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        if not result.data:
            break
        for row in result.data:
            t  = row.get("tranche")         or "NULL"
            cc = row.get("campaign_cluster") or "NULL"
            om = row.get("outreach_mode")    or "NULL"
            tranche_counts[t]  = tranche_counts.get(t, 0)  + 1
            cluster_counts[cc] = cluster_counts.get(cc, 0) + 1
            mode_counts[om]    = mode_counts.get(om, 0)    + 1
        if len(result.data) < PAGE:
            break
        offset += PAGE

    print(f"\nTranche:  {dict(sorted(tranche_counts.items()))}")
    print(f"Cluster:  {dict(sorted(cluster_counts.items()))}")
    print(f"Mode:     {dict(sorted(mode_counts.items()))}")


if __name__ == "__main__":
    main()
