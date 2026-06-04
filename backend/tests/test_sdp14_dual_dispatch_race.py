"""SDP#14: _send_approved_drafts is retired and must not send emails.

The method is a hard-guarded stub. Calling it must return immediately with
an error result and zero sends — it must never call Resend.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_send_approved_drafts_is_retired():
    """_send_approved_drafts must return immediately with errors=1 and processed=0."""
    from backend.app.agents.engagement import EngagementAgent

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"

    # Capture any Resend calls
    resend_calls: list = []

    with patch("resend.Emails.send", side_effect=lambda *a, **kw: resend_calls.append((a, kw))):
        result = agent._send_approved_drafts()

    assert result.processed == 0, (
        f"Retired _send_approved_drafts must not send anything, but processed={result.processed}"
    )
    assert result.errors > 0, (
        "Retired _send_approved_drafts must report errors to signal misuse"
    )
    assert len(resend_calls) == 0, (
        f"Retired _send_approved_drafts called Resend {len(resend_calls)} time(s)"
    )


def test_send_approved_drafts_does_not_call_resend_even_with_send_enabled():
    """Even when SEND_ENABLED=true, the retired path must not reach Resend."""
    from backend.app.agents.engagement import EngagementAgent
    import os

    agent = EngagementAgent.__new__(EngagementAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"

    resend_calls: list = []

    with patch.dict(os.environ, {"SEND_ENABLED": "true"}), \
         patch("resend.Emails.send", side_effect=lambda *a, **kw: resend_calls.append(True)):
        result = agent._send_approved_drafts(campaign_name="test", draft_ids=["d1", "d2"])

    assert len(resend_calls) == 0, (
        "Retired path must not reach Resend regardless of SEND_ENABLED"
    )
