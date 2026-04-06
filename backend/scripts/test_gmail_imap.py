"""Test Gmail IMAP connection and preview unseen reply emails.

Run once to verify credentials and see what replies would be processed.
Does NOT mark emails as read or write anything to the database.

Usage:
    # Using env vars from .env:
    python backend/scripts/test_gmail_imap.py

    # Or pass credentials directly:
    python backend/scripts/test_gmail_imap.py --user avi@digitillis.io --password "xxxx xxxx xxxx xxxx"

Setup:
    1. In Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP
    2. Go to myaccount.google.com/apppasswords
       (Google Account → Security → 2-Step Verification → App passwords)
    3. Create app password: Select app "Mail", device "Other (Custom name)" → "ProspectIQ"
    4. Copy the 16-character password (format: xxxx xxxx xxxx xxxx)
    5. Add to .env:
         GMAIL_USER=avi@digitillis.io
         GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from rich.console import Console
from rich.table import Table

from backend.app.integrations.gmail_imap import GmailImapClient, _classify_intent

console = Console()


def main(user: str | None = None, password: str | None = None) -> None:
    if not user or not password:
        from backend.app.core.config import get_settings
        settings = get_settings()
        user = user or settings.gmail_user
        password = password or settings.gmail_app_password

    if not user or not password:
        console.print("[red]GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env or passed as args[/red]")
        console.print("\n[bold]Setup instructions:[/bold]")
        console.print("  1. Gmail Settings → Forwarding and POP/IMAP → [bold]Enable IMAP[/bold]")
        console.print("  2. myaccount.google.com/apppasswords → Create 'ProspectIQ' app password")
        console.print("  3. Add to .env:")
        console.print("       GMAIL_USER=avi@digitillis.io")
        console.print("       GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")
        return

    console.print(f"[cyan]Connecting to Gmail IMAP as {user}...[/cyan]")

    try:
        with GmailImapClient(user, password) as gmail:
            console.print("[green]✓ Connected[/green]")
            replies = gmail.fetch_unseen_replies()

        if not replies:
            console.print("[yellow]No unseen reply emails found in INBOX.[/yellow]")
            console.print("(This is fine if you have no unread replies — try sending a test reply to yourself.)")
            return

        console.print(f"\n[bold]{len(replies)} unseen reply email(s) found:[/bold]")

        table = Table(show_lines=True)
        table.add_column("From", width=30)
        table.add_column("Subject", width=40)
        table.add_column("Intent", width=15)
        table.add_column("Preview", width=50)

        for reply in replies:
            intent = _classify_intent(reply["body"], reply["subject"])
            preview = (reply["body"] or "")[:100].replace("\n", " ")
            table.add_row(
                reply["from_email"],
                reply["subject"][:40],
                intent,
                preview,
            )

        console.print(table)
        console.print("\n[dim]No emails marked as read — this was a dry run.[/dim]")

    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")
        if "Invalid credentials" in str(e) or "authentication failed" in str(e).lower():
            console.print("\n[yellow]Tip: Make sure you're using an App Password, not your regular Gmail password.[/yellow]")
            console.print("App passwords require 2-Step Verification to be enabled on the account.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Gmail IMAP connection")
    parser.add_argument("--user", help="Gmail address (default: GMAIL_USER from .env)")
    parser.add_argument("--password", help="App password (default: GMAIL_APP_PASSWORD from .env)")
    args = parser.parse_args()
    main(user=args.user, password=args.password)
