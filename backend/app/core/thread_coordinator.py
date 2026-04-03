# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: ProspectIQ Technical Team
"""Multi-thread account campaign coordinator.

Orchestrates simultaneous outreach to multiple contacts at the same target
account. Assigns roles by title heuristic, generates coordinated drafts that
are aware of sibling threads, and enforces suppression windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.app.core.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role assignment heuristic — title keyword matching
# ---------------------------------------------------------------------------

_ECONOMIC_BUYER_KEYWORDS = (
    "ceo", "cfo", "coo", "president", "owner", "founder",
    "vp", "svp", "evp",
)
_CHAMPION_KEYWORDS = (
    "director", "manager", "head of", "lead",
)
_TECHNICAL_KEYWORDS = (
    "engineer", "architect", "analyst", "developer", "cto", "cio",
)


def _assign_role(title: str) -> str:
    """Assign a role label from a contact's title using keyword matching."""
    t = (title or "").lower()
    for kw in _ECONOMIC_BUYER_KEYWORDS:
        if kw in t:
            return "economic_buyer"
    for kw in _CHAMPION_KEYWORDS:
        if kw in t:
            return "champion"
    for kw in _TECHNICAL_KEYWORDS:
        if kw in t:
            return "technical_evaluator"
    return "influencer"


def _messaging_angle(role: str) -> str:
    """Return a default messaging angle for each role."""
    angles = {
        "economic_buyer": "ROI, risk reduction, and competitive advantage",
        "champion": "Operational efficiency, team productivity, and quick wins",
        "technical_evaluator": "Integration depth, data quality, and implementation roadmap",
        "influencer": "Day-to-day workflow improvements and ease of adoption",
    }
    return angles.get(role, "Value and impact for your team")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AccountCampaign:
    id: str
    workspace_id: str
    company_id: str
    campaign_name: str
    strategy: str
    status: str
    coordinator_notes: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class ThreadRole:
    thread_id: str
    contact_id: str
    contact_name: str
    contact_title: str
    role_label: str
    messaging_angle: str


@dataclass
class CoordinatedDraft:
    thread_id: str
    contact_id: str
    contact_name: str
    contact_title: str
    role_label: str
    messaging_angle: str
    subject: str
    body: str
    awareness_note: Optional[str]
    suppressed: bool
    suppress_reason: Optional[str] = None


@dataclass
class AccountCampaignStatus:
    account_campaign: dict
    threads: list[dict]
    drafts_generated: int
    suppressed_count: int
    next_available_at: Optional[str]


# ---------------------------------------------------------------------------
# ThreadCoordinator
# ---------------------------------------------------------------------------

