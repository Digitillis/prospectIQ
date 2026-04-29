"""LinkedIn Sender Agent — automate LinkedIn sends via Unipile.

Replaces the manual copy-paste workflow with automated send via the Unipile
unified messaging API. Unipile maintains a LinkedIn session on behalf of the
user's connected account and exposes a REST API for sending connection
requests and direct messages.

Flow:
  1. Pick approved linkedin_connection drafts that haven't been sent
  2. Send connection request via Unipile
  3. Mark contact linkedin_connection_sent_at + update draft as sent
  4. Unipile webhook fires on connection_accepted → this agent queues opening DM
  5. After acceptance, send opening DM; after DM reply, handle via reply agent

Daily safety limits (LinkedIn soft limits):
  - Max 20 connection requests/day per account
  - Auto-withdraw pending invites older than 21 days (keeps pending count <400)

Requires env vars:
  UNIPILE_API_KEY       — Unipile API key
  UNIPILE_ACCOUNT_ID    — LinkedIn account ID registered in Unipile
  UNIPILE_DSN           — Unipile DSN e.g. api4.unipile.com:13453
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

# Daily send limits — stay within LinkedIn's informal safety thresholds
DAILY_CONNECTION_REQUEST_LIMIT = 20
STALE_INVITE_WITHDRAW_DAYS = 21


class UnipileClient:
    """Thin wrapper around the Unipile REST API for LinkedIn actions."""

    def __init__(self, api_key: str, dsn: str, account_id: str) -> None:
        self.api_key = api_key
        self.dsn = dsn.rstrip("/")
        self.account_id = account_id
        self._base = f"https://{self.dsn}"

    def _headers(self) -> dict:
        return {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    def send_connection_request(self, linkedin_profile_url: str, message: str) -> dict:
        """Send a LinkedIn connection request with a personalised note.

        Args:
            linkedin_profile_url: Full LinkedIn profile URL of the prospect
            message: Connection note text (max 200 characters enforced by LinkedIn)

        Returns:
            Unipile API response dict.

        Raises:
            httpx.HTTPStatusError on 4xx/5xx from Unipile.
        """
        payload = {
            "account_id": self.account_id,
            "linkedin_profile_url": linkedin_profile_url,
            "message": message[:200],  # Hard enforce LinkedIn limit
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{self._base}/api/v1/linkedin/connection_requests",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def send_message(self, linkedin_profile_url: str, message: str) -> dict:
        """Send a LinkedIn direct message to an existing connection.

        Args:
            linkedin_profile_url: Full LinkedIn profile URL of the prospect
            message: DM text

        Returns:
            Unipile API response dict.
        """
        payload = {
            "account_id": self.account_id,
            "linkedin_profile_url": linkedin_profile_url,
            "message": message,
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{self._base}/api/v1/linkedin/messages",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def list_pending_invitations(self) -> list[dict]:
        """Return all pending (not yet accepted) connection requests.

        Used to identify stale invites to withdraw.
        """
        params = {"account_id": self.account_id, "status": "pending"}
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{self._base}/api/v1/linkedin/connection_requests",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("items", [])

    def withdraw_invitation(self, invitation_id: str) -> bool:
        """Withdraw a pending connection request.

        Returns True on success, False if the withdraw fails gracefully.
        """
        with httpx.Client(timeout=30) as client:
            resp = client.delete(
                f"{self._base}/api/v1/linkedin/connection_requests/{invitation_id}",
                headers=self._headers(),
                params={"account_id": self.account_id},
            )
            return resp.status_code in (200, 204)


class LinkedInSenderAgent(BaseAgent):
    """Send approved LinkedIn drafts via Unipile and manage the send lifecycle."""

    agent_name = "linkedin_sender"

    def run(
        self,
        send_connection_requests: bool = True,
        send_dms: bool = True,
        withdraw_stale: bool = True,
        dry_run: bool = False,
    ) -> AgentResult:
        """Execute the LinkedIn send cycle.

        Args:
            send_connection_requests: Send pending connection request drafts.
            send_dms: Send pending opening DM drafts for accepted connections.
            withdraw_stale: Withdraw pending invitations older than STALE_INVITE_WITHDRAW_DAYS.
            dry_run: Log actions without actually sending anything.

        Returns:
            AgentResult with send stats.
        """
        result = AgentResult()
        settings = get_settings()

        if not settings.unipile_api_key:
            logger.error(
                "LinkedInSenderAgent: UNIPILE_API_KEY not configured. "
                "Set UNIPILE_API_KEY, UNIPILE_ACCOUNT_ID, and UNIPILE_DSN in env vars."
            )
            result.errors += 1
            result.add_detail("config", "error", "UNIPILE_API_KEY not configured")
            return result

        unipile = UnipileClient(
            api_key=settings.unipile_api_key,
            dsn=settings.unipile_dsn or "api4.unipile.com:13453",
            account_id=settings.unipile_account_id,
        )

        if withdraw_stale:
            self._withdraw_stale_invites(unipile, dry_run, result)

        if send_connection_requests:
            self._send_connection_requests(unipile, dry_run, result)

        if send_dms:
            self._send_opening_dms(unipile, dry_run, result)

        return result

    # ─────────────────────────────────────────────────────────────────────
    # Connection requests
    # ─────────────────────────────────────────────────────────────────────

    def _send_connection_requests(
        self, unipile: UnipileClient, dry_run: bool, result: AgentResult
    ) -> None:
        """Send up to DAILY_CONNECTION_REQUEST_LIMIT approved connection note drafts."""
        try:
            sent_today = self._count_sent_today("linkedin_connection")
            remaining = DAILY_CONNECTION_REQUEST_LIMIT - sent_today
            if remaining <= 0:
                logger.info(
                    "LinkedInSenderAgent: daily connection request limit reached (%d/%d)",
                    sent_today, DAILY_CONNECTION_REQUEST_LIMIT,
                )
                result.add_detail(
                    "connection_requests", "skipped",
                    f"Daily limit reached ({sent_today}/{DAILY_CONNECTION_REQUEST_LIMIT})"
                )
                return

            drafts = self._get_approved_linkedin_drafts(
                sequence_name="linkedin_connection",
                limit=remaining,
            )
            logger.info(
                "LinkedInSenderAgent: %d connection request drafts to send (limit: %d)",
                len(drafts), remaining,
            )

            for draft in drafts:
                self._send_connection_draft(unipile, draft, dry_run, result)

        except Exception as exc:
            logger.error("LinkedInSenderAgent: connection requests failed: %s", exc, exc_info=True)
            result.errors += 1

    def _send_connection_draft(
        self, unipile: UnipileClient, draft: dict, dry_run: bool, result: AgentResult
    ) -> None:
        """Send a single connection request draft."""
        contact = self._get_contact(draft.get("contact_id"))
        if not contact:
            result.skipped += 1
            return

        linkedin_url = contact.get("linkedin_url", "")
        if not linkedin_url:
            logger.warning(
                "LinkedInSenderAgent: contact %s has no linkedin_url — skipping",
                draft.get("contact_id"),
            )
            result.skipped += 1
            result.add_detail(
                contact.get("full_name", "unknown"),
                "skipped",
                "No linkedin_url on contact",
            )
            return

        message = draft.get("edited_body") or draft.get("body", "")
        contact_name = contact.get("full_name") or contact.get("first_name", "Unknown")
        company_name = draft.get("companies", {}).get("name", "") if draft.get("companies") else ""

        if dry_run:
            logger.info(
                "[DRY RUN] Would send connection request to %s (%s): %r",
                contact_name, linkedin_url, message[:80],
            )
            result.processed += 1
            result.add_detail(contact_name, "dry_run_connection", company_name)
            return

        try:
            # Validate message compliance before sending
            from backend.app.core.outbound_validator import OutboundValidator, OutboundValidationError
            try:
                OutboundValidator().validate_linkedin_connect(message)
            except OutboundValidationError as ve:
                logger.warning(
                    "LinkedInSenderAgent: connect note blocked by validator for %s: %s",
                    contact_name, ve,
                )
                result.skipped += 1
                result.add_detail(contact_name, "blocked", str(ve))
                return

            # Consume from DB-backed rate limiter
            from backend.app.core.linkedin_rate_limiter import LinkedInRateLimiter
            limiter = LinkedInRateLimiter(self.db, self.workspace_id)
            if not limiter.consume("linkedin_connect"):
                result.add_detail(contact_name, "rate_limited", "Daily connect limit reached")
                result.skipped += 1
                return

            unipile.send_connection_request(linkedin_url, message)

            now_iso = datetime.now(timezone.utc).isoformat()
            # Mark contact as connection sent
            self.db.client.table("contacts").update({
                "linkedin_connection_sent_at": now_iso,
            }).eq("id", draft["contact_id"]).execute()

            # Mark draft as sent
            self.db.client.table("outreach_drafts").update({
                "sent_at": now_iso,
                "approval_status": "approved",
            }).eq("id", draft["id"]).execute()

            # Log interaction
            self.db.insert_interaction({
                "company_id": draft["company_id"],
                "contact_id": draft["contact_id"],
                "type": "linkedin_connection",
                "channel": "linkedin",
                "body": message,
                "source": "linkedin_sender_agent",
                "metadata": {"draft_id": draft["id"], "linkedin_url": linkedin_url},
            })

            result.processed += 1
            result.add_detail(contact_name, "connection_sent", company_name)
            logger.info("LinkedInSenderAgent: connection request sent to %s", contact_name)

        except httpx.HTTPStatusError as exc:
            logger.error(
                "LinkedInSenderAgent: Unipile error sending connection to %s: %s",
                contact_name, exc.response.text[:200],
            )
            result.errors += 1
            result.add_detail(contact_name, "error", f"Unipile HTTP {exc.response.status_code}")
        except Exception as exc:
            logger.error(
                "LinkedInSenderAgent: unexpected error for %s: %s", contact_name, exc
            )
            result.errors += 1
            result.add_detail(contact_name, "error", str(exc)[:200])

    # ─────────────────────────────────────────────────────────────────────
    # Opening DMs
    # ─────────────────────────────────────────────────────────────────────

    def _send_opening_dms(
        self, unipile: UnipileClient, dry_run: bool, result: AgentResult
    ) -> None:
        """Send opening DMs to contacts who have accepted the connection request."""
        try:
            drafts = self._get_approved_linkedin_drafts(
                sequence_name="linkedin_dm_opening",
                require_connection_accepted=True,
                limit=50,
            )
            logger.info(
                "LinkedInSenderAgent: %d opening DM drafts to send", len(drafts)
            )

            for draft in drafts:
                self._send_dm_draft(unipile, draft, "opening_dm", dry_run, result)

        except Exception as exc:
            logger.error("LinkedInSenderAgent: DM send failed: %s", exc, exc_info=True)
            result.errors += 1

    def _send_dm_draft(
        self,
        unipile: UnipileClient,
        draft: dict,
        dm_type: str,
        dry_run: bool,
        result: AgentResult,
    ) -> None:
        """Send a single DM draft."""
        contact = self._get_contact(draft.get("contact_id"))
        if not contact:
            result.skipped += 1
            return

        linkedin_url = contact.get("linkedin_url", "")
        if not linkedin_url:
            result.skipped += 1
            return

        message = draft.get("edited_body") or draft.get("body", "")
        contact_name = contact.get("full_name") or contact.get("first_name", "Unknown")
        company_name = draft.get("companies", {}).get("name", "") if draft.get("companies") else ""

        if dry_run:
            logger.info(
                "[DRY RUN] Would send %s DM to %s: %r",
                dm_type, contact_name, message[:80],
            )
            result.processed += 1
            result.add_detail(contact_name, f"dry_run_{dm_type}", company_name)
            return

        try:
            # Validate DM compliance
            from backend.app.core.outbound_validator import OutboundValidator, OutboundValidationError
            try:
                OutboundValidator().validate_linkedin_dm(message)
            except OutboundValidationError as ve:
                logger.warning("LinkedInSenderAgent: DM blocked by validator for %s: %s", contact_name, ve)
                result.skipped += 1
                result.add_detail(contact_name, "blocked", str(ve))
                return

            # DB-backed rate limiter
            from backend.app.core.linkedin_rate_limiter import LinkedInRateLimiter
            limiter = LinkedInRateLimiter(self.db, self.workspace_id)
            if not limiter.consume("linkedin_dm"):
                result.add_detail(contact_name, "rate_limited", "Daily DM limit reached")
                result.skipped += 1
                return

            unipile.send_message(linkedin_url, message)

            now_iso = datetime.now(timezone.utc).isoformat()
            self.db.client.table("contacts").update({
                "linkedin_dm_sent_at": now_iso,
            }).eq("id", draft["contact_id"]).execute()

            self.db.client.table("outreach_drafts").update({
                "sent_at": now_iso,
            }).eq("id", draft["id"]).execute()

            self.db.insert_interaction({
                "company_id": draft["company_id"],
                "contact_id": draft["contact_id"],
                "type": "linkedin_message",
                "channel": "linkedin",
                "body": message,
                "source": "linkedin_sender_agent",
                "metadata": {"draft_id": draft["id"], "dm_type": dm_type},
            })

            result.processed += 1
            result.add_detail(contact_name, f"{dm_type}_sent", company_name)

        except httpx.HTTPStatusError as exc:
            logger.error(
                "LinkedInSenderAgent: Unipile DM error for %s: %s",
                contact_name, exc.response.text[:200],
            )
            result.errors += 1
            result.add_detail(contact_name, "error", f"Unipile HTTP {exc.response.status_code}")
        except Exception as exc:
            logger.error("LinkedInSenderAgent: DM error for %s: %s", contact_name, exc)
            result.errors += 1
            result.add_detail(contact_name, "error", str(exc)[:200])

    # ─────────────────────────────────────────────────────────────────────
    # Stale invite withdrawal
    # ─────────────────────────────────────────────────────────────────────

    def _withdraw_stale_invites(
        self, unipile: UnipileClient, dry_run: bool, result: AgentResult
    ) -> None:
        """Withdraw pending invites older than STALE_INVITE_WITHDRAW_DAYS.

        LinkedIn enforces a ~400 pending invite limit. Stale invites that
        were never accepted clog this limit. Auto-withdrawing after 21 days
        keeps the queue clean and is standard practice.
        """
        try:
            pending = unipile.list_pending_invitations()
            cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_INVITE_WITHDRAW_DAYS)
            stale = [
                inv for inv in pending
                if inv.get("sent_at") and
                datetime.fromisoformat(inv["sent_at"].replace("Z", "+00:00")) < cutoff
            ]

            if not stale:
                return

            logger.info(
                "LinkedInSenderAgent: withdrawing %d stale invites (>%d days old)",
                len(stale), STALE_INVITE_WITHDRAW_DAYS,
            )

            withdrawn = 0
            for inv in stale:
                if dry_run:
                    withdrawn += 1
                    continue
                if unipile.withdraw_invitation(inv["id"]):
                    withdrawn += 1

            result.add_detail(
                "stale_invites",
                "withdrawn" if not dry_run else "dry_run_withdraw",
                f"{withdrawn}/{len(stale)}",
            )

        except Exception as exc:
            # Non-fatal — log and continue
            logger.warning("LinkedInSenderAgent: stale invite withdrawal failed: %s", exc)

    # ─────────────────────────────────────────────────────────────────────
    # DB helpers
    # ─────────────────────────────────────────────────────────────────────

    def _get_approved_linkedin_drafts(
        self,
        sequence_name: str,
        require_connection_accepted: bool = False,
        limit: int = 25,
    ) -> list[dict]:
        """Fetch approved, unsent LinkedIn drafts for the given sequence."""
        try:
            query = (
                self.db._filter_ws(
                    self.db.client.table("outreach_drafts")
                    .select(
                        "id, company_id, contact_id, body, edited_body, sequence_name, "
                        "companies(name)"
                    )
                )
                .eq("channel", "linkedin")
                .eq("sequence_name", sequence_name)
                .in_("approval_status", ["approved", "edited"])
                .is_("sent_at", "null")
                .limit(limit)
            )
            result = query.execute()
            drafts = result.data or []

            if require_connection_accepted:
                # Filter to contacts with linkedin_accepted_at set
                filtered = []
                for draft in drafts:
                    contact = self._get_contact(draft.get("contact_id"))
                    if contact and contact.get("linkedin_accepted_at"):
                        filtered.append(draft)
                return filtered

            return drafts
        except Exception as exc:
            logger.error(
                "LinkedInSenderAgent: failed to fetch %s drafts: %s", sequence_name, exc
            )
            return []

    def _get_contact(self, contact_id: Optional[str]) -> Optional[dict]:
        """Fetch a contact row by ID."""
        if not contact_id:
            return None
        try:
            result = (
                self.db.client.table("contacts")
                .select(
                    "id, full_name, first_name, linkedin_url, "
                    "linkedin_connection_sent_at, linkedin_accepted_at, linkedin_dm_sent_at"
                )
                .eq("id", contact_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            return None

    def _count_sent_today(self, sequence_name: str) -> int:
        """Count LinkedIn connection requests sent today for this workspace."""
        try:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            result = (
                self.db._filter_ws(
                    self.db.client.table("outreach_drafts")
                    .select("id", count="exact")
                )
                .eq("channel", "linkedin")
                .eq("sequence_name", sequence_name)
                .not_.is_("sent_at", "null")
                .gte("sent_at", today_start)
                .execute()
            )
            return result.count or 0
        except Exception:
            return 0

    def handle_connection_accepted(self, contact_id: str) -> None:
        """Called by the Unipile webhook when a connection is accepted.

        Marks the contact's linkedin_accepted_at and makes the opening DM
        draft eligible for the next send cycle.
        """
        try:
            self.db.client.table("contacts").update({
                "linkedin_accepted_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", contact_id).execute()
            logger.info(
                "LinkedInSenderAgent: connection accepted for contact %s — "
                "opening DM queued for next cycle",
                contact_id,
            )
        except Exception as exc:
            logger.error(
                "LinkedInSenderAgent: failed to mark connection accepted for %s: %s",
                contact_id, exc,
            )
