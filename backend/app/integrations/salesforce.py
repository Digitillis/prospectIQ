"""Salesforce CRM sync integration.

Pushes ProspectIQ companies, contacts, and opportunities to Salesforce via
the REST API using username/password OAuth flow (simple_salesforce library).

Required env vars:
    SALESFORCE_USERNAME     — your Salesforce login email
    SALESFORCE_PASSWORD     — your Salesforce password
    SALESFORCE_SECURITY_TOKEN — user security token (append to password)
    SALESFORCE_DOMAIN         — "test" for sandbox, "login" for production (default)
    SALESFORCE_CONSUMER_KEY   — connected app client_id
    SALESFORCE_CONSUMER_SECRET — connected app client_secret

Dependency (optional — gracefully skipped if not installed):
    pip install simple-salesforce

Usage:
    from backend.app.integrations.salesforce import SalesforceSync
    from backend.app.core.database import Database

    db = Database()
    sf = SalesforceSync(username="...", password="...", security_token="...")
    result = sf.sync_all(db)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ProspectIQ status → Salesforce Opportunity Stage
_STAGE_MAP: dict[str, str] = {
    "discovered": "Prospecting",
    "researching": "Prospecting",
    "qualified": "Qualification",
    "outreach_pending": "Qualification",
    "contacted": "Needs Analysis",
    "engaged": "Value Proposition",
    "meeting_scheduled": "Id. Decision Makers",
    "pilot_discussion": "Perception Analysis",
    "pilot_signed": "Proposal/Price Quote",
    "active_pilot": "Negotiation/Review",
    "converted": "Closed Won",
    "not_interested": "Closed Lost",
    "bounced": "Closed Lost",
}


class SalesforceSync:
    """Push ProspectIQ data to Salesforce CRM."""

    def __init__(
        self,
        username: str,
        password: str,
        security_token: str,
        domain: str = "login",
        consumer_key: str = "",
        consumer_secret: str = "",
    ) -> None:
        self.username = username
        self.password = password
        self.security_token = security_token
        self.domain = domain
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self._sf: Any = None  # lazy-initialized

    def _get_client(self) -> Any:
        """Return authenticated simple_salesforce client (lazy init)."""
        if self._sf is not None:
            return self._sf
        try:
            from simple_salesforce import Salesforce  # type: ignore[import]
        except ImportError:
            raise ImportError(
                "simple-salesforce is required for Salesforce sync. "
                "Install it with: pip install simple-salesforce"
            )
        self._sf = Salesforce(
            username=self.username,
            password=self.password,
            security_token=self.security_token,
            domain=self.domain,
        )
        return self._sf

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def sync_all(self, db: Any) -> dict:
        """Run a full sync: accounts → contacts → opportunities.

        Returns:
            Summary dict with counts per object type.
        """
        accounts_pushed = self.sync_accounts(db)
        contacts_pushed = self.sync_contacts(db)
        opps_pushed = self.sync_opportunities(db)
        return {
            "accounts_pushed": accounts_pushed,
            "contacts_pushed": contacts_pushed,
            "opportunities_pushed": opps_pushed,
        }

    def sync_accounts(self, db: Any, limit: int = 500) -> int:
        """Upsert ProspectIQ companies as Salesforce Accounts."""
        sf = self._get_client()

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
                record = {
                    "Name": c.get("name", "")[:255],
                    "Website": (
                        f"https://{c['domain']}" if c.get("domain") else ""
                    ),
                    "Industry": c.get("industry") or "",
                    "BillingState": c.get("state") or "",
                    "NumberOfEmployees": c.get("employee_count") or None,
                    "Description": (
                        f"ProspectIQ | Tier: {c.get('tier', 'N/A')} | "
                        f"PQS: {c.get('pqs_total', 0)} | "
                        f"Status: {c.get('status', '')}"
                    ),
                    "AnnualRevenue": _revenue_to_float(c.get("revenue_range")),
                }
                # Upsert by Name (idempotent for demo purposes; production
                # should use a custom external ID field like ProspectIQ_ID__c)
                existing = sf.query(
                    f"SELECT Id FROM Account WHERE Name = '{_sf_escape(record['Name'])}' LIMIT 1"
                )
                if existing["records"]:
                    sf.Account.update(existing["records"][0]["Id"], record)
                else:
                    sf.Account.create(record)
                pushed += 1
            except Exception as e:
                logger.warning(f"Salesforce: failed to push account {c.get('name')}: {e}")

        logger.info(f"Salesforce: pushed {pushed}/{len(companies)} accounts")
        return pushed

    def sync_contacts(self, db: Any, limit: int = 1000) -> int:
        """Upsert ProspectIQ contacts as Salesforce Contacts."""
        sf = self._get_client()

        result = (
            db._filter_ws(
                db.client.table("contacts").select(
                    "id, first_name, last_name, full_name, email, title, status"
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
                full = c.get("full_name") or ""
                first = c.get("first_name") or (full.split()[0] if full else "Unknown")
                last = c.get("last_name") or (" ".join(full.split()[1:]) if full else "")
                email = c.get("email", "")

                record = {
                    "FirstName": first[:40],
                    "LastName": (last or first)[:80],
                    "Email": email,
                    "Title": (c.get("title") or "")[:128],
                }
                existing = sf.query(
                    f"SELECT Id FROM Contact WHERE Email = '{_sf_escape(email)}' LIMIT 1"
                )
                if existing["records"]:
                    sf.Contact.update(existing["records"][0]["Id"], record)
                else:
                    sf.Contact.create(record)
                pushed += 1
            except Exception as e:
                logger.warning(f"Salesforce: failed to push contact {c.get('email')}: {e}")

        logger.info(f"Salesforce: pushed {pushed}/{len(contacts)} contacts")
        return pushed

    def sync_opportunities(self, db: Any, limit: int = 500) -> int:
        """Create/update Salesforce Opportunities for engaged+ companies."""
        sf = self._get_client()

        result = (
            db._filter_ws(
                db.client.table("companies").select(
                    "id, name, tier, status, pqs_total"
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
                from datetime import datetime, timedelta
                close_days = {"engaged": 90, "meeting_scheduled": 75,
                              "pilot_discussion": 60, "pilot_signed": 45,
                              "active_pilot": 30, "converted": 0}.get(c.get("status", ""), 90)
                close_date = (datetime.utcnow() + timedelta(days=close_days)).strftime("%Y-%m-%d")
                opp_name = f"{c.get('name', '')} — Digitillis Pilot"

                record = {
                    "Name": opp_name[:120],
                    "StageName": _STAGE_MAP.get(c.get("status", ""), "Qualification"),
                    "CloseDate": close_date,
                    "Amount": float(_tier_to_deal_amount(c.get("tier", ""))),
                    "Description": (
                        f"Tier: {c.get('tier', 'N/A')} | "
                        f"PQS: {c.get('pqs_total', 0)}"
                    ),
                }
                existing = sf.query(
                    f"SELECT Id FROM Opportunity WHERE Name = '{_sf_escape(opp_name)}' LIMIT 1"
                )
                if existing["records"]:
                    sf.Opportunity.update(existing["records"][0]["Id"], record)
                else:
                    sf.Opportunity.create(record)
                pushed += 1
            except Exception as e:
                logger.warning(f"Salesforce: failed to push opp for {c.get('name')}: {e}")

        logger.info(f"Salesforce: pushed {pushed}/{len(companies)} opportunities")
        return pushed


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _revenue_to_float(revenue_range: str | None) -> float | None:
    """Parse '100M-400M' style strings to a float."""
    if not revenue_range:
        return None
    import re
    match = re.search(r"(\d+)", revenue_range)
    if not match:
        return None
    value = float(match.group(1))
    if "B" in (revenue_range or "").upper():
        value *= 1_000_000_000
    elif "M" in (revenue_range or "").upper():
        value *= 1_000_000
    return value


def _tier_to_deal_amount(tier: str) -> int:
    return {
        "1": 50_000, "mfg1": 50_000, "mfg2": 50_000,
        "2": 80_000, "mfg3": 80_000,
        "3": 150_000, "mfg4": 150_000,
        "fnb1": 50_000, "fnb2": 80_000,
    }.get(str(tier).lower(), 60_000)


def _sf_escape(value: str) -> str:
    """Escape single quotes for SOQL string literals."""
    return value.replace("'", "\\'")
