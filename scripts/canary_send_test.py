#!/usr/bin/env python3
"""Canary send test — exercises the FULL dispatch pipeline (queue claim → Resend API → DB updates)
by sending ONE email to the founder's address. Cleans up test records on success or failure.

Run from /Users/avanish/prospectIQ:
    SEND_WINDOW_START=0 SEND_WINDOW_END=0 python3 scripts/canary_send_test.py
"""
import os, sys, uuid, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Load .env before any app imports so INSTANTLY_SEQ_* and other env vars are present
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

# Disable send window for this test run (override AFTER loading .env)
os.environ["SEND_WINDOW_START"] = "0"
os.environ["SEND_WINDOW_END"] = "0"

from backend.app.core.database import Database
from backend.app.core.config import get_settings
from backend.app.core.dispatch_scheduler import dispatch_workspace

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
REVIEWER_ID  = "e463105c-4cdc-45e2-967d-66e3dd5728df"   # founder user ID
TO_EMAIL     = "avanish.mehrotra@gmail.com"
TO_NAME      = "Avanish"
COMPANY_NAME = "_canary_test_digitillis_internal"

TEST_SUBJECT = "[CANARY TEST] ProspectIQ dispatch pipeline — please ignore"

TEST_BODY = """\
Hi Avanish,

This is an automated canary test of the ProspectIQ dispatch pipeline sent to verify
the full path: draft approval → outbound_queue claim → Resend API → delivery record.

If you received this, the pipeline is working correctly. You can delete it.

Best regards,
Avanish
"""

def main():
    settings = get_settings()
    if not settings.send_enabled:
        print("ERROR: SEND_ENABLED is false in .env — aborting. Set SEND_ENABLED=true.")
        sys.exit(1)

    db = Database()
    co_id = ct_id = draft_id = q_id = None

    try:
        # 1. Create test company
        co_id = str(uuid.uuid4())
        db.client.table("companies").insert({
            "id": co_id,
            "name": COMPANY_NAME,
            "workspace_id": WORKSPACE_ID,
            "domain": "internal.digitillis.io",
            "industry": "Manufacturing",
            "campaign_cluster": "mfg",
            "tier": "mfg3",
        }).execute()
        print(f"Created test company {co_id}")

        # 2. Create test contact
        ct_id = str(uuid.uuid4())
        db.client.table("contacts").insert({
            "id": ct_id,
            "company_id": co_id,
            "workspace_id": WORKSPACE_ID,
            "full_name": TO_NAME,
            "first_name": TO_NAME,
            "email": TO_EMAIL,
            "email_status": "verified",
            "is_outreach_eligible": True,
            "persona_type": "vp_ops",
        }).execute()
        print(f"Created test contact {ct_id}")

        # 3. Create test draft (approved)
        draft_id = str(uuid.uuid4())
        db.client.table("outreach_drafts").insert({
            "id": draft_id,
            "company_id": co_id,
            "contact_id": ct_id,
            "workspace_id": WORKSPACE_ID,
            "sequence_step": 1,
            "sequence_name": "email_value_first",
            "channel": "email",
            "subject": TEST_SUBJECT,
            "body": TEST_BODY,
            "personalization_notes": "https://digitillis.io — internal canary test",
            "approval_status": "approved",
            "approved_by": REVIEWER_ID,
            "reviewed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "model": "opus-via-claude-code",
        }).execute()
        print(f"Created test draft {draft_id}")

        # 4. Enqueue (priority 5 = Step 1; lower number = higher urgency in ASC ORDER BY)
        q_row = db.client.table("outbound_queue").insert({
            "draft_id": draft_id,
            "workspace_id": WORKSPACE_ID,
            "priority": 5,
            "retry_count": 0,
        }).execute().data[0]
        q_id = q_row["id"]
        print(f"Enqueued → queue row {q_id}")

        # 5. Dispatch
        print("\nRunning dispatch_workspace() …")
        result = dispatch_workspace(db.client, WORKSPACE_ID, batch_size=1)
        print(f"\nResult: dispatched={result.dispatched} delivered={result.delivered} "
              f"assertion_skipped={result.assertion_skipped} "
              f"transient_failed={result.transient_failed} "
              f"permanently_failed={result.permanently_failed} "
              f"errors={result.errors}")

        if result.delivered == 1:
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
        # 6. Cleanup — remove test records in reverse dependency order
        print("\nCleaning up test records …")
        try:
            if q_id:
                db.client.table("outbound_queue").delete().eq("id", q_id).execute()
                print(f"  Deleted queue row {q_id}")
        except Exception as e:
            print(f"  WARN: could not delete queue row: {e}")

        try:
            if draft_id:
                # Also clean up any send_attempts rows created for this draft
                db.client.table("send_attempts").delete().eq("draft_id", draft_id).execute()
                db.client.table("outreach_drafts").delete().eq("id", draft_id).execute()
                print(f"  Deleted draft {draft_id} + send_attempts")
        except Exception as e:
            print(f"  WARN: could not delete draft: {e}")

        try:
            if ct_id:
                db.client.table("contacts").delete().eq("id", ct_id).execute()
                print(f"  Deleted contact {ct_id}")
        except Exception as e:
            print(f"  WARN: could not delete contact: {e}")

        try:
            if co_id:
                db.client.table("companies").delete().eq("id", co_id).execute()
                print(f"  Deleted company {co_id}")
        except Exception as e:
            print(f"  WARN: could not delete company: {e}")

        print("Cleanup done.")

if __name__ == "__main__":
    main()
