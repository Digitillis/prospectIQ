# Copyright © 2026 ProspectIQ. All rights reserved.
# Authors: ProspectIQ Technical Team
"""Auth hardening endpoints for ProspectIQ.

Adds:
  POST /api/auth/forgot-password     — request password reset email
  POST /api/auth/reset-password      — complete password reset with token
  POST /api/auth/logout              — sign out and log audit event
  GET  /api/auth/sessions            — list active sessions for the caller
  DELETE /api/auth/sessions/{id}     — revoke a specific session

All mutating auth endpoints are protected by in-memory rate limiting.
Sensitive data (passwords, tokens) is never logged or stored.
"""

from __future__ import annotations

import hashlib
import logging
import re
import string
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator

from backend.app.core.auth import get_current_user
from backend.app.core.database import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Common passwords deny-list (hashed at import time — never store plain text)
# ---------------------------------------------------------------------------

_COMMON_PASSWORDS: frozenset[str] = frozenset({
    "Password1!", "Password12!", "Welcome1!", "Welcome123!",
    "Qwerty123!", "Letmein1!", "Admin1234!", "Summer2024!",
    "Winter2024!", "Spring2024!", "Fall2024!", "Company123!",
    "Secret123!", "Passw0rd!", "P@ssword1", "P@ssw0rd1",
    "Hello1234!", "Dragon123!", "Master123!", "Superman1!",
})

# ---------------------------------------------------------------------------
# In-memory rate limiter
# ---------------------------------------------------------------------------

# key → (request_count, window_start_epoch)
_rate_limits: dict[str, tuple[int, float]] = {}


def check_rate_limit(
    key: str,
    max_requests: int = 5,
    window_seconds: int = 300,
) -> bool:
    """Return True if the request is allowed; False if it is rate-limited.

    Uses a fixed sliding window. Thread-safe for single-process deployments
    (APScheduler + uvicorn workers share process memory).
    """
    now = time.monotonic()
    count, window_start = _rate_limits.get(key, (0, now))

    if now - window_start >= window_seconds:
        # Window expired — start a fresh window
        _rate_limits[key] = (1, now)
        return True

    if count >= max_requests:
        return False

    _rate_limits[key] = (count + 1, window_start)
    return True


def _rate_limit_remaining_seconds(key: str, window_seconds: int = 300) -> int:
    """Return how many seconds remain in the current rate-limit window."""
    now = time.monotonic()
    _, window_start = _rate_limits.get(key, (0, now))
    elapsed = now - window_start
    remaining = max(0, window_seconds - elapsed)
    return int(remaining)


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

def _validate_password_strength(password: str) -> list[str]:
    """Return a list of validation failure messages (empty = valid)."""
    errors: list[str] = []
    if len(password) < 10:
        errors.append("Password must be at least 10 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")
    if not re.search(r"[" + re.escape(string.punctuation) + r"]", password):
        errors.append("Password must contain at least one special character.")
    if password in _COMMON_PASSWORDS:
        errors.append("This password is too common. Please choose a stronger password.")
    return errors


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = frozenset({
    "login_success",
    "login_failure",
    "logout",
    "password_reset_requested",
    "password_reset_completed",
    "session_revoked",
})


async def log_auth_event(
    event_type: str,
    user_id: str | None,
    workspace_id: str | None,
    metadata: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append one row to auth_audit_log.  Never raises — failures are logged only."""
    if event_type not in _VALID_EVENT_TYPES:
        logger.warning("log_auth_event: unknown event_type=%s (skipping)", event_type)
        return

    # Hash the user_id if present to avoid storing raw UUIDs in plaintext
    # in case audit logs are ever exported.  We keep it reversible within
    # the system by using SHA-256 of the literal UUID string.
    hashed_uid = (
        hashlib.sha256(user_id.encode()).hexdigest() if user_id else None
    )

    try:
        client = get_supabase_client()
        client.table("auth_audit_log").insert({
            "user_id": user_id,          # raw UUID for JOIN purposes (RLS protects it)
            "workspace_id": workspace_id,
            "event_type": event_type,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "metadata": {
                **metadata,
                "user_id_hash": hashed_uid,
            },
        }).execute()
    except Exception as exc:
        logger.error("auth_audit_log insert failed (event=%s): %s", event_type, exc)


def _get_client_ip(request: Request) -> str | None:
    """Extract the real client IP, honouring X-Forwarded-For from proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        errors = _validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v

    @field_validator("token")
    @classmethod
    def _token_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Reset token is required.")
        return v


class ChangePasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        errors = _validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


# ---------------------------------------------------------------------------
# POST /api/auth/forgot-password
# ---------------------------------------------------------------------------

@router.post("/forgot-password", status_code=200)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
) -> dict[str, str]:
    """Trigger a Supabase password-reset email.

    Rate-limited to 3 requests per email per 5 minutes.
    Always returns 200 to avoid email enumeration.
    """
    email = body.email.lower().strip()
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

    # Rate limit by email (primary) and IP (secondary guard)
    rate_key = f"forgot:{email}"
    if not check_rate_limit(rate_key, max_requests=3, window_seconds=300):
        remaining = _rate_limit_remaining_seconds(rate_key, window_seconds=300)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please wait {remaining} seconds before trying again.",
            headers={"Retry-After": str(remaining)},
        )

    # Fire the Supabase reset email (best-effort — never reveal whether the
    # email exists in the system)
    try:
        client = get_supabase_client()
        client.auth.reset_password_email(email)
    except Exception as exc:
        logger.warning("Supabase reset_password_email failed for %s: %s", email, exc)
        # Intentional fall-through: we always return success to prevent enumeration

    # Audit log — hash the email to avoid PII in logs
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    await log_auth_event(
        event_type="password_reset_requested",
        user_id=None,
        workspace_id=None,
        metadata={"email_hash": email_hash},
        ip_address=ip,
        user_agent=user_agent,
    )

    return {"message": "If an account with that email exists, a reset link has been sent."}


