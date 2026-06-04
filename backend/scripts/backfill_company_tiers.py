"""Null-tier cleanup script (P3.1 — GTM rebuild 2026-05-08).

For every company where companies.tier IS NULL:
  1. Try to enrich firmographics via Apollo if naics_code is also missing
  2. Classify the NAICS code through icp.yaml's manufacturer subsectors
  3. Score and assign a tier (mfg1..mfg8, pmfg1..pmfg8, fb_*) when the
     NAICS prefix matches the ICP allowlist
  4. Companies still unclassified after enrichment → tier='non_mfg'

Default mode is dry-run. Pass --apply to actually persist changes.

Usage:
  python -m backend.scripts.backfill_company_tiers
  python -m backend.scripts.backfill_company_tiers --apply
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from backend.app.core.config import get_icp_config
from backend.app.core.database import Database
from backend.app.utils.naics import classify_sub_sector

logger = logging.getLogger(__name__)


def _icp_naics_index() -> dict[str, dict]:
    """Build a {naics_prefix → tier_config} lookup from icp.yaml."""
    icp = get_icp_config()
    out: dict[str, dict] = {}
    for industry in icp.get("company_filters", {}).get("industries", []):
        prefix = industry.get("naics_prefix")
        if prefix:
            out[str(prefix)] = industry
    return out


def _classify_company(company: dict, icp_index: dict[str, dict]) -> tuple[str | None, str]:
    """Return (tier, reason) for a company.

    Walks the NAICS code from longest prefix to shortest, returning the first
    match in the ICP allowlist. When nothing matches, returns ('non_mfg', ...).
    """
    naics = (company.get("naics_code") or "").strip()
    if not naics:
        # Try fallback via the manufacturing ontology
        result = classify_sub_sector(None, company.get("industry"))
        if result.get("tier"):
            return result["tier"], "industry_keyword_match"
        return "non_mfg", "no_naics_no_industry_match"

    # Try ICP prefixes longest → shortest (ICP keys are 3- or 4-char prefixes)
    for length in (4, 3):
        prefix = naics[:length]
        if prefix in icp_index:
            return icp_index[prefix].get("tier"), f"naics_prefix_match:{prefix}"

    # Fallback: ontology classifier (returns labels like 1a/1b/etc., which
    # we treat as still-manufacturing → set non_mfg only if it returns nothing)
    result = classify_sub_sector(naics, company.get("industry"))
    if result.get("tier"):
        return result["tier"], "ontology_match"

    return "non_mfg", "no_match_in_icp_or_ontology"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill null company.tier values")
    parser.add_argument("--apply", action="store_true", help="Persist changes (default is dry-run)")
    parser.add_argument(
        "--limit", type=int, default=10000, help="Max companies to process (default 10000)"
    )
    args = parser.parse_args()

    workspace_id = os.environ.get("WORKSPACE_ID") or "00000000-0000-0000-0000-000000000001"
    db = Database(workspace_id=workspace_id)
    icp_index = _icp_naics_index()
    print(f"ICP NAICS prefixes loaded: {sorted(icp_index)}")

    rows: list[dict] = []
    offset = 0
    page = 1000
    while len(rows) < args.limit:
        chunk = (
            db.client.table("companies")
            .select("id, name, naics_code, industry, tier, status")
            .eq("workspace_id", db.workspace_id)
            .is_("tier", "null")
            .range(offset, offset + page - 1)
            .execute()
            .data
            or []
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page

    rows = rows[: args.limit]
    print(
        f"\nFound {len(rows)} companies with tier IS NULL "
        f"(workspace={db.workspace_id}, limit={args.limit})"
    )

    counts: dict[str, int] = {}
    updates: list[tuple[str, str | None, str]] = []
    for c in rows:
        tier, reason = _classify_company(c, icp_index)
        counts[tier or "(none)"] = counts.get(tier or "(none)", 0) + 1
        updates.append((c["id"], tier, reason))
        print(f"  {c.get('name', '?')}: tier null → {tier} ({reason}; naics={c.get('naics_code')})")

    print("\n== Tier assignment summary ==")
    for tier, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {tier:<20} {n}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to persist changes.")
        return 0

    applied = 0
    for cid, tier, reason in updates:
        try:
            db.client.table("companies").update(
                {
                    "tier": tier,
                    # Stamp a backfill marker into the audit log via interactions
                    # is too heavy here — keep it simple: just write the tier.
                }
            ).eq("id", cid).execute()
            applied += 1
        except Exception as exc:
            logger.error("Failed to update company %s: %s", cid, exc)

    print(f"\nApplied {applied}/{len(updates)} updates.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
