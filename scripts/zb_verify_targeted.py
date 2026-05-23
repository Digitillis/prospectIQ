"""ZeroBounce targeted verification — prioritized by send readiness.

Priority order:
  1. Contacts with a pending or approved step-2 draft (directly unlocks sends)
  2. Enriched, outreach-eligible contacts with ICP-matching titles
  3. Fill remainder to credit limit with other eligible contacts

Pre-run analysis (2026-05-13):
  P1 = 132  (28 approved + 104 pending step-2 drafts, null email_status)
  P2 = 712  (ICP titles: Plant Manager, GM, Dir Ops, Maintenance Mgr, COO, VP Ops)
  P3 = 0    (credits exhausted at P1+P2)
  Skip = 567 (bounced/opted_out/already contacted/ineligible)
  Expected new sendable: 464-590 (55-70% pass rate)

Run:
  ZEROBOUNCE_API_KEY=xxx python3.11 scripts/zb_verify_targeted.py [--dry-run]
"""
import sys
import os
import requests
from datetime import datetime, timezone

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
    print("Run as: ZEROBOUNCE_API_KEY=your_key python3.11 scripts/zb_verify_targeted.py")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# --- Check credits ---
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

CREDIT_LIMIT = credits

ICP_SIGNALS = [
    "maintenance", "reliability", "operations", "plant manager", "plant director",
    "manufacturing", "production", "engineering", "vp ops", "director of ops",
    "chief operating", "coo", "facilities", "asset", "continuous improvement",
    "process engineer", "quality", "supply chain", "vice president", "svp", "evp",
    "director", "manager",
]
SKIP_STATES = {"bounced", "unsubscribed", "opted_out", "disqualified", "touch_2_sent", "touch_3_sent"}

# --- Fetch all null-status contacts with a valid email ---
print("Fetching null-status contacts...")
all_null = []
page = 0
while True:
    rows = (
        client.table("contacts")
        .select("id, email, full_name, title, outreach_state, is_outreach_eligible")
        .is_("email_status", "null")
        .not_.is_("email", "null")
        .neq("email", "")
        .range(page * 1000, (page + 1) * 1000 - 1)
        .execute()
    ).data or []
    all_null.extend(rows)
    if len(rows) < 1000:
        break
    page += 1

print(f"Total null-status contacts with email: {len(all_null)}")
null_ids = {c["id"] for c in all_null}
contact_by_id = {c["id"]: c for c in all_null}

# --- Priority 1: contacts with pending/approved step-2 drafts ---
draft_rows = (
    client.table("outreach_drafts")
    .select("contact_id, approval_status")
    .eq("sequence_step", 2)
    .in_("approval_status", ["pending", "approved"])
    .execute()
).data or []

p1_ids_ordered = []
seen = set()
for r in draft_rows:
    cid = r["contact_id"]
    if cid in null_ids and cid not in seen:
        # approved first, then pending
        if r["approval_status"] == "approved":
            p1_ids_ordered.insert(0, cid)
        else:
            p1_ids_ordered.append(cid)
        seen.add(cid)

# Stable deduplicate preserving approved-first order
p1_seen = set()
p1_final = []
for cid in p1_ids_ordered:
    if cid not in p1_seen:
        p1_final.append(cid)
        p1_seen.add(cid)

print(f"P1 (step-2 draft blocked):  {len(p1_final)}")

# --- Priority 2: eligible, ICP title, not in skip states ---
non_p1 = [c for c in all_null if c["id"] not in p1_seen]
p2 = [
    c["id"] for c in non_p1
    if (c.get("outreach_state") or "").lower() not in SKIP_STATES
    and c.get("is_outreach_eligible") is not False
    and any(sig in (c.get("title") or "").lower() for sig in ICP_SIGNALS)
]
print(f"P2 (eligible, ICP title):   {len(p2)}")

# --- Priority 3: remaining eligible ---
p2_set = set(p2)
p3 = [
    c["id"] for c in non_p1
    if c["id"] not in p2_set
    and (c.get("outreach_state") or "").lower() not in SKIP_STATES
    and c.get("is_outreach_eligible") is not False
]
print(f"P3 (other eligible):        {len(p3)}")

# --- Build final list trimmed to credit limit ---
ordered_ids = p1_final + p2 + p3
to_verify = [contact_by_id[cid] for cid in ordered_ids[:CREDIT_LIMIT]]

p1_count = min(len(p1_final), CREDIT_LIMIT)
p2_count = max(0, min(len(p2), CREDIT_LIMIT - len(p1_final)))
p3_count = max(0, CREDIT_LIMIT - len(p1_final) - len(p2))

print(f"\nSelected for verification: {len(to_verify)}")
print(f"  P1: {p1_count}  P2: {p2_count}  P3: {p3_count}")
skipped = len(all_null) - len(to_verify)
print(f"  Skipped (low value / no credits): {skipped}")

if DRY_RUN:
    print("\n[DRY RUN] No credits consumed. Remove --dry-run to execute.")
    sys.exit(0)

confirm = input(f"\nAbout to verify {len(to_verify)} contacts using {len(to_verify)} credits. Continue? [y/N] ").strip().lower()
if confirm != "y":
    print("Aborted.")
    sys.exit(0)

# --- ZeroBounce batch verification ---
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
        print(f"  Batch {batch_start+1}-{batch_start+len(batch)}: API error: {e}")
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
            print(f"  Write error for {email}: {e}")
            errors += 1

    print(f"  Batch {batch_start+1}-{batch_start+len(batch)} done")

print(f"\nResults:")
print(f"  Verified (sendable):   {verified}")
print(f"  Catch-all (sendable):  {catch_all}")
print(f"  Invalid (suppressed):  {invalid}")
print(f"  Unverified:            {unknown_count}")
print(f"  Errors:                {errors}")
print(f"  New sendable contacts: {verified + catch_all}")
