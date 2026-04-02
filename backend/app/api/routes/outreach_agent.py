"""Outreach Agent API routes — Personalized draft generation and intelligence.

Endpoints:
    POST /api/outreach/generate          — Generate one draft
    POST /api/outreach/generate-batch    — Generate drafts for multiple companies
    GET  /api/outreach/intelligence/{contact_id} — Fetch personalization intel
    POST /api/outreach/score-draft/{draft_id}    — Score draft quality
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.agents.outreach_agent import OutreachAgent, _infer_persona
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GenerateDraftRequest(BaseModel):
    company_id: str
    contact_id: str
    sequence_step: str = "touch_1"
    force_regenerate: bool = False


class GenerateBatchRequest(BaseModel):
    company_ids: list[str]
    sequence_step: str = "touch_1"


class GenerateDraftResponse(BaseModel):
    data: dict[str, Any]
    message: str = "Draft generated successfully"


class GenerateBatchResponse(BaseModel):
    created: int
    drafts: list[dict[str, Any]]
    message: str


class IntelligenceResponse(BaseModel):
    contact: dict[str, Any]
    company: dict[str, Any]
    research_summary: dict[str, Any]
    personalization_hooks: list[str]
    pain_signals: list[str]
    trigger_events: list[dict[str, Any]]
    persona_type: str
    recommended_hooks: list[str]


class ScoreResponse(BaseModel):
    draft_id: str
    scores: dict[str, int]
    overall: float
    suggestions: list[str]


# ---------------------------------------------------------------------------
# POST /api/outreach/generate
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateDraftResponse)
async def generate_outreach_draft(body: GenerateDraftRequest):
    """Generate a hyper-personalized outreach draft for a company-contact pair.

    Uses all available research context: personalization hooks, pain signals,
    trigger events, equipment profile, and manufacturing profile to craft a
    draft that references specific company intelligence rather than generic templates.

    Returns the created outreach_drafts record.
    """
    workspace_id = get_workspace_id()
    try:
        agent = OutreachAgent(workspace_id=workspace_id)
        draft = agent.generate_draft(
            company_id=body.company_id,
            contact_id=body.contact_id,
            sequence_step=body.sequence_step,
            workspace_id=workspace_id,
            force_regenerate=body.force_regenerate,
        )
        return GenerateDraftResponse(data=draft)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Draft generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Draft generation failed: {e}")


# ---------------------------------------------------------------------------
# POST /api/outreach/generate-batch
# ---------------------------------------------------------------------------

@router.post("/generate-batch", response_model=GenerateBatchResponse)
async def generate_outreach_batch(body: GenerateBatchRequest):
    """Generate personalized drafts for multiple companies in one request.

    For each company, picks the primary contact (decision maker or highest
    seniority) and generates a draft. Adds a 0.5s delay between calls to
    avoid Claude rate limits.

    Returns count of created drafts and the draft records.
    """
    if not body.company_ids:
        raise HTTPException(status_code=400, detail="company_ids must not be empty")
    if len(body.company_ids) > 50:
        raise HTTPException(
            status_code=400,
            detail="Batch size limited to 50 companies per request",
        )

    workspace_id = get_workspace_id()
    try:
        agent = OutreachAgent(workspace_id=workspace_id)
        drafts = agent.generate_batch(
            company_ids=body.company_ids,
            sequence_step=body.sequence_step,
            workspace_id=workspace_id,
        )
        return GenerateBatchResponse(
            created=len(drafts),
            drafts=drafts,
            message=f"Created {len(drafts)} drafts for {len(body.company_ids)} companies",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Batch generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch generation failed: {e}")


# ---------------------------------------------------------------------------
# GET /api/outreach/intelligence/{contact_id}
# ---------------------------------------------------------------------------

@router.get("/intelligence/{contact_id}", response_model=IntelligenceResponse)
async def get_outreach_intelligence(contact_id: str):
    """Return the full personalization intelligence payload for a contact.

    Surfaces: contact details, company research_summary, personalization_hooks,
    pain_signals, trigger_events, inferred persona_type, and recommended_hooks
    (ranked by specificity and relevance).
    """
    import json as _json

    db = get_db()

    # Load contact
    contact_rows = db.client.table("contacts").select("*").eq("id", contact_id).execute().data
    if not contact_rows:
        raise HTTPException(status_code=404, detail=f"Contact not found: {contact_id}")
    contact = contact_rows[0]

    # Load company
    company = db.get_company(str(contact["company_id"]))
    if not company:
        raise HTTPException(
            status_code=404,
            detail=f"Company not found for contact {contact_id}",
        )

    # Parse research_summary
    research_summary: dict[str, Any] = {}
    raw_research = company.get("research_summary")
    if isinstance(raw_research, dict):
        research_summary = raw_research
    elif isinstance(raw_research, str):
        try:
            research_summary = _json.loads(raw_research)
        except (_json.JSONDecodeError, TypeError):
            research_summary = {}

    # Extract structured fields
    personalization_hooks: list[str] = company.get("personalization_hooks") or []
    pain_signals: list[str] = company.get("pain_signals") or []
    trigger_events: list[dict[str, Any]] = research_summary.get("trigger_events", [])

    # Infer persona
    persona_type = contact.get("persona_type")
    if not persona_type:
        persona_type = _infer_persona(
            contact.get("title"),
            contact.get("seniority"),
        )

    # Recommended hooks: trigger events first (highest signal), then personalization hooks
    recommended_hooks: list[str] = []
    for te in trigger_events[:2]:
        if isinstance(te, dict):
            desc = te.get("description") or te.get("type", "")
            relevance = te.get("outreach_relevance", "")
            if desc:
                hook = desc
                if relevance:
                    hook = f"{desc} — {relevance}"
                recommended_hooks.append(hook)
    for hook in personalization_hooks[:3]:
        if hook not in recommended_hooks:
            recommended_hooks.append(hook)

    return IntelligenceResponse(
        contact={k: v for k, v in contact.items() if k not in ("workspace_id",)},
        company={
            "id": company.get("id"),
            "name": company.get("name"),
            "domain": company.get("domain"),
            "tier": company.get("tier"),
            "pqs_total": company.get("pqs_total"),
            "status": company.get("status"),
            "campaign_cluster": company.get("campaign_cluster"),
            "tranche": company.get("tranche"),
            "research_updated_at": company.get("research_updated_at"),
        },
        research_summary=research_summary,
        personalization_hooks=personalization_hooks,
        pain_signals=pain_signals,
        trigger_events=trigger_events,
        persona_type=persona_type,
        recommended_hooks=recommended_hooks,
    )


# ---------------------------------------------------------------------------
# POST /api/outreach/score-draft/{draft_id}
# ---------------------------------------------------------------------------

@router.post("/score-draft/{draft_id}", response_model=ScoreResponse)
async def score_draft(draft_id: str):
    """Score an outreach draft across four quality dimensions using Claude.

    Dimensions: specificity (1-5), relevance (1-5), tone_match (1-5), cta_clarity (1-5).

    Returns overall score (average) and concrete improvement suggestions.
    """
    workspace_id = get_workspace_id()
    try:
        agent = OutreachAgent(workspace_id=workspace_id)
        result = agent.score_draft_quality(
            draft_id=draft_id,
            workspace_id=workspace_id,
        )
        return ScoreResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Draft scoring failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Draft scoring failed: {e}")
