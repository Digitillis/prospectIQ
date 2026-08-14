"""A failure writing to reply_classifications must be logged, not silently
discarded.

reply_classifications had 0 rows in production despite classify_reply()
having genuinely run at least once (confirmed live: a paired interactions
row from its caller, ReplyAgent, exists with no corresponding
reply_classifications row). The insert was wrapped in a bare
`except Exception: pass` -- no variable, no log call -- so there was no way
to tell whether the one real invocation's insert failed, or never reached
that line at all. See backend/app/agents/reply_classifier.py.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


def _make_anthropic_mock(response_json: dict):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(response_json))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


class _FakeTable:
    """Routes by table name. reply_classifications.insert() raises; every
    other table returns an empty/no-op result so downstream handlers
    (_update_outcome, wrong_person/unsubscribe/not_a_fit) no-op cleanly
    rather than needing their own fakes for this test's purpose.
    """

    def __init__(self, name: str, raise_on_insert: bool):
        self._name = name
        self._raise_on_insert = raise_on_insert

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def delete(self, *a, **k):
        return self

    def insert(self, *a, **k):
        if self._name == "reply_classifications" and self._raise_on_insert:
            raise RuntimeError("simulated insert failure (e.g. constraint violation)")
        return self

    def execute(self):
        result = MagicMock()
        result.data = []
        return result


class _FakeDB:
    def __init__(self, raise_on_insert: bool = True):
        self._raise_on_insert = raise_on_insert
        self.client = MagicMock()
        self.client.table.side_effect = lambda name: _FakeTable(name, self._raise_on_insert)
        self.workspace_id = "ws-1"


def test_insert_failure_is_logged_not_swallowed(caplog):
    from backend.app.agents.reply_classifier import ReplyClassifierAgent

    db = _FakeDB(raise_on_insert=True)
    agent = ReplyClassifierAgent(db)

    with (
        patch(
            "anthropic.Anthropic",
            return_value=_make_anthropic_mock(
                {
                    "sentiment": "neutral",
                    "intent": "other",
                    "wrong_person_flag": False,
                    "key_objection": None,
                    "confidence": 0.5,
                    "reasoning": "test",
                }
            ),
        ),
        patch("backend.app.core.config.get_settings") as mock_settings,
        patch(
            "backend.app.core.config.get_outreach_guidelines",
            return_value={"sender": {"name": "Test", "company": "Acme"}},
        ),
        caplog.at_level(logging.ERROR),
    ):
        mock_settings.return_value.anthropic_api_key = "test-key"
        result = agent.classify_reply(
            reply_text="Not interested, thanks.",
            contact_id="contact-1",
            company_id="company-1",
        )

    # The failure must appear in logs at ERROR level, not vanish silently.
    assert any(
        "reply_classifications insert failed" in r.message and "contact-1" in r.message
        for r in caplog.records
    )
    # And it must be non-fatal: classify_reply() still returns a real result
    # rather than raising out to the caller (ReplyAgent's own try/except
    # exists for genuine failures, not to mask this one).
    assert result["intent"] == "other"


def test_insert_success_produces_no_error_log(caplog):
    """Sanity check: the fix doesn't make the happy path noisy."""
    from backend.app.agents.reply_classifier import ReplyClassifierAgent

    db = _FakeDB(raise_on_insert=False)
    agent = ReplyClassifierAgent(db)

    with (
        patch(
            "anthropic.Anthropic",
            return_value=_make_anthropic_mock(
                {
                    "sentiment": "neutral",
                    "intent": "other",
                    "wrong_person_flag": False,
                    "key_objection": None,
                    "confidence": 0.5,
                    "reasoning": "test",
                }
            ),
        ),
        patch("backend.app.core.config.get_settings") as mock_settings,
        patch(
            "backend.app.core.config.get_outreach_guidelines",
            return_value={"sender": {"name": "Test", "company": "Acme"}},
        ),
        caplog.at_level(logging.ERROR),
    ):
        mock_settings.return_value.anthropic_api_key = "test-key"
        agent.classify_reply(
            reply_text="Not interested, thanks.",
            contact_id="contact-1",
            company_id="company-1",
        )

    assert not any("reply_classifications insert failed" in r.message for r in caplog.records)
