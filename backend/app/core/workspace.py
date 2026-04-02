"""Workspace context — per-request identity carrier for ProspectIQ.

Mirrors the Digitillis tenant context pattern: a frozen dataclass stored
in a ContextVar so any code in the call stack can read the current
workspace without threading it through every function signature.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    name: str
    owner_email: str
    tier: str                          # e.g. "starter", "professional", "enterprise"
    subscription_status: str           # e.g. "active", "trialing", "past_due", "canceled"
    settings: dict = field(default_factory=dict)
    # Caller identity — populated from the auth token at request time
    user_id: str | None = None
    user_email: str | None = None


_workspace_context: ContextVar[WorkspaceContext | None] = ContextVar(
    "_workspace_context", default=None
)


def get_current_workspace() -> WorkspaceContext | None:
    """Return the WorkspaceContext bound to the current async task, or None."""
    return _workspace_context.get()


def get_workspace_id() -> str | None:
    """Shortcut — return workspace_id from context, or None if no context set."""
    ctx = _workspace_context.get()
    return ctx.workspace_id if ctx is not None else None


def set_workspace_context(ctx: WorkspaceContext) -> None:
    """Bind a WorkspaceContext to the current async task."""
    _workspace_context.set(ctx)


def clear_workspace_context() -> None:
    """Reset the ContextVar to None (called after request completes)."""
    _workspace_context.set(None)
