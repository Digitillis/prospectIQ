"""Invite acceptance endpoints.

GET  /api/auth/invite/validate?token=...  — public; returns workspace/inviter info
POST /api/auth/invite/accept              — requires auth; links the calling user to the invite
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.app.core.auth import get_current_user
from backend.app.core.database import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth/invite", tags=["invite"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AcceptInviteRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/validate")
async def validate_invite(token: str = Query(...)) -> dict[str, Any]:
    """Public endpoint — no auth required.

    Returns workspace name, inviter email, role, and invitee email so the
    frontend can render the invite card before the user signs in.

    Status codes:
      200  — valid pending invite
      404  — token not found
      410  — token already used (member is active)
      409  — invitee is already an active member
    """
    client = get_supabase_client()

    result = (
        client.table("workspace_members")
        .select("id, email, role, status, workspace_id, invited_by")
        .eq("invite_token", token)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or expired.")

    row = result.data[0]

    if row.get("status") == "active":
        # Token has already been used (member accepted previously)
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invite link has already been used.")

    # Fetch workspace name
    ws = (
        client.table("workspaces")
        .select("name, owner_email")
        .eq("id", row["workspace_id"])
        .limit(1)
        .execute()
    )
    ws_row = ws.data[0] if ws.data else {}

    # Best-effort: resolve inviter email
    inviter_email = ws_row.get("owner_email", "your team")
    if row.get("invited_by"):
        try:
            inviter_res = (
                client.table("workspace_members")
                .select("email")
                .eq("workspace_id", row["workspace_id"])
                .eq("user_id", row["invited_by"])
                .limit(1)
                .execute()
            )
            if inviter_res.data:
                inviter_email = inviter_res.data[0].get("email", inviter_email)
        except Exception:
            pass  # fall back to owner_email

    return {
        "workspace_name": ws_row.get("name", "ProspectIQ Workspace"),
        "inviter_email": inviter_email,
        "role": row.get("role", "member"),
        "invitee_email": row.get("email", ""),
    }


@router.post("/accept", status_code=200)
async def accept_invite(
    body: AcceptInviteRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Accept an invitation.

    Requires the caller to be authenticated (Supabase JWT).
    Links the calling user's user_id to the pending workspace_members row,
    sets status='active', and nulls out the invite_token.

    Status codes:
      200  — accepted successfully; returns the member row
      404  — token not found
      409  — already an active member of this workspace
      410  — token already consumed
    """
    client = get_supabase_client()

    # Find the pending invite
    result = (
        client.table("workspace_members")
        .select("id, email, role, status, workspace_id, invite_token")
        .eq("invite_token", body.token)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or expired.")

    row = result.data[0]

    if row.get("status") == "active":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invite link has already been used.")

    user_id = user.get("user_id")
    user_email = user.get("email", "")

    # Guard: check this user isn't already an active member of this workspace
    existing = (
        client.table("workspace_members")
        .select("id, status")
        .eq("workspace_id", row["workspace_id"])
        .eq("user_id", user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already an active member of this workspace.",
        )

    # Activate the membership
    updated = (
        client.table("workspace_members")
        .update({
            "user_id": user_id,
            "email": user_email or row.get("email"),
            "status": "active",
            "invite_token": None,  # consume the token
        })
        .eq("id", row["id"])
        .execute()
    )

    member_row = updated.data[0] if updated.data else {}
    # Don't expose token in response (already nulled, but be safe)
    member_row.pop("invite_token", None)

    logger.info(
        "Invite accepted: workspace=%s user=%s email=%s role=%s",
        row["workspace_id"], user_id, user_email, row.get("role"),
    )

    return {
        "status": "accepted",
        "workspace_id": row["workspace_id"],
        "role": row.get("role"),
        "member": member_row,
    }
