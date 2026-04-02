# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: Avanish Mehrotra & ProspectIQ Technical Team
"""Ghostwriting API routes for ProspectIQ.

Exposes the GhostwritingEngine as a REST API for the dashboard.

Endpoints:
    GET    /api/ghostwriting/voice-profile            — get current voice profile
    POST   /api/ghostwriting/voice-profile/calibrate  — calibrate from writing samples
    POST   /api/ghostwriting/generate                 — generate a post
    POST   /api/ghostwriting/posts/{id}/regenerate    — regenerate with feedback
    GET    /api/ghostwriting/posts                    — list generated posts
    DELETE /api/ghostwriting/posts/{id}               — archive a post
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id
from backend.app.core.ghostwriting_engine import GhostwritingEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ghostwriting", tags=["ghostwriting"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CalibrateRequest(BaseModel):
    samples: list[str] = Field(..., min_length=1, description="1–5 past posts to calibrate voice from")


class GenerateRequest(BaseModel):
    topic: str = Field(..., description="What to write about")
    content_type: str = Field("linkedin_post", description="linkedin_post | short_article | thread")
    target_persona: Optional[str] = Field(None, description="Who this content is aimed at, e.g. 'plant managers'")
    include_cta: bool = Field(True, description="Whether to include a call-to-action")
    voice_profile_id: Optional[str] = Field(None, description="Override which voice profile to use")


class RegenerateRequest(BaseModel):
    feedback: str = Field(..., description="Revision directive, e.g. 'make it shorter'")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/voice-profile")
async def get_voice_profile() -> dict[str, Any]:
    """Return the current workspace's voice profile, or null if not calibrated."""
    ws_id = get_workspace_id()
    engine = GhostwritingEngine()
    try:
        profile = await engine.get_voice_profile(ws_id)
        if profile is None:
            return {"profile": None}
        return {"profile": profile.to_dict()}
    except Exception as e:
        logger.error(f"get_voice_profile failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch voice profile: {str(e)[:200]}")


@router.post("/voice-profile/calibrate")
async def calibrate_voice(request: CalibrateRequest) -> dict[str, Any]:
    """Calibrate the workspace's voice profile from 1–5 writing samples.

    Analyses tone, sentence length, vocabulary level, structural patterns,
    and up to 5 signature phrases using Claude.
    """
    ws_id = get_workspace_id()
    if not request.samples:
        raise HTTPException(status_code=400, detail="At least one writing sample is required.")
    if len(request.samples) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 writing samples allowed.")

    engine = GhostwritingEngine()
    try:
        profile = await engine.calibrate_voice(ws_id, request.samples)
        return {"profile": profile.to_dict(), "message": "Voice profile calibrated successfully."}
    except Exception as e:
        logger.error(f"calibrate_voice failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Calibration failed: {str(e)[:200]}")


@router.post("/generate")
async def generate_post(request: GenerateRequest) -> dict[str, Any]:
    """Generate a post in the workspace's calibrated voice.

    Falls back to a professional, authoritative voice when no profile exists.
    """
    ws_id = get_workspace_id()
    if not request.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    valid_types = {"linkedin_post", "short_article", "thread"}
    if request.content_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"content_type must be one of: {', '.join(sorted(valid_types))}",
        )

    engine = GhostwritingEngine()
    try:
        post = await engine.generate_post(
            workspace_id=ws_id,
            topic=request.topic,
            content_type=request.content_type,
            voice_profile_id=request.voice_profile_id,
            target_persona=request.target_persona,
            include_cta=request.include_cta,
        )
        return {"post": post.to_dict()}
    except Exception as e:
        logger.error(f"generate_post failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)[:200]}")


@router.post("/posts/{post_id}/regenerate")
async def regenerate_post(post_id: str, request: RegenerateRequest) -> dict[str, Any]:
    """Regenerate a post with user feedback applied.

    Example feedback: "make it shorter", "more technical", "add a personal story".
    """
    ws_id = get_workspace_id()
    if not request.feedback.strip():
        raise HTTPException(status_code=400, detail="Feedback cannot be empty.")

    engine = GhostwritingEngine()
    try:
        post = await engine.regenerate(post_id=post_id, workspace_id=ws_id, feedback=request.feedback)
        return {"post": post.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"regenerate_post failed for {post_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {str(e)[:200]}")


@router.get("/posts")
async def list_posts(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """List generated posts for the workspace, newest first."""
    ws_id = get_workspace_id()
    engine = GhostwritingEngine()
    try:
        posts = await engine.list_posts(workspace_id=ws_id, limit=limit)
        return {"posts": [p.to_dict() for p in posts], "count": len(posts)}
    except Exception as e:
        logger.error(f"list_posts failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list posts: {str(e)[:200]}")


@router.delete("/posts/{post_id}")
async def archive_post(post_id: str) -> dict[str, Any]:
    """Archive a post (sets status = 'archived', does not hard-delete)."""
    ws_id = get_workspace_id()
    db = Database(workspace_id=ws_id)
    try:
        result = (
            db.client.table("ghostwritten_posts")
            .update({"status": "archived"})
            .eq("id", post_id)
            .eq("workspace_id", ws_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found.")
        return {"message": "Post archived.", "post_id": post_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"archive_post failed for {post_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Archive failed: {str(e)[:200]}")
