"""Structured lifecycle event writer for ProspectIQ.

Single entry point: emit_workflow_event().

Call this whenever approval_status, sent_at, or suppression state changes
so the event log is deterministic and queryable.

Non-fatal: any insert failure is logged as a warning and silently suppressed.
Callers must never need a try/except around a lifecycle state transition just
because of this module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.core.database import Database

logger = logging.getLogger(__name__)


def emit_workflow_event(
    db: "Database",
    *,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    from_state: str | None = None,
    to_state: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    triggered_by: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Insert one row into workflow_events; return its UUID or None on failure.

    Parameters
    ----------
    db:           Database instance — provides the Supabase client.
    workspace_id: Tenant UUID string (required — row is invisible without it).
    entity_type:  'draft' | 'contact' | 'company' | 'sequence' | 'suppression'
    entity_id:    UUID string of the entity that transitioned.
    event_type:   Dot-scoped label e.g. 'draft.approved', 'contact.suppressed'.
    from_state:   Previous approval_status / outreach_state (omit for creation events).
    to_state:     New state after the transition.
    actor_type:   'human' | 'system' | 'webhook' | 'operator_script'
    actor_id:     user_id UUID string for human actors; job name for system actors.
    triggered_by: The endpoint path, job name, or script that caused this event.
    metadata:     Arbitrary context dict (rejection reason, assertion flags, etc.).
    """
    try:
        row: dict[str, Any] = {
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "metadata": metadata or {},
        }
        if from_state is not None:
            row["from_state"] = from_state
        if to_state is not None:
            row["to_state"] = to_state
        if actor_id is not None:
            row["actor_id"] = actor_id
        if triggered_by is not None:
            row["triggered_by"] = triggered_by

        result = db.client.table("workflow_events").insert(row).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as exc:
        logger.warning(
            "audit_events: failed to emit %s for %s %s: %s",
            event_type,
            entity_type,
            entity_id,
            exc,
        )
    return None
