#!/usr/bin/env python3
"""Backfill full_name from first_name + last_name for contacts missing it."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.database import get_supabase_client

client = get_supabase_client()

result = (
    client.table("contacts")
    .select("id, first_name, last_name")
    .is_("full_name", "null")
    .not_.is_("first_name", "null")
    .limit(1000)
    .execute()
)
contacts = result.data or []
print(f"Contacts needing backfill: {len(contacts)}")

updated = 0
for c in contacts:
    parts = [c.get("first_name") or "", c.get("last_name") or ""]
    full = " ".join(p for p in parts if p).strip()
    if full:
        client.table("contacts").update({"full_name": full}).eq("id", c["id"]).execute()
        updated += 1

print(f"Updated: {updated}")
