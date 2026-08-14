"""One-click unsubscribe (CAN-SPAM / RFC 8058).

Public, unauthenticated by design — the recipient clicking the link in an
email has no ProspectIQ account. Two entry points:

  GET  /api/unsubscribe   — the link a human clicks. Renders a CONFIRMATION
                             page and takes NO action — see below for why.
  POST /api/unsubscribe   — the action. Records the unsubscribe. Reached two
                             ways: (a) the confirm button on the GET page
                             submitting a form, or (b) RFC 8058's One-Click
                             target for the List-Unsubscribe-Post header,
                             which mail clients call automatically.

GET must not mutate state. Corporate email security gateways (Microsoft
Defender/Safe Links, Proofpoint URL Defense, Mimecast) and some mail clients
automatically GET-fetch every link in an inbound email to scan it for
phishing/malware, BEFORE the human recipient ever opens the message. A
valid, real unsubscribe link — exactly the one in the real email — gets
fetched by the security scanner's GET request, carrying a genuinely valid
token. If GET recorded the unsubscribe, that scan would silently unsubscribe
the recipient with zero human intent involved, for any organization running
standard corporate email security. This is precisely the failure mode RFC
8058 introduced List-Unsubscribe-Post to prevent: scanners only ever GET,
never POST, so making POST the sole action-taking method is what makes the
protection real rather than nominal.

do_not_contact has no workspace_id column (see supabase_migrations/
migrations/003_dnc_priority_queue.sql) — it is a global suppression list, so
this route needs no workspace context, unlike almost every other route in
this API.
"""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from backend.app.core.database import Database
from backend.app.core.unsubscribe import UnsubscribeConfigError, record_unsubscribe, verify_unsubscribe_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/unsubscribe", tags=["unsubscribe"])

_CONFIRM_HTML = """<!DOCTYPE html>
<html><head><title>Confirm unsubscribe</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto; text-align: center;">
<h2>Unsubscribe {email}?</h2>
<p>Click below to confirm you no longer want to receive emails from us.</p>
<form method="POST" action="/api/unsubscribe?email={email_q}&draft_id={draft_id_q}&token={token_q}">
<button type="submit" style="font-size: 1rem; padding: 0.6rem 1.2rem; cursor: pointer;">
Confirm unsubscribe
</button>
</form>
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
    """Renders a confirmation page. Takes NO action — see module docstring
    for why GET must not mutate state. A security scanner or mail-preview
    prefetch hitting this endpoint does nothing but render HTML.
    """
    try:
        valid = _verify(email, draft_id, token)
    except HTTPException:
        return HTMLResponse(_INVALID_HTML, status_code=503)

    if not valid:
        return HTMLResponse(_INVALID_HTML, status_code=400)

    from urllib.parse import quote

    # email is unvalidated, scraped/imported contact data (no EmailStr/regex
    # enforcement anywhere on contacts.email) rendered into an HTML response
    # on a public, unauthenticated route — must be escaped for the HTML
    # display context. email_q/draft_id_q/token_q are separately
    # URL-encoded via quote() for the query-string context in the form
    # action; HTML-escaping and URL-encoding are not interchangeable and
    # both are required here for their respective contexts.
    return HTMLResponse(
        _CONFIRM_HTML.format(
            email=html.escape(email),
            email_q=quote(email),
            draft_id_q=quote(draft_id),
            token_q=quote(token),
        )
    )


@router.post("", response_class=PlainTextResponse)
async def unsubscribe_post(
    email: str = Query(...),
    draft_id: str = Query(...),
    token: str = Query(...),
) -> PlainTextResponse:
    """The action-taking endpoint. Reached two ways:

      1. RFC 8058 One-Click: mail clients (Gmail, Outlook, Apple Mail) call
         this automatically when the recipient clicks their native
         "Unsubscribe" affordance — no page render, no redirect, just a 2xx.
      2. The confirm button on the GET page's form submission — also lands
         here, also gets a bare "OK" response rather than a fancier
         confirmation page, which is an acceptable trade-off for keeping
         exactly one action-taking code path rather than two.
    """
    if not _verify(email, draft_id, token):
        raise HTTPException(status_code=400, detail="Invalid or tampered unsubscribe token")
    db = Database(workspace_id=None)
    record_unsubscribe(db.client, email=email, draft_id=draft_id, source="one_click_post")
    return PlainTextResponse("OK", status_code=200)
