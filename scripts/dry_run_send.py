"""Dry run — send approved drafts to your own inbox via Resend.

Picks N approved+unsent email drafts and sends them to YOUR_TEST_EMAIL
from avi@digitillis.io via Resend. Nothing goes to real prospects.

Usage:
    python3 scripts/dry_run_send.py --email avi@digitillis.com --count 3
    python3 scripts/dry_run_send.py --email avi@digitillis.com --count 3 --cluster machinery
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.core.database import Database
from backend.app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Your test inbox (e.g. avi@digitillis.com)")
    parser.add_argument("--count", type=int, default=3, help="Number of drafts to dry-run")
    parser.add_argument("--cluster", default=None, help="Filter by campaign_cluster (e.g. machinery)")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.resend_api_key:
        print("ERROR: RESEND_API_KEY not set in .env")
        sys.exit(1)

    import resend
    resend.api_key = settings.resend_api_key

    db = Database()

    query = (
        db.client.table("outreach_drafts")
        .select(
            "id, subject, body, edited_body, sequence_name, sequence_step, channel, "
            "companies(name, campaign_cluster), "
            "contacts(full_name, first_name, last_name, persona_type, title, email)"
        )
        .eq("approval_status", "approved")
        .is_("sent_at", "null")
        .eq("channel", "email")
        .not_.is_("subject", "null")
        .neq("subject", "")
        .order("created_at")
        .limit(args.count * 5)
    )
    drafts = query.execute().data or []

    if args.cluster:
        drafts = [
            d for d in drafts
            if (d.get("companies") or {}).get("campaign_cluster", "").lower() == args.cluster.lower()
        ]

    drafts = drafts[:args.count]

    if not drafts:
        print("No approved email drafts found matching criteria.")
        return

    print(f"\n{'='*60}")
    print(f"DRY RUN — sending {len(drafts)} email(s) to {args.email}")
    print(f"From: avi@digitillis.io (via Resend)")
    print(f"{'='*60}\n")

    sent = 0
    for draft in drafts:
        company = draft.get("companies") or {}
        contact = draft.get("contacts") or {}
        company_name = company.get("name", "Unknown")
        cluster = (company.get("campaign_cluster") or "other").lower()
        persona = (contact.get("persona_type") or "").lower()

        subject = draft.get("subject", "")
        body = draft.get("edited_body") or draft.get("body", "")

        print(f"Draft:    {draft['id'][:8]}")
        print(f"Company:  {company_name}  [{cluster} / {persona}]")
        print(f"Contact:  {contact.get('full_name', '?')} ({contact.get('title', '?')})")
        print(f"Real To:  {contact.get('email', 'N/A')}  →  overriding to {args.email}")
        print(f"Subject:  {subject}")
        print(f"Body preview:\n{'—'*40}")
        print(body[:300] + ("..." if len(body) > 300 else ""))
        print(f"{'—'*40}")

        try:
            resend.Emails.send({
                "from": "Avanish Mehrotra <avi@digitillis.io>",
                "to": [args.email],
                "subject": f"[DRY RUN] {subject}",
                "text": body,
            })
            print(f"  ✓ Sent via Resend → {args.email}\n")
            sent += 1
        except Exception as e:
            print(f"  ✗ Failed: {e}\n")

    print(f"{'='*60}")
    print(f"Done. {sent}/{len(drafts)} sent. Check {args.email} — should arrive within seconds.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
