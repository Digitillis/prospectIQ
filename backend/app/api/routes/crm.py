"""CRM sync routes — HubSpot and Salesforce.

POST /api/crm/hubspot/sync        — push all companies/contacts/deals to HubSpot
POST /api/crm/hubspot/sync/companies — companies only
POST /api/crm/hubspot/sync/contacts  — contacts only
POST /api/crm/hubspot/sync/deals     — deals only (engaged+ companies)

POST /api/crm/salesforce/sync        — push all accounts/contacts/opps to Salesforce
POST /api/crm/salesforce/sync/accounts      — accounts only
POST /api/crm/salesforce/sync/contacts      — contacts only
POST /api/crm/salesforce/sync/opportunities — opportunities only
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.config import get_settings
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

router = APIRouter(prefix="/api/crm", tags=["crm"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


def _get_hubspot():
    """Return a configured HubSpotSync or raise 400 if not configured."""
    from backend.app.integrations.hubspot import HubSpotSync
    settings = get_settings()
    if not settings.hubspot_api_key:
        raise HTTPException(
            status_code=400,
            detail="HubSpot not configured. Set HUBSPOT_API_KEY in .env.",
        )
    return HubSpotSync(
        api_key=settings.hubspot_api_key,
        portal_id=getattr(settings, "hubspot_portal_id", ""),
    )


def _get_salesforce():
    """Return a configured SalesforceSync or raise 400 if not configured."""
    from backend.app.integrations.salesforce import SalesforceSync
    settings = get_settings()
    if not settings.salesforce_username:
        raise HTTPException(
            status_code=400,
            detail="Salesforce not configured. Set SALESFORCE_USERNAME + SALESFORCE_PASSWORD + SALESFORCE_SECURITY_TOKEN in .env.",
        )
    return SalesforceSync(
        username=settings.salesforce_username,
        password=settings.salesforce_password,
        security_token=settings.salesforce_security_token,
        domain=getattr(settings, "salesforce_domain", "login"),
    )


# ------------------------------------------------------------------
# HubSpot endpoints
# ------------------------------------------------------------------

@router.post("/hubspot/sync")
async def hubspot_sync_all():
    """Push all companies, contacts, and deals to HubSpot."""
    hs = _get_hubspot()
    db = get_db()
    try:
        result = hs.sync_all(db)
        return {"data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hubspot/sync/companies")
async def hubspot_sync_companies():
    """Push companies to HubSpot."""
    hs = _get_hubspot()
    db = get_db()
    try:
        pushed = hs.sync_companies(db)
        return {"data": {"companies_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hubspot/sync/contacts")
async def hubspot_sync_contacts():
    """Push contacts (with emails) to HubSpot."""
    hs = _get_hubspot()
    db = get_db()
    try:
        pushed = hs.sync_contacts(db)
        return {"data": {"contacts_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hubspot/sync/deals")
async def hubspot_sync_deals():
    """Push engaged+ companies as HubSpot Deals."""
    hs = _get_hubspot()
    db = get_db()
    try:
        pushed = hs.sync_deals(db)
        return {"data": {"deals_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Salesforce endpoints
# ------------------------------------------------------------------

@router.post("/salesforce/sync")
async def salesforce_sync_all():
    """Push all accounts, contacts, and opportunities to Salesforce."""
    sf = _get_salesforce()
    db = get_db()
    try:
        result = sf.sync_all(db)
        return {"data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/salesforce/sync/accounts")
async def salesforce_sync_accounts():
    """Push companies as Salesforce Accounts."""
    sf = _get_salesforce()
    db = get_db()
    try:
        pushed = sf.sync_accounts(db)
        return {"data": {"accounts_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/salesforce/sync/contacts")
async def salesforce_sync_contacts():
    """Push contacts (with emails) to Salesforce."""
    sf = _get_salesforce()
    db = get_db()
    try:
        pushed = sf.sync_contacts(db)
        return {"data": {"contacts_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/salesforce/sync/opportunities")
async def salesforce_sync_opportunities():
    """Push engaged+ companies as Salesforce Opportunities."""
    sf = _get_salesforce()
    db = get_db()
    try:
        pushed = sf.sync_opportunities(db)
        return {"data": {"opportunities_pushed": pushed}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
