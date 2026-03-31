"""Sequence routing: maps (vertical, persona_type) → Instantly campaign ID.

Campaign IDs are read from environment variables so they can be swapped
without code changes when Instantly sequences are created or renamed.

Usage:
    from backend.app.core.sequence_router import get_campaign_id, get_vertical_bucket

    vertical = get_vertical_bucket(naics_prefix="311", campaign_name=None)
    campaign_id = get_campaign_id(vertical, persona_type="vp_quality_food_safety")
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping of (vertical_bucket, persona_type) → env-var name for campaign ID
# ---------------------------------------------------------------------------
# Vertical buckets:
#   "fb"  — Food & Beverage (NAICS 311x, 312x)
#   "mfg" — Discrete Manufacturing (NAICS 332, 333, 336)
#
# If the NAICS prefix matches neither bucket the caller should default to
# "mfg" (safe fallback for any manufacturing vertical).
# ---------------------------------------------------------------------------

SEQUENCE_MAP: dict[tuple[str, str | None], str] = {
    # F&B — Food Safety / Quality (primary FSMA buyers)
    ("fb", "vp_quality_food_safety"):    "INSTANTLY_SEQ_FB_VP_QUALITY",
    ("fb", "director_quality_food_safety"): "INSTANTLY_SEQ_FB_DIR_QUALITY",
    # F&B — Operations
    ("fb", "vp_ops"):       "INSTANTLY_SEQ_FB_VP_OPS",
    ("fb", "coo"):          "INSTANTLY_SEQ_FB_VP_OPS",   # same sequence as VP Ops
    ("fb", "plant_manager"): "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    ("fb", "director_ops"): "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    # F&B — Supply chain / adjacent
    ("fb", "vp_supply_chain"):  "INSTANTLY_SEQ_FB_VP_OPS",
    ("fb", "maintenance_leader"): "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    # Manufacturing — Operations
    ("mfg", "vp_ops"):       "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "coo"):          "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "plant_manager"): "INSTANTLY_SEQ_MFG_PLANT_MANAGER",
    ("mfg", "director_ops"): "INSTANTLY_SEQ_MFG_PLANT_MANAGER",
    # Manufacturing — Maintenance / Reliability (PdM angle)
    ("mfg", "maintenance_leader"): "INSTANTLY_SEQ_MFG_MAINTENANCE",
    # Manufacturing — Supply chain / other
    ("mfg", "vp_supply_chain"): "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "director_quality_food_safety"): "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "vp_quality_food_safety"):       "INSTANTLY_SEQ_MFG_VP_OPS",
}

# NAICS prefixes that map to each vertical bucket
_FB_NAICS_PREFIXES = ("311", "312")
_MFG_NAICS_PREFIXES = ("332", "333", "336")


def get_vertical_bucket(
    naics_prefix: str | None,
    campaign_name: str | None,
) -> str:
    """Classify a company into a vertical bucket ('fb' or 'mfg').

    Checks NAICS prefix first, then falls back to heuristic matching
    against the campaign name, then defaults to 'mfg'.

    Args:
        naics_prefix: Leading digits of the company's NAICS code, e.g. "311".
        campaign_name: ProspectIQ campaign name (used as a fallback signal).

    Returns:
        'fb' or 'mfg'.
    """
    if naics_prefix:
        clean = naics_prefix.strip()
        if any(clean.startswith(p) for p in _FB_NAICS_PREFIXES):
            return "fb"
        if any(clean.startswith(p) for p in _MFG_NAICS_PREFIXES):
            return "mfg"

    if campaign_name:
        name = campaign_name.lower()
        if any(x in name for x in ("fb", "food", "beverage", "fsma", "dairy")):
            return "fb"
        if any(x in name for x in ("mfg", "manufacturing", "industrial", "machinery")):
            return "mfg"

    logger.debug(
        "Could not determine vertical from naics_prefix=%r, campaign=%r — defaulting to 'mfg'",
        naics_prefix,
        campaign_name,
    )
    return "mfg"


def get_campaign_id(vertical: str, persona_type: str | None) -> str | None:
    """Look up the Instantly campaign ID for a vertical + persona combination.

    Reads the corresponding environment variable. Returns None if the env
    var is not set (not yet configured in Instantly).

    Args:
        vertical: Vertical bucket string — 'fb' or 'mfg'.
        persona_type: Contact persona type from classify_persona(), e.g.
            'vp_quality_food_safety', 'plant_manager', etc.

    Returns:
        Instantly campaign ID string, or None if not configured.
    """
    key = (vertical, persona_type)
    env_var = SEQUENCE_MAP.get(key)

    if not env_var:
        # Fall back to the generic ops sequence for this vertical
        env_var = f"INSTANTLY_SEQ_{vertical.upper()}_VP_OPS"
        logger.debug(
            "No exact sequence mapping for (%r, %r) — falling back to %s",
            vertical,
            persona_type,
            env_var,
        )

    campaign_id = os.environ.get(env_var, "").strip()
    if not campaign_id:
        logger.warning(
            "Sequence env var %s is not set — contact will be skipped", env_var
        )
        return None

    return campaign_id
