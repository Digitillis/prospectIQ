"""Sequence routing: maps (campaign_cluster, persona_type) → Instantly campaign ID.

Campaign IDs are read from environment variables so they can be swapped
without code changes when Instantly sequences are created or renamed.

Primary routing dimension: campaign_cluster (machinery / auto / chemicals /
metals / process / fb / other).  The old vertical bucket ('fb' / 'mfg') is
kept as a legacy fallback for any callers not yet passing campaign_cluster.

T3 override: companies with tranche='T3' are set to outreach_mode='manual'
at discovery time and must NOT be pushed to Instantly automatically.

Usage:
    from backend.app.core.sequence_router import get_campaign_id, should_skip_outreach

    # New cluster-based path (preferred)
    campaign_id = get_campaign_id(
        campaign_cluster="machinery",
        persona_type="vp_ops",
        tranche="T2",
        outreach_mode="auto",
    )

    # Legacy NAICS-based path (backward-compat)
    campaign_id = get_campaign_id_legacy(
        naics_prefix="333",
        persona_type="vp_ops",
    )
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cluster → persona → env-var name for the Instantly campaign ID
#
# Env var naming convention:
#   INSTANTLY_SEQ_{CLUSTER}_{PERSONA}
#
# Where CLUSTER ∈ {MACHINERY, AUTO, CHEMICALS, METALS, PROCESS, FB, GENERAL}
# and   PERSONA ∈ {VP_OPS, PLANT_MANAGER, MAINTENANCE, DIRECTOR_OPS, GENERAL}
#
# Not all combinations need a dedicated sequence — fall-through to GENERAL
# is intentional for lower-priority persona × cluster combinations.
# ---------------------------------------------------------------------------

CLUSTER_SEQUENCE_MAP: dict[tuple[str, str | None], str] = {
    # ── Machinery cluster ────────────────────────────────────────────────────
    ("machinery", "vp_ops"):           "INSTANTLY_SEQ_MACHINERY_VP_OPS",
    ("machinery", "coo"):              "INSTANTLY_SEQ_MACHINERY_VP_OPS",
    ("machinery", "plant_manager"):    "INSTANTLY_SEQ_MACHINERY_PLANT_MANAGER",
    ("machinery", "director_ops"):     "INSTANTLY_SEQ_MACHINERY_PLANT_MANAGER",
    ("machinery", "maintenance_leader"): "INSTANTLY_SEQ_MACHINERY_MAINTENANCE",
    ("machinery", "digital_transformation"): "INSTANTLY_SEQ_MACHINERY_VP_OPS",
    ("machinery", None):               "INSTANTLY_SEQ_MACHINERY_GENERAL",

    # ── Auto cluster ─────────────────────────────────────────────────────────
    ("auto", "vp_ops"):                "INSTANTLY_SEQ_AUTO_VP_OPS",
    ("auto", "coo"):                   "INSTANTLY_SEQ_AUTO_VP_OPS",
    ("auto", "plant_manager"):         "INSTANTLY_SEQ_AUTO_PLANT_MANAGER",
    ("auto", "director_ops"):          "INSTANTLY_SEQ_AUTO_PLANT_MANAGER",
    ("auto", "maintenance_leader"):    "INSTANTLY_SEQ_AUTO_MAINTENANCE",
    ("auto", None):                    "INSTANTLY_SEQ_AUTO_GENERAL",

    # ── Chemicals cluster ────────────────────────────────────────────────────
    ("chemicals", "vp_ops"):           "INSTANTLY_SEQ_CHEMICALS_VP_OPS",
    ("chemicals", "coo"):              "INSTANTLY_SEQ_CHEMICALS_VP_OPS",
    ("chemicals", "plant_manager"):    "INSTANTLY_SEQ_CHEMICALS_PLANT_MANAGER",
    ("chemicals", "director_ops"):     "INSTANTLY_SEQ_CHEMICALS_PLANT_MANAGER",
    ("chemicals", "maintenance_leader"): "INSTANTLY_SEQ_CHEMICALS_MAINTENANCE",
    ("chemicals", None):               "INSTANTLY_SEQ_CHEMICALS_GENERAL",

    # ── Metals cluster ───────────────────────────────────────────────────────
    ("metals", "vp_ops"):              "INSTANTLY_SEQ_METALS_VP_OPS",
    ("metals", "coo"):                 "INSTANTLY_SEQ_METALS_VP_OPS",
    ("metals", "plant_manager"):       "INSTANTLY_SEQ_METALS_PLANT_MANAGER",
    ("metals", "director_ops"):        "INSTANTLY_SEQ_METALS_PLANT_MANAGER",
    ("metals", "maintenance_leader"):  "INSTANTLY_SEQ_METALS_MAINTENANCE",
    ("metals", None):                  "INSTANTLY_SEQ_METALS_GENERAL",

    # ── Process cluster (refining, mining, paper, cement) ───────────────────
    ("process", "vp_ops"):             "INSTANTLY_SEQ_PROCESS_VP_OPS",
    ("process", "coo"):                "INSTANTLY_SEQ_PROCESS_VP_OPS",
    ("process", "plant_manager"):      "INSTANTLY_SEQ_PROCESS_PLANT_MANAGER",
    ("process", "director_ops"):       "INSTANTLY_SEQ_PROCESS_PLANT_MANAGER",
    ("process", "maintenance_leader"): "INSTANTLY_SEQ_PROCESS_MAINTENANCE",
    ("process", None):                 "INSTANTLY_SEQ_PROCESS_GENERAL",

    # ── Food & Beverage cluster ──────────────────────────────────────────────
    # F&B: ops/uptime messaging only — NOT food safety / FSMA angle
    ("fb", "vp_ops"):                  "INSTANTLY_SEQ_FB_VP_OPS",
    ("fb", "coo"):                     "INSTANTLY_SEQ_FB_VP_OPS",
    ("fb", "plant_manager"):           "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    ("fb", "director_ops"):            "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    ("fb", "maintenance_leader"):      "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    ("fb", "vp_quality_food_safety"):  "INSTANTLY_SEQ_FB_VP_OPS",   # ops angle
    ("fb", "director_quality_food_safety"): "INSTANTLY_SEQ_FB_PLANT_MANAGER",
    ("fb", None):                      "INSTANTLY_SEQ_FB_GENERAL",

    # ── Other / unknown cluster ──────────────────────────────────────────────
    ("other", "vp_ops"):               "INSTANTLY_SEQ_GENERAL_VP_OPS",
    ("other", "coo"):                  "INSTANTLY_SEQ_GENERAL_VP_OPS",
    ("other", "plant_manager"):        "INSTANTLY_SEQ_GENERAL_PLANT_MANAGER",
    ("other", "director_ops"):         "INSTANTLY_SEQ_GENERAL_PLANT_MANAGER",
    ("other", "maintenance_leader"):   "INSTANTLY_SEQ_GENERAL_MAINTENANCE",
    ("other", None):                   "INSTANTLY_SEQ_GENERAL",

    # ── Legacy "mfg" bucket (returned by get_vertical_bucket() for all non-FB)
    # Maps to the INSTANTLY_SEQ_MFG_* env vars already set in .env.
    ("mfg", "vp_ops"):               "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "coo"):                  "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", "plant_manager"):        "INSTANTLY_SEQ_MFG_PLANT_MANAGER",
    ("mfg", "director_ops"):         "INSTANTLY_SEQ_MFG_DIRECTOR_OPS",
    ("mfg", "maintenance_leader"):   "INSTANTLY_SEQ_MFG_MAINTENANCE",
    ("mfg", "digital_transformation"): "INSTANTLY_SEQ_MFG_VP_OPS",
    ("mfg", None):                   "INSTANTLY_SEQ_MFG_GENERAL",
}

# ---------------------------------------------------------------------------
# Legacy NAICS-based vertical buckets (backward-compat)
# ---------------------------------------------------------------------------
_FB_NAICS_PREFIXES = ("311", "312", "3116", "3115")
_LEGACY_CLUSTER_MAP: dict[str, str] = {
    "mfg1": "machinery", "mfg2": "machinery", "mfg4": "machinery",
    "mfg5": "machinery", "mfg8": "machinery",
    "mfg3": "auto",
    "mfg7": "metals",
    "pmfg1": "chemicals",
    "pmfg3": "process", "pmfg4": "process", "pmfg7": "process", "pmfg8": "process",
    "fb1": "fb", "fb2": "fb", "fb3": "fb", "fb4": "fb", "fb5": "fb",
}


def should_skip_outreach(company: dict) -> tuple[bool, str]:
    """Return (skip, reason) for a company based on tranche and outreach_mode.

    Args:
        company: Company record dict (from DB or Supabase).

    Returns:
        (True, reason) if outreach should be skipped; (False, "") otherwise.
    """
    # Read from dedicated column first, fall back to custom_tags JSONB
    outreach_mode = company.get("outreach_mode") or _get_custom_tag(company, "outreach_mode")
    tranche = company.get("tranche") or _get_custom_tag(company, "tranche")
    status = company.get("status", "")

    if status in ("paused", "disqualified", "contacted", "outreach_pending"):
        if status in ("contacted", "outreach_pending"):
            return True, f"Already in outreach (status={status})"
        return True, f"Company is {status}"

    if outreach_mode == "manual":
        return True, "outreach_mode=manual — requires human review before sequencing"

    if tranche == "T3":
        return True, "T3 tranche — manual motion only, not cold email"

    campaign_cluster = company.get("campaign_cluster") or _get_custom_tag(company, "campaign_cluster")
    if campaign_cluster == "watchlist":
        return True, "campaign_cluster=watchlist — excluded from auto outreach"

    return False, ""


def get_campaign_id(
    campaign_cluster: str | None,
    persona_type: str | None,
    tranche: str | None = None,
    outreach_mode: str | None = None,
) -> str | None:
    """Look up the Instantly campaign ID for a cluster + persona combination.

    Reads the corresponding environment variable.  Returns None if the env
    var is not set (sequence not yet created in Instantly) or if outreach
    should be skipped for this company.

    Args:
        campaign_cluster: Vertical cluster — 'machinery', 'auto', 'chemicals',
            'metals', 'process', 'fb', 'other', or 'watchlist'.
        persona_type: Contact persona type, e.g. 'vp_ops', 'plant_manager'.
        tranche: Revenue tranche — 'T1', 'T2', 'T3'.  T3 → returns None.
        outreach_mode: 'auto' or 'manual'.  manual → returns None.

    Returns:
        Instantly campaign ID string, or None if not configured / should skip.
    """
    # Hard guards
    if outreach_mode == "manual":
        logger.info("Skipping contact — outreach_mode=manual")
        return None
    if tranche == "T3":
        logger.info("Skipping contact — T3 tranche (manual motion only)")
        return None
    if campaign_cluster == "watchlist":
        logger.info("Skipping contact — campaign_cluster=watchlist")
        return None

    # Resolve cluster
    cluster = campaign_cluster or "other"
    key = (cluster, persona_type)
    env_var = CLUSTER_SEQUENCE_MAP.get(key)

    if not env_var:
        # Fall back to cluster-level general sequence
        fallback_key = (cluster, None)
        env_var = CLUSTER_SEQUENCE_MAP.get(fallback_key, "INSTANTLY_SEQ_GENERAL")
        logger.debug(
            "No exact sequence for (%r, %r) — falling back to %s",
            cluster, persona_type, env_var,
        )

    campaign_id = os.environ.get(env_var, "").strip()
    if not campaign_id:
        logger.warning("Sequence env var %s is not set — contact will be skipped", env_var)
        return None

    return campaign_id


def get_campaign_id_for_company(company: dict, persona_type: str | None) -> str | None:
    """Convenience wrapper that reads cluster/tranche/mode directly from a company record.

    Args:
        company: Company dict from DB.
        persona_type: Resolved persona type for the contact.

    Returns:
        Instantly campaign ID or None.
    """
    skip, reason = should_skip_outreach(company)
    if skip:
        logger.info("Skipping %s — %s", company.get("name", "?"), reason)
        return None

    cluster = company.get("campaign_cluster") or _get_custom_tag(company, "campaign_cluster") or "other"
    tranche = company.get("tranche") or _get_custom_tag(company, "tranche")
    outreach_mode = company.get("outreach_mode") or _get_custom_tag(company, "outreach_mode", "auto")

    return get_campaign_id(
        campaign_cluster=cluster,
        persona_type=persona_type,
        tranche=tranche,
        outreach_mode=outreach_mode,
    )


# ---------------------------------------------------------------------------
# Legacy helpers — keep for backward compatibility
# ---------------------------------------------------------------------------

def get_vertical_bucket(
    naics_prefix: str | None,
    campaign_name: str | None,
) -> str:
    """Legacy: classify into old 'fb' / 'mfg' vertical bucket.

    Prefer get_campaign_id() with campaign_cluster going forward.
    """
    if naics_prefix:
        clean = naics_prefix.strip()
        if any(clean.startswith(p) for p in _FB_NAICS_PREFIXES):
            return "fb"

    if campaign_name:
        name = campaign_name.lower()
        if any(x in name for x in ("fb", "food", "beverage", "fsma", "dairy")):
            return "fb"

    return "mfg"


def get_campaign_id_legacy(
    naics_prefix: str | None = None,
    tier: str | None = None,
    persona_type: str | None = None,
    campaign_name: str | None = None,
) -> str | None:
    """Legacy NAICS/tier-based campaign ID lookup.

    Resolves cluster from tier or NAICS prefix, then delegates to
    get_campaign_id().  Use for callers that have not been migrated yet.
    """
    cluster: str | None = None

    if tier and tier in _LEGACY_CLUSTER_MAP:
        cluster = _LEGACY_CLUSTER_MAP[tier]
    elif naics_prefix:
        clean = naics_prefix.strip()
        if any(clean.startswith(p) for p in _FB_NAICS_PREFIXES):
            cluster = "fb"
        elif clean.startswith("333"):
            cluster = "machinery"
        elif clean.startswith("336"):
            cluster = "auto"
        elif clean.startswith("331"):
            cluster = "metals"
        elif clean.startswith("325"):
            cluster = "chemicals"
        else:
            cluster = "other"

    if not cluster:
        # Fall back to old vertical heuristic
        vertical = get_vertical_bucket(naics_prefix, campaign_name)
        cluster = "fb" if vertical == "fb" else "machinery"

    return get_campaign_id(campaign_cluster=cluster, persona_type=persona_type)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_custom_tag(company: dict, key: str, default: str | None = None) -> str | None:
    """Safely read a value from the company's custom_tags JSONB field."""
    custom_tags = company.get("custom_tags")
    if not custom_tags:
        return default
    if isinstance(custom_tags, str):
        try:
            custom_tags = json.loads(custom_tags)
        except (json.JSONDecodeError, TypeError):
            return default
    if isinstance(custom_tags, dict):
        return custom_tags.get(key, default)
    return default
