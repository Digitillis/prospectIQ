#!/usr/bin/env python3
"""Seed ProspectIQ Supabase DB with Tier 0 prospects from the curated markdown lists.

Reads:
  - docs/commercial/gtm/PROSPECT_LIST_MFG.md  → tier=mfg1 (17 companies)
  - docs/commercial/gtm/PROSPECT_LIST_FB.md   → tier=fb1  (14 companies)

Inserts company + contact records into Supabase so the Prospects page shows
Tier 0 accounts and the enrichment / outreach pipeline can act on them.

Note: Apollo IDs in the markdown are truncated (e.g. "6896ea...").  They are
stored as-is for deduplication but are NOT sufficient to call Apollo's
/people/match enrichment endpoint — full 24-char IDs are required.  Run
enrichment via the ProspectIQ UI or Apollo directly to obtain full emails.

Usage (from prospectIQ/backend/):
    python -m scripts.import_tier0
    python -m scripts.import_tier0 --dry-run
    python -m scripts.import_tier0 --vertical mfg   # only MFG
    python -m scripts.import_tier0 --vertical fb    # only F&B
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running from the backend/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.database import Database

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3] / "digitillis-platform"
MFG_LIST  = REPO_ROOT / "docs" / "commercial" / "gtm" / "PROSPECT_LIST_MFG.md"
FB_LIST   = REPO_ROOT / "docs" / "commercial" / "gtm" / "PROSPECT_LIST_FB.md"

# ---------------------------------------------------------------------------
# Persona classification (mirrors discovery.py)
# ---------------------------------------------------------------------------

def classify_persona(title: str) -> tuple[str, bool]:
    """Return (persona_type, is_decision_maker) from a job title string."""
    t = title.lower()
    if any(x in t for x in ["chief executive", " ceo"]):
        return "c_suite", True
    if any(x in t for x in ["chief operating", " coo"]):
        return "c_suite", True
    if any(x in t for x in ["chief technology", " cto"]):
        return "c_suite", True
    if "food safety" in t and any(x in t for x in ["vp", "vice president", "svp", "evp"]):
        return "vp_food_safety", True
    if "quality" in t and any(x in t for x in ["vp", "vice president", "svp", "evp"]):
        return "vp_quality", True
    if any(x in t for x in ["vp operations", "vice president operations", "vp ops"]):
        return "vp_ops", True
    if any(x in t for x in ["vp manufacturing", "vice president manufacturing"]):
        return "vp_mfg", True
    if any(x in t for x in ["vp engineering", "vice president engineering"]):
        return "vp_eng", True
    if any(x in t for x in ["svp", "evp", "senior vice president", "executive vice president"]):
        return "vp_ops", True
    if any(x in t for x in ["vice president", " vp "]) or t.startswith("vp "):
        return "vp_ops", True
    if "food safety" in t and "dir" in t:
        return "director_food_safety", True
    if "quality" in t and "dir" in t:
        return "director_quality", True
    if any(x in t for x in ["dir. ops", "director ops", "director operations", "dir. operations"]):
        return "director_ops", True
    if any(x in t for x in ["dir. mfg", "director mfg", "director manufacturing", "dir. manufacturing"]):
        return "director_mfg", True
    if any(x in t for x in ["dir. eng", "director eng", "director engineering", "dir. engineering"]):
        return "director_eng", True
    if "director" in t or t.startswith("dir."):
        return "director_ops", True
    if any(x in t for x in ["plant manager", "gm", "general manager"]):
        return "plant_manager", True
    return "other", False

# ---------------------------------------------------------------------------
# Markdown parser — extracts Tier 0 table rows
# ---------------------------------------------------------------------------

# Matches a contact entry like:  Michael — Dir. Ops (6896ea...)
_CONTACT_RE = re.compile(
    r"([A-Z][a-zA-Z\-]+)"        # First name (capitalised)
    r"\s*[—–-]\s*"               # dash separator
    r"([^(]+?)"                  # title (greedy up to open paren)
    r"\s*\(([a-f0-9]{4,8}\.{3})\)"  # partial Apollo ID like (6896ea...)
)


def _parse_tier0_table(md_path: Path) -> list[dict]:
    """Parse the ## Tier 0 table from a prospect markdown file.

    Returns a list of company dicts, each with a 'contacts' list.
    """
    text = md_path.read_text(encoding="utf-8")
    companies: list[dict] = []

    in_tier0 = False
    for line in text.splitlines():
        stripped = line.strip()

        # Section detection
        if stripped.startswith("## "):
            section = stripped.lstrip("#").strip().lower()
            in_tier0 = "tier 0" in section or "multi-contact" in section
            continue

        if not in_tier0:
            continue

        # Table rows only
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| #") or stripped.startswith("|---"):
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue

        company_name = cells[1].strip().strip("*")
        if not company_name or company_name in ("#", "Company"):
            continue

        decision_makers_cell = cells[3].strip() if len(cells) > 3 else ""
        why_cell = cells[4].strip() if len(cells) > 4 else ""

        # Parse individual contacts from the decision_makers cell
        contacts: list[dict] = []
        for m in _CONTACT_RE.finditer(decision_makers_cell):
            first_name  = m.group(1).strip()
            title       = m.group(2).strip().rstrip(",")
            partial_id  = m.group(3).strip()  # e.g. "6896ea..."
            persona, is_dm = classify_persona(title)
            contacts.append({
                "first_name":        first_name,
                "title":             title,
                "apollo_id":         partial_id,   # truncated — enrichment needed
                "persona_type":      persona,
                "is_decision_maker": is_dm,
            })

        companies.append({
            "name":     company_name,
            "why":      why_cell,
            "contacts": contacts,
        })

    return companies


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------

def _get_or_create_company(db: Database, name: str, tier: str, industry: str,
                            campaign_name: str, notes: str, dry_run: bool) -> dict | None:
    """Return existing company or insert a new one.  Returns the company row."""
    # Dedup by exact name (case-insensitive search)
    existing = db.get_companies(search=name, limit=5)
    for row in existing:
        if row["name"].strip().lower() == name.strip().lower():
            print(f"    ↩  {name} already in DB (id={row['id'][:8]}...)")
            return row

    data = {
        "name":          name,
        "tier":          tier,
        "industry":      industry,
        "status":        "discovered",
        "campaign_name": campaign_name,
    }
    if dry_run:
        print(f"    [DRY-RUN] would insert company: {name} (tier={tier})")
        return None

    row = db.insert_company(data)
    print(f"    ✅ Inserted company: {name} (id={row.get('id', '?')[:8]}...)")
    return row


def _get_or_create_contact(db: Database, company_id: str, contact: dict,
                            dry_run: bool) -> dict | None:
    """Return existing contact or insert a new one."""
    partial_id = contact["apollo_id"]

    # Dedup by partial apollo_id stored at import time
    existing = db.get_contact_by_apollo_id(partial_id)
    if existing:
        print(f"      ↩  {contact['first_name']} ({partial_id}) already in DB")
        return existing

    data = {
        "company_id":        company_id,
        "first_name":        contact["first_name"],
        "last_name":         "",
        "title":             contact["title"],
        "apollo_id":         partial_id,
        "persona_type":      contact["persona_type"],
        "is_decision_maker": contact["is_decision_maker"],
        # email/phone not yet known — needs enrichment via Apollo
    }
    if dry_run:
        print(f"      [DRY-RUN] would insert: {contact['first_name']} — {contact['title']} ({partial_id})")
        return None

    row = db.insert_contact(data)
    print(f"      ✅ {contact['first_name']} — {contact['title']} ({partial_id})")
    return row


def run_import(verticals: list[str], dry_run: bool) -> None:
    db = Database()

    sources = []
    if "mfg" in verticals:
        sources.append((MFG_LIST, "mfg1", "Discrete Manufacturing", "tier0-mfg-pdm-roi"))
    if "fb" in verticals:
        sources.append((FB_LIST, "fb1", "Food & Beverage", "tier0-fb-fsma"))

    total_companies = 0
    total_contacts  = 0

    for md_path, tier, industry, campaign_name in sources:
        if not md_path.exists():
            print(f"⚠️  File not found: {md_path}")
            continue

        print(f"\n{'='*60}")
        print(f"  {md_path.name}  →  tier={tier}, industry={industry}")
        print(f"{'='*60}")

        companies = _parse_tier0_table(md_path)
        print(f"  Parsed {len(companies)} Tier 0 companies from markdown\n")

        for co in companies:
            print(f"  🏭  {co['name']} ({len(co['contacts'])} contacts)")
            co_row = _get_or_create_company(
                db, co["name"], tier, industry, campaign_name, co["why"], dry_run
            )
            if co_row is None and not dry_run:
                continue  # insert failed

            company_id = co_row["id"] if co_row else "dry-run"
            total_companies += 1

            for contact in co["contacts"]:
                result = _get_or_create_contact(db, company_id, contact, dry_run)
                if result is not None or dry_run:
                    total_contacts += 1

    print(f"\n{'='*60}")
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"  {prefix}Done — {total_companies} companies, {total_contacts} contacts")
    if not dry_run:
        print(f"\n  Next steps:")
        print(f"  1. Open crm.digitillis.com/prospects and filter by tier=mfg1 / fb1")
        print(f"  2. Run enrichment in the CRM (Actions → Run Enrichment) to fetch")
        print(f"     full emails via Apollo credits (~April 14, after warmup completes)")
        print(f"  3. Lower Instantly daily limit to 10 before first send")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Import Tier 0 prospects into ProspectIQ Supabase DB")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be inserted without writing")
    parser.add_argument(
        "--vertical",
        choices=["mfg", "fb", "both"],
        default="both",
        help="Which vertical to import (default: both)",
    )
    args = parser.parse_args()

    verticals = ["mfg", "fb"] if args.vertical == "both" else [args.vertical]
    run_import(verticals=verticals, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
