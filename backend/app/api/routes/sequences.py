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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


# ===========================================================================
# V2 Visual Sequence Builder — models and routes
# Stored in campaign_sequence_definitions_v2 table with full SequenceStepV2
# shape supporting email / wait / condition / task / linkedin step types.
# ===========================================================================


class SequenceStepV2(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_type: str                        # email | wait | condition | linkedin | task
    step_order: int

    # Email
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    persona_variants: Optional[Dict[str, str]] = None

    # Wait
    wait_days: Optional[int] = None
    wait_condition: Optional[str] = None  # no_reply | no_open | any

    # Condition branch
    condition_type: Optional[str] = None  # if_opened | if_replied | if_clicked | if_pqs_above
    condition_value: Optional[Any] = None
    branch_yes: Optional[str] = None      # step_id
    branch_no: Optional[str] = None       # step_id

    # Task
    task_description: Optional[str] = None
    task_due_offset_days: Optional[int] = None

    metadata: Dict[str, Any] = {}


class SequenceDefinitionV2Body(BaseModel):
    name: str
    description: Optional[str] = None
    cluster: Optional[str] = None
    persona: Optional[str] = None
    steps: List[SequenceStepV2]
    is_template: bool = False
    tags: List[str] = []


class SequencePreviewRequest(BaseModel):
    contact_id: str
    company_id: str


def _validate_sequence_steps(steps: List[SequenceStepV2]) -> List[str]:
    """Return list of validation error strings (empty = valid)."""
    errors: List[str] = []
    email_steps = [s for s in steps if s.step_type == "email"]
    if not email_steps:
        errors.append("Sequence must contain at least one email step.")
    for step in email_steps:
        if not step.subject_template or not step.subject_template.strip():
            errors.append(f"Email step (order {step.step_order}) is missing a subject template.")
        if not step.body_template or not step.body_template.strip():
            errors.append(f"Email step (order {step.step_order}) is missing a body template.")
    step_ids = {s.step_id for s in steps}
    for step in steps:
        if step.step_type == "condition":
            if step.branch_yes and step.branch_yes not in step_ids:
                errors.append(f"Condition step (order {step.step_order}) branch_yes points to unknown step_id.")
            if step.branch_no and step.branch_no not in step_ids:
                errors.append(f"Condition step (order {step.step_order}) branch_no points to unknown step_id.")
    return errors


def _render_template(template: str, contact: dict, company: dict) -> str:
    """Fill {variable} placeholders with contact/company data."""
    replacements = {
        "{first_name}": contact.get("first_name") or "",
        "{last_name}": contact.get("last_name") or "",
        "{company_name}": company.get("name") or "",
        "{industry}": company.get("industry") or "",
        "{title}": contact.get("title") or "",
        "{pain_signal_1}": ((company.get("pain_signals") or []) + [""])[0],
        "{personalization_hook_1}": ((company.get("personalization_hooks") or []) + [""])[0],
        "{trigger_event_1}": "",
    }
    result = template
    for key, value in replacements.items():
        result = result.replace(key, str(value))
    return result


# ---------------------------------------------------------------------------
# V2 Router — /api/sequences/v2/*
# ---------------------------------------------------------------------------

v2_router = APIRouter(prefix="/api/sequences/v2", tags=["sequences-v2"])


@v2_router.post("")
async def create_sequence_v2(body: SequenceDefinitionV2Body):
    """Create a new V2 visual sequence. Validates steps before saving."""
    errors = _validate_sequence_steps(body.steps)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    steps_data = [step.model_dump() for step in body.steps]

    try:
        result = (
            db.client.table("campaign_sequence_definitions_v2")
            .insert(db._inject_ws({
                "id": str(uuid.uuid4()),
                "name": body.name,
                "description": body.description or "",
                "cluster": body.cluster,
                "persona": body.persona,
                "steps": steps_data,
                "is_template": body.is_template,
                "tags": body.tags,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }))
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert returned no data")
        return {"data": result.data[0], "message": f"Sequence '{body.name}' created"}
    except HTTPException:
        raise
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Sequence named '{body.name}' already exists.")
        raise HTTPException(status_code=500, detail=str(e))


@v2_router.get("/{sequence_id}")
async def get_sequence_v2(sequence_id: str):
    """Fetch a single V2 sequence by UUID."""
    db = get_db()
    try:
        result = (
            db._filter_ws(db.client.table("campaign_sequence_definitions_v2").select("*"))
            .eq("id", sequence_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found.")
        return {"data": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@v2_router.put("/{sequence_id}")
async def update_sequence_v2(sequence_id: str, body: SequenceDefinitionV2Body):
    """Replace all steps for a V2 sequence. Full validation applied."""
    errors = _validate_sequence_steps(body.steps)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    db = get_db()
    existing = (
        db._filter_ws(db.client.table("campaign_sequence_definitions_v2").select("id"))
        .eq("id", sequence_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found.")

    now = datetime.now(timezone.utc).isoformat()
    update_data = {
        "name": body.name,
        "description": body.description or "",
        "cluster": body.cluster,
        "persona": body.persona,
        "steps": [s.model_dump() for s in body.steps],
        "is_template": body.is_template,
        "tags": body.tags,
        "updated_at": now,
    }

    try:
        result = (
            db._filter_ws(db.client.table("campaign_sequence_definitions_v2").update(update_data))
            .eq("id", sequence_id)
            .execute()
        )
        return {"data": result.data[0] if result.data else None, "message": f"Sequence '{sequence_id}' updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@v2_router.delete("/{sequence_id}")
async def delete_sequence_v2(sequence_id: str):
    """Soft-delete a V2 sequence (sets is_active=false)."""
    db = get_db()
    existing = (
        db._filter_ws(db.client.table("campaign_sequence_definitions_v2").select("id"))
        .eq("id", sequence_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found.")

    db._filter_ws(
        db.client.table("campaign_sequence_definitions_v2")
        .update({"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()})
    ).eq("id", sequence_id).execute()

    return {"message": f"Sequence '{sequence_id}' deactivated"}


@v2_router.post("/{sequence_id}/duplicate")
async def duplicate_sequence_v2(sequence_id: str):
    """Create a copy of a V2 sequence."""
    db = get_db()
    existing = (
        db._filter_ws(db.client.table("campaign_sequence_definitions_v2").select("*"))
        .eq("id", sequence_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found.")

    source = existing.data[0]
    now = datetime.now(timezone.utc).isoformat()
    new_id = str(uuid.uuid4())

    try:
        result = (
            db.client.table("campaign_sequence_definitions_v2")
            .insert(db._inject_ws({
                "id": new_id,
                "name": f"{source['name']}_copy_{new_id[:6]}",
                "description": source.get("description", ""),
                "cluster": source.get("cluster"),
                "persona": source.get("persona"),
                "steps": source.get("steps", []),
                "is_template": source.get("is_template", False),
                "tags": source.get("tags", []),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }))
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=500, detail="Duplicate returned no data")
        return {"data": result.data[0], "message": f"Sequence duplicated as '{new_id}'"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@v2_router.post("/{sequence_id}/preview")
async def preview_sequence_v2(sequence_id: str, body: SequencePreviewRequest):
    """Render template variables for a specific contact/company."""
    db = get_db()
    seq_result = (
        db._filter_ws(db.client.table("campaign_sequence_definitions_v2").select("*"))
        .eq("id", sequence_id)
        .execute()
    )
    if not seq_result.data:
        raise HTTPException(status_code=404, detail=f"Sequence '{sequence_id}' not found.")
    seq = seq_result.data[0]

    try:
        contact_result = db._filter_ws(db.client.table("contacts").select("*")).eq("id", body.contact_id).execute()
        contact = contact_result.data[0] if contact_result.data else {}
    except Exception:
        contact = {}

    try:
        company_result = db._filter_ws(db.client.table("companies").select("*")).eq("id", body.company_id).execute()
        company = company_result.data[0] if company_result.data else {}
    except Exception:
        company = {}

    rendered_steps = []
    for step in (seq.get("steps") or []):
        rendered: dict[str, Any] = {
            "step_id": step.get("step_id"),
            "step_type": step.get("step_type"),
            "step_order": step.get("step_order"),
        }
        stype = step.get("step_type")
        if stype == "email":
            rendered["subject"] = _render_template(step.get("subject_template") or "", contact, company)
            rendered["body"] = _render_template(step.get("body_template") or "", contact, company)
        elif stype == "wait":
            rendered["wait_days"] = step.get("wait_days")
            rendered["wait_condition"] = step.get("wait_condition")
        elif stype == "condition":
            rendered["condition_type"] = step.get("condition_type")
        elif stype == "task":
            rendered["task_description"] = _render_template(step.get("task_description") or "", contact, company)
        elif stype == "linkedin":
            rendered["body"] = _render_template(step.get("body_template") or "", contact, company)
        rendered_steps.append(rendered)

    contact_name = (
        contact.get("full_name")
        or f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
        or None
    )

    return {
        "sequence_id": sequence_id,
        "contact_id": body.contact_id,
        "company_id": body.company_id,
        "contact_name": contact_name,
        "company_name": company.get("name"),
        "steps": rendered_steps,
    }


class EnrollmentPatchRequest(BaseModel):
    status: str  # "paused" | "active" | "stopped"


@v2_router.patch("/enrollments/{enrollment_id}")
async def patch_enrollment(enrollment_id: str, body: EnrollmentPatchRequest):
    """Pause, resume, or stop a contact's enrollment in a sequence."""
    allowed = {"paused", "active", "stopped"}
    if body.status not in allowed:
        raise HTTPException(status_code=422, detail=f"status must be one of: {allowed}")
    db = get_db()
    existing = (
        db._filter_ws(db.client.table("engagement_sequences").select("id"))
        .eq("id", enrollment_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail=f"Enrollment '{enrollment_id}' not found.")
    now = datetime.now(timezone.utc).isoformat()
    db._filter_ws(
        db.client.table("engagement_sequences")
        .update({"status": body.status, "updated_at": now})
    ).eq("id", enrollment_id).execute()
    return {"message": f"Enrollment {enrollment_id} set to '{body.status}'", "status": body.status}


@v2_router.get("/{sequence_id}/stats")
async def get_sequence_stats_v2(sequence_id: str):
    """Return engagement stats for a V2 sequence."""
    db = get_db()
    try:
        enroll_result = (
            db._filter_ws(db.client.table("engagement_sequences").select("id,status", count="exact"))
            .eq("sequence_name", sequence_id)
            .execute()
        )
        total = enroll_result.count or 0
        enrollments = enroll_result.data or []
        active_count = sum(1 for e in enrollments if e.get("status") == "active")
        completed_count = sum(1 for e in enrollments if e.get("status") == "completed")
    except Exception:
        total = active_count = completed_count = 0

    return {
        "sequence_id": sequence_id,
        "enrolled_count": total,
        "active_count": active_count,
        "completed_count": completed_count,
        "bounced_count": 0,
        "open_rate": 0.0,
        "reply_rate": 0.0,
        "click_rate": 0.0,
        "conversion_rate": 0.0,
    }


# ---------------------------------------------------------------------------
# Timeline — GET /api/sequences/v2/timeline
# ---------------------------------------------------------------------------

@v2_router.get("/timeline")
async def get_sequence_timeline():
    """Return all active/paused/completed enrollment rows with per-step due dates.

    Joins engagement_sequences + outreach_drafts (step=1, sent_at) + companies +
    contacts + thread_messages (latest inbound) to build a full timeline view.
    """
    db = get_db()

    # Fetch all enrollments for this workspace
    enroll_result = (
        db._filter_ws(
            db.client.table("engagement_sequences").select(
                "id, company_id, contact_id, sequence_name, current_step, total_steps, "
                "status, next_action_at, next_action_type, created_at"
            )
        )
        .execute()
    )
    enrollments = enroll_result.data or []
    if not enrollments:
        return {"data": [], "total": 0}

    company_ids = list({e["company_id"] for e in enrollments if e.get("company_id")})
    contact_ids = list({e["contact_id"] for e in enrollments if e.get("contact_id")})

    # Batch-fetch companies
    companies_map: dict[str, dict] = {}
    if company_ids:
        comp_result = (
            db.client.table("companies")
            .select("id, name")
            .in_("id", company_ids)
            .execute()
        )
        companies_map = {c["id"]: c for c in (comp_result.data or [])}

    # Batch-fetch contacts
    contacts_map: dict[str, dict] = {}
    if contact_ids:
        cont_result = (
            db.client.table("contacts")
            .select("id, full_name, email, persona_type")
            .in_("id", contact_ids)
            .execute()
        )
        contacts_map = {c["id"]: c for c in (cont_result.data or [])}

    # Batch-fetch step-1 sent_at from outreach_drafts
    step1_map: dict[str, str] = {}  # contact_id -> sent_at
    if contact_ids:
        drafts_result = (
            db._filter_ws(
                db.client.table("outreach_drafts").select("contact_id, sent_at")
            )
            .eq("sequence_step", 1)
            .not_.is_("sent_at", "null")
            .in_("contact_id", contact_ids)
            .execute()
        )
        for d in (drafts_result.data or []):
            if d["contact_id"] not in step1_map:
                step1_map[d["contact_id"]] = d["sent_at"]

    # Batch-fetch latest inbound thread_messages per contact
    reply_map: dict[str, dict] = {}  # contact_id -> latest inbound
    if contact_ids:
        try:
            thread_result = (
                db.client.table("thread_messages")
                .select("contact_id, body, classification, created_at")
                .eq("direction", "inbound")
                .in_("contact_id", contact_ids)
                .order("created_at", desc=True)
                .execute()
            )
            for msg in (thread_result.data or []):
                cid = msg.get("contact_id")
                if cid and cid not in reply_map:
                    reply_map[cid] = msg
        except Exception:
            pass  # thread_messages may not have contact_id FK — degrade gracefully

    # Load sequence step delays from YAML to compute per-step due dates
    from backend.app.core.config import get_sequences_config
    sequences_config = get_sequences_config()
    step_delays_by_seq: dict[str, dict[int, int]] = {}
    for seq_name, seq_def in sequences_config.get("sequences", {}).items():
        delays: dict[int, int] = {}
        for step in seq_def.get("steps", []):
            delays[step["step"]] = step.get("delay_days", 0)
        step_delays_by_seq[seq_name] = delays

    from datetime import timedelta

    rows = []
    for e in enrollments:
        contact_id = e.get("contact_id", "")
        company_id = e.get("company_id", "")
        company = companies_map.get(company_id, {})
        contact = contacts_map.get(contact_id, {})
        reply = reply_map.get(contact_id)

        step1_sent_at = step1_map.get(contact_id)
        total_steps = e.get("total_steps", 4)
        seq_name = e.get("sequence_name", "")
        delays = step_delays_by_seq.get(seq_name, {})

        step_due_dates: dict[str, str | None] = {}
        if step1_sent_at:
            try:
                base = datetime.fromisoformat(step1_sent_at.replace("Z", "+00:00"))
                for step_num in range(1, total_steps + 1):
                    delay = delays.get(step_num, 0)
                    due = base + timedelta(days=delay)
                    step_due_dates[f"step{step_num}_due_at"] = due.isoformat()
            except Exception:
                pass

        rows.append({
            "enrollment_id": e["id"],
            "company_id": company_id,
            "company_name": company.get("name"),
            "contact_id": contact_id,
            "contact_name": contact.get("full_name"),
            "contact_email": contact.get("email"),
            "persona_type": contact.get("persona_type"),
            "sequence_name": seq_name,
            "current_step": e.get("current_step"),
            "total_steps": total_steps,
            "status": e.get("status"),
            "next_action_at": e.get("next_action_at"),
            "next_action_type": e.get("next_action_type"),
            "step1_sent_at": step1_sent_at,
            **step_due_dates,
            "reply_received": reply is not None,
            "reply_intent": reply.get("classification") if reply else None,
            "reply_body_preview": (reply.get("body", "")[:120] if reply else None),
        })

    return {"data": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Log Reply — POST /api/sequences/v2/contacts/{contact_id}/reply
# ---------------------------------------------------------------------------

class LogReplyRequest(BaseModel):
    body: str
    intent: str  # interested | not_interested | question | referral | objection
    notes: Optional[str] = None
    sequence_enrollment_id: Optional[str] = None


@v2_router.post("/contacts/{contact_id}/reply")
async def log_reply(contact_id: str, body: LogReplyRequest):
    """Log a reply received from a prospect.

    - Inserts into interactions (type=email_replied, direction inbound via metadata)
    - Inserts into thread_messages (direction=inbound)
    - Updates campaign_threads.status = replied, last_replied_at = now
    - If intent=not_interested → pauses engagement_sequences
    - If intent=interested → advances next_action_at to now+1d
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Upsert interaction record
    try:
        db._filter_ws(
            db.client.table("interactions").insert(db._inject_ws({
                "contact_id": contact_id,
                "type": "email_replied",
                "body": body.body,
                "source": "manual",
                "metadata": {"direction": "inbound", "intent": body.intent, "notes": body.notes},
                "created_at": now,
            }))
        ).execute()
    except Exception as e:
        logger.warning(f"log_reply: failed to insert interaction: {e}")

    # Insert thread_messages inbound row
    # Look up campaign_thread for this contact
    thread_id: str | None = None
    try:
        thread_result = (
            db._filter_ws(
                db.client.table("campaign_threads").select("id")
            )
            .eq("contact_id", contact_id)
            .limit(1)
            .execute()
        )
        if thread_result.data:
            thread_id = thread_result.data[0]["id"]
    except Exception:
        pass

    if thread_id:
        try:
            db.client.table("thread_messages").insert({
                "thread_id": thread_id,
                "contact_id": contact_id,
                "direction": "inbound",
                "body": body.body,
                "classification": body.intent,
                "source": "manual",
                "created_at": now,
            }).execute()
        except Exception as e:
            logger.warning(f"log_reply: failed to insert thread_messages: {e}")

        # Update campaign_threads status
        try:
            db.client.table("campaign_threads").update({
                "status": "replied",
                "last_replied_at": now,
            }).eq("id", thread_id).execute()
        except Exception as e:
            logger.warning(f"log_reply: failed to update campaign_threads: {e}")

    # Update engagement_sequences based on intent
    enrollment_id = body.sequence_enrollment_id
    try:
        query = db._filter_ws(
            db.client.table("engagement_sequences").select("id, status")
        ).eq("contact_id", contact_id)
        if enrollment_id:
            query = query.eq("id", enrollment_id)
        enroll_result = query.limit(1).execute()
        enrollment = enroll_result.data[0] if enroll_result.data else None

        if enrollment:
            eid = enrollment["id"]
            if body.intent in ("not_interested", "unsubscribe"):
                db.client.table("engagement_sequences").update({
                    "status": "paused",
                    "updated_at": now,
                }).eq("id", eid).execute()
                new_status = "paused"
            elif body.intent == "interested":
                from datetime import timedelta
                next_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                db.client.table("engagement_sequences").update({
                    "next_action_at": next_at,
                    "updated_at": now,
                }).eq("id", eid).execute()
                new_status = "active (expedited)"
            else:
                new_status = enrollment["status"]
        else:
            eid = None
            new_status = "no enrollment found"
    except Exception as e:
        logger.warning(f"log_reply: failed to update engagement_sequences: {e}")
        eid = None
        new_status = "update failed"

    return {
        "message": "Reply logged",
        "contact_id": contact_id,
        "intent": body.intent,
        "enrollment_id": eid,
        "enrollment_status": new_status,
    }


# ---------------------------------------------------------------------------
# Reschedule Step — PATCH /api/sequences/v2/enrollments/{enrollment_id}/schedule
# ---------------------------------------------------------------------------

class RescheduleStepRequest(BaseModel):
    step: int
    new_date: str  # ISO datetime string


@v2_router.patch("/enrollments/{enrollment_id}/schedule")
async def reschedule_step(enrollment_id: str, body: RescheduleStepRequest):
    """Reschedule a specific step for an enrollment by updating next_action_at.

    Only updates if the enrollment's current_step matches the requested step
    (i.e., the step hasn't been sent yet). For steps that have already passed,
    returns a 400 with context.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Fetch enrollment
    result = (
        db._filter_ws(
            db.client.table("engagement_sequences").select(
                "id, current_step, total_steps, status, next_action_at"
            )
        )
        .eq("id", enrollment_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Enrollment {enrollment_id} not found")

    enrollment = result.data[0]
    current_step = enrollment.get("current_step", 1)

    if body.step < current_step:
        raise HTTPException(
            status_code=400,
            detail=f"Step {body.step} has already been sent (current step is {current_step}). Cannot reschedule past steps."
        )

    if body.step != current_step + 1 and body.step != current_step:
        raise HTTPException(
            status_code=400,
            detail=f"Can only reschedule the next pending step. Current step: {current_step}, requested: {body.step}."
        )

    try:
        new_dt = datetime.fromisoformat(body.new_date.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {body.new_date}")

    db.client.table("engagement_sequences").update({
        "next_action_at": new_dt.isoformat(),
        "updated_at": now,
    }).eq("id", enrollment_id).execute()

    return {
        "message": f"Step {body.step} rescheduled",
        "enrollment_id": enrollment_id,
        "step": body.step,
        "new_next_action_at": new_dt.isoformat(),
    }


# ---------------------------------------------------------------------------
# Email Engagement Dashboard
# ---------------------------------------------------------------------------

@v2_router.get("/email-engagement")
async def get_email_engagement(limit: int = 200, offset: int = 0):
    """Return all sent outreach drafts with delivery/engagement status.

    Joins outreach_drafts (sent) + contacts + companies + interactions
    to show per-contact: sent date, resend_status, opens, clicks, bounces.
    """
    db = get_db()

    # Fetch sent drafts
    drafts_result = (
        db._filter_ws(
            db.client.table("outreach_drafts").select(
                "id, contact_id, company_id, sequence_step, sent_at, "
                "resend_status, resend_message_id, subject, approval_status"
            )
        )
        .not_.is_("sent_at", "null")
        .order("sent_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    drafts = drafts_result.data or []
    if not drafts:
        return {"data": [], "total": 0}

    # Count total
    count_result = (
        db._filter_ws(
            db.client.table("outreach_drafts").select("id", count="exact")
        )
        .not_.is_("sent_at", "null")
        .execute()
    )
    total = count_result.count or len(drafts)

    contact_ids = list({d["contact_id"] for d in drafts if d.get("contact_id")})
    company_ids = list({d["company_id"] for d in drafts if d.get("company_id")})

    # Batch-fetch contacts
    contacts_map: dict[str, dict] = {}
    if contact_ids:
        cont = (
            db.client.table("contacts")
            .select("id, full_name, email, persona_type")
            .in_("id", contact_ids)
            .execute()
        )
        contacts_map = {c["id"]: c for c in (cont.data or [])}

    # Batch-fetch companies
    companies_map: dict[str, dict] = {}
    if company_ids:
        comp = (
            db.client.table("companies")
            .select("id, name, industry")
            .in_("id", company_ids)
            .execute()
        )
        companies_map = {c["id"]: c for c in (comp.data or [])}

    # Batch-fetch engagement interactions (opens, clicks, bounces)
    engagement_map: dict[str, list] = {}  # contact_id -> list of events
    if contact_ids:
        events_result = (
            db.client.table("interactions")
            .select("contact_id, type, created_at, metadata")
            .in_("contact_id", contact_ids)
            .in_("type", ["email_opened", "email_clicked", "email_bounced",
                          "email_delivered", "email_complained"])
            .order("created_at", desc=False)
            .execute()
        )
        for ev in (events_result.data or []):
            cid = ev["contact_id"]
            if cid not in engagement_map:
                engagement_map[cid] = []
            engagement_map[cid].append(ev)

    rows = []
    for d in drafts:
        cid = d.get("contact_id")
        company = companies_map.get(d.get("company_id") or "", {})
        contact = contacts_map.get(cid or "", {})
        events = engagement_map.get(cid or "", [])

        opens = sum(1 for e in events if e["type"] == "email_opened")
        clicks = sum(1 for e in events if e["type"] == "email_clicked")
        bounced = any(e["type"] == "email_bounced" for e in events)
        complained = any(e["type"] == "email_complained" for e in events)
        delivered = any(e["type"] == "email_delivered" for e in events)
        last_open_at = next(
            (e["created_at"] for e in reversed(events) if e["type"] == "email_opened"),
            None
        )

        # Derive display status
        if complained:
            display_status = "complained"
        elif bounced:
            display_status = "bounced"
        elif clicks > 0:
            display_status = "clicked"
        elif opens > 0:
            display_status = "opened"
        elif delivered or d.get("resend_status") == "delivered":
            display_status = "delivered"
        elif d.get("resend_status"):
            display_status = d["resend_status"]
        else:
            display_status = "sent"

        rows.append({
            "draft_id": d["id"],
            "contact_id": cid,
            "contact_name": contact.get("full_name") or "—",
            "contact_email": contact.get("email") or "—",
            "persona_type": contact.get("persona_type"),
            "company_id": d.get("company_id"),
            "company_name": company.get("name") or "—",
            "industry": company.get("industry"),
            "sequence_step": d.get("sequence_step", 1),
            "subject": d.get("subject"),
            "sent_at": d["sent_at"],
            "resend_status": d.get("resend_status"),
            "resend_message_id": d.get("resend_message_id"),
            "display_status": display_status,
            "opens": opens,
            "clicks": clicks,
            "bounced": bounced,
            "complained": complained,
            "last_open_at": last_open_at,
        })

    return {"data": rows, "total": total}
