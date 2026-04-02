"""HubSpot CRM sync integration.

Pushes ProspectIQ companies, contacts, and deal stages to HubSpot via the
HubSpot v3 REST API. Designed as a one-way push (ProspectIQ → HubSpot) to
keep HubSpot as a presentation/reporting layer while ProspectIQ owns the
intelligence.

Required env vars:
    HUBSPOT_API_KEY     — private app access token (not OAuth for simplicity)
    HUBSPOT_PORTAL_ID   — your HubSpot portal/account ID (numeric string)

Usage:
    from backend.app.integrations.hubspot import HubSpotSync
    from backend.app.core.database import Database

    db = Database()
    hs = HubSpotSync(api_key="...", portal_id="12345")
    result = hs.sync_all(db)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Status map: ProspectIQ status → HubSpot Deal Stage label
_STAGE_MAP: dict[str, str] = {
    "discovered": "prospecting",
    "researching": "prospecting",
    "qualified": "prospecting",
    "outreach_pending": "prospecting",
    "contacted": "appointment_scheduled",
    "engaged": "qualified_to_buy",
    "meeting_scheduled": "appointment_scheduled",
    "pilot_discussion": "presentation_scheduled",
    "pilot_signed": "decision_maker_bought_in",
    "active_pilot": "decision_maker_bought_in",
    "converted": "closed_won",
    "not_interested": "closed_lost",
    "bounced": "closed_lost",
}

_BASE = "https://api.hubapi.com"


class HubSpotSync:
    """Push ProspectIQ data to HubSpot CRM."""

    def __init__(self, api_key: str, portal_id: str = "") -> None:
        self.api_key = api_key
        self.portal_id = portal_id
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sync_all(self, db: Any) -> dict:
        """Run a full sync: companies → contacts → deals.

        Returns:
            Summary dict with counts per object type.
        """
        companies_pushed = self.sync_companies(db)
        contacts_pushed = self.sync_contacts(db)
        deals_pushed = self.sync_deals(db)
        return {
            "companies_pushed": companies_pushed,
            "contacts_pushed": contacts_pushed,
            "deals_pushed": deals_pushed,
        }

    def sync_companies(self, db: Any, limit: int = 500) -> int:
        """Upsert ProspectIQ companies as HubSpot Companies.

        Uses domain as the deduplication key. Creates if not found, updates if found.
        """
        result = (
            db._filter_ws(
                db.client.table("companies").select(
                    "id, name, domain, industry, state, employee_count, "
                    "revenue_range, status, tier, pqs_total"
                )
            )
            .not_.in_("status", ["discovered", "not_interested", "bounced"])
            .limit(limit)
            .execute()
        )
        companies = result.data or []
        pushed = 0

        for c in companies:
            try:
                props = {
                    "name": c.get("name", ""),
                    "domain": c.get("domain") or "",
                    "industry": c.get("industry") or "",
                    "state": c.get("state") or "",
                    "numberofemployees": str(c.get("employee_count") or ""),
                    "annualrevenue": _revenue_to_int(c.get("revenue_range")),
                    "hs_lead_status": _STAGE_MAP.get(c.get("status", ""), "lead"),
                    "description": (
                        f"ProspectIQ tier: {c.get('tier', 'N/A')} | "
                        f"PQS: {c.get('pqs_total', 0)}"
                    ),
                }
                self._upsert_company(props, domain=c.get("domain"))
                pushed += 1
            except Exception as e:
                logger.warning(f"HubSpot: failed to push company {c.get('name')}: {e}")

        logger.info(f"HubSpot: pushed {pushed}/{len(companies)} companies")
        return pushed

    def sync_contacts(self, db: Any, limit: int = 1000) -> int:
        """Upsert ProspectIQ contacts as HubSpot Contacts.

        Uses email as the deduplication key. Only syncs contacts with an email.
        """
        result = (
            db._filter_ws(
                db.client.table("contacts").select(
                    "id, first_name, last_name, full_name, email, title, "
                    "company_id, status, linkedin_url"
                )
            )
            .not_.is_("email", "null")
            .neq("status", "unsubscribed")
            .neq("status", "bounced")
            .limit(limit)
            .execute()
        )
        contacts = result.data or []
        pushed = 0

        for c in contacts:
            try:
                full_name = c.get("full_name") or ""
                first = c.get("first_name") or (full_name.split()[0] if full_name else "")
                last = c.get("last_name") or (" ".join(full_name.split()[1:]) if full_name else "")
                props = {
                    "firstname": first,
                    "lastname": last,
                    "email": c.get("email", ""),
                    "jobtitle": c.get("title") or "",
                    "linkedin_bio": c.get("linkedin_url") or "",
                    "hs_lead_status": "IN_PROGRESS" if c.get("status") == "active" else "NEW",
                }
                self._upsert_contact(props, email=c.get("email", ""))
                pushed += 1
            except Exception as e:
                logger.warning(f"HubSpot: failed to push contact {c.get('email')}: {e}")

        logger.info(f"HubSpot: pushed {pushed}/{len(contacts)} contacts")
        return pushed

    def sync_deals(self, db: Any, limit: int = 500) -> int:
        """Create/update HubSpot Deals for companies at engaged+ stages."""
        result = (
            db._filter_ws(
                db.client.table("companies").select(
                    "id, name, tier, status, pqs_total, updated_at"
                )
            )
            .in_("status", [
                "engaged", "meeting_scheduled", "pilot_discussion",
                "pilot_signed", "active_pilot", "converted",
            ])
            .limit(limit)
            .execute()
        )
        companies = result.data or []
        pushed = 0

        for c in companies:
            try:
                deal_stage = _STAGE_MAP.get(c.get("status", ""), "qualified_to_buy")
                amount = _tier_to_deal_amount(c.get("tier", ""))
                props = {
                    "dealname": f"{c.get('name', '')} — Digitillis Pilot",
                    "dealstage": deal_stage,
                    "amount": str(amount),
                    "pipeline": "default",
                    "description": (
                        f"Tier: {c.get('tier', 'N/A')} | "
                        f"PQS: {c.get('pqs_total', 0)} | "
                        f"Status: {c.get('status', '')}"
                    ),
                    "closedate": _estimate_close_date(c.get("status", "")),
                }
                self._upsert_deal(props, deal_name=props["dealname"])
                pushed += 1
            except Exception as e:
                logger.warning(f"HubSpot: failed to push deal for {c.get('name')}: {e}")

        logger.info(f"HubSpot: pushed {pushed}/{len(companies)} deals")
        return pushed

    # ------------------------------------------------------------------
    # Internal API helpers
    # ------------------------------------------------------------------

    def _upsert_company(self, props: dict, domain: str | None) -> None:
        """Upsert a HubSpot Company by domain."""
        if domain:
            # Search for existing company by domain
            existing_id = self._search_object(
                "companies", "domain", domain
            )
            if existing_id:
                self._update_object("companies", existing_id, props)
                return
        # Create new
        self._create_object("companies", props)

    def _upsert_contact(self, props: dict, email: str) -> None:
        """Upsert a HubSpot Contact by email."""
        existing_id = self._search_object("contacts", "email", email)
        if existing_id:
            self._update_object("contacts", existing_id, props)
        else:
            self._create_object("contacts", props)

    def _upsert_deal(self, props: dict, deal_name: str) -> None:
        """Upsert a HubSpot Deal by name."""
        existing_id = self._search_object("deals", "dealname", deal_name)
        if existing_id:
            self._update_object("deals", existing_id, props)
        else:
            self._create_object("deals", props)

    def _search_object(self, object_type: str, prop: str, value: str) -> str | None:
        """Search for a CRM object by a property value. Returns HS ID or None."""
        url = f"{_BASE}/crm/v3/objects/{object_type}/search"
        body = {
            "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
            "properties": [prop],
            "limit": 1,
        }
        resp = httpx.post(url, headers=self._headers, json=body, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0]["id"] if results else None

    def _create_object(self, object_type: str, props: dict) -> str:
        """Create a new CRM object. Returns the new HS ID."""
        url = f"{_BASE}/crm/v3/objects/{object_type}"
        resp = httpx.post(url, headers=self._headers, json={"properties": props}, timeout=10)
        resp.raise_for_status()
        return resp.json()["id"]

    def _update_object(self, object_type: str, hs_id: str, props: dict) -> None:
        """Update an existing CRM object by HS ID."""
        url = f"{_BASE}/crm/v3/objects/{object_type}/{hs_id}"
        resp = httpx.patch(url, headers=self._headers, json={"properties": props}, timeout=10)
        resp.raise_for_status()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _revenue_to_int(revenue_range: str | None) -> str:
    """Parse '100M-400M' style strings to an integer string HubSpot expects."""
    if not revenue_range:
        return ""
    import re
    # Extract first number (e.g. '100' from '100M-400M')
    match = re.search(r"(\d+)", revenue_range)
    if not match:
        return ""
    value = int(match.group(1))
    # Scale by M or B suffix in the string
    if "B" in (revenue_range or "").upper():
        value *= 1_000_000_000
    elif "M" in (revenue_range or "").upper():
        value *= 1_000_000
    return str(value)


def _tier_to_deal_amount(tier: str) -> int:
    """Map Digitillis tier to estimated pilot deal value (USD)."""
    tier_amounts = {
        "1": 50_000,   # T1: $100M–$400M — entry pilot
        "mfg1": 50_000,
        "mfg2": 50_000,
        "2": 80_000,   # T2: $400M–$1B — full pilot
        "mfg3": 80_000,
        "3": 150_000,  # T3: $1B–$2B — enterprise
        "mfg4": 150_000,
        "fnb1": 50_000,
        "fnb2": 80_000,
    }
    return tier_amounts.get(str(tier).lower(), 60_000)


def _estimate_close_date(status: str) -> str:
    """Return ISO close date estimate based on deal stage."""
    from datetime import datetime, timedelta
    days_to_close = {
        "engaged": 90,
        "meeting_scheduled": 75,
        "pilot_discussion": 60,
        "pilot_signed": 45,
        "active_pilot": 30,
        "converted": 0,
    }
    days = days_to_close.get(status, 90)
    close_dt = datetime.utcnow() + timedelta(days=days)
    return str(int(close_dt.timestamp() * 1000))  # HubSpot expects millisecond epoch
