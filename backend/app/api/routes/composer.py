"""Campaign Composer API routes — natural language campaign builder.

Endpoints:
    POST /api/composer/plan        — generate plan from natural language
    POST /api/composer/variants    — generate message templates for a plan
    POST /api/composer/confirm     — confirm plan + create sequence + enroll contacts
    GET  /api/composer/rate-limits — current provider rate limit status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/composer", tags=["composer"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


class PlanRequest(BaseModel):
    request: str  # Natural language campaign description


class VariantsRequest(BaseModel):
    plan: dict    # CampaignPlan returned by /plan endpoint


class ConfirmRequest(BaseModel):
    plan: dict
    variants: list[dict]
    sequence_name: str


@router.post("/plan")
async def compose_plan(payload: PlanRequest):
    """Generate a structured campaign plan from a natural language request.

    Returns a plan for user review — nothing is executed yet.
    """
    if not payload.request or len(payload.request.strip()) < 10:
        raise HTTPException(400, "Request must be at least 10 characters.")

    db = get_db()
    workspace_id = get_workspace_id()

    from backend.app.core.config import get_settings
    if not get_settings().anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured.")

    try:
        from backend.app.core.campaign_planner import CampaignPlanner
        planner = CampaignPlanner(db, workspace_id)
        plan = planner.compose(payload.request)

        # Enrich estimated reach with live DB count
        filters = plan.get("target_segment", {}).get("filters", {})
        actual_reach = planner.estimate_reach(filters)
        if actual_reach > 0:
            plan["target_segment"]["actual_reach"] = actual_reach

        return {"plan": plan, "status": "draft"}
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.error(f"composer.plan failed: {e}")
        raise HTTPException(500, "Campaign plan generation failed. Try rephrasing your request.")


@router.post("/variants")
async def compose_variants(payload: VariantsRequest):
    """Generate message templates (email + LinkedIn) for each variant in the plan.

    Returns validated templates for user review. Nothing is sent.
    """
    if not payload.plan:
        raise HTTPException(400, "plan is required.")

    db = get_db()
    workspace_id = get_workspace_id()

    try:
        from backend.app.core.template_composer import TemplateComposer
        composer = TemplateComposer(db, workspace_id)
        variants = composer.generate(payload.plan)

        validation_issues = [
            f"Variant {v['variant']}: {', '.join(v.get('validation_warnings', []))}"
            for v in variants
            if v.get("validation_warnings")
        ]

        return {
            "variants": variants,
            "all_valid": all(v.get("valid", False) for v in variants),
            "validation_issues": validation_issues,
        }
    except Exception as e:
        logger.error(f"composer.variants failed: {e}")
        raise HTTPException(500, f"Template generation failed: {str(e)[:200]}")


@router.post("/confirm")
async def confirm_campaign(payload: ConfirmRequest):
    """Confirm a campaign plan — create the sequence and enroll matching contacts.

    This is the execution step. Called after user reviews plan + variants.
    """
    if not payload.plan or not payload.variants:
        raise HTTPException(400, "plan and variants are required.")

    db = get_db()
    workspace_id = get_workspace_id()

    plan = payload.plan
    variants = payload.variants
    sequence_name = payload.sequence_name.strip()

    if not sequence_name:
        raise HTTPException(400, "sequence_name is required.")

    # Check all variants are valid before creating anything
    invalid = [v for v in variants if not v.get("valid", False)]
    if invalid:
        raise HTTPException(
            422,
            f"Variants {[v['variant'] for v in invalid]} have validation errors. "
            f"Fix templates before confirming."
        )

    # Build sequence steps from plan schedule
    schedule = plan.get("schedule", {})
    step_wait_days = schedule.get("step_wait_days", [0, 4, 7])
    channels = plan.get("channels", ["email"])
    steps = []

    for i, wait_days in enumerate(step_wait_days):
        step: dict = {
            "id": f"step_{i+1}",
            "wait_days": wait_days,
        }
        if "email" in channels and variants:
            email = variants[0].get("email", {})
            step["type"] = "email"
            step["subject"] = email.get("subject_a", f"Step {i+1}")
            step["template"] = email.get(f"body_step{i+1}", "")
        elif "linkedin" in channels and variants:
            linkedin = variants[0].get("linkedin", {})
            if i == 0:
                step["type"] = "linkedin_connect"
                step["template"] = linkedin.get("connect_note", "")
            else:
                step["type"] = "linkedin_dm"
                step["template"] = linkedin.get(f"dm_step{i}", "")
        steps.append(step)

    # Create the sequence in DB
    try:
        from datetime import datetime, timezone
        seq_result = db.client.table("sequences").insert({
            "name": sequence_name,
            "description": plan.get("hypothesis", ""),
            "steps": steps,
            "routing_rules": plan.get("target_segment", {}).get("filters", {}),
            "workspace_id": workspace_id,
        }).execute()
        sequence_id = seq_result.data[0]["id"] if seq_result.data else None
    except Exception as e:
        logger.error(f"composer.confirm: sequence insert failed: {e}")
        raise HTTPException(500, "Failed to create sequence.")

    # Find matching contacts based on plan filters
    enrolled_count = 0
    try:
        filters = plan.get("target_segment", {}).get("filters", {})
        contacts_query = (
            db.client.table("contacts")
            .select("id, company_id")
            .eq("workspace_id", workspace_id)
        )
        if filters.get("personas"):
            contacts_query = contacts_query.in_("persona", filters["personas"])
        if filters.get("min_pqs"):
            contacts_query = contacts_query.gte("pqs_persona", filters["min_pqs"])
        contacts_result = contacts_query.limit(500).execute()
        contacts = contacts_result.data or []

        # Enroll contacts in sequence
        now = datetime.now(timezone.utc).isoformat()
        enrollments = [
            {
                "sequence_id": sequence_id,
                "company_id": c["company_id"],
                "contact_id": c["id"],
                "status": "active",
                "current_step_index": 0,
                "enrolled_at": now,
                "workspace_id": workspace_id,
            }
            for c in contacts
        ]
        if enrollments:
            db.client.table("sequence_enrollments").insert(enrollments).execute()
            enrolled_count = len(enrollments)
    except Exception as e:
        logger.error(f"composer.confirm: enrollment failed: {e}")
        # Don't fail the whole request — sequence was created, enrollment is recoverable

    return {
        "status": "created",
        "sequence_id": sequence_id,
        "sequence_name": sequence_name,
        "enrolled_contacts": enrolled_count,
        "hypothesis": plan.get("hypothesis"),
        "variants_created": len(variants),
    }


@router.get("/rate-limits")
async def get_rate_limits():
    """Return current provider rate limit usage for this workspace."""
    db = get_db()
    workspace_id = get_workspace_id()

    try:
        from backend.app.core.linkedin_rate_limiter import LinkedInRateLimiter
        limiter = LinkedInRateLimiter(db, workspace_id)
        return {"limits": limiter.usage()}
    except Exception as e:
        logger.error(f"composer.rate-limits: {e}")
        raise HTTPException(500, "Failed to retrieve rate limits.")
