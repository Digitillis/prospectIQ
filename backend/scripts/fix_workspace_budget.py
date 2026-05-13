"""Raise workspace monthly_api_budget_usd to unblock pipeline.

The workspace budget cap defaults to $200. May 2026 spend hit $242, causing
workspace_budget_ok() to return False and blocking all research/enrichment
discovery runs when they are re-enabled.

Run BEFORE re-enabling research/enrichment/pipeline_advance in main.py.

Usage:
    python -m backend.scripts.fix_workspace_budget [--budget 350] [--dry-run]
"""

import argparse
import json
import sys

from backend.app.core.database import get_supabase_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Raise workspace monthly API budget cap")
    parser.add_argument("--budget", type=float, default=350.0, help="New monthly budget in USD (default: 350)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing")
    args = parser.parse_args()

    client = get_supabase_client()

    rows = client.table("workspaces").select("id,name,settings").execute().data or []
    if not rows:
        print("No workspaces found.", file=sys.stderr)
        sys.exit(1)

    for ws in rows:
        ws_id = ws["id"]
        ws_name = ws.get("name", ws_id)
        settings = ws.get("settings") or {}
        current_budget = float(settings.get("monthly_api_budget_usd", 200.0))

        if current_budget >= args.budget:
            print(f"  {ws_name}: budget already ${current_budget:.2f} — no change needed")
            continue

        new_settings = {**settings, "monthly_api_budget_usd": args.budget}
        print(f"  {ws_name}: ${current_budget:.2f} → ${args.budget:.2f}", end="")

        if args.dry_run:
            print("  [dry-run — not written]")
            continue

        client.table("workspaces").update({"settings": json.dumps(new_settings)}).eq("id", ws_id).execute()
        print("  [updated]")

    if not args.dry_run:
        print("\nDone. Re-run workspace_budget_ok() to confirm the new cap takes effect.")


if __name__ == "__main__":
    main()
