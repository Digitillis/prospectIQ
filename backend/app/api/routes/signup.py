"""Self-serve workspace signup endpoint.

POST /api/auth/signup

Public endpoint — no auth required.

Flow:
  1. Validate request fields (email, password ≥8 chars, workspace_name).
  2. Create a Supabase auth user via the Admin API (service role key).
  3. Create a workspace row (owner_email, name, tier=starter).
  4. Create a workspace_members row (owner, active).
  5. Send a welcome email via Resend (best-effort).
  6. Return {user_id, workspace_id, workspace_name}.

Idempotency: if the Supabase user already exists, returns 409 so the
caller can redirect to /login instead.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator

from backend.app.core.database import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["signup"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_name: str
    full_name: str = ""

    @field_validator("password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("workspace_name")
    @classmethod
    def _workspace_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Workspace name is required")
        return v


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/signup", status_code=201)
async def signup(body: SignupRequest) -> dict[str, Any]:
    """Create a new workspace and Supabase auth user.

    Returns:
        201  — {user_id, workspace_id, workspace_name}
        409  — email already registered
        422  — validation error (password too short, empty workspace name)
        500  — Supabase admin API error
    """
    client = get_supabase_client()
    email = body.email.lower().strip()
    workspace_name = body.workspace_name.strip()
    workspace_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # 1. Create the Supabase auth user via Admin API
    # ------------------------------------------------------------------
    try:
        user_response = client.auth.admin.create_user({
            "email": email,
            "password": body.password,
            "email_confirm": True,  # Skip confirmation email — user can log in immediately
            "user_metadata": {
                "workspace_id": workspace_id,
                "full_name": body.full_name or "",
            },
        })
    except Exception as exc:
        err_str = str(exc).lower()
        # Supabase raises when the email is already registered
        if "already registered" in err_str or "already been registered" in err_str or "duplicate" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists. Sign in instead.",
            )
        logger.error("Supabase admin create_user failed for %s: %s", email, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account. Please try again.",
        )

    # Extract user_id from response
    user_obj = getattr(user_response, "user", None) or user_response
    if isinstance(user_obj, dict):
        user_id = user_obj.get("id")
    else:
        user_id = getattr(user_obj, "id", None)

    if not user_id:
        logger.error("Supabase user created but no ID returned for %s", email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account created but setup failed. Contact support.",
        )

    # ------------------------------------------------------------------
    # 2. Create the workspace row
    # ------------------------------------------------------------------
    try:
        client.table("workspaces").insert({
            "id": workspace_id,
            "name": workspace_name,
            "owner_email": email,
            "tier": "starter",
            "subscription_status": "active",
            "seats_limit": 1,
            "settings": {
                "onboarding_complete": False,
                "onboarding_step": 0,
                "auto_approve_pqs_threshold": 70,
                "monthly_api_budget_usd": 200,
            },
        }).execute()
    except Exception as exc:
        logger.error("Failed to create workspace for user %s: %s", user_id, exc)
        # Best-effort cleanup: delete the Supabase user so the email isn't stuck
        try:
            client.auth.admin.delete_user(user_id)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set up workspace. Please try again.",
        )

    # ------------------------------------------------------------------
    # 3. Create the owner workspace_members row
    # ------------------------------------------------------------------
    try:
        client.table("workspace_members").insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "email": email,
            "role": "owner",
            "status": "active",
            "invited_by": None,
        }).execute()
    except Exception as exc:
        logger.error("Failed to create workspace_members for user %s: %s", user_id, exc)
        # Non-fatal — workspace exists; user can still log in and be associated later

    # ------------------------------------------------------------------
    # 4. Welcome email (best-effort)
    # ------------------------------------------------------------------
    try:
        from backend.app.core.notifications import notify_welcome
        await notify_welcome(
            user_email=email,
            workspace_name=workspace_name,
            full_name=body.full_name or email.split("@")[0],
        )
    except Exception as exc:
        logger.warning("Welcome email failed for %s: %s", email, exc)

    logger.info("New workspace created: workspace_id=%s owner=%s", workspace_id, email)

    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
    }
