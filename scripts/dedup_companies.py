#!/usr/bin/env python3
"""Deduplicate companies within a workspace.

Groups companies by exact name (case-insensitive) and merges each group
into one canonical row. Child records (contacts, outreach_drafts,
interactions, engagement_sequences, api_costs, learning_outcomes,
research_intelligence) are re-pointed to the winner before the
duplicates are deleted.

Winner selection priority:
  1. Highest pipeline status (contacted > outreach_pending > qualified > researched > discovered)
  2. Highest pqs_total
  3. Most recently created

Usage:
    python3 scripts/dedup_companies.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import get_supabase_client

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

STATUS_RANK = {
    "contacted": 7,
    "engaged": 6,
    "outreach_pending": 5,
    "qualified": 4,
    "researched": 3,
    "discovered": 2,
    "disqualified": 1,
    "paused": 0,
}

# Tables to re-point before deleting duplicate company rows.
# Format: (table_name, column_name)
CHILD_TABLES = [
    ("contacts",             "company_id"),
    ("outreach_drafts",      "company_id"),
    ("interactions",         "company_id"),
    ("engagement_sequences", "company_id"),
    ("api_costs",            "company_id"),
    ("learning_outcomes",    "company_id"),
    ("research_intelligence","company_id"),
    ("action_queue",         "company_id"),
    ("contact_events",       "company_id"),
]


def pick_winner(rows: list[dict]) -> dict:
    """Return the canonical row from a group of duplicate companies."""
    def sort_key(r):
        status_score = STATUS_RANK.get(r.get("status", "discovered"), 2)
        pqs = r.get("pqs_total") or 0
        created = r.get("created_at") or ""
        return (status_score, pqs, created)

    return max(rows, key=sort_key)


def merge_winner_fields(winner: dict, losers: list[dict]) -> dict:
    """Merge non-null fields from losers into winner (winner fields take priority)."""
    updates = {}
    enrichable = [
        "domain", "website", "linkedin_url", "phone", "employee_count",
        "revenue_range", "research_summary", "technology_stack", "pain_signals",
        "personalization_hooks",
    ]
    for field in enrichable:
        if not winner.get(field):
            for loser in losers:
                if loser.get(field):
                    updates[field] = loser[field]
                    break
    return updates


def run(dry_run: bool) -> None:
    client = get_supabase_client()

    print(f"{'[DRY-RUN] ' if dry_run else ''}Fetching companies in workspace {WORKSPACE_ID}...")
    result = (
        client.table("companies")
        .select("id,name,tier,status,pqs_total,domain,campaign_name,created_at,"
                "research_summary,technology_stack,pain_signals,personalization_hooks,"
                "employee_count,revenue_range,linkedin_url,website,phone")
        .eq("workspace_id", WORKSPACE_ID)
        .limit(10000)
        .execute()
    )
    companies = result.data or []
    print(f"  Total rows: {len(companies)}")

    # Group by lowercased name
    by_name: dict[str, list[dict]] = defaultdict(list)
    for co in companies:
        key = co["name"].strip().lower()
        by_name[key].append(co)

    dupe_groups = {k: v for k, v in by_name.items() if len(v) > 1}
    print(f"  Unique names: {len(by_name)}")
    print(f"  Names with duplicates: {len(dupe_groups)}")
    print(f"  Rows to delete: {sum(len(v) - 1 for v in dupe_groups.values())}")
    print()

    total_repointed = 0
    total_deleted = 0
    errors = 0

    for name_key, rows in sorted(dupe_groups.items(), key=lambda x: -len(x[1])):
        winner = pick_winner(rows)
        losers = [r for r in rows if r["id"] != winner["id"]]
        loser_ids = [r["id"] for r in losers]

        print(f"  Merging {rows[0]['name']!r} x{len(rows)} → keep {winner['id'][:8]}... (status={winner['status']}, pqs={winner['pqs_total']})")

        # Merge enrichment fields from losers into winner
        field_updates = merge_winner_fields(winner, losers)
        if field_updates and not dry_run:
            try:
                client.table("companies").update(field_updates).eq("id", winner["id"]).execute()
            except Exception as e:
                print(f"    WARNING: could not merge fields into winner: {e}")

        # Re-point child records from each loser to winner
        for loser_id in loser_ids:
            for table, col in CHILD_TABLES:
                try:
                    if not dry_run:
                        client.table(table).update({col: winner["id"]}).eq(col, loser_id).execute()
                    total_repointed += 1
                except Exception as e:
                    # Table may not exist or loser had no children — non-fatal
                    if "does not exist" not in str(e).lower():
                        print(f"    WARNING: repoint {table}.{col} {loser_id[:8]}→{winner['id'][:8]}: {e}")

        # Delete loser rows
        if not dry_run:
            try:
                client.table("companies").delete().in_("id", loser_ids).execute()
                total_deleted += len(loser_ids)
            except Exception as e:
                print(f"    ERROR deleting losers for {rows[0]['name']!r}: {e}")
                errors += 1
        else:
            total_deleted += len(loser_ids)

    print()
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}Done.")
    print(f"  Companies deleted: {total_deleted}")
    print(f"  Child table re-points: {total_repointed}")
    print(f"  Errors: {errors}")

    if not dry_run:
        # Final count
        final = client.table("companies").select("id", count="exact").eq("workspace_id", WORKSPACE_ID).execute()
        print(f"  Companies remaining: {final.count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
