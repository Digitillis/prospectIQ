"""Bounce suppression hygiene.

Reconciles ``outreach_drafts.bounced_at`` events back onto the contact and
DNC tables so a single bounce permanently disqualifies the contact (and any
contact under the same domain once a per-domain threshold is hit).

The Resend / Instantly webhooks stamp ``bounced_at`` on the draft row but
do not always flip ``contacts.status`` or insert into ``do_not_contact``.
This job is the safety net: a daily sweep that catches anything the
webhooks missed and writes the suppression so the next send cycle skips
the contact.

Usage:
    from backend.app.core.bounce_suppressor import run_bounce_suppression
    from backend.app.core.database import Database

    summary = run_bounce_suppression(Database(workspace_id=ws_id))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from backend.app.core.database import Database
from backend.app.core.dnc_registry import DNCRegistry

logger = logging.getLogger(__name__)


# Contacts must accumulate at least this many bounced contacts under one
# domain before the whole domain is blocked. Three independent bounces is
# the heuristic Postmark and Resend both use as evidence the MX/catch-all
# is rejecting cold mail rather than a single stale address.
DOMAIN_BOUNCE_THRESHOLD = 3


def _domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


def _fetch_bounced_drafts(db: Database) -> list[dict[str, Any]]:
    """Return every bounced draft for the workspace with the joined contact."""
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        q = db._filter_ws(
            db.client.table("outreach_drafts").select(
                "id, contact_id, workspace_id, bounced_at, contacts(id, email, status, is_outreach_eligible)"
            )
        ).not_.is_("bounced_at", "null")
        page = q.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _existing_dnc_emails(db: Database, emails: set[str]) -> set[str]:
    """Return the subset of ``emails`` already present in do_not_contact."""
    if not emails:
        return set()
    found: set[str] = set()
    chunk: list[str] = []
    # Supabase IN-clause is URL-bounded; chunk to stay under the 8KB limit.
    for email in emails:
        chunk.append(email)
        if len(chunk) >= 200:
            res = db.client.table("do_not_contact").select("email").in_("email", chunk).execute()
            for row in res.data or []:
                if row.get("email"):
                    found.add(row["email"].lower())
            chunk = []
    if chunk:
        res = db.client.table("do_not_contact").select("email").in_("email", chunk).execute()
        for row in res.data or []:
            if row.get("email"):
                found.add(row["email"].lower())
    return found


def _existing_dnc_domains(db: Database, domains: set[str]) -> set[str]:
    if not domains:
        return set()
    res = db.client.table("do_not_contact").select("domain").in_("domain", list(domains)).execute()
    return {row["domain"].lower() for row in (res.data or []) if row.get("domain")}


def run_bounce_suppression(db: Database) -> dict[str, Any]:
    """Sweep bounced drafts, suppress contacts and high-bounce domains.

    Returns a summary dict shaped:
        {
          "contacts_suppressed": int,
          "domains_suppressed": int,
          "already_suppressed": int,
          "errors": list[str],
        }
    """
    summary: dict[str, Any] = {
        "contacts_suppressed": 0,
        "domains_suppressed": 0,
        "already_suppressed": 0,
        "errors": [],
    }

    workspace_id = db.workspace_id
    if not workspace_id:
        logger.warning("run_bounce_suppression called without workspace_id — skipping")
        summary["errors"].append("missing_workspace_id")
        return summary

    try:
        drafts = _fetch_bounced_drafts(db)
    except Exception as exc:
        logger.error("run_bounce_suppression: failed to fetch bounced drafts: %s", exc)
        summary["errors"].append(f"fetch_failed:{exc}")
        return summary

    # De-duplicate on (contact_id, email) — multiple bounced drafts for the
    # same contact only count once for the domain threshold.
    by_contact: dict[str, dict[str, Any]] = {}
    for row in drafts:
        contact = row.get("contacts") or {}
        contact_id = row.get("contact_id") or contact.get("id")
        email = (contact.get("email") or "").strip().lower()
        if not contact_id or not email:
            continue
        if contact_id in by_contact:
            continue
        by_contact[contact_id] = {
            "contact_id": contact_id,
            "email": email,
            "status": contact.get("status"),
            "is_outreach_eligible": contact.get("is_outreach_eligible"),
        }

    if not by_contact:
        logger.info(
            "run_bounce_suppression: no bounced drafts found for workspace %s", workspace_id
        )
        return summary

    emails = {c["email"] for c in by_contact.values()}
    try:
        already_emails = _existing_dnc_emails(db, emails)
    except Exception as exc:
        logger.warning(
            "run_bounce_suppression: DNC lookup failed (%s) — assuming none suppressed", exc
        )
        already_emails = set()

    dnc = DNCRegistry(workspace_id=workspace_id)

    # ------------------------------------------------------------------
    # Per-contact suppression
    # ------------------------------------------------------------------
    for contact_id, info in by_contact.items():
        email = info["email"]
        already_dnc = email in already_emails
        already_marked = (
            info.get("status") == "bounced" and info.get("is_outreach_eligible") is False
        )

        if already_dnc and already_marked:
            summary["already_suppressed"] += 1
            continue

        try:
            db.client.table("contacts").update(
                {
                    "status": "bounced",
                    "is_outreach_eligible": False,
                }
            ).eq("id", contact_id).execute()
        except Exception as exc:
            logger.warning(
                "run_bounce_suppression: failed to update contact %s: %s", contact_id, exc
            )
            summary["errors"].append(f"contact_update:{contact_id}:{exc}")
            continue

        if not already_dnc:
            try:
                # add_entry does not inject workspace_id; insert directly to keep
                # the existing public API unchanged while still satisfying the
                # NOT NULL workspace_id constraint on do_not_contact.
                db.client.table("do_not_contact").insert(
                    {
                        "email": email,
                        "reason": "bounced",
                        "added_by": "bounce_suppressor",
                        "workspace_id": workspace_id,
                    }
                ).execute()
            except Exception as exc:
                # If a concurrent writer beat us to it the unique index will
                # raise; treat that as already-suppressed rather than an error.
                msg = str(exc).lower()
                if "duplicate" in msg or "unique" in msg or "conflict" in msg:
                    summary["already_suppressed"] += 1
                    continue
                logger.warning("run_bounce_suppression: failed to add DNC for %s: %s", email, exc)
                summary["errors"].append(f"dnc_email:{email}:{exc}")
                continue

        summary["contacts_suppressed"] += 1

    # ------------------------------------------------------------------
    # Domain-level suppression
    # ------------------------------------------------------------------
    by_domain: dict[str, set[str]] = defaultdict(set)
    for info in by_contact.values():
        domain = _domain_of(info["email"])
        if domain:
            by_domain[domain].add(info["contact_id"])

    candidate_domains = {d for d, ids in by_domain.items() if len(ids) >= DOMAIN_BOUNCE_THRESHOLD}
    try:
        already_domains = _existing_dnc_domains(db, candidate_domains)
    except Exception as exc:
        logger.warning("run_bounce_suppression: domain DNC lookup failed (%s)", exc)
        already_domains = set()

    for domain in candidate_domains:
        if domain in already_domains:
            continue
        try:
            db.client.table("do_not_contact").insert(
                {
                    "domain": domain,
                    "reason": "bounced_domain",
                    "added_by": "bounce_suppressor",
                    "workspace_id": workspace_id,
                    "notes": f"Auto-suppressed after {len(by_domain[domain])} bounces",
                }
            ).execute()
            summary["domains_suppressed"] += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "conflict" in msg:
                continue
            logger.warning("run_bounce_suppression: failed to add domain DNC %s: %s", domain, exc)
            summary["errors"].append(f"dnc_domain:{domain}:{exc}")

    # Avoid leaking the unused dnc instance — DNCRegistry warms the Database
    # client which we want to keep cached for subsequent calls in the same
    # scheduler tick.
    _ = dnc

    logger.info(
        "run_bounce_suppression [%s]: contacts=%d domains=%d already=%d errors=%d",
        workspace_id,
        summary["contacts_suppressed"],
        summary["domains_suppressed"],
        summary["already_suppressed"],
        len(summary["errors"]),
    )
    return summary
