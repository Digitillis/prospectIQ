"""Unit tests for scripts/warm_reply_reconcile.py — the WARM reply reconciler.

These tests exercise the PURE logic only (sentiment heuristic, From-address parsing,
msgid dedup decision, and the warm!=cold workspace guard). They never open a live IMAP
connection and never touch the database, so they pass in CI without any credentials —
mirroring the skip-cleanly posture of test_warm_isolation.py.
"""

from __future__ import annotations

import importlib

import pytest

from backend.app.core import config as config_module

# Import the script as a module. It lives under scripts/ (no package), so load it by path.
recon = importlib.import_module("scripts.warm_reply_reconcile")


# ---------------------------------------------------------------------------
# Sentiment heuristic (keyword-only, not an LLM)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Happy to chat next week, let's find time on my calendar", "positive"),
        ("Sure, I'm available Thursday", "positive"),
        ("Sounds good, interested to learn more", "positive"),
        ("Not interested, please remove me", "negative"),
        ("No thanks, unsubscribe", "negative"),
        ("Please stop emailing me", "negative"),
        ("Thanks for the note, I'll think about it", "neutral"),
        ("", "neutral"),
    ],
)
def test_heuristic_sentiment(text, expected):
    assert recon.heuristic_sentiment(text) == expected


def test_negative_wins_over_positive():
    # An opt-out that also contains a positive token must read as negative.
    assert recon.heuristic_sentiment("I'd be happy to, but please remove me") == "negative"


# ---------------------------------------------------------------------------
# From-address normalization / parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Dana Whitfield <Dana@AcmeCast.com>", "dana@acmecast.com"),
        ("dana@acmecast.com", "dana@acmecast.com"),
        ('"Whitfield, Dana" <DANA@acmecast.com>', "dana@acmecast.com"),
        ("  Spaced <user@x.io>  ", "user@x.io"),
        ("", ""),
    ],
)
def test_parse_from_address(header, expected):
    assert recon.parse_from_address(header) == expected


# ---------------------------------------------------------------------------
# msgid dedup decision
# ---------------------------------------------------------------------------


def test_msgid_dedup_dict_tags():
    existing = [{"tags": {"msgid": "<abc@mail>"}}]
    assert recon.msgid_already_logged(existing, "<abc@mail>") is True
    assert recon.msgid_already_logged(existing, "<new@mail>") is False


def test_msgid_dedup_list_tags():
    existing = [{"tags": ["warm", "<xyz@mail>"]}]
    assert recon.msgid_already_logged(existing, "<xyz@mail>") is True
    assert recon.msgid_already_logged(existing, "<other@mail>") is False


def test_msgid_dedup_empty_inputs():
    # No prior events → not a duplicate.
    assert recon.msgid_already_logged([], "<abc@mail>") is False
    # Empty msgid is not loggable idempotently → treated as already-logged (skip).
    assert recon.msgid_already_logged([{"tags": {"msgid": "<x>"}}], "") is True


def test_build_event_payload_carries_msgid_and_warm_fields():
    contact = {"id": "c1", "company_id": "co1", "full_name": "Dana"}
    msg = {"subject": "Re: hi", "body": "b" * 5000, "message_id": "<m@x>"}
    payload = recon.build_event_payload(contact, msg, "positive")
    assert payload["event_type"] == "response_received"
    assert payload["channel"] == "email"
    assert payload["direction"] == "inbound"
    assert payload["created_by"] == "system"
    assert payload["tags"]["msgid"] == "<m@x>"
    assert len(payload["body"]) == 2000  # truncated to ~2000 chars


# ---------------------------------------------------------------------------
# Workspace guard — must REFUSE to run when warm == cold
# ---------------------------------------------------------------------------


def test_resolve_workspaces_refuses_when_warm_equals_cold(monkeypatch):
    """If warm_workspace_id == default_workspace_id, the script must exit nonzero."""

    class _FakeSettings:
        warm_workspace_id = "00000000-0000-0000-0000-000000000001"
        default_workspace_id = "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(recon, "get_settings", lambda: _FakeSettings())
    with pytest.raises(SystemExit) as exc:
        recon.resolve_workspaces()
    assert exc.value.code != 0


def test_resolve_workspaces_refuses_when_warm_unset(monkeypatch):
    class _FakeSettings:
        warm_workspace_id = ""
        default_workspace_id = "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(recon, "get_settings", lambda: _FakeSettings())
    with pytest.raises(SystemExit):
        recon.resolve_workspaces()


def test_resolve_workspaces_ok_when_distinct(monkeypatch):
    class _FakeSettings:
        warm_workspace_id = "00000000-0000-0000-0000-000000000002"
        default_workspace_id = "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(recon, "get_settings", lambda: _FakeSettings())
    ws, cold = recon.resolve_workspaces()
    assert ws == "00000000-0000-0000-0000-000000000002"
    assert cold == "00000000-0000-0000-0000-000000000001"
    assert ws != cold


def test_real_default_settings_keep_warm_distinct():
    # Sanity: the shipped config keeps warm and cold distinct.
    s = config_module.get_settings()
    if not s.warm_workspace_id:
        pytest.skip("warm_workspace_id not set in this environment")
    assert s.warm_workspace_id != s.default_workspace_id
