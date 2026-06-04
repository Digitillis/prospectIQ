"""Single-source webhook authentication helper.

Every webhook handler in the platform MUST use verify_webhook() for
signature/secret checking. Direct hmac.compare_digest calls in route
handlers are a code-smell — the properties (fail-closed when unconfigured,
timing-safe compare, structured error) must be applied consistently.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def verify_webhook(
    provided: str | None,
    expected: str | None,
    *,
    endpoint: str,
    fail_closed: bool = True,
) -> None:
    """Verify a webhook secret or signature. Raises HTTPException on failure.

    Args:
        provided:   The secret/signature from the request (query param or header).
        expected:   The configured secret (from settings). None = not configured.
        endpoint:   Human-readable name for error messages (e.g. "Resend").
        fail_closed: True (default) = raise 503 when expected is not configured.
                     False = silently pass when unconfigured (use only for
                     genuinely optional webhooks with an explicit comment).
    """
    if not expected:
        if fail_closed:
            logger.warning("verify_webhook: %s secret not configured — rejecting", endpoint)
            raise HTTPException(
                status_code=503, detail=f"{endpoint} webhook endpoint not configured"
            )
        logger.debug(
            "verify_webhook: %s secret not configured — passing (fail_closed=False)", endpoint
        )
        return
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail=f"Invalid {endpoint} webhook signature")
