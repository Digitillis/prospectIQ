"""ZeroBounce validation for email_status='unverified' contacts (Apollo inserts).

Priority:
  1. Contacts at qualified companies
  2. Contacts at outreach_pending companies
  3. Contacts at contacted companies
  4. Other

Consumes up to all available ZB credits. Run with --dry-run to preview.
"""
import sys
import os
import requests
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
    sys.exit(1)
ZEROBOUNCE_API_KEY = os.environ.get("ZEROBOUNCE_API_KEY", "")
DRY_RUN = "--dry-run" in sys.argv

if not ZEROBOUNCE_API_KEY:
    print("ERROR: ZEROBOUNCE_API_KEY not set")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Check credits
credits_resp = requests.get(
    "https://api.zerobounce.net/v2/getcredits",
    params={"api_key": ZEROBOUNCE_API_KEY},
    timeout=10,
)
credits = int(credits_resp.json().get("Credits", 0))
print(f"ZeroBounce credits available: {credits}")
if credits == 0:
    print("No credits remaining.")
    sys.exit(0)

# Fetch all email_status='unverified' contacts with a valid email
print("Fetching email_status='unverified' contacts...")
all_unverified = []
page = 0
while True:
    rows = (
        client.table("contacts")
        .select("id, email, full_name, title, company_id, outreach_state")
        .eq("email_status", "unverified")
        .not_.is_("email", "null")
        .neq("email", "")
        .range(page * 1000, (page + 1) * 1000 - 1)
        .execute()
    ).data or []
    all_unverified.extend(rows)
    if len(rows) < 1000:
        break
    page += 1

print(f"Total unverified contacts: {len(all_unverified)}")
if not all_unverified:
    print("Nothing to verify.")
    sys.exit(0)

# Fetch company statuses
company_ids = list(set(c["company_id"] for c in all_unverified if c.get("company_id")))
co_status_map = {}
for i in range(0, len(company_ids), 500):
    batch = company_ids[i : i + 500]
    cos = (
        client.table("companies")
        .select("id, status")
        .in_("id", batch)
        .execute()
    ).data or []
    for co in cos:
        co_status_map[co["id"]] = co["status"]

PRIORITY_ORDER = {"qualified": 0, "outreach_pending": 1, "contacted": 2, "engaged": 3, "researched": 4}

def contact_priority(c):
    co_s = co_status_map.get(c.get("company_id"), "unknown")
    return PRIORITY_ORDER.get(co_s, 99)

all_unverified.sort(key=contact_priority)

# Trim to credit limit
to_verify = all_unverified[:credits]

# Summary by company status
from collections import Counter
co_buckets = Counter(co_status_map.get(c.get("company_id"), "unknown") for c in to_verify)
print(f"\nSelected for verification: {len(to_verify)} (of {len(all_unverified)} total)")
for s, n in sorted(co_buckets.items(), key=lambda x: PRIORITY_ORDER.get(x[0], 99)):
    print(f"  {s}: {n}")

if DRY_RUN:
    print("\n[DRY RUN] No credits consumed. Remove --dry-run to execute.")
    sys.exit(0)

confirm = input(f"\nAbout to verify {len(to_verify)} contacts using {len(to_verify)} credits. Continue? [y/N] ").strip().lower()
if confirm != "y":
    print("Aborted.")
    sys.exit(0)

# ZeroBounce batch API
BATCH_SIZE = 200
STATUS_MAP = {
    "valid": "verified",
    "invalid": "invalid",
    "catch-all": "catch_all",
    "unknown": "unverified",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}

verified = invalid = catch_all = unknown_count = errors = 0

for batch_start in range(0, len(to_verify), BATCH_SIZE):
    batch = to_verify[batch_start : batch_start + BATCH_SIZE]
    email_list = [{"email_address": c["email"], "ip_address": ""} for c in batch]

    try:
        resp = requests.post(
            "https://api.zerobounce.net/v2/validatebatch",
            json={"api_key": ZEROBOUNCE_API_KEY, "email_batch": email_list},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Batch error: {e}")
        errors += len(batch)
        continue

    results = data.get("email_batch", [])
    contact_map = {c["email"].lower(): c for c in batch}

    for r in results:
        email = (r.get("address") or "").lower()
        zb_status = (r.get("status") or "unknown").lower()
        new_status = STATUS_MAP.get(zb_status, "unverified")
        contact = contact_map.get(email)
        if not contact:
            continue
        try:
            client.table("contacts").update({
                "email_status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", contact["id"]).execute()

            if new_status == "verified":      verified += 1
            elif new_status == "invalid":     invalid += 1
            elif new_status == "catch_all":   catch_all += 1
            else:                             unknown_count += 1
        except Exception as e:
            print(f"  Write error {email}: {e}")
            errors += 1

    print(f"  Batch {batch_start+1}–{batch_start+len(batch)} done")

print(f"\nResults:")
print(f"  Verified (sendable):   {verified}")
print(f"  Catch-all (sendable):  {catch_all}")
print(f"  Invalid (suppressed):  {invalid}")
print(f"  Unverified (unknown):  {unknown_count}")
print(f"  Errors:                {errors}")
print(f"  New sendable contacts: {verified + catch_all}")
print(f"  Remaining unverified:  {len(all_unverified) - len(to_verify)}")
