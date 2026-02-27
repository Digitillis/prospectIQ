"""Deterministic territory mapping.

Maps US state codes to sales territories. No LLM needed.
"""

from __future__ import annotations

# Direct lookup table for O(1) performance
STATE_TO_TERRITORY: dict[str, str] = {
    # New England
    "CT": "New England", "MA": "New England", "ME": "New England",
    "NH": "New England", "RI": "New England", "VT": "New England",
    # Central US + Canada
    "AZ": "Central US + Canada", "CO": "Central US + Canada",
    "DC": "Central US + Canada", "DE": "Central US + Canada",
    "IA": "Central US + Canada", "ID": "Central US + Canada",
    "IL": "Central US + Canada", "IN": "Central US + Canada",
    "KS": "Central US + Canada", "MD": "Central US + Canada",
    "MI": "Central US + Canada", "MN": "Central US + Canada",
    "MO": "Central US + Canada", "MT": "Central US + Canada",
    "ND": "Central US + Canada", "NE": "Central US + Canada",
    "NJ": "Central US + Canada", "NM": "Central US + Canada",
    "NV": "Central US + Canada", "NY": "Central US + Canada",
    "OH": "Central US + Canada", "PA": "Central US + Canada",
    "SD": "Central US + Canada", "UT": "Central US + Canada",
    "WI": "Central US + Canada", "WY": "Central US + Canada",
    # Southern US + International
    "AL": "Southern US + International", "AR": "Southern US + International",
    "FL": "Southern US + International", "GA": "Southern US + International",
    "KY": "Southern US + International", "LA": "Southern US + International",
    "MS": "Southern US + International", "NC": "Southern US + International",
    "OK": "Southern US + International", "PR": "Southern US + International",
    "SC": "Southern US + International", "TN": "Southern US + International",
    "TX": "Southern US + International", "VA": "Southern US + International",
    "WV": "Southern US + International",
    # West Coast
    "AK": "West Coast", "CA": "West Coast", "HI": "West Coast",
    "OR": "West Coast", "WA": "West Coast",
}

DEFAULT_TERRITORY = "Southern US + International"


def get_territory(state_code: str | None) -> str:
    """Get territory name from a US state code.

    Args:
        state_code: Two-letter state code (e.g., 'IL', 'OH'). Case-insensitive.

    Returns:
        Territory name. Defaults to 'Southern US + International' if unknown.
    """
    if not state_code:
        return DEFAULT_TERRITORY
    return STATE_TO_TERRITORY.get(state_code.upper().strip(), DEFAULT_TERRITORY)


def is_midwest(state_code: str | None) -> bool:
    """Check if a state is in the Midwest target geography."""
    if not state_code:
        return False
    return state_code.upper().strip() in {
        "IL", "IN", "MI", "OH", "WI", "MN", "IA", "MO"
    }
