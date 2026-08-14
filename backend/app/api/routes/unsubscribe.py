"""One-click unsubscribe (CAN-SPAM / RFC 8058).

Public, unauthenticated by design — the recipient clicking the link in an
email has no ProspectIQ account. Two entry points:

  GET  /api/unsubscribe   — the link a human clicks; returns a confirmation page
  POST /api/unsubscribe   — RFC 8058 One-Click target for the
                             List-Unsubscribe-Post header; mail clients call
                             this automatically with no user interaction and
                             expect a bare 2xx, not a redirect or HTML body

do_not_contact has no workspace_id column (see supabase_migrations/
migrations/003_dnc_priority_queue.sql) — it is a global suppression list, so
this route needs no workspace context, unlike almost every other route in
this API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from backend.app.core.database import Database
from backend.app.core.unsubscribe import UnsubscribeConfigError, record_unsubscribe, verify_unsubscribe_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/unsubscribe", tags=["unsubscribe"])

_CONFIRMATION_HTML = """<!DOCTYPE html>
<html><head><title>Unsubscribed</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto; text-align: center;">
<h2>You've been unsubscribed</h2>
<p>{email} will not receive further emails from us. If this was a mistake,
reply to any prior email and we'll remove you from the suppression list.</p>
</body></html>"""

_INVALID_HTML = """<!DOCTYPE html>
<html><head><title>Invalid unsubscribe link</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto; text-align: center;">
<h2>This unsubscribe link is invalid or has expired</h2>
<p>If you no longer wish to receive emails, reply to any prior message and
we'll remove you manually.</p>
</body></html>"""


def _verify(email: str, draft_id: str, token: str) -> bool:
    """Returns True/False; raises HTTPException(503) only when the signing
    secret itself is unconfigured — a real invalid/tampered token is a
    normal False, not an error, so callers can render an honest page for it
    without leaking whether the (email, draft_id) pair exists.
    """
    try:
        return verify_unsubscribe_token(email, draft_id, token)
    except UnsubscribeConfigError:
        logger.error("unsubscribe.config_error — WEBHOOK_SECRET not set, cannot verify token")
        raise HTTPException(status_code=503, detail="Unsubscribe service temporarily unavailable")


@router.get("", response_class=HTMLResponse)
async def unsubscribe_get(
    email: str = Query(...),
    draft_id: str = Query(...),
    token: str = Query(...),
) -> HTMLResponse:
    """The link a human clicks from the email footer or mail client's
    unsubscribe UI.
    """
    try:
        valid = _verify(email, draft_id, token)
    except HTTPException:
        return HTMLResponse(_INVALID_HTML, status_code=503)

    if not valid:
        return HTMLResponse(_INVALID_HTML, status_code=400)

    db = Database(workspace_id=None)
    record_unsubscribe(db.client, email=email, draft_id=draft_id, source="one_click_get")
    return HTMLResponse(_CONFIRMATION_HTML.format(email=email))


@router.post("", response_class=PlainTextResponse)
async def unsubscribe_post(
    email: str = Query(...),
    draft_id: str = Query(...),
    token: str = Query(...),
) -> PlainTextResponse:
    """RFC 8058 One-Click target. Mail clients (Gmail, Outlook, Apple Mail)
    call this automatically when the recipient clicks their native
    "Unsubscribe" affordance — no page render, no redirect, just a 2xx.
    """
    if not _verify(email, draft_id, token):
        raise HTTPException(status_code=400, detail="Invalid or tampered unsubscribe token")
    db = Database(workspace_id=None)
    record_unsubscribe(db.client, email=email, draft_id=draft_id, source="one_click_post")
    return PlainTextResponse("OK", status_code=200)
