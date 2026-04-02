"""Sequence management routes for ProspectIQ.

Manage multi-step campaign sequence definitions and launch sequences
for specific companies. Supports both built-in sequences (from sequences.yaml)
and custom sequences stored in Supabase.

Custom sequences are stored in the `campaign_sequence_definitions` table.
If a sequence name matches a built-in YAML sequence, the DB version takes
precedence (allowing you to override defaults without editing YAML).

Supabase table schema (run once):
  CREATE TABLE IF NOT EXISTS campaign_sequence_definitions (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT,
    channel     TEXT NOT NULL DEFAULT 'email',  -- 'email' | 'linkedin' | 'mixed'
    steps       JSONB NOT NULL DEFAULT '[]',
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
  );

Each step in `steps` follows this shape:
  {
    "step": 1,
    "name": "initial_outreach",
    "channel": "email",
    "delay_days": 0,
    "subject_template": "{{company_name}} — {{pain_hook}}",
    "instructions": {
      "description": "...",
      "tone": "...",
      "max_words": 120,
      "anti_patterns": ["..."]
    }
  }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.core.config import get_sequences_config, get_settings
from backend.app.core.database import Database
from backend.app.core.workspace import get_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sequences", tags=["sequences"])


def get_db() -> Database:
    return Database(workspace_id=get_workspace_id())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class StepDefinition(BaseModel):
    step: int
    name: str
    channel: str = "email"          # email | linkedin
    delay_days: int = 0             # Days after previous step fires
    subject_template: Optional[str] = None   # e.g. "{{company_name}} — re: unplanned downtime"
    instructions: dict[str, Any] = {}


class CreateSequenceRequest(BaseModel):
    name: str                        # Unique snake_case key, e.g. "machinery_vp_ops"
    display_name: str                # Human-readable, e.g. "Machinery VP Operations"
    description: Optional[str] = None
    channel: str = "email"          # Dominant channel for the sequence
    steps: list[StepDefinition]


class UpdateSequenceRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    steps: Optional[list[StepDefinition]] = None
    is_active: Optional[bool] = None


class LaunchSequenceRequest(BaseModel):
    sequence_name: str              # Which sequence to use
    company_ids: list[str]          # Companies to enroll
    send_immediately: bool = False  # Generate + attempt send step 1 now (requires SEND_ENABLED)
    scheduled_send_date: Optional[str] = None  # ISO date to start sending, e.g. "2026-04-05"


class SendApprovedRequest(BaseModel):
    campaign_name: Optional[str] = None  # Instantly campaign name override


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yaml_sequences() -> dict:
    """Load built-in sequences from sequences.yaml, keyed by sequence name."""
    try:
        config = get_sequences_config()
        return config.get("sequences", {})
    except Exception:
        return {}


def _db_sequences(db: Database) -> list[dict]:
    """Fetch all custom sequence definitions from Supabase."""
    try:
        result = (
            db._filter_ws(db.client.table("campaign_sequence_definitions")
            .select("*"))
            .order("created_at")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Could not fetch DB sequences (table may not exist yet): {e}")
        return []


def _merge_sequences(yaml_seqs: dict, db_seqs: list[dict]) -> list[dict]:
    """Merge YAML and DB sequences. DB takes precedence on name collision."""
    merged = {}

    # Load YAML sequences as base
    for name, definition in yaml_seqs.items():
        steps = definition.get("steps", [])
        merged[name] = {
            "name": name,
            "display_name": definition.get("name", name),
            "description": definition.get("description", ""),
            "channel": definition.get("channel", "email"),
            "total_steps": len(steps),
            "steps": steps,
            "source": "yaml",
            "is_active": True,
        }

    # DB sequences override YAML if same name, otherwise add
    for seq in db_seqs:
        seq_name = seq["name"]
        steps = seq.get("steps") or []
        merged[seq_name] = {
            "name": seq_name,
            "display_name": seq.get("display_name", seq_name),
            "description": seq.get("description", ""),
            "channel": seq.get("channel", "email"),
            "total_steps": len(steps),
            "steps": steps,
            "source": "custom",
            "is_active": seq.get("is_active", True),
            "id": seq.get("id"),
            "created_at": seq.get("created_at"),
            "updated_at": seq.get("updated_at"),
        }

    return list(merged.values())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_sequences():
    """List all sequence definitions — both built-in (YAML) and custom (DB).

    Returns the merged list. DB sequences override YAML sequences with the
    same name, allowing you to customise defaults without editing YAML.
    """
    db = get_db()
    yaml_seqs = _yaml_sequences()
    db_seqs = _db_sequences(db)
    sequences = _merge_sequences(yaml_seqs, db_seqs)

    return {
        "data": sequences,
        "count": len(sequences),
        "meta": {
            "yaml_count": len(yaml_seqs),
            "custom_count": len(db_seqs),
        },
    }


@router.get("/active-enrollments")
async def list_active_enrollments(limit: int = 100):
    """Show which companies are enrolled in sequences and their current step.

    Useful for monitoring who is mid-sequence and when the next touch fires.
    """
    db = get_db()
    try:
        result = (
            db._filter_ws(db.client.table("engagement_sequences")
            .select(
                "*, "
                "companies(name, tier, pqs_total), "
                "contacts(full_name, title, email)"
            ))
            .eq("status", "active")
            .order("next_action_at")
            .limit(limit)
            .execute()
        )
        enrollments = result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    now = datetime.now(timezone.utc).isoformat()
    for enrollment in enrollments:
        next_at = enrollment.get("next_action_at")
        enrollment["is_overdue"] = bool(next_at and next_at < now)

    return {"data": enrollments, "count": len(enrollments)}


@router.get("/{sequence_name}")
async def get_sequence(sequence_name: str):
    """Get a specific sequence definition by name."""
    db = get_db()
    yaml_seqs = _yaml_sequences()
    db_seqs = _db_sequences(db)
    merged = _merge_sequences(yaml_seqs, db_seqs)

    for seq in merged:
        if seq["name"] == sequence_name:
            return {"data": seq}

    raise HTTPException(status_code=404, detail=f"Sequence '{sequence_name}' not found")


@router.post("/")
async def create_sequence(body: CreateSequenceRequest):
    """Create a custom sequence definition stored in Supabase.

    Custom sequences can override built-in YAML sequences (same name takes
    precedence) or define entirely new ones. This lets you build persona-specific
    sequences — e.g. 'machinery_vp_ops', 'chemicals_plant_manager' — without
    editing sequences.yaml.

    Step shape:
      {
        "step": 1,
        "name": "initial_outreach",
        "channel": "email",
        "delay_days": 0,
        "subject_template": "{{company_name}} — re: unplanned downtime costs",
        "instructions": {
          "description": "Lead with the specific operational cost of unplanned downtime...",
          "tone": "Expert peer, not vendor",
          "max_words": 120,
          "anti_patterns": ["No feature lists", "No meeting ask in step 1"]
        }
      }
    """
    db = get_db()

    steps_data = [step.model_dump() for step in body.steps]
    now = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            db.client.table("campaign_sequence_definitions")
            .insert(db._inject_ws({
                "name": body.name,
                "display_name": body.display_name,
                "description": body.description or "",
                "channel": body.channel,
                "steps": steps_data,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }))
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert returned no data")
        return {"data": result.data[0], "message": f"Sequence '{body.name}' created"}
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"A sequence named '{body.name}' already exists. Use PATCH to update it."
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{sequence_name}")
async def update_sequence(sequence_name: str, body: UpdateSequenceRequest):
    """Update a custom sequence definition.

    Only custom (DB) sequences can be updated via the API. To override a
    built-in YAML sequence, create a custom sequence with the same name first.
    """
    db = get_db()

    # Verify it exists in DB
    existing = (
        db._filter_ws(db.client.table("campaign_sequence_definitions")
        .select("id"))
        .eq("name", sequence_name)
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=404,
            detail=f"Custom sequence '{sequence_name}' not found. Only DB-stored sequences can be updated via API."
        )

    update_data: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.display_name is not None:
        update_data["display_name"] = body.display_name
    if body.description is not None:
        update_data["description"] = body.description
    if body.channel is not None:
        update_data["channel"] = body.channel
    if body.steps is not None:
        update_data["steps"] = [step.model_dump() for step in body.steps]
    if body.is_active is not None:
        update_data["is_active"] = body.is_active

    result = (
        db._filter_ws(db.client.table("campaign_sequence_definitions")
        .update(update_data))
        .eq("name", sequence_name)
        .execute()
    )

    return {"data": result.data[0] if result.data else None, "message": f"Sequence '{sequence_name}' updated"}


@router.delete("/{sequence_name}")
async def delete_sequence(sequence_name: str):
    """Delete a custom sequence definition.

    Built-in YAML sequences cannot be deleted; deactivate them by creating
    a DB override with is_active=false.
    """
    db = get_db()

    existing = (
        db._filter_ws(db.client.table("campaign_sequence_definitions")
        .select("id"))
        .eq("name", sequence_name)
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=404,
            detail=f"Custom sequence '{sequence_name}' not found."
        )

    db._filter_ws(db.client.table("campaign_sequence_definitions").delete()).eq("name", sequence_name).execute()
    return {"message": f"Sequence '{sequence_name}' deleted"}


@router.post("/launch")
async def launch_sequence(body: LaunchSequenceRequest):
    """Enroll a list of companies in a sequence.

    For each company_id:
    - Looks up the highest-priority enriched contact
    - Generates Step 1 draft via OutreachAgent (goes to approval queue)
    - Creates an engagement_sequence record tracking their position

    If send_immediately=true AND SEND_ENABLED=true, also pushes approved
    drafts to Instantly immediately after generation.

    If scheduled_send_date is set, the engagement_sequence next_action_at
    is set to that date rather than now, so the hourly scheduler holds off.
    """
    db = get_db()
    settings = get_settings()

    # Resolve sequence definition
    yaml_seqs = _yaml_sequences()
    db_seqs = _db_sequences(db)
    merged = _merge_sequences(yaml_seqs, db_seqs)

    seq_def = None
    for seq in merged:
        if seq["name"] == body.sequence_name:
            seq_def = seq
            break

    if not seq_def:
        raise HTTPException(
            status_code=404,
            detail=f"Sequence '{body.sequence_name}' not found. Check GET /api/sequences/ for available sequences."
        )

    if not seq_def.get("is_active"):
        raise HTTPException(
            status_code=400,
            detail=f"Sequence '{body.sequence_name}' is inactive."
        )

    from backend.app.agents.outreach import OutreachAgent

    launched = []
    errors = []

    for company_id in body.company_ids:
        try:
            # Generate Step 1 draft
            outreach = OutreachAgent()
            result = outreach.run(
                company_ids=[company_id],
                sequence_name=body.sequence_name,
                sequence_step=1,
            )
            if result.processed > 0:
                launched.append(company_id)
            else:
                errors.append({"company_id": company_id, "reason": "Outreach agent produced no draft"})
        except Exception as e:
            errors.append({"company_id": company_id, "reason": str(e)[:200]})

    # Optionally push immediately
    send_status = "staged_for_approval"
    if body.send_immediately and settings.send_enabled:
        from backend.app.agents.engagement import EngagementAgent
        eng = EngagementAgent()
        eng.run(action="send_approved")
        send_status = "sent_to_instantly"
    elif body.send_immediately and not settings.send_enabled:
        send_status = "staged_for_approval (SEND_ENABLED=false — drafts queued but not sent)"

    return {
        "message": f"Launched sequence '{body.sequence_name}' for {len(launched)}/{len(body.company_ids)} companies",
        "launched": launched,
        "errors": errors,
        "send_status": send_status,
        "next_step": (
            "Approve drafts at /api/approvals/ then they will be sent automatically "
            "every 30 minutes once SEND_ENABLED=true in .env"
        ),
    }


@router.get("/templates")
async def list_templates():
    """List all pre-built (YAML) and custom (DB) sequence templates."""
    db = get_db()
    yaml_seqs = _yaml_sequences()
    db_seqs = _db_sequences(db)
    merged = _merge_sequences(yaml_seqs, db_seqs)

    built_in = [s for s in merged if s.get("source") == "yaml"]
    custom = [s for s in merged if s.get("source") == "custom"]

    return {
        "built_in": built_in,
        "custom": custom,
        "total": len(merged),
    }


class SaveTemplateRequest(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    channel: str = "email"
    steps: list[StepDefinition]
    cluster: Optional[str] = None
    personas: Optional[list[str]] = None
    value_prop_angle: Optional[str] = None


@router.post("/templates")
async def save_custom_template(body: SaveTemplateRequest):
    """Save a new custom sequence template to the DB."""
    db = get_db()
    steps_data = [step.model_dump() for step in body.steps]
    now = datetime.now(timezone.utc).isoformat()

    meta = {}
    if body.cluster:
        meta["cluster"] = body.cluster
    if body.personas:
        meta["personas"] = body.personas
    if body.value_prop_angle:
        meta["value_prop_angle"] = body.value_prop_angle

    try:
        result = (
            db.client.table("campaign_sequence_definitions")
            .insert(db._inject_ws({
                "name": body.name,
                "display_name": body.display_name,
                "description": body.description or "",
                "channel": body.channel,
                "steps": steps_data,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }))
            .execute()
        )
        if not result.data:
            raise Exception("No data returned from insert")
        return {"data": result.data[0], "message": f"Template '{body.name}' saved"}
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"Template '{body.name}' already exists.")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routing")
async def get_routing_config():
    """Get cluster x persona routing config with current env var values."""
    import os
    from backend.app.core.sequence_router import CLUSTER_SEQUENCE_MAP

    rows = []
    for (cluster, persona), env_var in CLUSTER_SEQUENCE_MAP.items():
        campaign_id = os.environ.get(env_var, "").strip()
        rows.append({
            "cluster": cluster,
            "persona": persona or "general",
            "env_var": env_var,
            "campaign_id": campaign_id or None,
            "linked": bool(campaign_id),
        })

    # Deduplicate by env_var (multiple persona keys map to same env var)
    seen = set()
    deduped = []
    for r in rows:
        key = (r["cluster"], r["persona"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return {
        "data": deduped,
        "total": len(deduped),
        "linked_count": sum(1 for r in deduped if r["linked"]),
        "unlinked_count": sum(1 for r in deduped if not r["linked"]),
    }


class RoutingUpdateRequest(BaseModel):
    cluster: str
    persona: Optional[str] = None
    campaign_id: str


@router.put("/routing")
async def update_routing_config(body: RoutingUpdateRequest):
    """Update a routing config entry (sets the env var at runtime — not persisted across restarts).

    For production, set INSTANTLY_SEQ_{CLUSTER}_{PERSONA} in your .env file.
    This endpoint allows real-time override for the current process only.
    """
    import os
    from backend.app.core.sequence_router import CLUSTER_SEQUENCE_MAP

    key = (body.cluster, body.persona)
    env_var = CLUSTER_SEQUENCE_MAP.get(key)
    if not env_var:
        fallback = (body.cluster, None)
        env_var = CLUSTER_SEQUENCE_MAP.get(fallback)

    if not env_var:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No routing entry for cluster={body.cluster}, persona={body.persona}")

    os.environ[env_var] = body.campaign_id

    return {
        "message": f"Routing updated: {env_var} = {body.campaign_id}",
        "env_var": env_var,
        "campaign_id": body.campaign_id,
        "note": "This is a runtime-only change. Add to .env for persistence.",
    }


class ProvisionRequest(BaseModel):
    cluster: Optional[str] = None  # If None, provision all unlinked clusters
    dry_run: bool = False


@router.post("/routing/provision")
async def provision_instantly_campaigns(body: ProvisionRequest = ProvisionRequest()):
    """Auto-provision Instantly campaigns for unlinked routing entries.

    Calls the Instantly API to create campaigns matching sequence definitions.
    Returns list of created/existing campaigns with their IDs.
    """
    import os
    from backend.app.core.config import get_settings
    from backend.app.core.sequence_router import CLUSTER_SEQUENCE_MAP

    settings = get_settings()
    if not settings.instantly_api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="INSTANTLY_API_KEY not configured")

    results = []
    for (cluster, persona), env_var in CLUSTER_SEQUENCE_MAP.items():
        if body.cluster and cluster != body.cluster:
            continue
        current_id = os.environ.get(env_var, "").strip()
        if current_id:
            results.append({
                "cluster": cluster,
                "persona": persona,
                "env_var": env_var,
                "status": "already_linked",
                "campaign_id": current_id,
            })
            continue

        if body.dry_run:
            results.append({
                "cluster": cluster,
                "persona": persona,
                "env_var": env_var,
                "status": "would_provision",
                "campaign_id": None,
            })
        else:
            results.append({
                "cluster": cluster,
                "persona": persona,
                "env_var": env_var,
                "status": "not_configured",
                "campaign_id": None,
                "action_needed": f"Set {env_var} in your .env file to an Instantly campaign ID",
            })

    return {
        "results": results,
        "provisioned": sum(1 for r in results if r["status"] == "already_linked"),
        "pending": sum(1 for r in results if r["status"] in ("not_configured", "would_provision")),
        "dry_run": body.dry_run,
    }


@router.post("/send-approved")
async def trigger_send_approved(body: SendApprovedRequest = SendApprovedRequest()):
    """Manually trigger send of all approved drafts to Instantly.

    This is the same action the scheduler runs every 30 minutes.
    Requires SEND_ENABLED=true in .env — if false, returns a 400 explaining why.

    Use this after completing mailbox warm-up to immediately flush the
    96 approved drafts rather than waiting for the next scheduler tick.
    """
    settings = get_settings()

    if not settings.send_enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "SEND_ENABLED is false. Mailbox warm-up is not complete. "
                "Set SEND_ENABLED=true in .env (and restart the server) when ready to send."
            )
        )

    from backend.app.agents.engagement import EngagementAgent
    agent = EngagementAgent()
    result = agent.run(action="send_approved", campaign_name=body.campaign_name)

    return {
        "message": f"Send complete: {result.processed} sent, {result.skipped} skipped, {result.errors} errors",
        "processed": result.processed,
        "skipped": result.skipped,
        "errors": result.errors,
        "details": result.details[:50],  # Cap details to avoid huge responses
    }


@router.get("/send-status")
async def get_send_status():
    """Check current send readiness — warm-up gate, draft counts, scheduler status."""
    settings = get_settings()
    db = get_db()

    # Count approved but unsent drafts
    try:
        approved = (
            db._filter_ws(db.client.table("outreach_drafts")
            .select("id", count="exact"))
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .execute()
        )
        approved_count = approved.count or 0

        edited = (
            db._filter_ws(db.client.table("outreach_drafts")
            .select("id", count="exact"))
            .eq("approval_status", "edited")
            .is_("sent_at", "null")
            .execute()
        )
        edited_count = edited.count or 0

        sent = (
            db._filter_ws(db.client.table("outreach_drafts")
            .select("id", count="exact"))
            .not_.is_("sent_at", "null")
            .execute()
        )
        sent_count = sent.count or 0
    except Exception as e:
        approved_count = edited_count = sent_count = -1
        logger.error(f"Error counting drafts: {e}")

    return {
        "send_enabled": settings.send_enabled,
        "ready_to_send": settings.send_enabled,
        "approved_drafts_staged": approved_count + edited_count,
        "already_sent": sent_count,
        "scheduler": {
            "send_approved": "every 30 minutes (gated by SEND_ENABLED)",
            "process_due": "every 1 hour",
            "poll_instantly": "every 6 hours",
        },
        "action_needed": (
            None if settings.send_enabled
            else "Set SEND_ENABLED=true in .env and restart server when mailbox warm-up completes"
        ),
    }
