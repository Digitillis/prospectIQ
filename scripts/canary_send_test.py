#!/usr/bin/env python3
"""Canary send test — exercises the FULL dispatch pipeline (queue claim → Resend API → DB updates)
by sending ONE email to the founder's address.

Run from /Users/avanish/prospectIQ:
    SEND_WINDOW_START=0 SEND_WINDOW_END=0 python3 scripts/canary_send_test.py

Cleanup behavior, and why this script is safe to re-run repeatedly:

A DB trigger (003_protect_sent_emails.sql) refuses to delete any outreach_drafts
row with sent_at set, cascading through its contact/company via FK ("Sent
emails are the permanent interaction record"). That means cleanup can only
ever fully succeed when the send did NOT deliver. On a successful send, the
draft (and therefore its contact and company) become a permanent fixture by
design -- this is the trigger doing its job, not a bug to work around.

Found the hard way (2026-08-17): an earlier version of this script assumed
full cleanup always succeeded, so the test company/contact/draft from a prior
successful run were never removed, and the NEXT run crashed on unique-
constraint collisions (company.domain, the (workspace_id, lower(email))
contact constraint, and idx_outreach_drafts_active_unique on
(workspace_id, contact_id, sequence_name, sequence_step)) instead of failing
cleanly or re-running successfully.

This version is idempotent: it reuses the same test company/contact across
runs (found by domain) rather than creating a new one every time, and picks
the next unused sequence_step for that contact automatically -- so a second,
third, or Nth run works the same as the first, indefinitely, with each
successful send permanently occupying the next step number.
"""

import os, sys, uuid, logging, datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

os.environ["SEND_WINDOW_START"] = "0"
os.environ["SEND_WINDOW_END"] = "0"

from backend.app.core.database import Database
from backend.app.core.config import get_settings
from backend.app.core.dispatch_scheduler import dispatch_workspace

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
REVIEWER_ID = "e463105c-4cdc-45e2-967d-66e3dd5728df"  # founder user ID
TO_EMAIL = "avanish.mehrotra@gmail.com"
TO_NAME = "Avanish"
COMPANY_NAME = "_canary_test_digitillis_internal"
COMPANY_DOMAIN = "internal.digitillis.io"
SEQUENCE_NAME = "email_value_first"

TEST_SUBJECT = "[CANARY TEST] ProspectIQ dispatch pipeline — please ignore"

TEST_BODY = """\
Hi Avanish,

This is an automated canary test of the ProspectIQ dispatch pipeline sent to verify
the full path: draft approval → outbound_queue claim → Resend API → delivery record.

If you received this, the pipeline is working correctly. You can delete it.

Best regards,
Avanish
"""


