"""Tests for the persona allowlist gate (P1.2).

Verifies the hard allowlist behavior of `is_eligible()`:
  - 8 allowed personas all pass
  - 4 wrong-function personas (HR, Sales, Marketing, Finance) all fail
  - confidence floor (0.70) is enforced
  - missing confidence on LLM source is rejected
"""

from __future__ import annotations

import pytest

from backend.app.core.contact_filter import (
    _ALLOWED_PERSONAS,
    is_eligible,
    normalize_persona_classification,
)


# -----------------------------
# Allowed: 8 canonical personas
# -----------------------------

@pytest.mark.parametrize(
    "classification",
    sorted(_ALLOWED_PERSONAS),
)
def test_allowed_personas_pass(classification: str) -> None:
    contact = {
        "id": "c1",
        "persona_classification": classification,
        "persona_confidence": 0.85,
    }
    assert is_eligible(contact) is True


def test_all_eight_allowlist_members_present() -> None:
    """The allowlist must contain exactly the 8 canonical personas required by P1.2."""
    expected = {
        "vp_operations",
        "vp_quality",
        "plant_manager",
        "director_operations",
        "director_quality",
        "director_manufacturing",
        "coo",
        "vp_supply_chain",
    }
    assert set(_ALLOWED_PERSONAS) == expected


# ------------------------------------
# Blocked: HR, Sales, Marketing, Finance
# ------------------------------------

@pytest.mark.parametrize(
    "classification",
    [
        "hr_manager",
        "sales_director",
        "marketing_manager",
        "finance_controller",
    ],
)
def test_blocked_wrong_function_personas(classification: str) -> None:
    contact = {
        "id": "c2",
        "persona_classification": classification,
        "persona_confidence": 0.99,
    }
    assert is_eligible(contact) is False


# ----------------------------
# Confidence floor enforcement
# ----------------------------

def test_below_confidence_floor_rejected() -> None:
    contact = {
        "persona_classification": "vp_operations",
        "persona_confidence": 0.69,  # just below 0.70 floor
    }
    assert is_eligible(contact) is False


def test_at_confidence_floor_accepted() -> None:
    contact = {
        "persona_classification": "plant_manager",
        "persona_confidence": 0.70,
    }
    assert is_eligible(contact) is True


def test_llm_source_missing_confidence_rejected() -> None:
    """LLM-classified rows must supply confidence — no implicit 1.0."""
    contact = {
        "persona_classification": "coo",
        "persona_source": "llm",
        # persona_confidence intentionally absent
    }
    assert is_eligible(contact) is False


def test_keyword_source_missing_confidence_accepted() -> None:
    """Deterministic keyword-classified rows are trusted at 1.0 by default."""
    contact = {
        "persona_classification": "vp_quality",
        # no persona_source, no persona_confidence — legacy data
    }
    assert is_eligible(contact) is True


# ---------------------------------
# persona_type → classification map
# ---------------------------------

def test_persona_type_to_classification_mapping() -> None:
    # Allowlisted source roles map correctly
    assert normalize_persona_classification("vp_ops") == "vp_operations"
    assert normalize_persona_classification("director_ops") == "director_operations"
    assert normalize_persona_classification("vp_quality_food_safety") == "vp_quality"
    assert normalize_persona_classification("plant_manager") == "plant_manager"
    assert normalize_persona_classification("coo") == "coo"

    # Roles previously soft-scored that must now fall outside the allowlist
    assert normalize_persona_classification("maintenance_leader") is None
    assert normalize_persona_classification("digital_transformation") is None
    assert normalize_persona_classification("cio") is None
    assert normalize_persona_classification(None) is None


def test_eligible_via_legacy_persona_type_only() -> None:
    """A contact with only the legacy `persona_type` field must still gate correctly."""
    allowed = {"persona_type": "vp_ops"}            # → vp_operations (allow)
    blocked = {"persona_type": "maintenance_leader"} # → None (block)

    assert is_eligible(allowed) is True
    assert is_eligible(blocked) is False
