"""Workspace management endpoints.

GET  /api/workspaces/me                      — current workspace info
PATCH /api/workspaces/me                     — update workspace name / settings
GET  /api/workspaces/me/members              — list members
POST /api/workspaces/me/members/invite       — invite a user by email
DELETE /api/workspaces/me/members/{user_id}  — remove member
GET  /api/workspaces/me/usage                — resource usage summary
GET  /api/workspaces/me/audit-log            — recent audit events

POST   /api/workspaces/api-keys              — create a new API key
GET    /api/workspaces/api-keys              — list API keys
DELETE /api/workspaces/api-keys/{key_id}     — revoke
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import secrets
import string
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.app.core.auth import require_workspace_member
from backend.app.core.database import get_supabase_client
from backend.app.core.workspace import WorkspaceContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    settings: dict | None = None


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"  # owner | admin | member | viewer


class AuditLogQuery(BaseModel):
    limit: int = 50
    offset: int = 0
    action: str | None = None   # filter by action prefix, e.g. "member."


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: list[str] = ["read", "write"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_audit(
    client,
    workspace_id: str,
    action: str,
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert a row into workspace_audit_log.  Best-effort — never raises."""
    try:
        client.table("workspace_audit_log").insert({
            "workspace_id": workspace_id,
            "user_id": user_id,
            "user_email": user_email,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata": metadata or {},
            "ip_address": ip_address,
        }).execute()
    except Exception:
        logger.debug("audit log write failed for action=%s", action, exc_info=True)


