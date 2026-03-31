"""Instantly.ai API v2 client for ProspectIQ.

Handles campaign management, lead ingestion, and campaign analytics
for cold outreach sequences.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

INSTANTLY_BASE_URL = "https://api.instantly.ai/api/v2"
RATE_LIMIT_DELAY = 1.0  # seconds between requests


class InstantlyClient:
    """Instantly.ai REST API v2 client.

    Authentication is via `api_key` query parameter appended to every request.
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.instantly_api_key
        if not self.api_key:
            raise ValueError("INSTANTLY_API_KEY must be set in .env")
        self.client = httpx.Client(
            base_url=INSTANTLY_BASE_URL,
            headers={
                "Content-Type": "application/json",
            },
            params={"api_key": self.api_key},
            timeout=30.0,
        )
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        """Make a GET request with rate limiting and error handling."""
        self._rate_limit()
        try:
            response = self.client.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Instantly API error {e.response.status_code} on GET {endpoint}: "
                f"{e.response.text[:500]}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Instantly request error on GET {endpoint}: {e}")
            raise

    def _post(self, endpoint: str, payload: dict | None = None) -> dict:
        """Make a POST request with rate limiting and error handling."""
        self._rate_limit()
        try:
            response = self.client.post(endpoint, json=payload or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Instantly API error {e.response.status_code} on POST {endpoint}: "
                f"{e.response.text[:500]}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Instantly request error on POST {endpoint}: {e}")
            raise

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    def list_campaigns(self) -> dict:
        """List all campaigns.

        Returns:
            Dict with campaign list from GET /campaigns.
        """
        logger.info("Listing Instantly campaigns")
        return self._get("/campaigns")

    def create_campaign(
        self,
        name: str,
        schedule: dict | None = None,
    ) -> dict:
        """Create a new email campaign.

        Args:
            name: Campaign name.
            schedule: Optional schedule configuration dict.

        Returns:
            Created campaign data.
        """
        payload: dict[str, Any] = {"name": name}
        if schedule is not None:
            payload["schedule"] = schedule

        logger.info(f"Creating Instantly campaign: {name}")
        return self._post("/campaigns", payload)

    def get_campaign(self, campaign_id: str) -> dict:
        """Get a single campaign by ID.

        Args:
            campaign_id: Instantly campaign ID.

        Returns:
            Campaign data dict.
        """
        return self._get(f"/campaigns/{campaign_id}")

    def pause_campaign(self, campaign_id: str) -> dict:
        """Pause a running campaign.

        Args:
            campaign_id: Instantly campaign ID.

        Returns:
            Response data confirming pause.
        """
        logger.info(f"Pausing Instantly campaign {campaign_id}")
        return self._post(f"/campaigns/{campaign_id}/pause")

    def resume_campaign(self, campaign_id: str) -> dict:
        """Resume a paused campaign.

        Args:
            campaign_id: Instantly campaign ID.

        Returns:
            Response data confirming resume.
        """
        logger.info(f"Resuming Instantly campaign {campaign_id}")
        return self._post(f"/campaigns/{campaign_id}/resume")

    def get_campaign_analytics(self, campaign_id: str) -> dict:
        """Get analytics for a campaign.

        Args:
            campaign_id: Instantly campaign ID.

        Returns:
            Analytics data (opens, replies, bounces, etc.).
        """
        return self._get(f"/campaigns/{campaign_id}/analytics")

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    def add_leads_to_campaign(
        self,
        campaign_id: str,
        leads: list[dict],
    ) -> dict:
        """Add leads to a campaign.

        Each lead dict should contain:
            - email (str): Lead email address (required).
            - first_name (str): First name.
            - last_name (str): Last name.
            - company_name (str): Company name.
            - campaign_id (str): Will be set automatically.
            - custom_variables (dict): Custom personalization variables.

        Args:
            campaign_id: Instantly campaign ID to add leads to.
            leads: List of lead dicts.

        Returns:
            Response confirming lead creation.
        """
        # Ensure each lead has the campaign_id set
        prepared_leads = []
        for lead in leads:
            lead_data = {**lead, "campaign_id": campaign_id}
            prepared_leads.append(lead_data)

        logger.info(
            f"Adding {len(prepared_leads)} leads to Instantly campaign {campaign_id}"
        )
        return self._post("/leads", {"leads": prepared_leads})

    def add_lead_to_campaign(self, campaign_id: str, lead: dict) -> dict:
        """Add a single contact as a lead to an Instantly campaign/sequence.

        Convenience wrapper around add_leads_to_campaign for single-lead pushes.

        Expected lead keys:
            email (str): Required.
            firstName / first_name (str): First name.
            lastName / last_name (str): Last name.
            companyName / company_name (str): Company name.
            personalization (str): First line of email (custom intro copy).
            website (str): Company website URL.

        Args:
            campaign_id: Instantly campaign ID.
            lead: Lead dict with contact details.

        Returns:
            Created lead object from Instantly.

        Raises:
            httpx.HTTPStatusError: On non-2xx response after retries.
        """
        # Normalise camelCase / snake_case keys into what Instantly expects
        normalised: dict = {
            "email": lead.get("email", lead.get("email_address", "")),
            "first_name": lead.get("firstName") or lead.get("first_name", ""),
            "last_name": lead.get("lastName") or lead.get("last_name", ""),
            "company_name": lead.get("companyName") or lead.get("company_name", ""),
            "website": lead.get("website", ""),
        }
        if lead.get("personalization"):
            normalised["custom_variables"] = {
                "personalization": lead["personalization"]
            }

        # Simple retry loop (3 attempts, 2 s backoff) around add_leads_to_campaign
        import time as _time

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = self.add_leads_to_campaign(campaign_id, [normalised])
                # add_leads_to_campaign returns the full response; surface the
                # first lead record so callers get a consistent dict back.
                if isinstance(result, dict):
                    leads_list = result.get("leads", result.get("data", []))
                    if leads_list:
                        return leads_list[0] if isinstance(leads_list, list) else leads_list
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 2:
                    logger.warning(
                        f"add_lead_to_campaign attempt {attempt + 1} failed: {exc}. "
                        "Retrying in 2 s…"
                    )
                    _time.sleep(2)
        raise RuntimeError(
            f"add_lead_to_campaign failed after 3 attempts"
        ) from last_exc

    def remove_lead_from_campaign(self, campaign_id: str, email: str) -> bool:
        """Remove / pause a lead from an Instantly campaign.

        Args:
            campaign_id: Instantly campaign ID.
            email: Lead email address.

        Returns:
            True if the request succeeded.
        """
        logger.info(f"Removing lead {email} from campaign {campaign_id}")
        try:
            self._post(
                f"/campaigns/{campaign_id}/leads/pause",
                payload={"emails": [email]},
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to remove lead {email} from {campaign_id}: {exc}")
            return False

    def get_lead(self, email: str) -> dict:
        """Look up a lead by email address.

        Args:
            email: Lead email address.

        Returns:
            Lead data dict.
        """
        return self._get("/leads", params={"email": email})

    def get_lead_status(self, email: str) -> dict | None:
        """Get the current status of a lead across campaigns.

        Args:
            email: Lead email address to look up.

        Returns:
            Lead status dict, or None if the lead is not found.
        """
        try:
            result = self._get("/leads", params={"email": email})
            if isinstance(result, list):
                return result[0] if result else None
            # Response shape varies by Instantly version
            items = result.get("items", result.get("leads", []))
            if isinstance(items, list):
                return items[0] if items else None
            return result or None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"get_lead_status lookup failed for {email}: {exc}")
            return None

    def list_campaign_leads(
        self,
        campaign_id: str,
        limit: int = 100,
        skip: int = 0,
    ) -> list[dict]:
        """List leads in a campaign with their activity status.

        Used by the polling mechanism to detect opens, replies, and bounces
        without requiring webhook support.

        Args:
            campaign_id: Instantly campaign ID.
            limit: Max leads per page (max 100).
            skip: Offset for pagination.

        Returns:
            List of lead dicts with activity fields (is_opened, is_replied,
            is_bounced, is_clicked, etc.).
        """
        logger.info(
            f"Listing leads for campaign {campaign_id} "
            f"(limit={limit}, skip={skip})"
        )
        result = self._get(
            "/leads",
            params={
                "campaign_id": campaign_id,
                "limit": limit,
                "skip": skip,
            },
        )
        # API may return {"items": [...]} or a plain list
        if isinstance(result, list):
            return result
        return result.get("items", result.get("leads", []))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
