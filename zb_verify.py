"""ZeroBounce bulk validation for email_status=None contacts.

Validates up to 200 emails per API call using /v2/validatebatch.
Updates contacts.email_status in DB based on results.
"""
import sys, os, requests, json
sys.path.insert(0, "/app" if os.path.exists("/app") else ".")

from backend.app.core.database import Database
from backend.app.core.config import get_settings

settings = get_settings()
api_key = settings.zerobounce_api_key
if not api_key:
    print("ERROR: ZEROBOUNCE_API_KEY not set")
    sys.exit(1)

# Check credits first
credits_resp = requests.get(
    "https://api.zerobounce.net/v2/getcredits",
    params={"api_key": api_key},
    timeout=10
)
credits_data = credits_resp.json()
credits = int(credits_data.get("Credits", 0))
print(f"ZeroBounce credits available: {credits}")

db = Database()

# Pull all contacts with email_status=None and a valid email
result = db.client.table("contacts")\
    .select("id, email, full_name")\
    .is_("email_status", "null")\
    .not_.is_("email", "null")\
    .neq("email", "")\
    .execute()

contacts = result.data or []
print(f"Contacts to verify: {len(contacts)}")

if credits < len(contacts):
    print(f"WARNING: Only {credits} credits, but {len(contacts)} contacts to verify")
    print(f"Verifying first {credits} contacts only")
    contacts = contacts[:credits]

if not contacts:
    print("No contacts to verify")
    sys.exit(0)

# Batch into groups of 200
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
from datetime import datetime, timezone

for batch_start in range(0, len(contacts), BATCH_SIZE):
    batch = contacts[batch_start:batch_start + BATCH_SIZE]
    email_list = [{"email_address": c["email"], "ip_address": ""} for c in batch]
    
    try:
        resp = requests.post(
            "https://api.zerobounce.net/v2/validatebatch",
            json={"api_key": api_key, "email_batch": email_list},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Batch {batch_start}-{batch_start+len(batch)}: API error: {e}")
        errors += len(batch)
        continue
    
    results = data.get("email_batch", [])
    contact_by_email = {c["email"].lower(): c for c in batch}
    
    for r in results:
        email = (r.get("address") or "").lower()
        zb_status = (r.get("status") or "unknown").lower()
        new_status = STATUS_MAP.get(zb_status, "unverified")
        
        contact = contact_by_email.get(email)
        if not contact:
            continue
        
        try:
            db.client.table("contacts").update({
                "email_status": new_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", contact["id"]).execute()
            
            if new_status == "verified":
                verified += 1
            elif new_status == "invalid":
                invalid += 1
            elif new_status == "catch_all":
                catch_all += 1
            else:
                unknown_count += 1
        except Exception as e:
            errors += 1
    
    print(f"  Processed batch {batch_start+1}-{batch_start+len(batch)}")

print(f"\nResults:")
print(f"  Verified (sendable):    {verified}")
print(f"  Catch-all (sendable):   {catch_all}")
print(f"  Invalid (suppressed):   {invalid}")
print(f"  Unverified (unknown):   {unknown_count}")
print(f"  Errors:                 {errors}")
print(f"  New sendable contacts:  {verified + catch_all}")
