"""SEC-001: All five admin endpoints must require authentication.

Tests:
- No auth → 401/403 on all five endpoints
- Valid stub user → 200 (dependency override)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


def _make_client_no_auth():
    """Return a TestClient with no auth override (anonymous caller)."""
    from backend.app.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _make_client_authed():
    """Return a TestClient with get_current_user stubbed to a valid user."""
    from backend.app.api.main import app
    from backend.app.core.auth import get_current_user

    async def _stub_user(request=None):
        return {
            "user_id": "test-user",
            "email": "test@example.com",
            "workspace_id": "ws-1",
            "auth_method": "bearer",
        }

    app.dependency_overrides[get_current_user] = _stub_user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/send-config"),
    ("GET", "/api/admin/send-trace"),
    ("POST", "/api/admin/trigger-send"),
    ("GET", "/api/prospectiq/admin/cadence-velocity"),
    ("GET", "/api/prospectiq/admin/metrics"),
]


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoint_no_auth_returns_401(method, path):
    """Anonymous callers must receive 401/403 on every admin endpoint."""
    from backend.app.api.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = getattr(client, method.lower())(path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code}, expected 401/403 for unauthenticated request"
        )


def test_send_config_authed_ok():
    """Authenticated caller gets a response (not 401/403) from send-config."""
    from backend.app.api.main import app
    from backend.app.core.auth import get_current_user

    async def _stub(request=None):
        return {
            "user_id": "u1",
            "email": "a@b.com",
            "workspace_id": "ws-1",
            "auth_method": "bearer",
        }

    app.dependency_overrides[get_current_user] = _stub
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/admin/send-config")
            assert r.status_code not in (401, 403), f"Expected success, got {r.status_code}"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
