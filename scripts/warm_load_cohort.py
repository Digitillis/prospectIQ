#!/usr/bin/env python3
"""Load the canonical warm prospect master into the ISOLATED warm workspace and write the
Cohort-1 Step-1 drafts in the confirmed structure (personalization -> burning platform ->
Gartner bio -> ask), with a 5/5/5 A/B/C subject-line split.

Everything is scoped to ``warm_workspace_id`` ONLY. Before loading any prospect this runs the
same cross-channel collision rule the ingest uses: anyone already COLD-CONTACTED is skipped
entirely (never loaded to warm) so the two channels can never double-touch the same person.

DEFAULT = DRY RUN. Prints what it would create and writes nothing. Pass --commit to write.
Idempotent: contacts dedupe by email within the warm workspace; a cohort Step-1 draft is not
re-created if a pending Step-1 already exists for that contact.

    python3 scripts/warm_load_cohort.py warm_outreach/warm_prospects_master.csv            # dry run
    python3 scripts/warm_load_cohort.py warm_outreach/warm_prospects_master.csv --commit   # write
    python3 scripts/warm_load_cohort.py ... --cohort-only   # load only the 15 cohort contacts
"""

from __future__ import annotations

import argparse
import csv
import re
import sys

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client

# --- Confirmed Step-1 body blocks (no dashes, no ellipses, American English) ---------------

BRIDGE = (
    "In a manufacturing operation like yours, you have probably lived the gap between what "
    "your operational data could tell you and what your teams can actually act on."
)
BURNING_PLATFORM = (
    "That gap is expensive. Most plants run well below the 85% world-class OEE benchmark, and "
    "the shortfall shows up as unplanned downtime, scrap, rework, and energy creeping up unit by "
    "unit. Unplanned downtime alone costs manufacturers around 11% of revenue (Siemens)."
)
GARTNER_DIGITILLIS = (
    "As Gartner Consulting's North America Digital Manufacturing Leader, I spent years working "
    "this exact issue with CIOs and COOs. My company, Digitillis, exists to close that gap. We "
    "turn the operational data your plants already collect into causal answers: what is "
    "happening, what is about to happen, what it costs, and where to act first."
)
ASK = (
    "We can pilot and prove the value in days to a few weeks. Worth 20 minutes to trade notes and "
    "show you what we have built? If it is better suited to your operations leadership, a quick "
    "introduction works too."
)
SIGNATURE = "Best regards,\nAvanish"

SUBJECT_A = "Unplanned downtime costs manufacturers ~11% of revenue. Digitillis closes the gap."
SUBJECT_C = "A question from Gartner's former NA Digital Manufacturing lead"


def subject_b(display: str) -> str:
    return f"What {display}'s operational data could already be telling you"


# --- The 15-person Cohort 1: company-name match key -> (display name, subject group) --------
# Groups assigned in balanced rotation (size-balanced across A/B/C), not optimized per prospect,
# so the subject-line A/B/C read is clean.
COHORT = {
    "TRADITIONAL MEDICINALS": ("Traditional Medicinals", "A"),
    "AMERICAN CAST IRON PIPE": ("American Cast Iron Pipe", "A"),
    "ADAC": ("ADAC Automotive", "A"),
    "SHURE": ("Shure", "A"),
    "ENPRO": ("Enpro", "A"),
    "VELAN": ("Velan", "B"),
    "GREENE TWEED": ("Greene Tweed", "B"),
    "BAY STATE MILLING": ("Bay State Milling", "B"),
    "LUCK": ("Luck Companies", "B"),
    "DELTA FAUCET": ("Delta Faucet", "B"),
    "NIBCO": ("NIBCO", "C"),
    "PVS CHEMICALS": ("PVS Chemicals", "C"),
    "CRAYOLA": ("Crayola", "C"),
    "MANNINGTON": ("Mannington", "C"),
    "WORTHINGTON": ("Worthington", "C"),
}

COLD_CONTACTED_STATES = ("touch_", "contacted", "engaged", "replied", "demo", "closed")


def cohort_match(company: str):
    """Return (display, group) if this company is in Cohort 1, else None."""
    up = (company or "").upper()
    for key, val in COHORT.items():
        if key in up:
            return val
    return None


def first_name(full: str) -> str:
    return (full or "").strip().split(" ")[0] if full else ""


def domain_of(email: str):
    return email.split("@", 1)[1].lower() if "@" in email else None


def extract_hook(body: str) -> str:
    """Pull the personalization paragraph out of an existing (old-structure) body: the
    paragraph that is neither the greeting, the Gartner opener, the ask, nor the signature."""
    body = (body or "").replace("\\n", "\n")
    for para in (p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()):
        low = para.lower()
        if low.startswith("hi "):
            continue
        if "gartner" in low:
            continue
        if "twenty minutes" in low or "i would welcome" in low or "best regards" in low:
            continue
        return para
    return ""


def compose_step1(first: str, hook: str, display: str, group: str) -> tuple[str, str]:
    """Return (subject, body) for the confirmed Step-1 structure."""
    if group == "A":
        subject = SUBJECT_A
    elif group == "B":
        subject = subject_b(display)
    else:
        subject = SUBJECT_C
    personalization = f"{hook} {BRIDGE}".strip()
    body = "\n\n".join(
        [
            f"Hi {first},",
            personalization,
            BURNING_PLATFORM,
            GARTNER_DIGITILLIS,
            ASK,
            SIGNATURE,
        ]
    )
    return subject, body


