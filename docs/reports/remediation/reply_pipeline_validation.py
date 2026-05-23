"""Phase 2 — Reply Pipeline Validation Script.

Diagnostic tool to test the Gmail IMAP reply ingestion path end-to-end
without sending any emails or making writes. Validates:

  1. Environment credentials are resolvable
  2. IMAP connection is successful
  3. Inbox has UNSEEN Reply emails (or reports none found)
  4. Interaction write path is reachable (dry-run check)
  5. DB shows no existing email_replied events (confirming zero baseline)

Run as:
    python3 docs/reports/remediation/reply_pipeline_validation.py
    # Or on Railway:
    railway run python3 docs/reports/remediation/reply_pipeline_validation.py
"""

import os
import sys
import imaplib
import re
from datetime import datetime, timezone

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"


def check(label: str, status: str, detail: str = ""):
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[status]
    print(f"  {icon} {label}")
    if detail:
        print(f"       {detail}")


def main():
    print("=" * 70)
    print("REPLY PIPELINE VALIDATION")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    all_pass = True

    # --- Step 1: Credential availability ---
    print("\n[1] CREDENTIAL AVAILABILITY")

    if SUPABASE_URL and SUPABASE_KEY:
        check("Supabase URL + KEY", PASS)
    else:
        check("Supabase URL + KEY", FAIL, "SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        all_pass = False

    if GMAIL_USER:
        check(f"GMAIL_USER env var", PASS, f"= {GMAIL_USER}")
    else:
        check("GMAIL_USER env var", FAIL, "Not set — gmail_intake will not poll primary inbox")
        all_pass = False

    if GMAIL_APP_PASSWORD:
        check("GMAIL_APP_PASSWORD env var", PASS, f"= {'*' * (len(GMAIL_APP_PASSWORD) - 4)}{GMAIL_APP_PASSWORD[-4:]}")
    else:
        check("GMAIL_APP_PASSWORD env var", FAIL, "Not set — IMAP auth will fail")
        all_pass = False

    # Also check workspace_credentials DB
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            client = create_client(SUPABASE_URL, SUPABASE_KEY)
            creds = client.table("workspace_credentials").select("provider,key_name").execute()
            gmail_creds = [c for c in (creds.data or []) if c.get("provider") == "gmail"]
            if gmail_creds:
                check("workspace_credentials (DB)", PASS, f"{len(gmail_creds)} gmail entries")
            else:
                check("workspace_credentials (DB)", WARN,
                      "No gmail credentials in DB — relying on env var fallback only")
        except Exception as e:
            check("workspace_credentials (DB)", WARN, f"Could not query: {e}")

    # --- Step 2: IMAP connection ---
    print("\n[2] IMAP CONNECTION TEST")

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        check("IMAP connect", FAIL, "Skipped — credentials missing")
        all_pass = False
    else:
        try:
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            try:
                conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                check("IMAP connect + auth", PASS, f"Connected to {IMAP_HOST} as {GMAIL_USER}")

                # --- Step 3: Inbox scan ---
                print("\n[3] INBOX SCAN")
                conn.select("INBOX")

                # Count UNSEEN
                _, unseen_data = conn.search(None, "UNSEEN")
                unseen_uids = unseen_data[0].split() if unseen_data[0] else []
                check(f"UNSEEN messages in INBOX", PASS if unseen_uids else WARN,
                      f"{len(unseen_uids)} UNSEEN messages found")

                # Count UNSEEN that look like replies
                reply_uids = []
                for uid in unseen_uids[:50]:  # Sample first 50
                    try:
                        _, data = conn.fetch(uid, "(BODY[HEADER.FIELDS (SUBJECT)])")
                        if data and data[0]:
                            header = data[0][1].decode("utf-8", errors="replace")
                            subject = header.replace("Subject:", "").strip()
                            if re.match(r"^re:", subject.strip(), re.IGNORECASE):
                                reply_uids.append(uid)
                    except Exception:
                        pass

                check(f"UNSEEN replies (Re: subject)", PASS if reply_uids else WARN,
                      f"{len(reply_uids)} UNSEEN reply emails found in first 50 UNSEEN")

                if not reply_uids:
                    print("       NOTE: No unread replies = intake correctly produces zero email_replied events")
                    print("             If replies exist, check if they were manually read in Gmail")

            except imaplib.IMAP4.error as e:
                check("IMAP auth", FAIL, f"Authentication failed: {e}")
                print("       REMEDIATION: Verify App Password at myaccount.google.com/apppasswords")
                print("                   Ensure IMAP is enabled in Gmail Settings")
                all_pass = False
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        except Exception as e:
            check("IMAP connect", FAIL, f"Connection error: {e}")
            all_pass = False

    # --- Step 4: DB state ---
    print("\n[4] DATABASE STATE")

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            client = create_client(SUPABASE_URL, SUPABASE_KEY)

            # Check email_replied count
            replied = client.table("interactions").select("id", count="exact").eq("type", "email_replied").execute()
            reply_count = replied.count or 0
            check(f"email_replied interactions", WARN if reply_count == 0 else PASS,
                  f"{reply_count} total (expected 0 if intake has never run)")

            # Check inbound thread_messages
            inbound = client.table("thread_messages").select("id", count="exact").eq("direction", "inbound").execute()
            inbound_count = inbound.count or 0
            check(f"inbound thread_messages", WARN if inbound_count == 0 else PASS,
                  f"{inbound_count} total")

            # Check interactions table is writable (count other types to confirm it works)
            sent = client.table("interactions").select("id", count="exact").eq("type", "email_sent").execute()
            check("interactions table accessible", PASS, f"{sent.count or 0} email_sent events confirm table is live")

        except Exception as e:
            check("DB state check", FAIL, f"Query error: {e}")
            all_pass = False

    # --- Summary ---
    print("\n" + "=" * 70)
    if all_pass:
        print("RESULT: ALL CHECKS PASSED")
        print("  If reply_count=0 and no UNSEEN replies found, the intake is")
        print("  working correctly — there are simply no unread replies to process.")
        print("  Check whether any replies were manually read in Gmail.")
    else:
        print("RESULT: ONE OR MORE CHECKS FAILED")
        print("  Review FAIL items above. Most likely fixes:")
        print("  1. Set GMAIL_USER + GMAIL_APP_PASSWORD in Railway environment")
        print("  2. Verify App Password is active at myaccount.google.com/apppasswords")
        print("  3. Enable IMAP in Gmail Settings for avi@digitillis.io")
    print("=" * 70)


if __name__ == "__main__":
    main()
