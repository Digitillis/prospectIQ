"""Run research on a filtered set of companies directly (no server needed).

Usage:
    # Research all discovered fb1 companies (limit 50)
    python run_research.py --tier fb1 --limit 50

    # Research all discovered 1a companies
    python run_research.py --tier 1a --limit 99

    # Multiple tiers
    python run_research.py --tiers fb1 fb2 fb3 --limit 100

    # Specific company IDs
    python run_research.py --ids "uuid-1" "uuid-2" "uuid-3"

    # Dry run — show what WOULD be researched without calling APIs
    python run_research.py --tier fb1 --limit 50 --dry-run

Requires .env with SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY.
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from backend.app.agents.research import ResearchAgent


def main():
    parser = argparse.ArgumentParser(description="Run ProspectIQ research agent")
    parser.add_argument("--tier", type=str, help="Single tier filter (e.g. fb1, 1a)")
    parser.add_argument("--tiers", nargs="+", help="Multiple tier filters (e.g. fb1 fb2)")
    parser.add_argument("--ids", nargs="+", help="Specific company IDs")
    parser.add_argument("--batch-id", type=str, help="Batch ID filter")
    parser.add_argument("--min-score", type=int, help="Minimum firmographic score")
    parser.add_argument("--limit", type=int, default=50, help="Max companies (default 50)")
    parser.add_argument("--dry-run", action="store_true", help="Show companies without researching")
    args = parser.parse_args()

    if args.dry_run:
        # Just query and display — no API calls
        from backend.app.core.database import Database

        db = Database()
        tier_list = list(args.tiers) if args.tiers else []
        if args.tier and args.tier not in tier_list:
            tier_list.append(args.tier)

        if args.ids:
            companies = [db.get_company(cid) for cid in args.ids]
            companies = [c for c in companies if c]
        elif tier_list:
            companies = []
            for t in tier_list:
                remaining = args.limit - len(companies)
                if remaining <= 0:
                    break
                companies.extend(
                    db.get_companies(status="discovered", tier=t, limit=remaining)
                )
        else:
            companies = db.get_companies(status="discovered", limit=args.limit)

        print(f"\n{'='*60}")
        print(f"DRY RUN — {len(companies)} companies would be researched:")
        print(f"{'='*60}")
        for i, c in enumerate(companies, 1):
            print(f"  {i:3d}. {c['name']:<40s}  tier={c.get('tier','?'):<5s}  pqs={c.get('pqs_total', 0)}")
        print(f"\nTo actually research, remove --dry-run")
        return

    agent = ResearchAgent()
    result = agent.execute(
        company_ids=args.ids,
        batch_id=args.batch_id,
        min_firmographic_score=args.min_score,
        tier=args.tier,
        tiers=args.tiers,
        limit=args.limit,
    )

    print(f"\n{'='*60}")
    print(f"Research complete: {result.summary()}")
    print(f"  Processed: {result.processed}")
    print(f"  Skipped:   {result.skipped}")
    print(f"  Errors:    {result.errors}")
    print(f"  Cost:      ${result.total_cost_usd:.4f}")
    print(f"  Duration:  {result.duration_seconds:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
