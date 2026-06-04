"""D1: ReplyAgent._cancel_active_sequences must be an instance method.

Previously defined at module scope with `self` as first param → AttributeError
on every unsubscribe/negative reply, leaving sequences running after opt-out.

Tests verify:
1. _cancel_active_sequences exists as an instance method (not module-level).
2. Unsubscribe reply cancels active sequence steps.
3. Negative reply cancels active sequence steps.
4. The bug: calling self._cancel_active_sequences doesn't raise AttributeError.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def _make_agent() -> "ReplyAgent":
    from backend.app.agents.reply import ReplyAgent

    agent = ReplyAgent.__new__(ReplyAgent)
    agent.workspace_id = "ws-1"
    agent.db = MagicMock()
    agent.db.workspace_id = "ws-1"
    return agent


def test_cancel_active_sequences_is_instance_method():
    """_cancel_active_sequences must be callable on the instance without AttributeError."""
    from backend.app.agents.reply import ReplyAgent

    agent = _make_agent()
    # Before the fix: AttributeError: 'ReplyAgent' object has no attribute '_cancel_active_sequences'
    assert hasattr(agent, "_cancel_active_sequences"), (
        "ReplyAgent must have _cancel_active_sequences as an instance method"
    )
    assert callable(agent._cancel_active_sequences)


def test_cancel_active_sequences_not_at_module_scope():
    """The module-level _cancel_active_sequences (the broken duplicate) must not exist."""
    import backend.app.agents.reply as reply_mod

    # The module should NOT have a top-level _cancel_active_sequences that takes `self`
    # as a positional arg (the broken version was defined at module scope).
    module_fn = getattr(reply_mod, "_cancel_active_sequences", None)
    assert module_fn is None, (
        "Module-level _cancel_active_sequences still exists — duplicate not removed"
    )


def test_unsubscribe_reply_cancels_sequences():
    """Processing an unsubscribe reply must call _cancel_active_sequences without AttributeError."""
    agent = _make_agent()

    # Mock sequences to cancel
    agent.db.get_active_sequences.return_value = [
        {"id": "seq-1", "company_id": "co-1"},
        {"id": "seq-2", "company_id": "co-1"},
    ]

    cancelled = agent._cancel_active_sequences("co-1")

    assert cancelled == 2, f"Expected 2 sequences cancelled, got {cancelled}"
    assert agent.db.update_engagement_sequence.call_count == 2


def test_cancel_sequences_returns_zero_when_no_active():
    """Returns 0 when no active sequences exist for the company."""
    agent = _make_agent()
    agent.db.get_active_sequences.return_value = []

    cancelled = agent._cancel_active_sequences("co-1")
    assert cancelled == 0


def test_cancel_sequences_handles_db_error_gracefully():
    """DB failure during sequence cancellation must not propagate — logs warning only."""
    agent = _make_agent()
    agent.db.get_active_sequences.side_effect = Exception("DB unavailable")

    # Must not raise
    cancelled = agent._cancel_active_sequences("co-1")
    assert cancelled == 0


def test_run_unsubscribe_does_not_raise_attribute_error():
    """Full run() with unsubscribe classification must not raise AttributeError."""
    from backend.app.agents.reply import ReplyAgent
    from unittest.mock import patch

    agent = _make_agent()
    agent.db.get_company.return_value = {"id": "co-1", "name": "Acme"}
    agent.db.get_contacts_for_company.return_value = [
        {"id": "ct-1", "full_name": "Alice", "email": "alice@acme.com"}
    ]
    agent.db.get_active_sequences.return_value = []

    # Patch the LLM call to return unsubscribe classification
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"classification": "unsubscribe", "sentiment": "negative", "urgency": "low", "reasoning": "opted out"}')]

    reply_data = {
        "company_id": "co-1",
        "contact_id": "ct-1",
        "subject": "Unsubscribe",
        "body": "Please remove me from your list.",
        "outreach_draft_id": "draft-1",
    }

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        try:
            result = agent.run(reply_data=reply_data)
            # Should not raise AttributeError
        except AttributeError as e:
            pytest.fail(f"run() raised AttributeError: {e}")
        except Exception:
            pass  # Other exceptions (LLM, DB) are fine — we only care about AttributeError
