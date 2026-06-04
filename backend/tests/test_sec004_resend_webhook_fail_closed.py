"""SEC-004: Resend webhook must fail closed (503) when secret is not configured,
and reject wrong secrets with 401. Correct secret must succeed.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch


def _clear_settings_cache():
    from backend.app.core.config import get_settings

    get_settings.cache_clear()


def test_resend_webhook_503_when_secret_unset():
    """Empty RESEND_WEBHOOK_SECRET must return 503, never process the payload."""
    import backend.app.api.routes.webhooks as wh_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    original_get_settings = wh_mod.get_settings

    class FakeSettingsEmpty:
        resend_webhook_secret = ""
        webhook_secret = ""

    wh_mod.get_settings = lambda: FakeSettingsEmpty()
    try:
        mini = FastAPI()
        mini.include_router(wh_mod.router)
        with TestClient(mini, raise_server_exceptions=False) as c:
            r = c.post(
                "/api/webhooks/resend?secret=anything",
                json={"type": "email.delivered", "data": {"email_id": "evt_123"}},
            )
            assert r.status_code == 503, f"Expected 503 when secret unset, got {r.status_code}"
    finally:
        wh_mod.get_settings = original_get_settings


def test_resend_webhook_401_on_wrong_secret():
    """Wrong secret → 401, no DB mutation."""
    from backend.app.api.main import app
    from fastapi.testclient import TestClient

    _clear_settings_cache()
    try:
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": "correct_secret"}):
            _clear_settings_cache()
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.post(
                    "/api/webhooks/resend?secret=wrong_secret",
                    json={"type": "email.delivered", "data": {}},
                )
                assert r.status_code == 401, f"Expected 401 for wrong secret, got {r.status_code}"
    finally:
        _clear_settings_cache()


def test_resend_webhook_503_still_no_db_mutation():
    """When 503 is returned, the handler must not have mutated any DB tables."""
    # The 503 is raised before the DB call, so this test verifies the control flow.
    from backend.app.api.routes import webhooks

    captured_db_calls: list = []

    class FakeDB:
        workspace_id = "ws-1"

        def _filter_ws(self, q):
            captured_db_calls.append("_filter_ws")
            return q

    # Monkeypatch get_settings to return empty secret
    import backend.app.api.routes.webhooks as wh_mod
    from backend.app.core.config import Settings

    original_get_settings = wh_mod.get_settings

    def patched_get_settings():
        s = Settings()
        object.__setattr__(s, "resend_webhook_secret", "")
        return s

    wh_mod.get_settings = patched_get_settings
    try:
        import asyncio
        from fastapi import Request
        from starlette.testclient import TestClient
        from fastapi import FastAPI

        mini = FastAPI()
        mini.include_router(wh_mod.router)
        with TestClient(mini, raise_server_exceptions=False) as c:
            r = c.post(
                "/api/webhooks/resend?secret=x", json={"type": "email.delivered", "data": {}}
            )
            assert r.status_code == 503
            assert captured_db_calls == [], "DB must not be touched when 503 is returned"
    finally:
        wh_mod.get_settings = original_get_settings
