"""Staging database seed script.

Inserts deterministic, synthetic data into a staging Supabase database.
All data uses @staging-test.invalid email addresses (RFC 2606 non-routable TLD),
which can never reach a real inbox even if SEND_ENABLED were accidentally set to true.

Idempotent: each INSERT uses ON CONFLICT DO NOTHING keyed on stable UUIDs.
Safe to run multiple times — subsequent runs are no-ops.

Usage:
    STAGING_DATABASE_URL=postgresql://... python scripts/seed_staging.py
    STAGING_DATABASE_URL=postgresql://... python scripts/seed_staging.py --dry-run

Dry-run prints SQL without connecting to any database.

SAFETY GUARDS:
    1. Refuses to run if DATABASE_URL contains the production Supabase project ref.
    2. Refuses to run if SEND_ENABLED env var is not "false" or absent.
    3. All emails use @staging-test.invalid — non-routable by design.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
import uuid

PRODUCTION_REF = "wlyhbdmjhgvovigogdco"

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

COMPANY_IDS = [
    "10000000-0000-0000-0000-000000000001",
    "10000000-0000-0000-0000-000000000002",
    "10000000-0000-0000-0000-000000000003",
    "10000000-0000-0000-0000-000000000004",
    "10000000-0000-0000-0000-000000000005",
    "10000000-0000-0000-0000-000000000006",
    "10000000-0000-0000-0000-000000000007",
    "10000000-0000-0000-0000-000000000008",
    "10000000-0000-0000-0000-000000000009",
    "10000000-0000-0000-0000-000000000010",
]

CONTACT_IDS = [
    "20000000-0000-0000-0000-" + str(i).zfill(12) for i in range(1, 31)
]

COMPANIES = [
    (COMPANY_IDS[0], "Apex Precision Parts", "apexprecision.staging", "manufacturing", "CA", "1-10M"),
    (COMPANY_IDS[1], "Midland Stamping Co", "midlandstamping.staging", "metal_fabrication", "OH", "10-50M"),
    (COMPANY_IDS[2], "Lakeview Plastics", "lakeviewplastics.staging", "plastics", "MI", "1-10M"),
    (COMPANY_IDS[3], "Northgate Tooling", "northgatetooling.staging", "tooling", "IL", "50-200M"),
    (COMPANY_IDS[4], "Cascade Electronics Mfg", "cascadeelectronics.staging", "electronics", "WA", "10-50M"),
    (COMPANY_IDS[5], "Redwood Aerospace Components", "redwoodaero.staging", "aerospace", "CA", "200M+"),
    (COMPANY_IDS[6], "Summit Hydraulics", "summithydraulics.staging", "hydraulics", "CO", "1-10M"),
    (COMPANY_IDS[7], "Ironclad Forge", "ironclad.staging", "forging", "PA", "10-50M"),
    (COMPANY_IDS[8], "Pacific Composites", "pacificcomposites.staging", "composites", "OR", "1-10M"),
    (COMPANY_IDS[9], "Heartland CNC", "heartlandcnc.staging", "cnc_machining", "KS", "1-10M"),
]

CONTACTS = [
    # (id, company_idx, first, last, title, email, approval_status, sequence_name, step)
    (CONTACT_IDS[0],  0, "Alice",   "Tran",     "VP of Operations",        "alice.tran@staging-test.invalid",        "approved",  "email_value_first", 1),
    (CONTACT_IDS[1],  0, "Bob",     "Okafor",   "Plant Manager",           "bob.okafor@staging-test.invalid",        "pending",   "email_value_first", 1),
    (CONTACT_IDS[2],  0, "Carol",   "Winters",  "Director of Engineering", "carol.winters@staging-test.invalid",     "rejected",  "email_value_first", 1),
    (CONTACT_IDS[3],  1, "David",   "Kim",      "COO",                     "david.kim@staging-test.invalid",         "approved",  "email_value_first", 2),
    (CONTACT_IDS[4],  1, "Eva",     "Sousa",    "VP of Manufacturing",     "eva.sousa@staging-test.invalid",         "pending",   "email_value_first", 2),
    (CONTACT_IDS[5],  1, "Frank",   "Nguyen",   "Operations Manager",      "frank.nguyen@staging-test.invalid",      "approved",  "short_form",        1),
    (CONTACT_IDS[6],  2, "Grace",   "Patel",    "Plant Manager",           "grace.patel@staging-test.invalid",       "pending",   "short_form",        1),
    (CONTACT_IDS[7],  2, "Henry",   "Marchand", "Director of Operations",  "henry.marchand@staging-test.invalid",    "rejected",  "short_form",        1),
    (CONTACT_IDS[8],  2, "Irene",   "Voss",     "VP Engineering",          "irene.voss@staging-test.invalid",        "approved",  "email_value_first", 3),
    (CONTACT_IDS[9],  3, "James",   "Otieno",   "CIO",                     "james.otieno@staging-test.invalid",      "pending",   "email_value_first", 1),
    (CONTACT_IDS[10], 3, "Karen",   "Bloom",    "VP Supply Chain",         "karen.bloom@staging-test.invalid",       "approved",  "email_value_first", 1),
    (CONTACT_IDS[11], 3, "Leo",     "Chen",     "Plant Manager",           "leo.chen@staging-test.invalid",          "pending",   "email_value_first", 2),
    (CONTACT_IDS[12], 4, "Maria",   "Ferreira", "VP of Operations",        "maria.ferreira@staging-test.invalid",    "approved",  "short_form",        2),
    (CONTACT_IDS[13], 4, "Nathan",  "Dubois",   "Director Engineering",    "nathan.dubois@staging-test.invalid",     "rejected",  "short_form",        1),
    (CONTACT_IDS[14], 4, "Olivia",  "Park",     "Operations Manager",      "olivia.park@staging-test.invalid",       "pending",   "email_value_first", 1),
    (CONTACT_IDS[15], 5, "Peter",   "Adeyemi",  "COO",                     "peter.adeyemi@staging-test.invalid",     "approved",  "email_value_first", 1),
    (CONTACT_IDS[16], 5, "Quinn",   "Leblanc",  "VP Manufacturing",        "quinn.leblanc@staging-test.invalid",     "pending",   "email_value_first", 2),
    (CONTACT_IDS[17], 5, "Rachel",  "Johansson","Plant Manager",           "rachel.johansson@staging-test.invalid",  "approved",  "short_form",        1),
    (CONTACT_IDS[18], 6, "Samuel",  "Osei",     "Director of Operations",  "samuel.osei@staging-test.invalid",       "pending",   "email_value_first", 1),
    (CONTACT_IDS[19], 6, "Tara",    "Morin",    "VP Engineering",          "tara.morin@staging-test.invalid",        "rejected",  "email_value_first", 1),
    (CONTACT_IDS[20], 6, "Ulysses", "Tanaka",   "Plant Manager",           "ulysses.tanaka@staging-test.invalid",    "pending",   "short_form",        2),
    (CONTACT_IDS[21], 7, "Vera",    "Hassan",   "COO",                     "vera.hassan@staging-test.invalid",       "approved",  "email_value_first", 3),
    (CONTACT_IDS[22], 7, "Walter",  "Mbeki",    "VP of Operations",        "walter.mbeki@staging-test.invalid",      "pending",   "email_value_first", 1),
    (CONTACT_IDS[23], 7, "Xena",    "Fischer",  "Director of Ops",         "xena.fischer@staging-test.invalid",      "approved",  "email_value_first", 2),
    (CONTACT_IDS[24], 8, "Yusuf",   "Brennan",  "Plant Manager",           "yusuf.brennan@staging-test.invalid",     "pending",   "short_form",        1),
    (CONTACT_IDS[25], 8, "Zoe",     "Andrade",  "VP Manufacturing",        "zoe.andrade@staging-test.invalid",       "rejected",  "short_form",        1),
    (CONTACT_IDS[26], 8, "Aaron",   "Lindqvist","Operations Manager",       "aaron.lindqvist@staging-test.invalid",   "pending",   "email_value_first", 1),
    (CONTACT_IDS[27], 9, "Beth",    "Nakamura", "COO",                     "beth.nakamura@staging-test.invalid",     "approved",  "email_value_first", 1),
    (CONTACT_IDS[28], 9, "Caleb",   "Obiora",   "VP of Engineering",       "caleb.obiora@staging-test.invalid",      "pending",   "email_value_first", 2),
    (CONTACT_IDS[29], 9, "Diana",   "Sorensen", "Plant Manager",           "diana.sorensen@staging-test.invalid",    "approved",  "email_value_first", 1),
]


def _guard_production(db_url: str) -> None:
    if PRODUCTION_REF in db_url:
        print(
            f"FATAL: DATABASE_URL contains the production Supabase project ref "
            f"({PRODUCTION_REF!r}). Refusing to seed production."
        )
        sys.exit(1)


def _guard_send_enabled() -> None:
    send_enabled = os.environ.get("SEND_ENABLED", "false").lower()
    if send_enabled not in ("false", "0", ""):
        print(
            f"FATAL: SEND_ENABLED={send_enabled!r}. "
            "This script must not run when sends are enabled."
        )
        sys.exit(1)


def build_sql() -> str:
    lines: list[str] = []

    lines.append("-- ProspectIQ staging seed — generated by scripts/seed_staging.py")
    lines.append("-- All emails use @staging-test.invalid (RFC 2606 non-routable).")
    lines.append("-- Idempotent: ON CONFLICT DO NOTHING on stable UUIDs.")
    lines.append("")

    # Workspace
    lines.append("-- Workspace")
    lines.append(
        f"INSERT INTO workspaces (id, name, slug, owner_email, tier) "
        f"VALUES ('{WORKSPACE_ID}', 'Staging Workspace', 'staging', 'staging@staging-test.invalid', 'growth') "
        f"ON CONFLICT (id) DO NOTHING;"
    )
    lines.append("")

    # Companies
    lines.append("-- Companies (10)")
    for cid, name, domain, industry, state, revenue in COMPANIES:
        lines.append(
            f"INSERT INTO companies (id, workspace_id, name, domain, industry, state, revenue_range, status) "
            f"VALUES ('{cid}', '{WORKSPACE_ID}', {_q(name)}, {_q(domain)}, "
            f"{_q(industry)}, {_q(state)}, {_q(revenue)}, 'qualified') "
            f"ON CONFLICT (id) DO NOTHING;"
        )
    lines.append("")

    # Contacts (30)
    lines.append("-- Contacts (30 — all @staging-test.invalid)")
    for (cid, company_idx, first, last, title, email, _approval_status, _seq_name, _step) in CONTACTS:
        company_id = COMPANY_IDS[company_idx]
        lines.append(
            f"INSERT INTO contacts "
            f"(id, workspace_id, company_id, first_name, last_name, title, email) "
            f"VALUES ('{cid}', '{WORKSPACE_ID}', '{company_id}', "
            f"{_q(first)}, {_q(last)}, {_q(title)}, {_q(email)}) "
            f"ON CONFLICT (id) DO NOTHING;"
        )
    lines.append("")

    lines.append("-- Verify: contact count should be exactly 30 after first run")
    lines.append(
        "SELECT COUNT(*) AS staging_contact_count FROM contacts "
        "WHERE workspace_id = '" + WORKSPACE_ID + "';"
    )

    return "\n".join(lines)


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def run(db_url: str) -> None:
    try:
        import psycopg2  # type: ignore[import]
    except ImportError:
        print("psycopg2 not installed. Install with: pip install psycopg2-binary")
        sys.exit(1)

    sql = build_sql()
    print("Connecting to staging database...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
        print("Seed complete. Verifying contact count...")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM contacts WHERE workspace_id = %s;",
                (WORKSPACE_ID,),
            )
            count = cur.fetchone()[0]
        print(f"Staging contacts in workspace: {count}")
        if count == 0:
            print("WARNING: 0 contacts found — contacts table may not have workspace_id column yet.")
        elif count > 30:
            print(f"WARNING: {count} contacts found (expected <=30). Prior seed runs may have partial data.")
        else:
            print("OK")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed staging database with synthetic data.")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without connecting.")
    args = parser.parse_args()

    db_url = os.environ.get("STAGING_DATABASE_URL") or os.environ.get("DATABASE_URL", "")

    if args.dry_run:
        if db_url and PRODUCTION_REF in db_url:
            print(f"WARNING: URL appears to be production ({PRODUCTION_REF!r}). Dry run only.")
        print(build_sql())
        return

    if not db_url:
        print("ERROR: Set STAGING_DATABASE_URL (or DATABASE_URL) before running.")
        sys.exit(1)

    _guard_production(db_url)
    _guard_send_enabled()

    run(db_url)


if __name__ == "__main__":
    main()