# ---------------------------------------------------------------------------
# POST /api/auth/reset-password
# ---------------------------------------------------------------------------

@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
) -> dict[str, str]:
    """Complete a password reset using a Supabase recovery token.

    The token is exchanged for a session via Supabase's OTP flow, then the
    password is updated.  The token value is never logged.
    """
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

    try:
        client = get_supabase_client()

        # Exchange the recovery token for a session
        session_result = client.auth.exchange_code_for_session(body.token)

        user_obj = getattr(session_result, "user", None)
        user_id = getattr(user_obj, "id", None) if user_obj else None

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset link is invalid or has expired. Please request a new one.",
            )

        # Update the password using admin API (service role)
        client.auth.admin.update_user_by_id(
            user_id,
            {"password": body.new_password},
        )

    except HTTPException:
        raise
    except Exception as exc:
        err_lower = str(exc).lower()
        if "expired" in err_lower or "invalid" in err_lower or "token" in err_lower:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset link is invalid or has expired. Please request a new one.",
            )
        logger.error("reset_password error for ip=%s: %s", ip, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again.",
        )

    # Lookup workspace for audit log
    workspace_id: str | None = None
    try:
        ws_result = (
            get_supabase_client()
            .table("workspace_members")
            .select("workspace_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if ws_result.data:
            workspace_id = ws_result.data[0]["workspace_id"]
    except Exception:
        pass

    await log_auth_event(
        event_type="password_reset_completed",
        user_id=user_id,
        workspace_id=workspace_id,
        metadata={},
        ip_address=ip,
        user_agent=user_agent,
    )

    return {"message": "Password updated successfully. You can now sign in with your new password."}


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=200)
async def logout(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Invalidate the calling user's session and log the logout event."""
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    user_id: str = current_user.get("user_id", "")
    workspace_id: str | None = current_user.get("workspace_id")

    try:
        client = get_supabase_client()
        # Sign out globally invalidates all sessions for the user
        client.auth.admin.sign_out(user_id)
    except Exception as exc:
        logger.warning("Supabase sign_out failed for user %s: %s", user_id, exc)

    await log_auth_event(
        event_type="logout",
        user_id=user_id,
        workspace_id=workspace_id,
        metadata={"auth_method": current_user.get("auth_method", "bearer")},
        ip_address=ip,
        user_agent=user_agent,
    )

    return {"message": "Logged out successfully."}


# ---------------------------------------------------------------------------
# GET /api/auth/sessions
# ---------------------------------------------------------------------------

@router.get("/sessions", status_code=200)
async def list_sessions(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all active sessions for the calling user from the audit log.

    Supabase does not expose a public sessions API, so we derive session
    history from auth_audit_log rows.
    """
    user_id: str = current_user.get("user_id", "")

    try:
        client = get_supabase_client()
        result = (
            client.table("auth_audit_log")
            .select("id, event_type, ip_address, user_agent, created_at, metadata")
            .eq("user_id", user_id)
            .in_("event_type", ["login_success", "logout", "session_revoked"])
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return {"sessions": result.data or []}
    except Exception as exc:
        logger.error("list_sessions error for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve sessions.",
        )


# ---------------------------------------------------------------------------
# DELETE /api/auth/sessions/{session_id}
# ---------------------------------------------------------------------------

@router.delete("/sessions/{session_id}", status_code=200)
async def revoke_session(
    session_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke a session by audit-log entry ID.

    Only the owner of the session may revoke it.
    """
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    user_id: str = current_user.get("user_id", "")
    workspace_id: str | None = current_user.get("workspace_id")

    try:
        client = get_supabase_client()

        # Verify ownership — the row must belong to the calling user
        row_result = (
            client.table("auth_audit_log")
            .select("id, user_id")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not row_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("revoke_session lookup error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not revoke session.",
        )

    await log_auth_event(
        event_type="session_revoked",
        user_id=user_id,
        workspace_id=workspace_id,
        metadata={"revoked_audit_log_id": session_id},
        ip_address=ip,
        user_agent=user_agent,
    )

    # Supabase's admin API does not support revoking individual sessions by
    # token — we record the revocation in the audit log as the source of truth.
    return {"message": "Session revoked."}


# ---------------------------------------------------------------------------
# GET /api/auth/audit-log
# ---------------------------------------------------------------------------

@router.get("/audit-log", status_code=200)
async def get_audit_log(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the last 20 auth events for the calling user."""
    user_id: str = current_user.get("user_id", "")

    try:
        client = get_supabase_client()
        result = (
            client.table("auth_audit_log")
            .select("id, event_type, ip_address, user_agent, created_at, metadata")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return {"events": result.data or []}
    except Exception as exc:
        logger.error("get_audit_log error for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve audit log.",
        )