def _get_or_create_fixture(db: Database) -> tuple[str, str]:
    """Return (company_id, contact_id) for the reusable canary test fixture,
    creating it only if this is the first run ever."""
    existing = (
        db.client.table("companies")
        .select("id")
        .eq("domain", COMPANY_DOMAIN)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        co_id = existing[0]["id"]
        ct_row = (
            db.client.table("contacts").select("id").eq("company_id", co_id).limit(1).execute().data
        )
        ct_id = ct_row[0]["id"]
        print(f"Reusing existing canary test fixture: company {co_id} / contact {ct_id}")
        return co_id, ct_id

    co_id = str(uuid.uuid4())
    db.client.table("companies").insert(
        {
            "id": co_id,
            "name": COMPANY_NAME,
            "workspace_id": WORKSPACE_ID,
            "domain": COMPANY_DOMAIN,
            "industry": "Manufacturing",
            "campaign_cluster": "mfg",
            "tier": "mfg3",
        }
    ).execute()
    print(f"Created test company {co_id}")

    ct_id = str(uuid.uuid4())
    db.client.table("contacts").insert(
        {
            "id": ct_id,
            "company_id": co_id,
            "workspace_id": WORKSPACE_ID,
            "full_name": TO_NAME,
            "first_name": TO_NAME,
            "email": TO_EMAIL,
            "email_status": "verified",
            "is_outreach_eligible": True,
            "persona_type": "vp_ops",
        }
    ).execute()
    print(f"Created test contact {ct_id}")
    return co_id, ct_id


def _next_sequence_step(db: Database, ct_id: str) -> int:
    """Lowest unused sequence_step for this contact/sequence_name. A prior
    successful run permanently occupies its step (see module docstring), so
    each run naturally advances to the next one; assert_prior_step_sent is
    satisfied because that prior step, if it exists, was genuinely sent."""
    rows = (
        db.client.table("outreach_drafts")
        .select("sequence_step")
        .eq("contact_id", ct_id)
        .eq("sequence_name", SEQUENCE_NAME)
        .execute()
        .data
    )
    return (max((r["sequence_step"] for r in rows), default=0)) + 1


def main():
    settings = get_settings()
    if not settings.send_enabled:
        print("ERROR: SEND_ENABLED is false in .env — aborting. Set SEND_ENABLED=true.")
        sys.exit(1)

    db = Database()
    draft_id = q_id = None

    co_id, ct_id = _get_or_create_fixture(db)
    step = _next_sequence_step(db, ct_id)
    print(f"Using sequence_step={step} for this run")

    try:
        # 1. Create test draft (approved)
        draft_id = str(uuid.uuid4())
        db.client.table("outreach_drafts").insert(
            {
                "id": draft_id,
                "company_id": co_id,
                "contact_id": ct_id,
                "workspace_id": WORKSPACE_ID,
                "sequence_step": step,
                "sequence_name": SEQUENCE_NAME,
                "channel": "email",
                "subject": TEST_SUBJECT,
                "body": TEST_BODY,
                "personalization_notes": "https://digitillis.io — internal canary test",
                "approval_status": "approved",
                "approved_by": REVIEWER_ID,
                "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "model": "opus-via-claude-code",
            }
        ).execute()
        print(f"Created test draft {draft_id}")

        # 2. Enqueue (priority 5 = Step 1; lower number = higher urgency in ASC ORDER BY)
        q_row = (
            db.client.table("outbound_queue")
            .insert(
                {
                    "draft_id": draft_id,
                    "workspace_id": WORKSPACE_ID,
                    "priority": 5,
                    "retry_count": 0,
                }
            )
            .execute()
            .data[0]
        )
        q_id = q_row["id"]
        print(f"Enqueued → queue row {q_id}")

        # 3. Dispatch
        print("\nRunning dispatch_workspace() …")
        result = dispatch_workspace(db.client, WORKSPACE_ID, batch_size=1)
        print(
            f"\nResult: dispatched={result.dispatched} delivered={result.delivered} "
            f"assertion_skipped={result.assertion_skipped} "
            f"transient_failed={result.transient_failed} "
            f"permanently_failed={result.permanently_failed} "
            f"errors={result.errors}"
        )

        delivered = result.delivered == 1
        if delivered:
            print(f"\nSUCCESS — email dispatched to {TO_EMAIL}. Check your inbox.")
        elif result.assertion_skipped == 1:
            print("\nASSERTION_FAILED — pre-send check blocked the send (see logs above).")
        elif result.transient_failed == 1:
            print("\nTRANSIENT_FAILED — Resend returned a retriable error (see logs above).")
        elif result.permanently_failed == 1:
            print("\nPERMANENTLY_FAILED — Resend returned a permanent error (see logs above).")
        else:
            print("\nNo queue row was claimed — window/gate blocked before dispatch.")

    finally:
        # 4. Cleanup. The test company/contact are the reusable fixture --
        # never deleted. The queue row has no protection and is always
        # removed. The draft (+ its send_attempts) is only removable when
        # the send did NOT deliver; a delivered draft's sent_at is set, and
        # 003_protect_sent_emails.sql refuses that delete by design -- see
        # module docstring. That is the expected, correct outcome on
        # success, not an error.
        print("\nCleaning up …")
        if q_id:
            try:
                db.client.table("outbound_queue").delete().eq("id", q_id).execute()
                print(f"  Deleted queue row {q_id}")
            except Exception as e:
                print(f"  WARN: could not delete queue row: {e}")

        if draft_id:
            try:
                db.client.table("send_attempts").delete().eq("draft_id", draft_id).execute()
                db.client.table("outreach_drafts").delete().eq("id", draft_id).execute()
                print(f"  Deleted draft {draft_id} + send_attempts (did not deliver)")
            except Exception as e:
                if "protect_sent_emails" in str(e) or "Cannot delete sent" in str(e):
                    print(
                        f"  Draft {draft_id} left in place — it delivered, so it is now "
                        f"the permanent interaction record for sequence_step={step} "
                        f"(expected, not an error)"
                    )
                else:
                    print(f"  WARN: could not delete draft: {e}")

        print(
            "Cleanup done. Test company/contact were reused, not deleted -- "
            "they are the fixture the next run will use too."
        )


if __name__ == "__main__":
    main()
