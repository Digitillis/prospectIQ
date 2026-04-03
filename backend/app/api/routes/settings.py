"""Settings routes — expose YAML configuration to the dashboard."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.audit import log_audit_event_from_ctx
from backend.app.core.auth import require_role

from backend.app.core.config import (
    CONFIG_DIR,
    get_icp_config,
    get_scoring_config,
    get_sequences_config,
    get_outreach_guidelines,
    get_content_guidelines,
    get_linkedin_messages_guidelines,
    get_offer_context,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_settings_response() -> dict:
    icp = get_icp_config()
    scoring = get_scoring_config()
    sequences_cfg = get_sequences_config()
    return {
        "icp": {
            "target_market": icp.get("target_market", {}),
            "revenue": icp.get("company_filters", {}).get("revenue", {}),
            "employee_count": icp.get("company_filters", {}).get("employee_count", {}),
            "geography": icp.get("company_filters", {}).get("geography", {}),
            "industries": icp.get("company_filters", {}).get("industries", []),
            "contact_titles_include": (
                icp.get("contact_filters", {}).get("titles", {}).get("include", [])
            ),
            "seniority": icp.get("contact_filters", {}).get("seniority", []),
            "discovery": icp.get("discovery", {}),
        },
        "scoring": {
            "dimensions": {
                name: {
                    "max_points": dim.get("max_points"),
                    "signals": {
                        sig_name: {
                            "points": sig.get("points"),
                            "description": sig.get("description", ""),
                            "evaluation": sig.get("evaluation", ""),
                        }
                        for sig_name, sig in dim.get("signals", {}).items()
                    },
                }
                for name, dim in scoring.get("dimensions", {}).items()
            },
            "thresholds": scoring.get("thresholds", {}),
            "min_firmographic_for_research": scoring.get(
                "min_firmographic_for_research", 10
            ),
        },
        "sequences": sequences_cfg.get("sequences", {}),
    }


# ---------------------------------------------------------------------------
# Pydantic models for PATCH request
# ---------------------------------------------------------------------------

class ICPRevenuePatch(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None


class ICPEmployeeCountPatch(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None


class ICPGeographyPatch(BaseModel):
    primary_states: Optional[list[str]] = None
    countries: Optional[list[str]] = None


class ICPIndustryItem(BaseModel):
    tier: str
    label: str
    apollo_industry: str


class ICPDiscoveryPatch(BaseModel):
    max_results_per_run: Optional[int] = None
    pages_per_tier: Optional[int] = None


class ICPPatch(BaseModel):
    revenue: Optional[ICPRevenuePatch] = None
    employee_count: Optional[ICPEmployeeCountPatch] = None
    geography: Optional[ICPGeographyPatch] = None
    industries: Optional[list[ICPIndustryItem]] = None
    contact_titles_include: Optional[list[str]] = None
    discovery: Optional[ICPDiscoveryPatch] = None


class ScoringSignalPatch(BaseModel):
    points: Optional[int] = None


class ScoringDimensionPatch(BaseModel):
    signals: Optional[Dict[str, ScoringSignalPatch]] = None


class ScoringThresholdPatch(BaseModel):
    max_score: Optional[int] = None


class ScoringPatch(BaseModel):
    min_firmographic_for_research: Optional[int] = None
    dimensions: Optional[Dict[str, ScoringDimensionPatch]] = None
    thresholds: Optional[Dict[str, ScoringThresholdPatch]] = None


class SettingsPatch(BaseModel):
    icp: Optional[ICPPatch] = None
    scoring: Optional[ScoringPatch] = None


# ---------------------------------------------------------------------------
# Outreach Guidelines CRUD
# ---------------------------------------------------------------------------

@router.get("/outreach-guidelines")
async def get_guidelines():
    """Get the current outreach guidelines (tone, structure, rules, signature)."""
    try:
        data = get_outreach_guidelines()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="outreach_guidelines.yaml not found")
    return {"data": data}


class GuidelinesPatch(BaseModel):
    voice_and_tone: Optional[str] = None
    email_structure: Optional[str] = None
    must_include: Optional[list[str]] = None
    never_include: Optional[list[str]] = None
    banned_phrases: Optional[list[str]] = None
    banned_characters: Optional[list[str]] = None
    product_facts: Optional[list[str]] = None
    subject_line_rules: Optional[str] = None
    sender_name: Optional[str] = None
    sender_title: Optional[str] = None
    sender_email: Optional[str] = None
    sender_phone: Optional[str] = None
    sender_signature: Optional[str] = None


@router.patch("/outreach-guidelines")
async def patch_guidelines(payload: GuidelinesPatch, _role=Depends(require_role("admin"))):
    """Update outreach guidelines. Changes take effect on the next outreach run.

    Only provided fields are updated. Others are left unchanged.
    The outreach agent reads this file fresh on every run (no cache).
    """
    import yaml

    guidelines_path = CONFIG_DIR / "outreach_guidelines.yaml"
    try:
        with open(guidelines_path, "r") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="outreach_guidelines.yaml not found")

    # Update top-level text fields
    for field in ["voice_and_tone", "email_structure", "subject_line_rules"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update list fields
    for field in ["must_include", "never_include", "banned_phrases",
                   "banned_characters", "product_facts"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update sender fields
    sender = data.setdefault("sender", {})
    if payload.sender_name is not None:
        sender["name"] = payload.sender_name
        # Auto-update short_name
        sender["short_name"] = payload.sender_name.split()[0]
    if payload.sender_title is not None:
        sender["title"] = payload.sender_title
    if payload.sender_email is not None:
        sender["email"] = payload.sender_email
    if payload.sender_phone is not None:
        sender["phone"] = payload.sender_phone
    if payload.sender_signature is not None:
        sender["signature"] = payload.sender_signature

    # Bump version
    ver = data.get("version", "1.0")
    try:
        major, minor = ver.split(".")
        data["version"] = f"{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        data["version"] = "1.1"

    # Write back
    with open(guidelines_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    log_audit_event_from_ctx("settings.updated", resource_type="outreach_guidelines")
    return {"data": data, "message": "Outreach guidelines updated. Changes apply to the next outreach run."}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/test-slack")
async def test_slack():
    """Send a test Slack notification to verify webhook configuration."""
    from backend.app.utils.notifications import notify_slack
    sent = notify_slack(
        "ProspectIQ test notification — your Slack integration is working!",
        emoji=":white_check_mark:",
    )
    if not sent:
        raise HTTPException(
            status_code=400,
            detail="Slack notification failed. Check that SLACK_WEBHOOK_URL is configured.",
        )
    return {"data": {"status": "sent"}}


@router.get("/icp-wizard")
async def get_icp_wizard():
    """Return ICP configuration in a structured wizard-friendly format.

    Designed for the guided ICP setup flow. Groups fields by wizard step:
      Step 1 — Company filters (revenue, employees, geography)
      Step 2 — Industry targeting (tiers, labels)
      Step 3 — Contact targeting (titles, seniority)
      Step 4 — Discovery settings (pages, results per run)
    """
    try:
        icp = get_icp_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    cf = icp.get("company_filters", {})
    ctf = icp.get("contact_filters", {})
    disc = icp.get("discovery", {})

    return {
        "data": {
            "step1_company_filters": {
                "revenue_min": cf.get("revenue", {}).get("min"),
                "revenue_max": cf.get("revenue", {}).get("max"),
                "employee_min": cf.get("employee_count", {}).get("min"),
                "employee_max": cf.get("employee_count", {}).get("max"),
                "primary_states": cf.get("geography", {}).get("primary_states", []),
                "countries": cf.get("geography", {}).get("countries", []),
            },
            "step2_industries": [
                {
                    "tier": ind.get("tier"),
                    "label": ind.get("label"),
                    "apollo_industry": ind.get("apollo_industry"),
                }
                for ind in cf.get("industries", [])
            ],
            "step3_contacts": {
                "titles_include": ctf.get("titles", {}).get("include", []),
                "seniority": ctf.get("seniority", []),
            },
            "step4_discovery": {
                "max_results_per_run": disc.get("max_results_per_run"),
                "pages_per_tier": disc.get("pages_per_tier"),
            },
        }
    }


@router.get("")
async def get_settings():
    """Return current ICP, scoring, and sequences configuration."""
    try:
        data = _build_settings_response()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"data": data}


@router.get("/templates")
async def get_templates():
    """Get all email/outreach templates from sequences config."""
    try:
        sequences_cfg = get_sequences_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    sequences = sequences_cfg.get("sequences", {})
    templates = []
    for seq_name, seq in sequences.items():
        for step in seq.get("steps", []):
            templates.append({
                "id": f"{seq_name}_step_{step['step']}",
                "sequence_name": seq_name,
                "sequence_display_name": seq.get("name", seq_name),
                "sequence_description": seq.get("description", ""),
                "step": step["step"],
                "channel": step.get("channel", "email"),
                "delay_days": step.get("delay_days", 0),
                "template_name": step.get("template", ""),
                "instructions": step.get("instructions", {}),
            })

    return {"data": templates}


@router.patch("")
async def patch_settings(payload: SettingsPatch, _role=Depends(require_role("admin"))):
    """Partially update ICP and/or scoring configuration and persist to YAML."""
    import yaml  # local import to keep top-level clean

    errors: list[str] = []

    # --- ICP updates ---
    if payload.icp is not None:
        icp_path = CONFIG_DIR / "icp.yaml"
        try:
            with open(icp_path, "r") as f:
                icp_raw: Dict[str, Any] = yaml.safe_load(f)
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="icp.yaml not found")

        icp_patch = payload.icp
        cf = icp_raw.setdefault("company_filters", {})

        if icp_patch.revenue is not None:
            rev = cf.setdefault("revenue", {})
            if icp_patch.revenue.min is not None:
                rev["min"] = icp_patch.revenue.min
            if icp_patch.revenue.max is not None:
                rev["max"] = icp_patch.revenue.max

        if icp_patch.employee_count is not None:
            ec = cf.setdefault("employee_count", {})
            if icp_patch.employee_count.min is not None:
                ec["min"] = icp_patch.employee_count.min
            if icp_patch.employee_count.max is not None:
                ec["max"] = icp_patch.employee_count.max

        if icp_patch.geography is not None:
            geo = cf.setdefault("geography", {})
            if icp_patch.geography.primary_states is not None:
                geo["primary_states"] = icp_patch.geography.primary_states
            if icp_patch.geography.countries is not None:
                geo["countries"] = icp_patch.geography.countries

        if icp_patch.industries is not None:
            # Rebuild full industry list preserving NAICS prefixes from original
            original_inds = {ind.get("tier"): ind for ind in cf.get("industries", [])}
            new_inds = []
            for item in icp_patch.industries:
                orig = original_inds.get(item.tier, {})
                entry = dict(orig)  # keep naics_prefix etc.
                entry["tier"] = item.tier
                entry["label"] = item.label
                entry["apollo_industry"] = item.apollo_industry
                new_inds.append(entry)
            cf["industries"] = new_inds

        if icp_patch.contact_titles_include is not None:
            ct = icp_raw.setdefault("contact_filters", {}).setdefault("titles", {})
            ct["include"] = icp_patch.contact_titles_include

        if icp_patch.discovery is not None:
            disc = icp_raw.setdefault("discovery", {})
            if icp_patch.discovery.max_results_per_run is not None:
                disc["max_results_per_run"] = icp_patch.discovery.max_results_per_run
            if icp_patch.discovery.pages_per_tier is not None:
                disc["pages_per_tier"] = icp_patch.discovery.pages_per_tier

        try:
            with open(icp_path, "w") as f:
                yaml.dump(icp_raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            errors.append(f"Failed to write icp.yaml: {exc}")

        # Bust lru_cache so next read picks up changes
        get_icp_config.cache_clear()

    # --- Scoring updates ---
    if payload.scoring is not None:
        scoring_path = CONFIG_DIR / "scoring.yaml"
        try:
            with open(scoring_path, "r") as f:
                scoring_raw: Dict[str, Any] = yaml.safe_load(f)
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="scoring.yaml not found")

        sc_patch = payload.scoring

        if sc_patch.min_firmographic_for_research is not None:
            scoring_raw["min_firmographic_for_research"] = sc_patch.min_firmographic_for_research

        if sc_patch.dimensions is not None:
            for dim_name, dim_patch in sc_patch.dimensions.items():
                if dim_name not in scoring_raw.get("dimensions", {}):
                    continue
                if dim_patch.signals:
                    for sig_name, sig_patch in dim_patch.signals.items():
                        sig = scoring_raw["dimensions"][dim_name].get("signals", {}).get(sig_name)
                        if sig and sig_patch.points is not None:
                            sig["points"] = sig_patch.points

        if sc_patch.thresholds is not None:
            for thr_name, thr_patch in sc_patch.thresholds.items():
                if thr_name not in scoring_raw.get("thresholds", {}):
                    continue
                if thr_patch.max_score is not None:
                    scoring_raw["thresholds"][thr_name]["max_score"] = thr_patch.max_score

        try:
            with open(scoring_path, "w") as f:
                yaml.dump(scoring_raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            errors.append(f"Failed to write scoring.yaml: {exc}")

        get_scoring_config.cache_clear()

    if errors:
        raise HTTPException(status_code=500, detail="; ".join(errors))

    # Return fresh settings after update
    try:
        data = _build_settings_response()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    log_audit_event_from_ctx(
        "settings.updated",
        resource_type="settings",
        metadata={"updated_sections": [k for k in ("icp", "scoring") if getattr(payload, k) is not None]},
    )
    return {"data": data, "message": "Settings saved successfully"}


# ---------------------------------------------------------------------------
# Content Guidelines CRUD
# ---------------------------------------------------------------------------

@router.get("/content-guidelines")
async def get_content_guidelines_route():
    """Get the current LinkedIn thought leadership content guidelines."""
    try:
        data = get_content_guidelines()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="content_guidelines.yaml not found")
    return {"data": data}


class ContentGuidelinesPatch(BaseModel):
    voice_and_tone: Optional[str] = None
    quality_standards: Optional[list[str]] = None
    banned_phrases: Optional[list[str]] = None
    never_include: Optional[list[str]] = None
    must_include: Optional[list[str]] = None
    author_name: Optional[str] = None
    author_title: Optional[str] = None
    author_linkedin_url: Optional[str] = None


@router.patch("/content-guidelines")
async def patch_content_guidelines(payload: ContentGuidelinesPatch, _role=Depends(require_role("admin"))):
    """Update content guidelines. Changes take effect on the next content generation run.

    Only provided fields are updated. Others are left unchanged.
    The content agent reads this file fresh on every run (no cache).
    """
    import yaml

    guidelines_path = CONFIG_DIR / "content_guidelines.yaml"
    try:
        with open(guidelines_path, "r") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="content_guidelines.yaml not found")

    # Update top-level text fields
    for field in ["voice_and_tone"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update list fields
    for field in ["quality_standards", "banned_phrases", "never_include", "must_include"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update author fields
    author = data.setdefault("author", {})
    if payload.author_name is not None:
        author["name"] = payload.author_name
        author["short_name"] = payload.author_name.split()[0]
    if payload.author_title is not None:
        author["title"] = payload.author_title
    if payload.author_linkedin_url is not None:
        author["linkedin_url"] = payload.author_linkedin_url

    # Bump version
    ver = data.get("version", "1.0")
    try:
        major, minor = ver.split(".")
        data["version"] = f"{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        data["version"] = "1.1"

    # Write back
    with open(guidelines_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return {"data": data, "message": "Content guidelines updated. Changes apply to the next content generation run."}


# ---------------------------------------------------------------------------
# LinkedIn Messages Guidelines CRUD
# ---------------------------------------------------------------------------

@router.get("/linkedin-guidelines")
async def get_linkedin_guidelines_route():
    """Get the current LinkedIn DM and connection note guidelines."""
    try:
        data = get_linkedin_messages_guidelines()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="linkedin_messages_guidelines.yaml not found")
    return {"data": data}


class LinkedInGuidelinesPatch(BaseModel):
    connection_note_rules: Optional[str] = None
    opening_dm_rules: Optional[str] = None
    followup_dm_rules: Optional[str] = None
    tone: Optional[str] = None
    fb_question_templates: Optional[list[str]] = None
    mfg_question_templates: Optional[list[str]] = None
    banned_phrases: Optional[list[str]] = None
    never_include: Optional[list[str]] = None
    sender_name: Optional[str] = None
    sender_title: Optional[str] = None
    sender_linkedin_url: Optional[str] = None


@router.patch("/linkedin-guidelines")
async def patch_linkedin_guidelines(payload: LinkedInGuidelinesPatch, _role=Depends(require_role("admin"))):
    """Update LinkedIn messages guidelines. Changes take effect on the next LinkedIn DM run.

    Only provided fields are updated. Others are left unchanged.
    The LinkedIn agent reads this file fresh on every run (no cache).
    """
    import yaml

    guidelines_path = CONFIG_DIR / "linkedin_messages_guidelines.yaml"
    try:
        with open(guidelines_path, "r") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="linkedin_messages_guidelines.yaml not found")

    # Update top-level text fields
    for field in ["connection_note_rules", "opening_dm_rules", "followup_dm_rules", "tone"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update list fields
    for field in ["fb_question_templates", "mfg_question_templates",
                   "banned_phrases", "never_include"]:
        value = getattr(payload, field, None)
        if value is not None:
            data[field] = value

    # Update sender fields
    sender = data.setdefault("sender", {})
    if payload.sender_name is not None:
        sender["name"] = payload.sender_name
        sender["short_name"] = payload.sender_name.split()[0]
    if payload.sender_title is not None:
        sender["title"] = payload.sender_title
    if payload.sender_linkedin_url is not None:
        sender["linkedin_url"] = payload.sender_linkedin_url

    # Bump version
    ver = data.get("version", "1.0")
    try:
        major, minor = ver.split(".")
        data["version"] = f"{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        data["version"] = "1.1"

    # Write back
    with open(guidelines_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return {"data": data, "message": "LinkedIn messages guidelines updated. Changes apply to the next LinkedIn DM run."}


# ---------------------------------------------------------------------------
# Offer Context CRUD
# ---------------------------------------------------------------------------

@router.get("/offer-context")
async def get_offer_context_route():
    """Get the current ProspectIQ offer context (capabilities, proof points, pilot offer)."""
    try:
        data = get_offer_context()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="offer_context.yaml not found")
    return {"data": data}


class OfferContextPatch(BaseModel):
    core_value_prop: Optional[str] = None
    capabilities: Optional[list[str]] = None
    proof_points: Optional[list[str]] = None
    pilot_offer_description: Optional[str] = None
    pilot_offer_timeline: Optional[str] = None


@router.patch("/offer-context")
async def patch_offer_context(payload: OfferContextPatch, _role=Depends(require_role("admin"))):
    """Update the offer context. Changes take effect on the next outreach run.

    Only provided fields are updated. Others are left unchanged.
    """
    import yaml

    ctx_path = CONFIG_DIR / "offer_context.yaml"
    try:
        with open(ctx_path, "r") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="offer_context.yaml not found")

    if payload.core_value_prop is not None:
        data["core_value_prop"] = payload.core_value_prop
    if payload.capabilities is not None:
        data["capabilities"] = payload.capabilities
    if payload.proof_points is not None:
        data["proof_points"] = payload.proof_points

    pilot = data.setdefault("pilot_offer", {})
    if payload.pilot_offer_description is not None:
        pilot["description"] = payload.pilot_offer_description
    if payload.pilot_offer_timeline is not None:
        pilot["pilot_timeline"] = payload.pilot_offer_timeline

    ver = data.get("version", "1.0")
    try:
        major, minor = ver.split(".")
        data["version"] = f"{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        data["version"] = "1.1"

    with open(ctx_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    log_audit_event_from_ctx("settings.updated", resource_type="offer_context")
    return {"data": data, "message": "Offer context updated. Changes apply to the next outreach run."}
