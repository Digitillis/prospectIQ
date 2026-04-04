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
        logger.debug("WorkspaceMiddleware.dispatch: path=%s method=%s", request.url.path, request.method)

        try:
            workspace_id = self._resolve_workspace_id(request)
            logger.debug("WorkspaceMiddleware: resolved workspace_id=%s", workspace_id)
        except Exception as exc:
            # Non-fatal: just skip context enrichment; auth deps will catch it properly.
            logger.debug("WorkspaceMiddleware: could not resolve workspace — %s", exc)

        if workspace_id:
            ctx = self._load_workspace(workspace_id)
            logger.debug("WorkspaceMiddleware: loaded context: %s", ctx)
            if ctx:
                set_workspace_context(ctx)
                logger.debug(
                    "WorkspaceMiddleware: context set with workspace=%s path=%s",
                    workspace_id,
                    request.url.path,
                )
            else:
                logger.warning("WorkspaceMiddleware: failed to load workspace %s", workspace_id)
        else:
            logger.debug("WorkspaceMiddleware: no workspace_id resolved, skipping context enrichment")

        try:
            response = await call_next(request)
        finally:
            # Always clear after the response, even on error paths.
            logger.debug("WorkspaceMiddleware: clearing context after response")
            clear_workspace_context()

        return response

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_workspace_id(self, request: Request) -> str | None:
        """Return workspace_id from JWT or API key header, or None."""
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")

        logger.debug("_resolve_workspace_id: auth_header present=%s api_key_header present=%s", bool(auth_header), bool(api_key_header))

        if auth_header.startswith("Bearer "):
            logger.debug("_resolve_workspace_id: extracting workspace from JWT")
            return self._workspace_from_jwt(auth_header.removeprefix("Bearer ").strip())

        if api_key_header:
            logger.debug("_resolve_workspace_id: extracting workspace from API key")
            return self._workspace_from_api_key(api_key_header)

        logger.debug("_resolve_workspace_id: no auth headers found")
        return None

    def _workspace_from_jwt(self, token: str) -> str | None:
        """Decode JWT and extract workspace_id."""
        settings = get_settings()
        if not settings.supabase_jwt_secret:
            logger.debug("JWT secret not configured, falling back to workspace_members table lookup")
            # Extract user_id from token without verification (we need the secret to verify anyway)
            try:
                import jwt
                unverified = jwt.decode(token, options={"verify_signature": False})
                user_id = unverified.get("sub", "")
                if user_id:
                    logger.debug(f"Extracted user_id from unverified JWT: {user_id}")
                    return self._lookup_workspace_member(user_id)
            except Exception as exc:
                logger.debug(f"Could not extract user_id from JWT: {exc}")
            return None
        try:
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            logger.debug("JWT decode failed: %s", exc)
            return None

        # Try app_metadata / user_metadata first (stamped by Auth hooks / triggers)
        app_meta = claims.get("app_metadata") or {}
        user_meta = claims.get("user_metadata") or {}
        workspace_id = app_meta.get("workspace_id") or user_meta.get("workspace_id")
        logger.debug(
            "JWT claims decoded: sub=%s app_meta=%s user_meta=%s workspace_id_from_claims=%s",
            claims.get("sub"),
            app_meta,
            user_meta,
            workspace_id,
        )
        if workspace_id:
            logger.debug("Found workspace_id in JWT claims: %s", workspace_id)
            return workspace_id

        # Fall back to workspace_members table
        user_id: str = claims.get("sub", "")
        logger.debug("workspace_id not in JWT, looking up via workspace_members for user_id=%s", user_id)
        if user_id:
            ws_id = self._lookup_workspace_member(user_id)
            logger.debug("workspace_members lookup result: %s", ws_id)
            return ws_id

        logger.debug("No workspace_id found via JWT or workspace_members")
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
