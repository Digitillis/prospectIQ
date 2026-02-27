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

    def get_lead(self, email: str) -> dict:
        """Look up a lead by email address.

        Args:
            email: Lead email address.

        Returns:
            Lead data dict.
        """
        return self._get("/leads", params={"email": email})

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
