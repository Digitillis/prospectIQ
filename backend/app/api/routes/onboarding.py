"""Onboarding wizard API — 5-step workspace setup.

Steps:
  1  vertical      — choose target industry vertical
  2  senders       — add sender email addresses + reply_to
  3  credentials   — connect Apollo key, Resend key
  4  reply_inbox   — connect Gmail reply inbox (user + app password)
  5  import        — import initial prospect list (CSV) or start discovery

Each step is idempotent: re-submitting with the same data is safe.
Completing step 5 sets workspace.settings.onboarding_complete = true.

GET  /api/onboarding/status      — current step + completion state
POST /api/onboarding/step/{n}    — submit a step (1-5)
POST /api/onboarding/complete    — mark onboarding done (called after step 5)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.auth import require_workspace_member
from backend.app.core.workspace import WorkspaceContext
from backend.app.core.database import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Step1Vertical(BaseModel):
    vertical: str               # e.g. "manufacturing", "food_beverage", "general"
    sub_verticals: list[str] = []

class Step2Senders(BaseModel):
    senders: list[dict]         # [{name, email}, ...]
    reply_to: str

class Step3Credentials(BaseModel):
    apollo_api_key: str | None = None
    resend_api_key: str | None = None

class Step4ReplyInbox(BaseModel):
    gmail_user: str
    gmail_app_password: str

class Step5Import(BaseModel):
    mode: str = "discovery"     # "discovery" | "csv_uploaded"
    csv_company_count: int = 0  # how many rows were uploaded (informational)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_workspace_settings(workspace_id: str, updates: dict) -> None:
    client = get_supabase_client()
    row = (
        client.table("workspaces")
        .select("settings")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    ).data
    current = (row[0]["settings"] or {}) if row else {}
    merged = {**current, **updates}
    client.table("workspaces").update({"settings": merged}).eq("id", workspace_id).execute()


def _get_workspace_settings(workspace_id: str) -> dict:
    client = get_supabase_client()
    row = (
        client.table("workspaces")
        .select("settings")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    ).data
    return (row[0]["settings"] or {}) if row else {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def onboarding_status(
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Return current onboarding state for the workspace."""
    settings = _get_workspace_settings(ctx.workspace_id)
    return {
        "onboarding_complete": settings.get("onboarding_complete", False),
        "current_step": settings.get("onboarding_step", 0),
        "vertical": settings.get("vertical"),
        "has_senders": bool(settings.get("sender_pool")),
        "has_apollo_key": bool(settings.get("has_apollo_key")),
        "has_resend_key": bool(settings.get("has_resend_key")),
        "has_reply_inbox": bool(settings.get("has_reply_inbox")),
        "import_mode": settings.get("import_mode"),
    }


