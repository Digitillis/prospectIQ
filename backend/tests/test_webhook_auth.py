"""Tests for the single-source webhook authentication helper.

verify_webhook() must enforce four properties consistently:
  1. Fail-closed (503) when the secret is not configured (default).
  2. Pass silently when unconfigured AND fail_closed=False (opt-in only).
  3. Reject (401) a wrong secret.
  4. Accept a correct secret.
The compare must be timing-safe (hmac.compare_digest), so a wrong secret
that shares a long prefix with the expected value is still rejected.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.core.webhook_auth import verify_webhook


def test_fails_closed_when_secret_not_configured():
    with pytest.raises(HTTPException) as exc:
        verify_webhook(None, None, endpoint="Test")
    assert exc.value.status_code == 503


def test_fails_closed_when_secret_empty_string():
    with pytest.raises(HTTPException) as exc:
        verify_webhook("anything", "", endpoint="Test")
    assert exc.value.status_code == 503


def test_passes_when_unconfigured_and_fail_closed_false():
    # Must not raise — genuinely optional webhook with no secret configured.
    verify_webhook(None, None, endpoint="Test", fail_closed=False)


def test_rejects_wrong_secret():
    with pytest.raises(HTTPException) as exc:
        verify_webhook("wrong", "correct", endpoint="Test")
    assert exc.value.status_code == 401


def test_rejects_missing_provided_when_expected_configured():
    with pytest.raises(HTTPException) as exc:
        verify_webhook(None, "correct", endpoint="Test")
    assert exc.value.status_code == 401


def test_accepts_correct_secret():
    # Must not raise.
    verify_webhook("correct", "correct", endpoint="Test")


def test_timing_safe_compare_rejects_prefix_match():
    # Secrets share a long prefix but differ at the last byte — must still reject.
    with pytest.raises(HTTPException) as exc:
        verify_webhook("aaaaaaaaaaaab", "aaaaaaaaaaaac", endpoint="Test")
    assert exc.value.status_code == 401


def test_error_message_includes_endpoint_name():
    with pytest.raises(HTTPException) as exc:
        verify_webhook("wrong", "correct", endpoint="Resend")
    assert "Resend" in exc.value.detail
