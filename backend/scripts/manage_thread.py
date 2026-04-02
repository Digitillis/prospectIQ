"""Campaign Thread Manager — Interactive CLI.

Phase 1: Manual reply insertion + AI classification + human confirmation + draft next message
Phase 2: Check webhook queue for auto-captured replies needing review
Phase 3: Push approved reply to Instantly sending API

Usage:
    # Insert a reply manually and work through the flow
    python -m backend.scripts.manage_thread insert-reply

    # Review replies that came in via webhook (Phase 2)
    python -m backend.scripts.manage_thread review-webhook-queue

    # List all active threads
    python -m backend.scripts.manage_thread list-threads

    # Push approved draft to Instantly (Phase 3)
    python -m backend.scripts.manage_thread send --draft-id <uuid>
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich.text import Text
from rich import box

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
console = Console()

CLASSIFICATION_LABELS = {
    "interested":    "✅  Interested — open to a call/demo",
    "objection":     "⚡  Objection — specific pushback (incumbent, budget, timing)",
    "referral":      "➡️  Referral — pointing to someone else in the org",
    "soft_no":       "🌫️  Soft No — not now, but not a hard rejection",
    "out_of_office": "📅  Out of Office — auto-reply",
    "unsubscribe":   "🚫  Unsubscribe — remove me",
    "bounce":        "❌  Bounce — delivery failure",
    "other":         "❓  Other — needs human review",
}

CLASSIFICATION_KEYS = list(CLASSIFICATION_LABELS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_and_agent():
    from backend.app.core.database import Database
    from backend.app.agents.thread import ThreadAgent
    db = Database()
    agent = ThreadAgent(batch_id="thread_cli")
    return db, agent


def _pick_thread(db) -> dict | None:
    """Interactive thread picker — shows active/paused threads."""
    from backend.app.core.thread_manager import ThreadManager
    tm = ThreadManager(db)

    # Fetch all active/paused threads
    result = (
        db.client.table("campaign_threads")
        .select("*, companies(name, sub_sector, tier), contacts(full_name, title, email)")
        .in_("status", ["active", "paused"])
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
    )
    threads = result.data or []

    if not threads:
        console.print("[yellow]No active threads found.[/yellow]")
        return None

    table = Table(title="Active / Paused Threads", box=box.ROUNDED, show_lines=True)
    table.add_column("#", width=3)
    table.add_column("Company", max_width=30)
    table.add_column("Contact", max_width=25)
    table.add_column("Step", width=5, justify="center")
    table.add_column("Status", width=10)
    table.add_column("Last Reply")

    for i, t in enumerate(threads, start=1):
        company = t.get("companies") or {}
        contact = t.get("contacts") or {}
        last_replied = t.get("last_replied_at") or "—"
        if last_replied and last_replied != "—":
            last_replied = last_replied[:10]
        table.add_row(
            str(i),
            company.get("name", "?"),
            f"{contact.get('full_name', '?')}\n[dim]{contact.get('title', '')}[/dim]",
            str(t.get("current_step", 1)),
            f"[{'green' if t['status'] == 'active' else 'yellow'}]{t['status']}[/]",
            last_replied,
        )

    console.print(table)
    choice = IntPrompt.ask("Select thread #", default=1)
    idx = choice - 1
    if 0 <= idx < len(threads):
        return threads[idx]
    console.print("[red]Invalid selection.[/red]")
    return None


def _confirm_classification(ai_result: dict) -> tuple[str, float]:
    """Show AI classification and let user confirm or override (Option 3 with fallback).

    Returns (confirmed_classification, confidence).
    """
    classification = ai_result["classification"]
    confidence = ai_result["confidence"]
    reasoning = ai_result["reasoning"]
    signal = ai_result["extracted_signal"]

    console.print()
    console.print(Panel(
        f"[bold]AI Classification[/bold]\n\n"
        f"  Category:   [cyan]{CLASSIFICATION_LABELS.get(classification, classification)}[/cyan]\n"
        f"  Confidence: [{'green' if confidence >= 0.75 else 'yellow'}]{confidence*100:.0f}%[/]\n\n"
        f"  [dim]Reasoning:[/dim] {reasoning}\n"
        f"  [dim]Key signal:[/dim] {signal}",
        title="🤖 Classification Result",
        border_style="blue",
    ))

    console.print("\nOptions:")
    console.print("  [bold]1[/bold]  Confirm this classification")
    console.print("  [bold]2[/bold]  Choose a different classification")
    console.print("  [bold]3[/bold]  Skip this reply (come back later)")

    choice = Prompt.ask("Your choice", choices=["1", "2", "3"], default="1")

    if choice == "1":
        return classification, confidence

    elif choice == "2":
        console.print("\nAvailable classifications:")
        for i, (key, label) in enumerate(CLASSIFICATION_LABELS.items(), start=1):
            console.print(f"  [bold]{i}[/bold]  {label}")

        keys = list(CLASSIFICATION_LABELS.keys())
        while True:
            sel = IntPrompt.ask("Select classification #")
            if 1 <= sel <= len(keys):
                new_class = keys[sel - 1]
                console.print(f"\n[green]Changed to: {CLASSIFICATION_LABELS[new_class]}[/green]")
                return new_class, 1.0  # User-confirmed = full confidence
            console.print("[red]Invalid selection, try again.[/red]")

    else:  # choice == "3"
        return "", 0.0  # Caller treats empty string as skip


def _show_draft(draft: dict, contact_name: str) -> None:
    """Pretty-print the AI-drafted reply."""
    console.print()
    console.print(Panel(
        f"[dim]Subject:[/dim] {draft['subject']}\n\n"
        f"{draft['body']}\n\n"
        f"[dim]Strategy: {draft.get('strategy_used', '')}[/dim]",
        title=f"✉️  Draft Reply — To: {contact_name}",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Command: insert-reply (Phase 1)
# ---------------------------------------------------------------------------

def cmd_insert_reply():
    """Manually insert a reply, classify it, and draft the next message."""
    db, agent = _get_db_and_agent()
    from backend.app.core.thread_manager import ThreadManager
    tm = ThreadManager(db)

    console.print("\n[bold blue]═══ INSERT REPLY ═══[/bold blue]")
    console.print("[dim]Paste a reply you received and work through the adaptive thread flow.[/dim]\n")

    # Step 1: Pick or create a thread
    console.print("[bold]Step 1: Select the thread (company/contact)[/bold]")
    use_existing = Confirm.ask("Select from existing threads?", default=True)

    if use_existing:
        thread = _pick_thread(db)
        if not thread:
            # Offer to look up by email
            email = Prompt.ask("Enter contact email to search")
            thread = tm.find_thread_by_email(email)
            if not thread:
                console.print(f"[red]No active thread found for {email}.[/red]")
                console.print("[dim]Tip: use 'list-threads' to see all threads, or create one by running the outreach pipeline first.[/dim]")
                sys.exit(1)
    else:
        # Create a new thread from a contact email
        email = Prompt.ask("Contact email")
        contact_result = db.client.table("contacts").select("id, full_name, company_id").eq("email", email).limit(1).execute()
        if not contact_result.data:
            console.print(f"[red]No contact found with email {email}[/red]")
            sys.exit(1)
        contact = contact_result.data[0]
        thread = tm.get_or_create_thread(
            company_id=contact["company_id"],
            contact_id=contact["id"],
        )
        console.print(f"[green]Thread created: {thread['id']}[/green]")

    thread_id = thread["id"]

    # Step 2: Paste the reply
    console.print(f"\n[bold]Step 2: Paste the reply[/bold]")
    console.print("[dim](Press Enter twice when done)[/dim]")

    reply_subject = Prompt.ask("Reply subject line")

    console.print("Reply body (paste, then type END on a new line):")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    reply_body = "\n".join(lines).strip()

    if not reply_body:
        console.print("[red]Empty reply body. Aborting.[/red]")
        sys.exit(1)

    reply_date = Prompt.ask("Reply date (YYYY-MM-DD, or press Enter for today)", default="")
    sent_at = f"{reply_date}T00:00:00+00:00" if reply_date else None

    # Step 3: Classify with Sonnet
    console.print("\n[bold]Step 3: Classifying reply...[/bold]")
    with console.status("[dim]Calling Claude Sonnet...[/dim]"):
        ai_result = agent.classify_reply(
            thread_id=thread_id,
            reply_subject=reply_subject,
            reply_body=reply_body,
            sent_at=sent_at,
            source="manual",
        )

    # Step 4: Confirm or override classification (Option 3 with fallback)
    console.print("\n[bold]Step 4: Confirm classification[/bold]")
    confirmed_class, confirmed_conf = _confirm_classification(ai_result)

    if not confirmed_class:
        console.print("[yellow]Skipped — thread remains paused for later review.[/yellow]")
        sys.exit(0)

    # Apply the confirmed classification
    agent._apply_classification_actions(
        thread=ai_result["thread"],
        message_id=ai_result["message_id"],
        classification=confirmed_class,
        confidence=confirmed_conf,
        reasoning=ai_result["reasoning"],
        confirmed_by="user",
    )

    # Handle terminal classifications
    if confirmed_class in ("unsubscribe", "bounce"):
        console.print(f"[yellow]Thread closed ({confirmed_class}). No reply needed.[/yellow]")
        sys.exit(0)

    if confirmed_class == "out_of_office":
        return_date = ai_result.get("return_date")
        msg = "Thread paused."
        if return_date:
            msg += f" Return date noted: {return_date}. Follow up after that date."
        console.print(f"[dim]{msg}[/dim]")
        sys.exit(0)

    # Step 5: Draft the next message
    console.print("\n[bold]Step 5: Drafting reply with Claude Sonnet...[/bold]")

    # Inject the confirmed classification back into ai_result before drafting
    ai_result["classification"] = confirmed_class

    while True:
        with console.status("[dim]Drafting...[/dim]"):
            draft = agent.draft_next_message(ai_result)

        contact = ai_result.get("contact", {})
        _show_draft(draft, contact.get("full_name", "contact"))

        console.print("\nOptions:")
        console.print("  [bold]1[/bold]  Save as pending draft (you'll send manually / via Instantly)")
        console.print("  [bold]2[/bold]  Regenerate draft")
        console.print("  [bold]3[/bold]  Skip — save classification only, draft later")

        action = Prompt.ask("Your choice", choices=["1", "2", "3"], default="1")

        if action == "1":
            draft_id = agent.save_draft(
                thread=ai_result["thread"],
                contact=contact,
                draft=draft,
                classification=confirmed_class,
            )
            console.print(f"\n[green]✓ Draft saved (ID: {draft_id})[/green]")
            console.print("[dim]Approve and send via: python -m backend.scripts.manage_thread send --draft-id " + (draft_id or "?") + "[/dim]")
            break
        elif action == "2":
            console.print("[dim]Regenerating...[/dim]")
            continue
        else:
            console.print("[dim]Draft skipped. Thread remains paused.[/dim]")
            break

    console.print("\n[bold green]Done.[/bold green]")


# ---------------------------------------------------------------------------
# Command: review-webhook-queue (Phase 2)
# ---------------------------------------------------------------------------

def cmd_review_webhook_queue():
    """Review auto-captured replies that need human classification confirmation."""
    db, agent = _get_db_and_agent()

    # Find inbound messages without a confirmed classification
    result = (
        db.client.table("thread_messages")
        .select("*, campaign_threads(company_id, contact_id, current_step, status)")
        .eq("direction", "inbound")
        .is_("classification_confirmed_by", "null")
        .order("created_at")
        .limit(20)
        .execute()
    )
    pending = result.data or []

    if not pending:
        console.print("[green]No replies pending review.[/green]")
        return

    console.print(f"\n[bold]{len(pending)} replies need your review.[/bold]\n")

    for msg in pending:
        thread_data = msg.get("campaign_threads") or {}
        company_id = thread_data.get("company_id") or msg.get("thread_id")

        company = db.get_company(company_id) if company_id else {}
        company_name = (company or {}).get("name", "Unknown")

        console.print(Panel(
            f"[bold]{company_name}[/bold]\n"
            f"[dim]{msg.get('subject', '(no subject)')}[/dim]\n\n"
            f"{(msg.get('body') or '')[:400]}"
            + ("..." if len(msg.get("body") or "") > 400 else ""),
            title=f"Reply from {msg.get('sent_at', '')[:10]}",
        ))

        # If there's an AI classification already (from auto-capture), show it
        if msg.get("classification") and not msg.get("classification_confirmed_by"):
            console.print(
                f"[dim]AI suggested: {CLASSIFICATION_LABELS.get(msg['classification'], msg['classification'])} "
                f"({(msg.get('classification_confidence') or 0)*100:.0f}% confidence)[/dim]"
            )

        # Build a mock ai_result for _confirm_classification
        mock_result = {
            "classification": msg.get("classification") or "other",
            "confidence": msg.get("classification_confidence") or 0.5,
            "reasoning": msg.get("classification_reasoning") or "Auto-captured via webhook",
            "extracted_signal": "",
        }
        confirmed_class, confirmed_conf = _confirm_classification(mock_result)

        if not confirmed_class:
            continue

        thread_id = msg["thread_id"]
        thread = db.client.table("campaign_threads").select("*").eq("id", thread_id).execute()
        thread_row = thread.data[0] if thread.data else {}

        agent._apply_classification_actions(
            thread=thread_row,
            message_id=msg["id"],
            classification=confirmed_class,
            confidence=confirmed_conf,
            reasoning=mock_result["reasoning"],
            confirmed_by="user",
        )

        if confirmed_class in ("unsubscribe", "bounce", "out_of_office"):
            console.print(f"[yellow]Handled: {confirmed_class}[/yellow]\n")
            continue

        # Draft reply
        ai_result = {
            "thread": thread_row,
            "company": company,
            "contact": {},
            "research": db.get_research(company_id) if company_id else {},
            "reply_subject": msg.get("subject", ""),
            "reply_body": msg.get("body", ""),
            "classification": confirmed_class,
            "reasoning": mock_result["reasoning"],
            "extracted_signal": mock_result["extracted_signal"],
            "recommended_next_action": "",
            "message_id": msg["id"],
        }

        contacts = db.get_contacts_for_company(company_id) if company_id else []
        contact = next((c for c in contacts if c["id"] == thread_row.get("contact_id")), {})
        ai_result["contact"] = contact

        with console.status("[dim]Drafting reply...[/dim]"):
            draft = agent.draft_next_message(ai_result)

        _show_draft(draft, contact.get("full_name", "contact"))

        save = Confirm.ask("Save as pending draft?", default=True)
        if save:
            draft_id = agent.save_draft(
                thread=thread_row,
                contact=contact,
                draft=draft,
                classification=confirmed_class,
            )
            console.print(f"[green]✓ Draft saved ({draft_id})[/green]\n")


# ---------------------------------------------------------------------------
# Command: list-threads
# ---------------------------------------------------------------------------

def cmd_list_threads():
    """List all active and paused threads with their status."""
    db, _ = _get_db_and_agent()

    result = (
        db.client.table("campaign_threads")
        .select("*, companies(name, sub_sector, tier), contacts(full_name, email)")
        .order("updated_at", desc=True)
        .limit(100)
        .execute()
    )
    threads = result.data or []

    if not threads:
        console.print("[yellow]No threads found.[/yellow]")
        return

    table = Table(title=f"Campaign Threads ({len(threads)} total)", box=box.ROUNDED, show_lines=True)
    table.add_column("Company", max_width=28)
    table.add_column("Contact", max_width=24)
    table.add_column("Seq", width=5, justify="center")
    table.add_column("Status", width=12)
    table.add_column("Last Sent", width=11)
    table.add_column("Last Reply", width=11)

    for t in threads:
        company = t.get("companies") or {}
        contact = t.get("contacts") or {}
        status = t["status"]
        color = {
            "active": "green", "paused": "yellow", "converted": "blue",
            "closed": "dim", "unsubscribed": "red", "bounced": "red",
        }.get(status, "white")
        table.add_row(
            company.get("name", "?"),
            f"{contact.get('full_name', '?')}\n[dim]{contact.get('email', '')}[/dim]",
            f"{t.get('current_step', 1)}→{t.get('next_step', '?')}",
            f"[{color}]{status}[/]",
            (t.get("last_sent_at") or "—")[:10],
            (t.get("last_replied_at") or "—")[:10],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Command: send (Phase 3) — push approved draft to Instantly
# ---------------------------------------------------------------------------

def cmd_send(draft_id: str | None = None):
    """Push an approved reply draft to Instantly sending API (Phase 3)."""
    db, _ = _get_db_and_agent()

    if not draft_id:
        # Show pending drafts from thread replies
        result = (
            db.client.table("outreach_drafts")
            .select("id, company_id, subject, created_at, personalization_notes, approval_status")
            .eq("approval_status", "pending")
            .ilike("sequence_name", "thread_reply_%")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        drafts = result.data or []
        if not drafts:
            console.print("[yellow]No pending thread reply drafts.[/yellow]")
            return

        table = Table(title="Pending Thread Reply Drafts", box=box.ROUNDED)
        table.add_column("#", width=3)
        table.add_column("Draft ID", width=10)
        table.add_column("Subject", max_width=40)
        table.add_column("Created")
        for i, d in enumerate(drafts, 1):
            table.add_row(
                str(i),
                d["id"][:8] + "...",
                d.get("subject", "?"),
                (d.get("created_at") or "")[:16],
            )
        console.print(table)
        idx = IntPrompt.ask("Select draft #") - 1
        if not (0 <= idx < len(drafts)):
            console.print("[red]Invalid selection[/red]")
            return
        draft_id = drafts[idx]["id"]

    # Fetch the draft
    draft_result = db.client.table("outreach_drafts").select("*").eq("id", draft_id).execute()
    if not draft_result.data:
        console.print(f"[red]Draft {draft_id} not found[/red]")
        return
    draft = draft_result.data[0]

    contacts = db.get_contacts_for_company(draft["company_id"])
    contact = next((c for c in contacts if c["id"] == draft.get("contact_id")), {})
    company = db.get_company(draft["company_id"]) or {}

    console.print(Panel(
        f"To: {contact.get('full_name', '?')} <{contact.get('email', '?')}>\n"
        f"Subject: {draft.get('subject', '?')}\n\n"
        f"{draft.get('body', '')}",
        title=f"📧  Sending to {company.get('name', '?')}",
        border_style="green",
    ))

    if not Confirm.ask("Send this via Instantly?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return

    # Phase 3: Instantly sending API — reply in-thread using /emails/reply
    try:
        from backend.app.integrations.instantly import InstantlyClient
        from backend.app.core.sequence_router import get_campaign_id_for_company
        from backend.app.core.thread_manager import ThreadManager

        instantly = InstantlyClient()

        # Resolve campaign ID — prefer what's stored on the thread, then fall back to routing
        tm = ThreadManager(db)
        thread = tm.get_thread_by_contact(draft["company_id"], draft.get("contact_id", ""))
        campaign_id = (thread or {}).get("instantly_campaign_id") or get_campaign_id_for_company(
            company, contact.get("persona_type")
        )
        if not campaign_id:
            console.print("[red]No Instantly campaign found for this thread. Cannot send.[/red]")
            return

        contact_email = contact.get("email", "")
        sent_via = "unknown"

        # --- Preferred path: reply in-thread via /emails/reply ---------------
        # This preserves email headers (In-Reply-To, References) so it lands
        # as a true reply in the prospect's inbox, not a new cold email.
        email_record = None
        try:
            email_record = instantly.get_email_by_lead(contact_email, campaign_id)
        except Exception as exc:
            logger.warning(f"get_email_by_lead failed ({exc}); will fall back to add_lead")

        if email_record and email_record.get("id"):
            email_id = email_record["id"]
            body_text = draft.get("body", "")
            body_html = body_text.replace("\n", "<br>")
            instantly.reply_to_email(
                reply_to_email_id=email_id,
                subject=draft.get("subject", ""),
                body_html=body_html,
                body_text=body_text,
            )
            sent_via = "reply_to_email"
            console.print(f"[green]✓ Replied in-thread via Instantly (email_id: {email_id[:12]}...)[/green]")

        else:
            # --- Fallback: add as campaign lead (sends as new email) ----------
            # This happens when the original email ID is unavailable — e.g. the
            # sequence was manually started before thread tracking existed.
            console.print(
                "[yellow]⚠️  Could not locate original email thread — "
                "sending as new campaign email (not in-thread).[/yellow]"
            )
            lead_payload = {
                "email": contact_email,
                "first_name": contact.get("first_name", ""),
                "last_name": contact.get("last_name", ""),
                "company_name": company.get("name", ""),
                "website": company.get("domain", ""),
                "personalization": draft.get("body", ""),
            }
            instantly.add_lead_to_campaign(campaign_id, lead_payload)
            sent_via = "add_lead_to_campaign"
            console.print(f"[green]✓ Sent via Instantly (campaign: {campaign_id})[/green]")

        # --- Update draft status and record in thread -----------------------
        db.client.table("outreach_drafts").update({
            "approval_status": "approved",
        }).eq("id", draft_id).execute()

        if thread:
            tm.add_outbound_message(
                thread_id=thread["id"],
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                outreach_draft_id=draft_id,
                source="instantly_webhook",
            )
            tm.resume_thread(thread["id"], advance_step=True)

        console.print(f"[dim]Sent via: {sent_via}[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to send: {e}[/red]")
        logger.error(f"Phase 3 send failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Webhook endpoint (Phase 2) — called by Instantly webhook handler
# ---------------------------------------------------------------------------

def register_webhook_routes(app):
    """Register the Instantly webhook route on a FastAPI app (Phase 2).

    Usage in your FastAPI main.py:
        from backend.scripts.manage_thread import register_webhook_routes
        register_webhook_routes(app)
    """
    from fastapi import Request, HTTPException

    @app.post("/webhooks/instantly/reply")
    async def instantly_reply_webhook(request: Request):
        """Receives reply notifications from Instantly."""
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Instantly webhook payload shape (v2):
        # { "type": "reply_received", "data": { "from_address": "...", "subject": "...", "body": "...", "timestamp": "..." } }
        event_type = payload.get("type") or payload.get("event_type")
        if event_type not in ("reply_received", "EMAIL_REPLY"):
            return {"status": "ignored", "reason": f"event_type={event_type}"}

        data = payload.get("data") or payload
        sender_email = data.get("from_address") or data.get("from") or data.get("reply_from")
        subject = data.get("subject", "")
        body = data.get("body") or data.get("body_text") or data.get("content", "")
        sent_at = data.get("timestamp") or data.get("received_at")

        if not sender_email or not body:
            return {"status": "ignored", "reason": "missing sender_email or body"}

        from dotenv import load_dotenv
        from pathlib import Path as _Path
        load_dotenv(_Path(__file__).resolve().parent.parent.parent / ".env")

        from backend.app.core.database import Database
        from backend.app.agents.thread import ThreadAgent

        db = Database()
        agent = ThreadAgent(batch_id="webhook_reply")

        result = agent.process_webhook_reply(
            sender_email=sender_email,
            reply_subject=subject,
            reply_body=body,
            sent_at=sent_at,
            raw_payload=payload,
        )

        if result is None:
            return {"status": "no_thread_found", "email": sender_email}

        return {
            "status": "processed",
            "thread_id": result["thread"]["id"],
            "classification": result.get("classification"),
            "auto_confirmed": result.get("auto_confirmed", False),
            "needs_review": result.get("needs_review", False),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Campaign Thread Manager — adaptive outreach with response handling."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("insert-reply", help="Manually insert a reply and work through the flow (Phase 1)")
    sub.add_parser("review-webhook-queue", help="Review auto-captured replies needing confirmation (Phase 2)")
    sub.add_parser("list-threads", help="List all active threads")
    send_p = sub.add_parser("send", help="Push approved reply to Instantly (Phase 3)")
    send_p.add_argument("--draft-id", default=None, help="Specific draft ID to send")

    args = parser.parse_args()

    if args.command == "insert-reply":
        cmd_insert_reply()
    elif args.command == "review-webhook-queue":
        cmd_review_webhook_queue()
    elif args.command == "list-threads":
        cmd_list_threads()
    elif args.command == "send":
        cmd_send(draft_id=args.draft_id)
    else:
        parser.print_help()
