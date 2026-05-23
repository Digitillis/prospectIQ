"""
One-time Gmail OAuth setup script.

Run this locally to generate a refresh token for the Gmail API.
It will open a browser window for you to authorize with avi@digitillis.io.

Prerequisites:
  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client

Steps:
  1. Complete Google Cloud Console setup (see instructions printed below)
  2. Download your OAuth credentials JSON and save it as:
       /Users/avanish/prospectIQ/gmail_oauth_credentials.json
  3. Run: python3 scripts/gmail_oauth_setup.py
  4. Authorize in the browser with avi@digitillis.io
  5. Copy the three values printed at the end into Railway Variables

DO NOT commit gmail_oauth_credentials.json or gmail_oauth_token.json to git.
"""

import json
import os
import sys

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "..", "gmail_oauth_credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "gmail_oauth_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

INSTRUCTIONS = """
============================================================
BEFORE RUNNING THIS SCRIPT — complete these steps first:
============================================================

1. Go to https://console.cloud.google.com
2. Create a new project named "ProspectIQ" (or select existing)
3. Go to "APIs & Services" -> "Library"
4. Search for "Gmail API" and click "Enable"
5. Go to "APIs & Services" -> "OAuth consent screen"
   - User type: Internal (since avi@digitillis.io is a Google Workspace account)
   - App name: ProspectIQ
   - User support email: avi@digitillis.io
   - Developer contact: avi@digitillis.io
   - Click Save and Continue through the scopes/test users screens
6. Go to "APIs & Services" -> "Credentials"
   - Click "+ Create Credentials" -> "OAuth 2.0 Client ID"
   - Application type: Desktop app
   - Name: ProspectIQ Desktop
   - Click Create
7. Click the download icon next to the new credential
8. Save the downloaded file as:
     /Users/avanish/prospectIQ/gmail_oauth_credentials.json
9. Run this script again

============================================================
"""


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("Missing dependencies. Run:")
        print("  pip3 install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        sys.exit(1)

    if not os.path.exists(CREDENTIALS_FILE):
        print(INSTRUCTIONS)
        print(f"Credentials file not found at: {CREDENTIALS_FILE}")
        print("Complete the steps above, then run this script again.")
        sys.exit(1)

    print("Opening browser for Gmail authorization...")
    print("Sign in with: avi@digitillis.io\n")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token locally for reference
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    token_data = json.loads(creds.to_json())

    print("\n" + "=" * 60)
    print("SUCCESS. Add these three variables to Railway:")
    print("=" * 60)
    print(f"\nGMAIL_CLIENT_ID\n  {token_data['client_id']}")
    print(f"\nGMAIL_CLIENT_SECRET\n  {token_data['client_secret']}")
    print(f"\nGMAIL_REFRESH_TOKEN\n  {token_data['refresh_token']}")
    print("\n" + "=" * 60)
    print("Also add: GMAIL_ACCOUNT = avi@digitillis.io")
    print("=" * 60)
    print(f"\nToken saved locally to: {TOKEN_FILE}")
    print("Do NOT commit that file to git.")


if __name__ == "__main__":
    main()
