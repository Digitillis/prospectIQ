"""Register Gmail app passwords for sender-pool accounts into CredentialStore.

Run this locally whenever a new inbox needs to be added to IMAP monitoring.
Credentials are encrypted and stored in workspace_credentials (Supabase).

Usage:
    python scripts/register_imap_credentials.py

The script prompts for an app password per account. Press Enter to skip any
account that is already registered or not yet ready.

Prerequisites:
  - CREDENTIAL_ENCRYPTION_KEY must be set in .env
  - DATABASE_URL must be set in .env
  - Each Google Workspace account must have 2FA enabled and an App Password
    generated at: https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

from backend.app.core.credential_store import CredentialStore

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

ACCOUNTS = [
    "avi@digitillis.io",          # primary — lives in env var, no DB entry needed
    "avanish@getdigitillis.com",
    "avanish@meetdigitillis.com",
    "avanish@trydigitillis.com",
    "avanish@usedigitillis.com",
    "hello@getdigitillis.com",
    "hello@meetdigitillis.com",
    "hello@trydigitillis.com",
    "hello@usedigitillis.com",
]


def _safe_key(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def main() -> None:
    store = CredentialStore(WORKSPACE_ID)

    print("Gmail IMAP credential registration")
    print("=" * 50)
    print("App passwords: https://myaccount.google.com/apppasswords")
    print("Press Enter to skip an account.\n")

    registered = 0
    for email in ACCOUNTS:
        if email == "avi@digitillis.io":
            print(f"  {email}: uses GMAIL_APP_PASSWORD env var — skip")
            continue

        provider = f"gmail_{_safe_key(email)}"
        existing = store.get(provider, "app_password")
        hint = f" [already set, hint=…{existing[-4:]}]" if existing else ""

        raw = input(f"  App password for {email}{hint}: ").strip()
        if not raw:
            print(f"    skipped")
            continue

        # Store email address too so the poller can use it
        store.set(provider, "app_password", raw)
        store.set(provider, "user", email)
        print(f"    stored (hint: …{raw[-4:]})")
        registered += 1

    print(f"\nDone. {registered} credential(s) registered.")
    print("Deploy to Railway for production IMAP coverage.")


if __name__ == "__main__":
    main()