class ThreadCoordinator:
    """Coordinates multi-contact outreach campaigns for a single account."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_account_campaign(
        self,
        company_id: str,
        contact_ids: list[str],
        strategy: str,
        workspace_id: str,
        campaign_name: str = "",
    ) -> AccountCampaign:
        """Create an account campaign and enroll the contact list as threads.

        If campaign_name is not provided, it is derived from the company name.
        """
        # Resolve company name for default campaign name
        if not campaign_name:
            try:
                c = (
                    self.db.client.table("companies")
                    .select("name")
                    .eq("id", company_id)
                    .limit(1)
                    .execute()
                )
                company_name = c.data[0]["name"] if c.data else "Unknown"
            except Exception:
                company_name = "Unknown"
            campaign_name = f"Multi-thread — {company_name}"

        # Insert account_campaign row
        row = {
            "workspace_id": workspace_id,
            "company_id": company_id,
            "campaign_name": campaign_name,
            "strategy": strategy,
            "status": "active",
        }
        result = self.db.client.table("account_campaigns").insert(row).execute()
        ac_row = result.data[0]
        ac_id = ac_row["id"]

        # Insert a thread row per contact
        for cid in contact_ids:
            thread_row = {
                "account_campaign_id": ac_id,
                "workspace_id": workspace_id,
                "contact_id": cid,
                "status": "active",
                "sequence_step": 1,
            }
            self.db.client.table("account_campaign_threads").insert(thread_row).execute()

        return AccountCampaign(
            id=ac_id,
            workspace_id=ac_row["workspace_id"],
            company_id=ac_row["company_id"],
            campaign_name=ac_row["campaign_name"],
            strategy=ac_row["strategy"],
            status=ac_row["status"],
            coordinator_notes=ac_row.get("coordinator_notes"),
            created_at=ac_row["created_at"],
            updated_at=ac_row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Role assignment
    # ------------------------------------------------------------------

    async def assign_roles(
        self, account_campaign_id: str, workspace_id: str
    ) -> list[ThreadRole]:
        """Assign role labels to threads based on contact title, persisting to DB."""
        threads = (
            self.db.client.table("account_campaign_threads")
            .select("id, contact_id")
            .eq("account_campaign_id", account_campaign_id)
            .eq("workspace_id", workspace_id)
            .execute()
        ).data or []

        results: list[ThreadRole] = []
        for t in threads:
            contact_row = {}
            try:
                cr = (
                    self.db.client.table("contacts")
                    .select("id, full_name, title")
                    .eq("id", t["contact_id"])
                    .limit(1)
                    .execute()
                )
                contact_row = cr.data[0] if cr.data else {}
            except Exception:
                pass

            title = contact_row.get("title") or ""
            role = _assign_role(title)
            angle = _messaging_angle(role)

            # Persist role and angle back to the thread row
            try:
                self.db.client.table("account_campaign_threads").update(
                    {"role_label": role, "messaging_angle": angle}
                ).eq("id", t["id"]).execute()
            except Exception as exc:
                logger.warning(f"Could not persist role for thread {t['id']}: {exc}")

            results.append(
                ThreadRole(
                    thread_id=t["id"],
                    contact_id=t["contact_id"],
                    contact_name=contact_row.get("full_name") or "Unknown",
                    contact_title=title,
                    role_label=role,
                    messaging_angle=angle,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Coordinated draft generation
    # ------------------------------------------------------------------

    async def generate_coordinated_drafts(
        self, account_campaign_id: str, workspace_id: str
    ) -> list[CoordinatedDraft]:
        """Generate one draft per thread, coordinated across sibling contacts.

        Each draft is aware of sibling threads so messaging is complementary,
        not conflicting. Uses claude-sonnet-4-6 for generation.
        """
        # Pull threads with contact + company context
        threads = (
            self.db.client.table("account_campaign_threads")
            .select("*, contacts(id, full_name, title, email)")
            .eq("account_campaign_id", account_campaign_id)
            .eq("workspace_id", workspace_id)
            .execute()
        ).data or []

        # Pull campaign + company
        ac_row = None
        company_row: dict = {}
        try:
            ac_res = (
                self.db.client.table("account_campaigns")
                .select("*, companies(id, name, industry, domain)")
                .eq("id", account_campaign_id)
                .limit(1)
                .execute()
            )
            if ac_res.data:
                ac_row = ac_res.data[0]
                company_row = ac_row.get("companies") or {}
        except Exception as exc:
            logger.warning(f"Could not fetch account_campaign: {exc}")

        company_name = company_row.get("name") or "the company"
        strategy = (ac_row or {}).get("strategy", "parallel")

        # Build sibling summary for awareness notes
        sibling_summary = self._build_sibling_summary(threads)

        drafts: list[CoordinatedDraft] = []
        for thread in threads:
            contact = thread.get("contacts") or {}
            contact_name = contact.get("full_name") or "there"
            contact_title = contact.get("title") or ""
            role = thread.get("role_label") or _assign_role(contact_title)
            angle = thread.get("messaging_angle") or _messaging_angle(role)

            # Suppression check
            suppressed = await self.check_suppression(
                company_id=ac_row["company_id"] if ac_row else "",
                contact_id=thread["contact_id"],
                message_type="email",
                workspace_id=workspace_id,
            )

            suppress_reason: Optional[str] = None
            next_available: Optional[str] = None
            if suppressed:
                suppress_reason = "Contact received a message within the last 48 hours."
                try:
                    last = (
                        self.db.client.table("account_suppression_log")
                        .select("sent_at")
                        .eq("workspace_id", workspace_id)
                        .eq("contact_id", thread["contact_id"])
                        .order("sent_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if last.data:
                        sent = datetime.fromisoformat(last.data[0]["sent_at"].replace("Z", "+00:00"))
                        next_available = (sent + timedelta(hours=48)).isoformat()
                except Exception:
                    pass

            # Build awareness note (only for parallel/waterfall strategies)
            awareness_note: Optional[str] = None
            siblings = [
                s for s in sibling_summary if s["contact_id"] != thread["contact_id"]
            ]
            if siblings and strategy in ("parallel", "waterfall"):
                sibling_names = [s["name"] for s in siblings[:2]]
                names_str = " and ".join(sibling_names)
                awareness_note = (
                    f"Your colleague {names_str} at {company_name} "
                    f"is also exploring this — we're coordinating our outreach so you receive relevant, "
                    f"complementary information."
                )

            if suppressed:
                # Return a suppressed placeholder — no LLM call needed
                drafts.append(
                    CoordinatedDraft(
                        thread_id=thread["id"],
                        contact_id=thread["contact_id"],
                        contact_name=contact_name,
                        contact_title=contact_title,
                        role_label=role,
                        messaging_angle=angle,
                        subject="",
                        body="",
                        awareness_note=None,
                        suppressed=True,
                        suppress_reason=suppress_reason,
                    )
                )
                continue

            # Generate draft via Claude
            subject, body = await self._generate_draft_llm(
                contact_name=contact_name,
                contact_title=contact_title,
                company_name=company_name,
                role=role,
                angle=angle,
                awareness_note=awareness_note,
                strategy=strategy,
            )

            drafts.append(
                CoordinatedDraft(
                    thread_id=thread["id"],
                    contact_id=thread["contact_id"],
                    contact_name=contact_name,
                    contact_title=contact_title,
                    role_label=role,
                    messaging_angle=angle,
                    subject=subject,
                    body=body,
                    awareness_note=awareness_note,
                    suppressed=False,
                )
            )

        return drafts

    def _build_sibling_summary(self, threads: list[dict]) -> list[dict]:
        """Return a compact list of {contact_id, name, role} for awareness notes."""
        result = []
        for t in threads:
            contact = t.get("contacts") or {}
            result.append(
                {
                    "contact_id": t["contact_id"],
                    "name": contact.get("full_name") or "your colleague",
                    "role": t.get("role_label") or "influencer",
                }
            )
        return result

    async def _generate_draft_llm(
        self,
        contact_name: str,
        contact_title: str,
        company_name: str,
        role: str,
        angle: str,
        awareness_note: Optional[str],
        strategy: str,
    ) -> tuple[str, str]:
        """Call claude-sonnet-4-6 to generate a coordinated outreach draft."""
        try:
            import anthropic

            awareness_block = ""
            if awareness_note:
                awareness_block = f"""