def cold_contacted(client, cold_ws: str, email: str) -> bool:
    rows = (
        client.table("contacts")
        .select("id,outreach_state,status")
        .eq("workspace_id", cold_ws)
        .eq("email", email)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return False
    cc = rows[0]
    state = (cc.get("outreach_state") or cc.get("status") or "").lower()
    if any(k in state for k in COLD_CONTACTED_STATES):
        return True
    sent = (
        client.table("outreach_drafts")
        .select("id")
        .eq("workspace_id", cold_ws)
        .eq("contact_id", cc["id"])
        .not_.is_("sent_at", "null")
        .limit(1)
        .execute()
        .data
    )
    return bool(sent)


def upsert_company(client, ws, commit, name, domain):
    """Warm companies are their OWN isolated rows, deduped by name within the warm workspace.

    ``companies.domain`` carries a GLOBAL unique index, so a domain can belong to only one
    workspace. Inserting a warm company with ``domain`` set would either collide with the cold
    registry or force a warm contact to reference a cold-owned company row — a cross-channel
    link we explicitly forbid. We therefore insert warm companies with ``domain=NULL`` (NULLs are
    exempt from the unique index) and dedupe by name. The contact still carries the real email.
    """
    found = (
        client.table("companies")
        .select("id")
        .eq("workspace_id", ws)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
    )
    if found:
        return found[0]["id"], False
    if not commit:
        return None, True
    ins = (
        client.table("companies")
        .insert(
            {
                "workspace_id": ws,
                "name": name,
                "domain": None,
                "status": "discovered",
                "campaign_name": "warm_personal",
            }
        )
        .execute()
        .data
    )
    return ins[0]["id"], True


def upsert_contact(client, ws, commit, company_id, row, email):
    found = (
        client.table("contacts")
        .select("id")
        .eq("workspace_id", ws)
        .eq("email", email)
        .limit(1)
        .execute()
        .data
    )
    if found:
        return found[0]["id"], False
    if not commit:
        return None, True
    full = row.get("contact") or ""
    parts = full.split(" ", 1)
    ins = (
        client.table("contacts")
        .insert(
            {
                "workspace_id": ws,
                "company_id": company_id,
                "first_name": parts[0] if parts else "",
                "last_name": parts[1] if len(parts) > 1 else "",
                "full_name": full,
                "email": email,
                "title": row.get("title") or None,
                "status": "identified",
            }
        )
        .execute()
        .data
    )
    return ins[0]["id"], True


def has_pending_step1(client, ws, contact_id) -> bool:
    if not contact_id:
        return False
    rows = (
        client.table("outreach_drafts")
        .select("id")
        .eq("workspace_id", ws)
        .eq("contact_id", contact_id)
        .eq("sequence_step", 1)
        .eq("sequence_name", "warm_cohort1")
        .limit(1)
        .execute()
        .data
    )
    return bool(rows)


def write_step1(client, ws, commit, company_id, contact_id, subject, body, notes):
    if not commit or not contact_id:
        return False
    client.table("outreach_drafts").insert(
        {
            "workspace_id": ws,
            "company_id": company_id,
            "contact_id": contact_id,
            "channel": "email",
            "sequence_name": "warm_cohort1",
            "sequence_step": 1,
            "subject": subject,
            "body": body,
            "personalization_notes": notes,
            "approval_status": "pending",
        }
    ).execute()
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    ap.add_argument("--cohort-only", action="store_true", help="load only the 15 cohort contacts")
    args = ap.parse_args()

    ws = get_settings().warm_workspace_id
    cold_ws = get_settings().default_workspace_id
    if not ws or ws == cold_ws:
        print("FATAL: warm_workspace_id unset or equals the cold workspace.", file=sys.stderr)
        return 1

    client = get_supabase_client()
    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] warm workspace = {ws}  (cold = {cold_ws})")

    with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    loaded = skipped_cold = drafts = existing = 0
    cohort_written = []
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        coh = cohort_match(row.get("company") or "")
        if args.cohort_only and not coh:
            continue

        if cold_contacted(client, cold_ws, email):
            skipped_cold += 1
            print(f"  [skip cold-contacted] {row.get('contact')} <{email}>")
            continue

        domain = domain_of(email)
        company_id, _ = upsert_company(
            client, ws, args.commit, row.get("company") or "Unknown", domain
        )
        contact_id, created = upsert_contact(client, ws, args.commit, company_id, row, email)
        if created:
            loaded += 1

        if not coh:
            continue
        # Cohort Step-1 draft in the confirmed structure.
        display, group = coh
        if has_pending_step1(client, ws, contact_id):
            existing += 1
            continue
        hook = extract_hook(row.get("body") or "")
        if not hook:
            print(
                f"  [WARN] no hook found for {row.get('company')} — draft skipped", file=sys.stderr
            )
            continue
        subject, body = compose_step1(first_name(row.get("contact") or ""), hook, display, group)
        notes = f"Cohort 1, subject group {group}. Hook: {hook[:120]}"
        wrote = write_step1(client, ws, args.commit, company_id, contact_id, subject, body, notes)
        drafts += 1 if wrote else 0
        cohort_written.append((group, display, subject, body))

    print(
        f"\nSUMMARY [{mode}]: contacts loaded={loaded}, cold-contacted skipped={skipped_cold}, "
        f"cohort drafts written={drafts}, cohort drafts already existed={existing}"
    )
    if not args.commit and cohort_written:
        print("\n----- COHORT-1 STEP-1 PREVIEW (first of each subject group) -----")
        seen = set()
        for group, display, subject, body in sorted(cohort_written):
            if group in seen:
                continue
            seen.add(group)
            print(f"\n=== GROUP {group} — {display} ===\nSubject: {subject}\n\n{body}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
