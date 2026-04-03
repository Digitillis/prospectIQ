# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: ProspectIQ Technical Team
"""Voice of Prospect API routes for ProspectIQ.

Exposes the VoiceOfProspectAgent as a REST API for the dashboard.

Endpoints:
    GET  /api/voice-of-prospect/insights   — latest cached insights (or 204 if none)
    POST /api/voice-of-prospect/analyse    — trigger fresh analysis, return insights
    GET  /api/voice-of-prospect/themes     — messaging themes only (resonance + objections)
    GET  /api/voice-of-prospect/sequence   — sequence step metrics only
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from backend.app.core.workspace import get_workspace_id
from backend.app.core.voice_of_prospect import VoiceOfProspectAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice-of-prospect", tags=["voice-of-prospect"])


def _get_agent() -> VoiceOfProspectAgent:
    return VoiceOfProspectAgent()


def _require_workspace() -> str:
    ws_id = get_workspace_id()
    if not ws_id:
        raise HTTPException(status_code=401, detail="Workspace context required.")
    return ws_id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/insights")
async def get_insights(response: Response) -> Any:
    """Return the latest cached VoiceInsights snapshot.

    Returns 204 No Content when no snapshot exists and the client should
    trigger a fresh analysis via POST /analyse.
    """
    ws_id = _require_workspace()
    agent = _get_agent()
    try:
        insights = await agent.get_latest_insights(ws_id)
        if insights is None:
            response.status_code = 204
            return None
        return insights.model_dump(mode="json")
    except Exception as e:
        logger.error(f"GET /voice-of-prospect/insights failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch insights: {str(e)[:200]}")


@router.post("/analyse")
async def trigger_analysis() -> Any:
    """Trigger a fresh full analysis of the workspace's reply corpus.

    Runs Claude Haiku theme extraction + Sonnet recommendation synthesis,
    persists the result, and returns the VoiceInsights payload.

    This is an async operation that typically completes in 5–30 seconds
    depending on corpus size.
    """
    ws_id = _require_workspace()
    agent = _get_agent()
    try:
        insights = await agent.analyse_workspace(ws_id)
        return insights.model_dump(mode="json")
    except Exception as e:
        logger.error(f"POST /voice-of-prospect/analyse failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)[:200]}")


@router.get("/themes")
async def get_themes() -> Any:
    """Return messaging themes — top 5 resonance and top 5 objection themes.

    Uses cached insights when available (< 24 h old), else runs a fresh
    analysis automatically.
    """
    ws_id = _require_workspace()
    agent = _get_agent()
    try:
        themes = await agent.get_messaging_themes(ws_id)
        return {
            "resonance": [t.model_dump() for t in themes["resonance"]],
            "objections": [t.model_dump() for t in themes["objections"]],
        }
    except Exception as e:
        logger.error(f"GET /voice-of-prospect/themes failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch themes: {str(e)[:200]}")


@router.get("/sequence")
async def get_sequence_metrics() -> Any:
    """Return per-step reply rate and drop-off analysis across all campaigns.

    Uses cached insights when available (< 24 h old), else runs a fresh
    analysis automatically.
    """
    ws_id = _require_workspace()
    agent = _get_agent()
    try:
        steps = await agent.get_sequence_dropoff(ws_id)
        return {"steps": [s.model_dump() for s in steps], "count": len(steps)}
    except Exception as e:
        logger.error(f"GET /voice-of-prospect/sequence failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch sequence metrics: {str(e)[:200]}")
