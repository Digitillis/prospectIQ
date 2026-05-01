"""Apollo.io API client for ProspectIQ.

Handles people search (free, no credits), organization search,
and people enrichment (credits consumed).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

APOLLO_BASE_URL = "https://api.apollo.io/api/v1"
RATE_LIMIT_DELAY = 3.5  # seconds between requests (100 req / 5 min ≈ 1 per 3s)

# ---------------------------------------------------------------------------
# Credit-guard constants
# ---------------------------------------------------------------------------

_FREE_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "pm.me", "tutanota.com", "zoho.com", "yandex.com",
    "gmx.com", "gmx.net", "mail.com", "fastmail.com", "hey.com",
})
_EMPTY_STREAK_WARN = 20


class ApolloClient:
    """Apollo.io REST API client."""

    # Class-level cache and streak counter — persist across instances
    _enrich_cache: dict[str, dict | None] = {}  # key → result (None = confirmed no-match)
    _empty_streak: int = 0

    def __init__(self, workspace_id: str | None = None):
        from backend.app.core.credential_store import get_credential
        self.api_key = get_credential("apollo", "api_key", workspace_id)
        if not self.api_key:
            # Final fallback to settings
            self.api_key = get_settings().apollo_api_key
        if not self.api_key:
            raise ValueError("Apollo API key not configured. Set APOLLO_API_KEY or add via workspace credentials.")
        self.client = httpx.Client(
            base_url=APOLLO_BASE_URL,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": self.api_key,
            },
            timeout=30.0,
        )
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Make a POST request with rate limiting and error handling."""
        self._rate_limit()
        try:
            response = self.client.post(endpoint, json=payload)
            if response.status_code == 429:
                logger.warning("Apollo rate limit hit, waiting 60s...")
                time.sleep(60)
                response = self.client.post(endpoint, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            logger.error(f"Apollo API error {e.response.status_code}: {body}")
            raise httpx.HTTPStatusError(
                f"{e} | Apollo response: {body}",
                request=e.request,
                response=e.response,
            )
        except httpx.RequestError as e:
            logger.error(f"Apollo request error: {e}")
            raise

    # ------------------------------------------------------------------
    # People Search (FREE — does not consume credits)
    # ------------------------------------------------------------------

    def search_people(
        self,
        person_titles: list[str] | None = None,
        person_not_titles: list[str] | None = None,
        person_seniorities: list[str] | None = None,
        organization_locations: list[str] | None = None,
        organization_num_employees_ranges: list[str] | None = None,
        revenue_range: dict | None = None,
        organization_industry_tag_ids: list[str] | None = None,
        q_organization_keyword_tags: list[str] | None = None,
        organization_domains: list[str] | None = None,
        q_organization_name: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Search for people in Apollo's database.

        This endpoint is FREE and does NOT consume credits.
        Returns up to 100 results per page, max 500 pages.
        Note: Does NOT return email addresses or phone numbers.

        Returns:
            Dict with 'people' list and 'pagination' info.
        """
        payload: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }

        if person_titles:
            payload["person_titles"] = person_titles
        if person_not_titles:
            payload["person_not_titles"] = person_not_titles
        if person_seniorities:
            payload["person_seniorities"] = person_seniorities
        if organization_locations:
            payload["organization_locations"] = organization_locations
        if organization_num_employees_ranges:
            payload["organization_num_employees_ranges"] = organization_num_employees_ranges
        if revenue_range:
            payload["revenue_range"] = revenue_range
        if organization_industry_tag_ids:
            payload["organization_industry_tag_ids"] = organization_industry_tag_ids
        if q_organization_keyword_tags:
            payload["q_organization_keyword_tags"] = q_organization_keyword_tags
        if organization_domains:
            payload["organization_domains"] = organization_domains
        if q_organization_name:
            payload["q_organization_name"] = q_organization_name

        return self._post("/mixed_people/api_search", payload)

    def search_people_paginated(
        self,
        max_pages: int = 5,
        **search_kwargs,
    ) -> list[dict]:
        """Search people across multiple pages.

        Args:
            max_pages: Maximum number of pages to fetch (100 results each).
            **search_kwargs: Arguments passed to search_people().

        Returns:
            List of all people records across pages.
        """
        all_people = []

        for page in range(1, max_pages + 1):
            logger.info(f"Fetching Apollo people search page {page}/{max_pages}...")
            result = self.search_people(page=page, **search_kwargs)

            people = result.get("people", [])
            if not people:
                logger.info(f"No more results at page {page}. Done.")
                break

            all_people.extend(people)

            pagination = result.get("pagination", {})
            total_pages = pagination.get("total_pages", 0)
            if page >= total_pages:
                logger.info(f"Reached last page ({total_pages}). Done.")
                break

        logger.info(f"Total people fetched: {len(all_people)}")
        return all_people

    # ------------------------------------------------------------------
    # Organization Search (consumes credits)
    # ------------------------------------------------------------------

    def search_organizations(
        self,
        organization_locations: list[str] | None = None,
        organization_num_employees_ranges: list[str] | None = None,
        revenue_range: dict | None = None,
        organization_industry_tag_ids: list[str] | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Search for organizations in Apollo's database.

        WARNING: This endpoint CONSUMES credits.

        Returns:
            Dict with 'organizations' list and 'pagination' info.
        """
        payload: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }

        if organization_locations:
            payload["organization_locations"] = organization_locations
        if organization_num_employees_ranges:
            payload["organization_num_employees_ranges"] = organization_num_employees_ranges
        if revenue_range:
            payload["revenue_range"] = revenue_range
        if organization_industry_tag_ids:
            payload["organization_industry_tag_ids"] = organization_industry_tag_ids

        return self._post("/mixed_companies/search", payload)

    # ------------------------------------------------------------------
    # People Enrichment (consumes credits — use selectively)
    # ------------------------------------------------------------------

    def enrich_person(
        self,
        person_id: str | None = None,
        email: str | None = None,
        linkedin_url: str | None = None,
        reveal_personal_emails: bool = True,
        reveal_phone_number: bool = False,
    ) -> dict:
        """Enrich a person to get email and phone.

        WARNING: This endpoint CONSUMES credits.
        Use selectively — only for qualified leads.

        Credit guards (applied automatically):
        - Free-domain filter: skips consumer email domains that never match B2B data
        - Result cache: class-level, prevents repeat API calls for the same identifier
        - Empty-streak counter: warns after 20 consecutive no-match responses

        Args:
            person_id: Apollo person ID
            email: Known email address
            linkedin_url: LinkedIn profile URL
            reveal_personal_emails: Request personal email addresses
            reveal_phone_number: Request phone numbers (async via webhook)

        Returns:
            Enriched person data.
        """
        # Free-domain filter — only when enriching by email
        if email and not person_id and not linkedin_url:
            domain = email.split("@")[-1].lower() if "@" in email else ""
            if domain in _FREE_EMAIL_DOMAINS:
                logger.info(f"enrich_person skipped — free domain: {domain}")
                return {}

        # Cache key: prefer person_id (most stable), then email, then linkedin_url
        cache_key = person_id or email or linkedin_url or ""
        if cache_key and cache_key in ApolloClient._enrich_cache:
            cached = ApolloClient._enrich_cache[cache_key]
            logger.info(f"enrich_person cache hit for key={cache_key[:20]}... matched={bool(cached)}")
            return cached or {}

        payload: dict[str, Any] = {
            "reveal_personal_emails": reveal_personal_emails,
            "reveal_phone_number": reveal_phone_number,
        }

        if person_id:
            payload["id"] = person_id
        elif email:
            payload["email"] = email
        elif linkedin_url:
            payload["linkedin_url"] = linkedin_url
        else:
            raise ValueError("Must provide person_id, email, or linkedin_url")

        result = self._post("/people/match", payload)

        # Cache result; None = confirmed no-match
        person = result.get("person") or None
        if cache_key:
            ApolloClient._enrich_cache[cache_key] = result if person else None

        # Track empty-response streak
        if not person:
            ApolloClient._empty_streak += 1
            if ApolloClient._empty_streak >= _EMPTY_STREAK_WARN:
                logger.warning(
                    f"Apollo enrich_person: {ApolloClient._empty_streak} consecutive "
                    "empty responses — check ICP targeting or credit balance"
                )
        else:
            ApolloClient._empty_streak = 0

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_state_from_raw_address(raw_address: str | None) -> str | None:
        """Extract a 2-letter US state code from Apollo's raw_address string.

        Apollo raw_address examples:
          "Cleveland, OH, United States"
          "Detroit, Michigan, United States"
          "Rolling Meadows, IL 60008, United States"
        """
        if not raw_address:
            return None

        _STATE_ABBREVS = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
            "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
            "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
            "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
            "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
            "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
            "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
            "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
            "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
            "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
            "wisconsin": "WI", "wyoming": "WY",
        }
        _VALID_ABBREVS = set(_STATE_ABBREVS.values())

        parts = [p.strip() for p in raw_address.split(",")]
        for part in parts:
            # Strip zip codes: "IL 60008" → "IL"
            token = part.split()[0].upper() if part.split() else ""
            if token in _VALID_ABBREVS:
                return token
            # Full state name match
            part_lower = part.strip().lower()
            if part_lower in _STATE_ABBREVS:
                return _STATE_ABBREVS[part_lower]
        return None

    @staticmethod
    def extract_company_data(person: dict) -> dict:
        """Extract company-level data from an Apollo person record.

        Apollo's People Search returns organization data embedded in each person.
        This extracts and normalizes it.
        """
        org = person.get("organization", {}) or {}

        # Apollo often omits city/state as separate fields; fall back to raw_address
        city = org.get("city") or org.get("headquarters_city")
        state = org.get("state") or org.get("headquarters_state")
        if not state:
            raw = org.get("raw_address") or org.get("headquarters_address")
            state = ApolloClient._parse_state_from_raw_address(raw)

        return {
            "apollo_id": org.get("id"),
            "name": org.get("name", ""),
            "domain": org.get("primary_domain"),
            "website": org.get("website_url"),
            "industry": org.get("industry"),
            "naics_code": None,  # Apollo doesn't always return NAICS
            "employee_count": org.get("estimated_num_employees"),
            "revenue_range": org.get("revenue_range"),
            "estimated_revenue": org.get("annual_revenue"),
            "founded_year": org.get("founded_year"),
            "city": city,
            "state": state,
            "country": org.get("country"),
            "linkedin_url": org.get("linkedin_url"),
            "twitter_url": org.get("twitter_url"),
            "phone": org.get("phone"),
            # Extended Apollo fields
            "sic_codes": org.get("sic_codes", []),
            "naics_codes": org.get("naics_codes", []),
            "headcount_growth_6m": org.get("organization_headcount_six_month_growth"),
            "headcount_growth_12m": org.get("organization_headcount_twelve_month_growth"),
            "headcount_growth_24m": org.get("organization_headcount_twenty_four_month_growth"),
            "parent_company_id": (org.get("owned_by_organization") or {}).get("id"),
            "parent_company_name": (org.get("owned_by_organization") or {}).get("name"),
            "is_public": bool(org.get("publicly_traded_symbol")),
            "stock_symbol": org.get("publicly_traded_symbol"),
            "logo_url": org.get("logo_url"),
            "sanitized_phone": org.get("sanitized_phone"),
            "revenue_printed": org.get("organization_revenue_printed"),
        }

    @staticmethod
    def extract_contact_data(person: dict) -> dict:
        """Extract contact-level data from an Apollo person record."""
        return {
            "apollo_id": person.get("id"),
            "first_name": person.get("first_name"),
            "last_name": person.get("last_name"),
            "full_name": person.get("name"),
            "email": person.get("email"),  # May be None from search (need enrichment)
            "phone": None,  # Requires enrichment
            "title": person.get("title"),
            "seniority": person.get("seniority"),
            "department": person.get("departments", [None])[0] if person.get("departments") else None,
            "headline": person.get("headline"),
            "linkedin_url": person.get("linkedin_url"),
            "twitter_url": person.get("twitter_url"),
            "photo_url": person.get("photo_url"),
            "city": person.get("city"),
            "state": person.get("state"),
            "country": person.get("country"),
            # Extended Apollo fields
            "has_email": bool(person.get("has_email")) if isinstance(person.get("has_email"), bool) else (str(person.get("has_email", "")).lower() in ("true", "1", "yes")),
            "has_direct_phone": bool(person.get("has_direct_phone")) if isinstance(person.get("has_direct_phone"), bool) else (str(person.get("has_direct_phone", "")).lower() in ("true", "1", "yes")),
            "last_refreshed_at": person.get("last_refreshed_at"),
        }

    def get_credits(self) -> dict:
        """Return Apollo account credit usage for the current month.

        Calls GET /auth/health — free, does not consume credits.

        Returns:
            Dict with keys:
              credits_used      — credits consumed this billing month
              credit_limit      — monthly credit cap
              credits_remaining — credit_limit - credits_used (0 if uncapped)
        """
        try:
            self._rate_limit()
            response = self.client.get("/auth/health")
            response.raise_for_status()
            data = response.json()
            user = data.get("user") or {}
            used = int(user.get("credits_used_for_the_month") or 0)
            limit = int(user.get("credit_limit_for_the_month") or 0)
            remaining = max(limit - used, 0) if limit else 9999
            return {"credits_used": used, "credit_limit": limit, "credits_remaining": remaining}
        except Exception as exc:
            logger.warning("get_credits failed: %s", exc)
            return {"credits_used": 0, "credit_limit": 0, "credits_remaining": 9999}

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
