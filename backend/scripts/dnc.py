"""DNC registry CLI.

Manage the do-not-contact list: add, remove, and list entries.

Usage:
    python -m backend.scripts.dnc list
    python -m backend.scripts.dnc add --email ceo@acme.com --reason unsubscribed
    python -m backend.scripts.dnc add --domain competitor.com --reason competitor
    python -m backend.scripts.dnc remove --email ceo@acme.com
    python -m backend.scripts.dnc check --email ceo@acme.com
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from backend.app.core.dnc_registry import DNCRegistry, print_dnc_table

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(description="DNC registry manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List all DNC entries")

    # add
    add_p = sub.add_parser("add", help="Add an entry to the DNC list")
    add_p.add_argument("--email", help="Exact email to block")
    add_p.add_argument("--domain", help="Domain to block (all @domain.com)")
    add_p.add_argument("--reason", default="unsubscribed",
                       choices=["unsubscribed", "bounced", "competitor", "legal", "manual"])
    add_p.add_argument("--notes", default="", help="Optional notes")

    # remove
    rm_p = sub.add_parser("remove", help="Remove an entry from the DNC list")
    rm_p.add_argument("--email", help="Email to remove")
    rm_p.add_argument("--domain", help="Domain to remove")

    # check
    chk_p = sub.add_parser("check", help="Check whether an email/domain is blocked")
    chk_p.add_argument("--email", help="Email to check")
    chk_p.add_argument("--domain", help="Domain to check")

    args = parser.parse_args()
    dnc = DNCRegistry()

    if args.command == "list":
        entries = dnc.list_entries()
        if not entries:
            console.print("[dim]No DNC entries.[/dim]")
        else:
            console.print(f"\n[bold red]DNC Registry — {len(entries)} entries[/bold red]\n")
            print_dnc_table(entries)

    elif args.command == "add":
        if not args.email and not args.domain:
            console.print("[red]Must provide --email or --domain[/red]")
            sys.exit(1)
        entry = dnc.add_entry(
            email=args.email,
            domain=args.domain,
            reason=args.reason,
            added_by="cli",
            notes=args.notes,
        )
        val = args.email or args.domain
        console.print(f"[green]✓ Added to DNC: {val} ({args.reason})[/green]")

    elif args.command == "remove":
        if not args.email and not args.domain:
            console.print("[red]Must provide --email or --domain[/red]")
            sys.exit(1)
        removed = dnc.remove_entry(email=args.email, domain=args.domain)
        console.print(f"[green]Removed {removed} entries[/green]")

    elif args.command == "check":
        blocked, reason = dnc.is_blocked(email=args.email, domain=args.domain)
        val = args.email or args.domain
        if blocked:
            console.print(f"[red]✗ BLOCKED: {val} — {reason}[/red]")
        else:
            console.print(f"[green]✓ NOT blocked: {val}[/green]")


if __name__ == "__main__":
    main()
