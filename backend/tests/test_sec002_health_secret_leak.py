"""SEC-002: /health must not expose any portion of RESEND_WEBHOOK_SECRET."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch


def _clear_settings_cache():
    from backend.app.core.config import get_settings

    get_settings.cache_clear()


def test_health_does_not_leak_secret():
    """GET /health must not include any substring of the secret in its body."""
    from backend.app.api.main import app
    from fastapi.testclient import TestClient

    secret = "wh_sec_test12345678"
    _clear_settings_cache()
    try:
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": secret}):
            _clear_settings_cache()
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/health")
                assert r.status_code == 200
                body = r.text
                # The secret itself must not appear anywhere in the response body
                assert secret not in body, f"Secret leaked in /health response: {body}"
                # Even a prefix of the secret must not appear
                assert secret[:8] not in body, f"Secret prefix leaked in /health response: {body}"
                # Boolean indicator is fine
                assert "resend_webhook_secret_set" in body
    finally:
        _clear_settings_cache()


def test_health_shows_secret_set_bool():
    """GET /health reports resend_webhook_secret_set as a boolean flag only."""
    from backend.app.api.main import app
    from fastapi.testclient import TestClient

    _clear_settings_cache()
    try:
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": "some_secret"}):
            _clear_settings_cache()
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/health")
                data = r.json()
                assert data["resend_webhook_secret_set"] is True
                assert "resend_webhook_secret_preview" not in data, (
                    "resend_webhook_secret_preview must not be present in health response"
                )
    finally:
        _clear_settings_cache()
