"""Shared pytest fixtures for ProspectIQ test suite."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that `backend.*` imports resolve.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# ---------------------------------------------------------------------------
# Company / contact fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_company():
    """A qualified mid-market F&B company dict matching the ICP."""
    return {
        "id": "company-001",
        "name": "Acme Foods Inc",
        "domain": "acmefoods.com",
        "tier": "fb1",
        "estimated_revenue": 75_000_000,
        "employee_count": 200,
        "state": "OH",
        "country": "US",
        "is_private": True,
        "status": "researched",
        "research_summary": "",
        "technology_stack": [],
        "pain_signals": [],
        "manufacturing_profile": {},
        "personalization_hooks": [],
        "pqs_engagement": 0,
    }


@pytest.fixture
def sample_research():
    """Research intelligence dict for a typical F&B prospect."""
    return {
        "company_id": "company-001",
        "perplexity_response": "Acme Foods uses SAP ERP and CMMS for maintenance tracking.",
        "claude_analysis": "Strong IoT maturity. Digital transformation initiative announced.",
        "company_description": "Mid-size food manufacturer focused on process automation.",
        "manufacturing_type": "process",
        "equipment_types": ["bottling lines", "conveyors"],
        "known_systems": ["SAP PM", "CMMS"],
        "iot_maturity": "intermediate",
        "maintenance_approach": "condition_based",
        "digital_transformation_status": "In progress — hired VP Digital in 2025",
        "pain_points": ["downtime on filling lines", "FSMA compliance burden"],
        "opportunities": ["predictive maintenance", "audit readiness"],
        "existing_solutions": [],
        "funding_status": "",
        "funding_details": "",
        "personalization_hooks": [
            "Recently hired VP Digital to lead Industry 4.0 initiative",
            "Bottling line downtime costing ~$500K/year",
        ],
        "confidence_level": "high",
    }


@pytest.fixture
def good_draft():
    """An outreach draft that should pass all quality checks."""
    return {
        "id": "draft-001",
        "subject": "Acme Foods — production uptime",
        "body": (
            "Hi Sarah,\n\n"
            "Noticed Acme Foods recently brought on a VP Digital — usually signals the team is "
            "ready to move beyond spreadsheets for maintenance. \n\n"
            "We built Digitillis specifically for manufacturers running SAP who want to reduce "
            "unplanned downtime without a 12-month IT project. Most customers see their first "
            "predictive alert within 48 hours of connecting their data.\n\n"
            "Would it be worth a 15-minute call to see if it's a fit for Acme Foods?\n\n"
            "Best regards,\n"
            "Avanish\n\n"
            "Avanish Mehrotra\n"
            "Founder & CEO\n"
            "Digitillis | www.digitillis.com\n"
            "avi@digitillis.com | 224.355.4500"
        ),
    }
