"""WorkspaceMiddleware — enriches every request with a WorkspaceContext when auth is present.

This middleware does NOT block unauthenticated requests; that is the job of
the auth dependencies (get_current_user / require_workspace_member).  Its
sole responsibility is:

  1. Parse the Authorization/X-API-Key header (best-effort, no raising).
  2. Look up the corresponding workspace.
  3. Set the WorkspaceContext ContextVar so downstream code can call
     get_current_workspace() without needing the dependency injected.
  4. Clear the context after the response is sent.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Callable

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.app.core.config import get_settings
from backend.app.core.database import get_supabase_client
from backend.app.core.workspace import (
    WorkspaceContext,
    clear_workspace_context,
    set_workspace_context,
)

logger = logging.getLogger(__name__)


class WorkspaceMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that populates WorkspaceContext from request credentials."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        workspace_id: str | None = None

        try:
            workspace_id = self._resolve_workspace_id(request)
        except Exception as exc:
            # Non-fatal: just skip context enrichment; auth deps will catch it properly.
            logger.debug("WorkspaceMiddleware: could not resolve workspace — %s", exc)

        if workspace_id:
            ctx = self._load_workspace(workspace_id)
            if ctx:
                set_workspace_context(ctx)
                logger.debug(
                    "WorkspaceMiddleware: workspace=%s path=%s",
                    workspace_id,
                    request.url.path,
                )

        try:
            response = await call_next(request)
        finally:
            # Always clear after the response, even on error paths.
            clear_workspace_context()

        return response

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_workspace_id(self, request: Request) -> str | None:
        """Return workspace_id from JWT or API key header, or None."""
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")

        if auth_header.startswith("Bearer "):
            return self._workspace_from_jwt(auth_header.removeprefix("Bearer ").strip())

        if api_key_header:
            return self._workspace_from_api_key(api_key_header)

        return None

    def _workspace_from_jwt(self, token: str) -> str | None:
        """Decode JWT and extract workspace_id."""
        settings = get_settings()
        if not settings.supabase_jwt_secret:
            return None
        try:
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except jwt.PyJWTError:
            return None

        # Try app_metadata / user_metadata first (stamped by Auth hooks / triggers)
        app_meta = claims.get("app_metadata") or {}
        user_meta = claims.get("user_metadata") or {}
        workspace_id = app_meta.get("workspace_id") or user_meta.get("workspace_id")
        if workspace_id:
            return workspace_id

        # Fall back to workspace_members table
        user_id: str = claims.get("sub", "")
        if user_id:
            return self._lookup_workspace_member(user_id)

        return None

    def _workspace_from_api_key(self, raw_key: str) -> str | None:
        """Hash the raw key and look up workspace_id in workspace_api_keys."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            client = get_supabase_client()
            result = (
                client.table("workspace_api_keys")
                .select("workspace_id")
                .eq("key_hash", key_hash)
                .is_("revoked_at", "null")
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]["workspace_id"]
        except Exception as exc:
            logger.debug("WorkspaceMiddleware: api key lookup failed — %s", exc)
        return None

    def _lookup_workspace_member(self, user_id: str) -> str | None:
        """Look up which workspace a user belongs to via workspace_members."""
        try:
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
        except Exception as exc:
            logger.debug("WorkspaceMiddleware: member lookup failed — %s", exc)
        return None

    def _load_workspace(self, workspace_id: str) -> WorkspaceContext | None:
        """Fetch workspace row and build a WorkspaceContext."""
        try:
            client = get_supabase_client()
            result = (
                client.table("workspaces")
                .select("id, name, owner_email, tier, subscription_status, settings")
                .eq("id", workspace_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            row = result.data[0]
            return WorkspaceContext(
                workspace_id=row["id"],
                name=row.get("name", ""),
                owner_email=row.get("owner_email", ""),
                tier=row.get("tier", "starter"),
                subscription_status=row.get("subscription_status", "active"),
                settings=row.get("settings") or {},
            )
        except Exception as exc:
            logger.debug("WorkspaceMiddleware: workspace load failed — %s", exc)
            return None
