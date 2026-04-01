"""Dry run — send approved drafts to your own inbox via Instantly.

Picks N approved+unsent drafts and fires them through the real Instantly
campaign (mfg-vp-ops / mfg-plant-manager etc.) but overrides the recipient
email to YOUR_TEST_EMAIL so nothing goes to real prospects.

Usage:
    python3 scripts/dry_run_send.py --email avi@digitillis.com --count 3
    python3 scripts/dry_run_send.py --email avi@digitillis.com --count 3 --cluster machinery
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.core.database import Database
from backend.app.integrations.instantly import InstantlyClient

# Same routing table as engagement agent
_CAMPAIGN_ROUTE: dict[tuple[str, str], str] = {
    ("machinery", "vp_ops"):        "mfg-vp-ops",
    ("machinery", "plant_manager"): "mfg-plant-manager",
    ("machinery", "director_ops"):  "mfg-director-ops",
    ("auto",      "vp_ops"):        "mfg-vp-ops",
    ("auto",      "plant_manager"): "mfg-plant-manager",
    ("metals",    "vp_ops"):        "mfg-vp-ops",
    ("metals",    "plant_manager"): "mfg-plant-manager",
    ("process",   "vp_ops"):        "mfg-vp-ops",
    ("process",   "plant_manager"): "mfg-plant-manager",
    ("chemicals", "vp_ops"):        "mfg-vp-ops",
    ("chemicals", "plant_manager"): "mfg-plant-manager",
    ("fb",        "vp_ops"):        "fb-vp-ops",
    ("fb",        "plant_manager"): "fb-maintenance",
    ("fb",        "maintenance_leader"): "fb-maintenance",
}
_FALLBACK = "mfg-general"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Your test inbox (e.g. avi@digitillis.com)")
    parser.add_argument("--count", type=int, default=3, help="Number of drafts to dry-run")
    parser.add_argument("--cluster", default=None, help="Filter by campaign_cluster (e.g. machinery)")
    args = parser.parse_args()

    db = Database()

    query = (
        db.client.table("outreach_drafts")
        .select(
            "id, subject, body, edited_body, sequence_name, sequence_step, "
            "companies(name, campaign_cluster), "
            "contacts(full_name, first_name, last_name, persona_type, title)"
        )
        .eq("approval_status", "approved")
        .is_("sent_at", "null")
        .order("created_at")
        .limit(args.count * 5)  # fetch more, filter below
    )
    drafts = query.execute().data or []

    if args.cluster:
        drafts = [
            d for d in drafts
            if (d.get("companies") or {}).get("campaign_cluster", "").lower() == args.cluster.lower()
        ]

    drafts = drafts[:args.count]

    if not drafts:
        print("No approved drafts found matching criteria.")
        return

    with InstantlyClient() as instantly:
        campaigns = instantly.list_campaigns()
        campaign_name_to_id = {
            c.get("name"): c.get("id") for c in campaigns if c.get("name") and c.get("id")
        }

        print(f"\n{'='*60}")
        print(f"DRY RUN — sending {len(drafts)} email(s) to {args.email}")
        print(f"{'='*60}\n")

        sent = 0
        for draft in drafts:
            company = draft.get("companies") or {}
            contact = draft.get("contacts") or {}
            company_name = company.get("name", "Unknown")
            cluster = (company.get("campaign_cluster") or "other").lower()
            persona = (contact.get("persona_type") or "").lower()

            route_key = (cluster, persona)
            campaign_name = (
                _CAMPAIGN_ROUTE.get(route_key)
                or _CAMPAIGN_ROUTE.get((cluster, "vp_ops"))
                or _FALLBACK
            )
            campaign_id = campaign_name_to_id.get(campaign_name)

            subject = draft.get("subject", "")
            body = draft.get("edited_body") or draft.get("body", "")

            print(f"Draft:    {draft['id'][:8]}")
            print(f"Company:  {company_name}  [{cluster} / {persona}]")
            print(f"Contact:  {contact.get('full_name', '?')} ({contact.get('title', '?')})")
            print(f"Campaign: {campaign_name}")
            print(f"Subject:  {subject}")
            print(f"Body preview:\n{'—'*40}")
            print(body[:300] + ("..." if len(body) > 300 else ""))
            print(f"{'—'*40}")

            if not campaign_id:
                print(f"  ⚠ Campaign '{campaign_name}' not found in Instantly. Skipping.\n")
                continue

            lead = {
                "email": args.email,          # override — goes to YOU, not the prospect
                "first_name": "Avanish",       # so {{first_name}} renders as your name in preview
                "last_name": "Mehrotra",
                "company_name": f"[DRY RUN] {company_name}",
                "campaign_id": campaign_id,
                "custom_variables": {
                    "subject": f"[DRY RUN] {subject}",
                    "body": body,
                },
            }

            try:
                instantly.add_leads_to_campaign(campaign_id=campaign_id, leads=[lead])
                print(f"  ✓ Queued in Instantly campaign '{campaign_name}' → {args.email}\n")
                sent += 1
            except Exception as e:
                print(f"  ✗ Failed: {e}\n")

        print(f"{'='*60}")
        print(f"Done. {sent}/{len(drafts)} queued. Check {args.email} — Instantly will deliver shortly.")
        print(f"Campaigns must be ACTIVE for delivery. Check Instantly UI if emails don't arrive.")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