@router.post("/step/1")
async def step1_vertical(
    body: Step1Vertical,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Step 1: Choose target industry vertical."""
    _update_workspace_settings(ctx.workspace_id, {
        "vertical": body.vertical,
        "sub_verticals": body.sub_verticals,
        "onboarding_step": max(1, _get_workspace_settings(ctx.workspace_id).get("onboarding_step", 0)),
    })
    return {"ok": True, "step": 1, "vertical": body.vertical}


@router.post("/step/2")
async def step2_senders(
    body: Step2Senders,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Step 2: Configure sender pool and reply-to address."""
    if not body.senders:
        raise HTTPException(400, "At least one sender is required")
    if not body.reply_to:
        raise HTTPException(400, "reply_to address is required")

    client = get_supabase_client()
    # Persist sender pool to outreach_send_config
    existing = (
        client.table("outreach_send_config")
        .select("id")
        .eq("workspace_id", ctx.workspace_id)
        .limit(1)
        .execute()
    ).data

    if existing:
        client.table("outreach_send_config").update({
            "sender_pool": body.senders,
            "reply_to": body.reply_to,
        }).eq("workspace_id", ctx.workspace_id).execute()
    else:
        client.table("outreach_send_config").insert({
            "workspace_id": ctx.workspace_id,
            "sender_pool": body.senders,
            "reply_to": body.reply_to,
            "daily_limit": 125,
            "batch_size": 25,
            "send_enabled": True,
        }).execute()

    _update_workspace_settings(ctx.workspace_id, {
        "sender_pool": body.senders,
        "reply_to": body.reply_to,
        "onboarding_step": max(2, _get_workspace_settings(ctx.workspace_id).get("onboarding_step", 0)),
    })
    return {"ok": True, "step": 2, "sender_count": len(body.senders)}


@router.post("/step/3")
async def step3_credentials(
    body: Step3Credentials,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Step 3: Store Apollo and Resend API keys (encrypted)."""
    from backend.app.core.credential_store import CredentialStore
    store = CredentialStore(ctx.workspace_id)

    saved = []
    if body.apollo_api_key:
        store.set("apollo", "api_key", body.apollo_api_key)
        saved.append("apollo")
    if body.resend_api_key:
        store.set("resend", "api_key", body.resend_api_key)
        saved.append("resend")

    _update_workspace_settings(ctx.workspace_id, {
        "has_apollo_key": store.has("apollo", "api_key"),
        "has_resend_key": store.has("resend", "api_key"),
        "onboarding_step": max(3, _get_workspace_settings(ctx.workspace_id).get("onboarding_step", 0)),
    })
    return {"ok": True, "step": 3, "saved": saved}


@router.post("/step/4")
async def step4_reply_inbox(
    body: Step4ReplyInbox,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Step 4: Connect Gmail reply inbox."""
    from backend.app.core.credential_store import CredentialStore
    store = CredentialStore(ctx.workspace_id)

    # Validate credentials before saving
    try:
        from backend.app.integrations.gmail_imap import GmailImapClient
        with GmailImapClient(body.gmail_user, body.gmail_app_password) as gmail:
            gmail.fetch_unseen_replies()  # Will raise if credentials are wrong
    except Exception as exc:
        raise HTTPException(400, f"Gmail connection failed: {exc}. Check the address and app password.")

    store.set("gmail", "user", body.gmail_user)
    store.set("gmail", "app_password", body.gmail_app_password)

    # Also persist gmail_user to outreach_send_config for reference
    try:
        get_supabase_client().table("outreach_send_config").update({
            "gmail_user": body.gmail_user,
        }).eq("workspace_id", ctx.workspace_id).execute()
    except Exception:
        pass

    _update_workspace_settings(ctx.workspace_id, {
        "has_reply_inbox": True,
        "gmail_user_hint": body.gmail_user,
        "onboarding_step": max(4, _get_workspace_settings(ctx.workspace_id).get("onboarding_step", 0)),
    })
    return {"ok": True, "step": 4, "gmail_user": body.gmail_user}


@router.post("/step/5")
async def step5_import(
    body: Step5Import,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Step 5: Choose import mode (discovery or CSV upload)."""
    _update_workspace_settings(ctx.workspace_id, {
        "import_mode": body.mode,
        "onboarding_step": 5,
    })
    return {"ok": True, "step": 5, "mode": body.mode}


@router.post("/complete")
async def complete_onboarding(
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Mark onboarding as complete — unlocks the full dashboard."""
    _update_workspace_settings(ctx.workspace_id, {
        "onboarding_complete": True,
        "onboarding_step": 5,
    })
    logger.info("Onboarding complete for workspace %s", ctx.workspace_id)
    return {"ok": True, "onboarding_complete": True}


@router.get("/credentials")
async def list_credentials(
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Return credential metadata (hints only — no plaintext) for this workspace."""
    from backend.app.core.credential_store import CredentialStore
    store = CredentialStore(ctx.workspace_id)
    return {"credentials": store.list_providers()}


@router.delete("/credentials/{provider}/{key_name}")
async def delete_credential(
    provider: str,
    key_name: str,
    ctx: WorkspaceContext = Depends(require_workspace_member),
) -> dict[str, Any]:
    """Remove a stored credential (e.g. to replace with a new key)."""
    from backend.app.core.credential_store import CredentialStore
    CredentialStore(ctx.workspace_id).delete(provider, key_name)
    return {"ok": True}
