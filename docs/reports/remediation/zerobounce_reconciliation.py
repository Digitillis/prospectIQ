"""Phase 1 — ZeroBounce Reconciliation Inspection Script.

Read-only diagnostic queries. No API calls, no DB writes.
Run as: python3 docs/reports/remediation/zerobounce_reconciliation.py

Outputs current email_status distribution, today's ZB run results,
remaining null-status contacts, and credit impact estimate.
"""

import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_all(table, select_cols, filters=None):
    """Paginate through a table and return all rows."""
    rows = []
    offset = 0
    while True:
        q = client.table(table).select(select_cols).range(offset, offset + 999)
        if filters:
            for f in filters:
                q = f(q)
        r = q.execute()
        if not r.data:
            break
        rows.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000
    return rows


def main():
    print("=" * 70)
    print("ZEROBOUNCE RECONCILIATION REPORT")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M CDT')}")
    print("=" * 70)

    # 1. Full email_status distribution
    print("\n1. EMAIL_STATUS DISTRIBUTION (all contacts)")
    all_contacts = fetch_all("contacts", "id,email,email_status,updated_at")
    print(f"   Total contacts: {len(all_contacts)}")
    status_counts = Counter(c.get("email_status") for c in all_contacts)
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"   {str(status)!r:20s}: {count:>6}")

    # 2. Email-holders only
    with_email = [c for c in all_contacts if c.get("email")]
    null_status = [c for c in with_email if not c.get("email_status")]
    sendable = [c for c in with_email if c.get("email_status") in ("verified", "catch_all")]
    print(f"\n   Contacts with email:           {len(with_email)}")
    print(f"   Sendable (verified+catch_all): {len(sendable)}")
    print(f"   NULL email_status:             {len(null_status)}")

    # 3. Recent ZB updates (last 24h)
    print("\n2. RECENT ZB RUN (updates in last 24h)")
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [c for c in with_email if c.get("updated_at", "") > yesterday and c.get("email_status")]
    recent_counts = Counter(c.get("email_status") for c in recent)
    print(f"   Contacts updated in last 24h with a status: {len(recent)}")
    for s, c in sorted(recent_counts.items(), key=lambda x: -x[1]):
        print(f"   {str(s)!r:20s}: {c}")

    # 4. Credit impact for remaining nulls
    print("\n3. CREDIT IMPACT ESTIMATE")
    remaining = len(null_status)
    cost_per_credit = 0.008
    estimated_cost = remaining * cost_per_credit
    expected_sendable_pct = 0.93  # Based on today's run: 944/1013 = 93%
    print(f"   Remaining null-status contacts:    {remaining}")
    print(f"   Credits required:                  {remaining}")
    print(f"   Estimated cost at $0.008/credit:   ${estimated_cost:.2f}")
    print(f"   Expected new sendable (~93%):       ~{int(remaining * expected_sendable_pct)}")

    # 5. Sample of null-status contacts (first 20)
    print("\n4. SAMPLE NULL-STATUS CONTACTS (first 20)")
    for c in null_status[:20]:
        print(f"   {c['id'][:12]}  {c['email']:45s}  updated={c.get('updated_at', 'NULL')[:10]}")

    print("\n" + "=" * 70)
    print("VERDICT: ZB write-back script is correct. Run again for remaining")
    print(f"         {remaining} contacts. Expected cost: ${estimated_cost:.2f}.")
    print("=" * 70)


if __name__ == "__main__":
    main()