If appropriate, you may subtly reference that a colleague at {company_name} is also
being engaged — use this as a natural social proof signal. Suggested note: "{awareness_note}"
Do not include this if it would feel forced or awkward in context.
"""

            prompt = f"""You are writing a cold outreach email on behalf of ProspectIQ to a contact at {company_name}.

Contact: {contact_name} ({contact_title})
Role in buying process: {role.replace("_", " ").title()}
Messaging angle: {angle}
Campaign strategy: {strategy}
{awareness_block}

Write a concise, personalized cold outreach email. It should:
- Be under 150 words
- Lead with their specific angle ({angle})
- Have a clear, low-friction CTA
- Sound human and specific, not templated
- NOT use phrases like "I hope this finds you well" or "I wanted to reach out"

Return ONLY this JSON (no markdown, no extra text):
{{"subject": "...", "body": "..."}}"""

            client = anthropic.Anthropic()
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            import json
            content = message.content[0].text.strip()
            parsed = json.loads(content)
            return parsed.get("subject", ""), parsed.get("body", "")
        except Exception as exc:
            logger.warning(f"LLM draft generation failed: {exc}")
            # Fallback draft
            subject = f"Quick question for {contact_name.split()[0]} at {company_name}"
            body = (
                f"Hi {contact_name.split()[0]},\n\n"
                f"Given your focus on {angle.lower()}, I thought this might be timely. "
                f"We work with manufacturing teams to surface actionable intelligence from "
                f"operational data — specifically helping {role.replace('_', ' ')}s like yourself.\n\n"
                f"Worth a 15-minute call this week to see if there's a fit?\n\nBest,"
            )
            return subject, body

    # ------------------------------------------------------------------
    # Suppression
    # ------------------------------------------------------------------

    async def check_suppression(
        self,
        company_id: str,
        contact_id: str,
        message_type: str,
        workspace_id: str,
        window_hours: int = 48,
    ) -> bool:
        """Return True if the contact is suppressed (too recently touched).

        Checks account_suppression_log for entries within window_hours.
        """
        if not company_id or not contact_id:
            return False
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=window_hours)
        ).isoformat()
        try:
            result = (
                self.db.client.table("account_suppression_log")
                .select("id")
                .eq("workspace_id", workspace_id)
                .eq("company_id", company_id)
                .eq("contact_id", contact_id)
                .eq("message_type", message_type)
                .gte("sent_at", cutoff)
                .limit(1)
                .execute()
            )
            return bool(result.data)
        except Exception as exc:
            logger.warning(f"Suppression check failed: {exc}")
            return False

    async def log_suppression(
        self,
        company_id: str,
        contact_id: str,
        message_type: str,
        workspace_id: str,
    ) -> None:
        """Record a send event in the suppression log."""
        try:
            self.db.client.table("account_suppression_log").insert(
                {
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                    "contact_id": contact_id,
                    "message_type": message_type,
                }
            ).execute()
        except Exception as exc:
            logger.warning(f"Could not write suppression log: {exc}")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_account_campaign_status(
        self, account_campaign_id: str, workspace_id: str
    ) -> AccountCampaignStatus:
        """Return full campaign status with thread details and suppression counts."""
        ac_row: dict = {}
        try:
            res = (
                self.db.client.table("account_campaigns")
                .select("*, companies(id, name, domain)")
                .eq("id", account_campaign_id)
                .eq("workspace_id", workspace_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                raise ValueError(f"Account campaign {account_campaign_id} not found")
            ac_row = res.data[0]
        except Exception as exc:
            raise ValueError(str(exc))

        threads = (
            self.db.client.table("account_campaign_threads")
            .select("*, contacts(id, full_name, title, email)")
            .eq("account_campaign_id", account_campaign_id)
            .eq("workspace_id", workspace_id)
            .execute()
        ).data or []

        company_id = ac_row.get("company_id", "")

        # Determine suppression state per thread
        suppressed_count = 0
        next_available_at: Optional[str] = None

        for t in threads:
            is_sup = await self.check_suppression(
                company_id=company_id,
                contact_id=t["contact_id"],
                message_type="email",
                workspace_id=workspace_id,
            )
            t["suppressed"] = is_sup
            if is_sup:
                suppressed_count += 1
                # Find next available time from suppression log
                try:
                    last = (
                        self.db.client.table("account_suppression_log")
                        .select("sent_at")
                        .eq("workspace_id", workspace_id)
                        .eq("contact_id", t["contact_id"])
                        .order("sent_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if last.data:
                        sent = datetime.fromisoformat(
                            last.data[0]["sent_at"].replace("Z", "+00:00")
                        )
                        candidate = (sent + timedelta(hours=48)).isoformat()
                        if next_available_at is None or candidate > next_available_at:
                            next_available_at = candidate
                except Exception:
                    pass

        # Count drafts generated (outreach_drafts linked by thread contact_ids)
        drafts_generated = 0
        try:
            contact_ids = [t["contact_id"] for t in threads]
            if contact_ids:
                res = (
                    self.db.client.table("outreach_drafts")
                    .select("id", count="exact")
                    .in_("contact_id", contact_ids)
                    .eq("workspace_id", workspace_id)
                    .execute()
                )
                drafts_generated = res.count or 0
        except Exception:
            pass

        return AccountCampaignStatus(
            account_campaign=ac_row,
            threads=threads,
            drafts_generated=drafts_generated,
            suppressed_count=suppressed_count,
            next_available_at=next_available_at,
        )
