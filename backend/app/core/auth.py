"""FastAPI authentication dependencies for ProspectIQ.

Two auth paths are supported:
  1. Bearer JWT  — Supabase-issued access token (frontend / dashboard users)
  2. X-API-Key   — SHA-256 hashed key stored in workspace_api_keys table
                   (pipeline scripts, CI jobs, integrations)

Both paths resolve to a user dict and, if the route needs it, a fully
populated WorkspaceContext via require_workspace_member().
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client
from backend.app.core.workspace import WorkspaceContext, set_workspace_context

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_bearer(token: str) -> dict[str, Any]:
    """Decode a Supabase JWT.  Returns the full claims dict."""
    settings = get_settings()
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_JWT_SECRET is not configured",
        )
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_ALGORITHM],
            options={"verify_aud": False},  # Supabase sets aud="authenticated"
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _lookup_api_key(raw_key: str) -> dict[str, Any] | None:
    """Validate a raw API key against workspace_api_keys and return metadata, or None."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    client = get_supabase_client()
    result = (
        client.table("workspace_api_keys")
        .select("workspace_id, name")
        .eq("key_hash", key_hash)
        .is_("revoked_at", "null")  # active = revoked_at IS NULL
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _build_user_from_jwt(claims: dict[str, Any]) -> dict[str, Any]:
    """Extract a normalised user dict from decoded JWT claims."""
    user_meta = claims.get("user_metadata") or {}
    app_meta = claims.get("app_metadata") or {}
    return {
        "user_id": claims.get("sub", ""),
        "email": claims.get("email", ""),
        # workspace_id may be stamped by a DB trigger or Auth hook into app_metadata
        "workspace_id": app_meta.get("workspace_id") or user_meta.get("workspace_id"),
        "auth_method": "bearer",
    }


def _lookup_workspace_for_user(user_id: str) -> str | None:
    """Look up workspace_id from workspace_members table."""
    client = get_supabase_client()
    result = (
        client.table("workspace_members")
        .select("workspace_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["workspace_id"]
    return None


def _fetch_workspace(workspace_id: str) -> dict[str, Any] | None:
    """Fetch workspace row by ID."""
    client = get_supabase_client()
    result = (
        client.table("workspaces")
        .select("id, name, owner_email, tier, subscription_status, settings")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> dict[str, Any]:
    """Resolve the calling identity from Authorization or X-API-Key header.

    Returns a dict with at minimum: user_id, email, workspace_id, auth_method.
    Raises HTTP 401 if credentials are absent or invalid.
    """
    auth_header: str | None = request.headers.get("Authorization")
    api_key_header: str | None = request.headers.get("X-API-Key")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        claims = _decode_bearer(token)
        user = _build_user_from_jwt(claims)
        logger.debug(f"get_current_user: JWT user={user}")

        # If workspace_id wasn't in the JWT claims, look it up from the DB
        if not user["workspace_id"]:
            logger.debug(f"get_current_user: workspace_id not in JWT, looking up for user_id={user['user_id']}")
            user["workspace_id"] = _lookup_workspace_for_user(user["user_id"])
            logger.debug(f"get_current_user: workspace_members lookup result={user['workspace_id']}")

        logger.debug(f"get_current_user: returning user={user}")
        return user

    if api_key_header:
        key_row = _lookup_api_key(api_key_header)
        if not key_row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive API key",
            )
        return {
            "user_id": f"apikey:{key_row['name']}",
            "email": "",
            "workspace_id": key_row["workspace_id"],
            "auth_method": "api_key",
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Same as get_current_user but returns None when auth is absent.

    Use on routes that serve both authenticated and anonymous callers.
    """
    auth_header = request.headers.get("Authorization")
    api_key_header = request.headers.get("X-API-Key")
    if not auth_header and not api_key_header:
        return None
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def require_workspace_member(
    user: dict[str, Any] = Depends(get_current_user),
) -> WorkspaceContext:
    """Verify the user belongs to a workspace, populate WorkspaceContext, and return it.

    Raises HTTP 403 if the workspace cannot be resolved.
    """
    workspace_id: str | None = user.get("workspace_id")
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any workspace",
        )

    row = _fetch_workspace(workspace_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Workspace {workspace_id} not found",
        )

    ctx = WorkspaceContext(
        workspace_id=row["id"],
        name=row.get("name", ""),
        owner_email=row.get("owner_email", ""),
        tier=row.get("tier", "starter"),
        subscription_status=row.get("subscription_status", "active"),
        settings=row.get("settings") or {},
        user_id=user.get("user_id"),
        user_email=user.get("email") or None,
    )
    set_workspace_context(ctx)
    return ctx


def require_role(min_role: str):
    """Dependency factory: enforce a minimum workspace role on a route.

    Role hierarchy (ascending): viewer → member → admin → owner

    Usage:
        @router.post("/something")
        async def my_route(
            ctx: WorkspaceContext = Depends(require_role("member")),
        ):
            ...

    Raises HTTP 403 if the authenticated user's role is below min_role.
    API key callers are treated as having "member" role by default.
    """
    _ROLE_RANK: dict[str, int] = {
        "viewer": 10,
        "member": 20,
        "admin": 30,
        "owner": 40,
    }
    required_rank = _ROLE_RANK.get(min_role, 20)

    async def _check(
        user: dict[str, Any] = Depends(get_current_user),
        ctx: WorkspaceContext = Depends(require_workspace_member),
    ) -> WorkspaceContext:
        # API key callers get member-level access
        if user.get("auth_method") == "api_key":
            if required_rank > _ROLE_RANK["member"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"API key access requires at least '{min_role}' role.",
                )
            return ctx

        # Look up the user's role in this workspace
        workspace_id = ctx.workspace_id
        user_id = user.get("user_id", "")
        client = get_supabase_client()
        try:
            result = (
                client.table("workspace_members")
                .select("role")
                .eq("workspace_id", workspace_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.warning("require_role: DB lookup failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not verify workspace role.",
            )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this workspace.",
            )

        role = result.data[0].get("role", "viewer")
        actual_rank = _ROLE_RANK.get(role, 10)
        if actual_rank < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires '{min_role}' role. Your role is '{role}'.",
            )

        return ctx

    return _check


# Convenience alias for routes that just need the DB dependency satisfied
# (kept separate from require_workspace_member so call sites are explicit)
def get_db():
    """Return a Database instance with workspace_id from context."""
    from backend.app.core.database import Database
    from backend.app.core.workspace import get_workspace_id
    ws_id = get_workspace_id()
    logger.debug(f"get_db() called: workspace_id from context={ws_id}")
    return Database(workspace_id=ws_id)