def _generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns (raw_key, key_hash, key_prefix).
    The raw key is shown once; only hash is stored.
    """
    alphabet = string.ascii_letters + string.digits
    token = "piq_" + "".join(secrets.choice(alphabet) for _ in range(36))
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key_prefix = token[:12]
    return token, key_hash, key_prefix


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/me")
async def get_workspace(ctx: WorkspaceContext = Depends(require_workspace_member)) -> dict[str, Any]:
    """Return the calling user's workspace."""
    client = get_supabase_client()
    result = (
        client.table("workspaces")
        .select("*")
        .eq("id", ctx.workspace_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result.data[0]


@router.patch("/me")
async def update_workspace(
    body: WorkspaceUpdateRequest,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Update workspace name or settings."""
    client = get_supabase_client()
    update_data: dict[str, Any] = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.settings is not None:
        update_data["settings"] = body.settings
    if not update_data:
        raise HTTPException(status_code=400, detail="Nothing to update")

    result = (
        client.table("workspaces")
        .update(update_data)
        .eq("id", ctx.workspace_id)
        .execute()
    )
    return result.data[0] if result.data else {}


@router.get("/me/members")
async def list_members(ctx: WorkspaceContext = Depends(require_workspace_member)) -> list[dict]:
    """List all members of the workspace."""
    client = get_supabase_client()
    result = (
        client.table("workspace_members")
        .select("*")
        .eq("workspace_id", ctx.workspace_id)
        .order("joined_at")
        .execute()
    )
    return result.data


@router.delete("/me/members/{user_id}", status_code=204)
async def remove_member(
    user_id: str,
    request: Request,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> None:
    """Remove a member from the workspace (owners cannot be removed)."""
    client = get_supabase_client()
    result = client.table("workspace_members").select("role, email").eq("workspace_id", ctx.workspace_id).eq("user_id", user_id).limit(1).execute()
    if result.data and result.data[0].get("role") == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove workspace owner")

    removed_email = result.data[0].get("email") if result.data else None
    client.table("workspace_members").delete().eq("workspace_id", ctx.workspace_id).eq("user_id", user_id).execute()

    _write_audit(
        client, ctx.workspace_id, "member.removed",
        user_id=ctx.user_id, user_email=ctx.user_email,
        resource_type="workspace_member", resource_id=user_id,
        metadata={"removed_email": removed_email},
        ip_address=request.client.host if request.client else None,
    )


@router.post("/me/members/invite", status_code=201)
async def invite_member(
    body: InviteMemberRequest,
    request: Request,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Invite a user by email.

    Creates a pending workspace_members row and sends an invite email.
    If the email is already a member (active or pending), returns 409.
    """
    from backend.app.core.notifications import notify_workspace_invite

    client = get_supabase_client()

    # Check seats limit
    ws = client.table("workspaces").select("seats_limit, name, owner_email").eq("id", ctx.workspace_id).limit(1).execute()
    if not ws.data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws_row = ws.data[0]
    seats_limit: int = ws_row.get("seats_limit") or 1

    active_count = (
        client.table("workspace_members")
        .select("id", count="exact")
        .eq("workspace_id", ctx.workspace_id)
        .execute()
    )
    if (active_count.count or 0) >= seats_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Seat limit reached ({seats_limit}). Upgrade to invite more members.",
        )

    # Idempotency check — don't re-invite an existing member
    existing = (
        client.table("workspace_members")
        .select("id, status")
        .eq("workspace_id", ctx.workspace_id)
        .eq("email", body.email)
        .limit(1)
        .execute()
    )
    if existing.data:
        existing_status = existing.data[0].get("status", "active")
        raise HTTPException(
            status_code=409,
            detail=f"User is already a {existing_status} member of this workspace.",
        )

    invite_token = secrets.token_urlsafe(32)
    app_base_url = os.environ.get("APP_BASE_URL", "https://app.prospectiq.ai")
    invite_url = f"{app_base_url}/invite/{invite_token}"

    result = client.table("workspace_members").insert({
        "workspace_id": ctx.workspace_id,
        "user_id": None,           # Unknown until they sign up / log in
        "email": body.email,
        "role": body.role,
        "invited_by": ctx.user_id,
        "status": "pending",
        "invite_token": invite_token,
        "invited_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    row = result.data[0] if result.data else {}

    # Fire invite email — best-effort
    try:
        await notify_workspace_invite(
            invitee_email=body.email,
            workspace_name=ws_row.get("name", "your workspace"),
            inviter_email=ctx.user_email or ws_row.get("owner_email", "your team"),
            invite_url=invite_url,
        )
    except Exception as exc:
        logger.warning("Failed to send invite email to %s: %s", body.email, exc)

    _write_audit(
        client, ctx.workspace_id, "member.invited",
        user_id=ctx.user_id, user_email=ctx.user_email,
        resource_type="workspace_member", resource_id=str(row.get("id", "")),
        metadata={"invitee_email": body.email, "role": body.role},
        ip_address=request.client.host if request.client else None,
    )

    # Never return the token in the API response — it's in the email only
    row.pop("invite_token", None)
    return row


# ---------------------------------------------------------------------------
# Usage summary
# ---------------------------------------------------------------------------

@router.get("/me/usage")
async def get_usage(ctx: WorkspaceContext = Depends(require_workspace_member)) -> dict[str, Any]:
    """Return resource usage counts for the current calendar month.

    Covers: companies (by status), contacts, outreach sent, API cost this month.
    """
    client = get_supabase_client()
    ws_id = ctx.workspace_id

    month_start = datetime.date.today().replace(day=1).isoformat()

    # --- companies ---
    companies_res = (
        client.table("companies")
        .select("status", count="exact")
        .eq("workspace_id", ws_id)
        .execute()
    )
    total_companies = companies_res.count or 0

    # Status breakdown — one call per status to keep Supabase simple
    def _count(table: str, **filters: Any) -> int:
        q = client.table(table).select("id", count="exact").eq("workspace_id", ws_id)
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute().count or 0

    qualified = sum(
        _count("companies", status=s) for s in ("qualified", "outreach_pending", "contacted", "engaged", "meeting_scheduled", "pilot_discussion", "pilot_signed", "active_pilot", "converted")
    )
    hot_prospects = _count("companies", status="qualified")  # companies scored hot_prospect keep status=qualified

    contacts_total = _count("contacts")

    # Outreach this month — interactions of type email_sent since month_start
    outreach_res = (
        client.table("interactions")
        .select("id", count="exact")
        .eq("workspace_id", ws_id)
        .eq("interaction_type", "email_sent")
        .gte("created_at", month_start)
        .execute()
    )
    outreach_this_month = outreach_res.count or 0

    # API cost this month
    cost_res = (
        client.table("api_costs")
        .select("cost_usd")
        .eq("workspace_id", ws_id)
        .gte("created_at", month_start)
        .execute()
    )
    api_cost_this_month = round(
        sum(float(r.get("cost_usd") or 0) for r in (cost_res.data or [])), 4
    )

    # Pending drafts
    drafts_pending = _count("outreach_drafts", approval_status="pending")

    # Active members
    members_active = _count("workspace_members", status="active")
    members_pending = _count("workspace_members", status="pending")

    return {
        "period_start": month_start,
        "companies": {
            "total": total_companies,
            "qualified": qualified,
        },
        "contacts": {
            "total": contacts_total,
        },
        "outreach": {
            "sent_this_month": outreach_this_month,
            "drafts_pending_approval": drafts_pending,
        },
        "api_cost_usd_this_month": api_cost_this_month,
        "members": {
            "active": members_active,
            "pending_invite": members_pending,
        },
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/me/audit-log")
async def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Return recent audit log entries for the workspace.

    Query params:
        limit   — max rows (default 50, max 200)
        offset  — pagination offset
        action  — optional prefix filter, e.g. "member." or "api_key."
    """
    limit = min(limit, 200)
    client = get_supabase_client()

    q = (
        client.table("workspace_audit_log")
        .select("*", count="exact")
        .eq("workspace_id", ctx.workspace_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if action:
        # Supabase doesn't support LIKE via the REST client, so do prefix
        # filtering by using gte/lte on the action string.
        q = q.gte("action", action).lte("action", action + "\uffff")

    result = q.execute()

    return {
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
        "items": result.data or [],
    }


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

@router.get("/api-keys")
async def list_api_keys(ctx: WorkspaceContext = Depends(require_workspace_member)) -> list[dict]:
    """List all active API keys for the workspace (key hash not returned)."""
    client = get_supabase_client()
    result = (
        client.table("workspace_api_keys")
        .select("id, name, key_prefix, scopes, last_used_at, expires_at, created_at, revoked_at")
        .eq("workspace_id", ctx.workspace_id)
        .is_("revoked_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("/api-keys", status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Create a new API key. The raw key is returned ONCE — store it securely."""
    raw_key, key_hash, key_prefix = _generate_api_key()

    client = get_supabase_client()
    result = client.table("workspace_api_keys").insert({
        "workspace_id": ctx.workspace_id,
        "name": body.name,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "scopes": body.scopes,
    }).execute()

    row = result.data[0] if result.data else {}
    key_id = str(row.get("id", ""))

    _write_audit(
        client, ctx.workspace_id, "api_key.created",
        user_id=ctx.user_id, user_email=ctx.user_email,
        resource_type="workspace_api_key", resource_id=key_id,
        metadata={"name": body.name, "scopes": body.scopes, "key_prefix": key_prefix},
        ip_address=request.client.host if request.client else None,
    )

    row["raw_key"] = raw_key  # Only time it's exposed
    return row


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> None:
    """Revoke an API key."""
    client = get_supabase_client()
    client.table("workspace_api_keys").update({
        "revoked_at": datetime.datetime.utcnow().isoformat()
    }).eq("id", key_id).eq("workspace_id", ctx.workspace_id).execute()

    _write_audit(
        client, ctx.workspace_id, "api_key.revoked",
        user_id=ctx.user_id, user_email=ctx.user_email,
        resource_type="workspace_api_key", resource_id=key_id,
        ip_address=request.client.host if request.client else None,
    )
