"""Audit logging utility for ProspectIQ.

Writes structured entries to workspace_audit_log for compliance and
operator visibility. Every significant action in the workspace is recorded.

Covered events:
  auth.login              — successful user login
  auth.logout             — user logout
  pipeline.run            — agent pipeline triggered
  draft.approved          — outreach draft approved (with or without edit)
  draft.rejected          — outreach draft rejected
  draft.edited            — draft body edited (saved without approval)
  contact.exported        — contacts exported to CSV/file
  member.invited          — workspace member invited
  member.removed          — workspace member removed
  api_key.created         — workspace API key created
  api_key.revoked         — workspace API key revoked
  settings.updated        — ICP/scoring/guidelines config changed
  plan.changed            — subscription tier changed
  linkedin.connection_sent — LinkedIn connection request sent
  linkedin.dm_sent         — LinkedIn DM sent

Usage:
    from backend.app.core.audit import log_audit_event

    log_audit_event(
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        user_email=ctx.user_email,
        action="draft.approved",
        resource_type="outreach_draft",
        resource_id=draft_id,
        metadata={"sequence_name": "email_value_first"},
        request=request,  # FastAPI Request for IP address (optional)
    )
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request

logger = logging.getLogger(__name__)


def log_audit_event(
    workspace_id: str,
    action: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """Write a single audit log entry to workspace_audit_log.

    This function is intentionally fire-and-forget — failures are logged
    as warnings but never raise exceptions so they cannot break the
    calling operation.

    Args:
        workspace_id: The workspace the action occurred in.
        action: Dot-notation event name (e.g. "draft.approved").
        user_id: Supabase user_id of the actor (None for system actions).
        user_email: Email of the actor.
        resource_type: Entity type affected (e.g. "outreach_draft").
        resource_id: Primary key of the affected entity (as string).
        metadata: Arbitrary JSON context for the event.
        request: FastAPI Request — used to extract the caller's IP address.
    """
    try:
        from backend.app.core.database import get_supabase_client

        ip_address: Optional[str] = None
        if request is not None:
            # Respect X-Forwarded-For (set by Railway / Vercel proxies)
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            else:
                ip_address = getattr(request.client, "host", None)

        row: dict[str, Any] = {
            "workspace_id": workspace_id,
            "action": action,
        }
        if user_id:
            row["user_id"] = user_id
        if user_email:
            row["user_email"] = user_email
        if resource_type:
            row["resource_type"] = resource_type
        if resource_id:
            row["resource_id"] = str(resource_id)
        if metadata:
            row["metadata"] = metadata
        if ip_address:
            row["ip_address"] = ip_address

        client = get_supabase_client()
        client.table("workspace_audit_log").insert(row).execute()

    except Exception as exc:
        # Audit failures must never crash the calling operation
        logger.warning("audit log write failed (action=%s workspace=%s): %s", action, workspace_id, exc)


def log_audit_event_from_ctx(
    action: str,
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """Convenience wrapper that reads workspace/user from the current WorkspaceContext.

    Use this in route handlers where WorkspaceContext is already set.
    """
    try:
        from backend.app.core.workspace import get_current_workspace
        ctx = get_current_workspace()
        if ctx:
            log_audit_event(
                workspace_id=ctx.workspace_id,
                action=action,
                user_id=ctx.user_id,
                user_email=ctx.user_email,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata=metadata,
                request=request,
            )
    except Exception as exc:
        logger.warning("audit log (from ctx) failed (action=%s): %s", action, exc)
