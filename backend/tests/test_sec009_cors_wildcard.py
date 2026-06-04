"""SEC-009: CORS must not echo arbitrary *.vercel.app or *.netlify.app origins.
Only localhost and *.digitillis.com origins should be echoed with credentials.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    from backend.app.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.vercel.app",
        "https://attack.netlify.app",
        "https://not-us.vercel.app",
    ],
)
def test_hostile_origin_not_echoed(origin):
    """Preflight from a hostile origin must not receive an echoed allow-origin."""
    with _client() as c:
        r = c.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin", "")
        assert allow_origin != origin, (
            f"CORS wildcard: {origin} should NOT be echoed, but Access-Control-Allow-Origin={allow_origin!r}"
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "https://app.digitillis.com",
        "https://dashboard.digitillis.com",
    ],
)
def test_allowed_origin_echoed(origin):
    """Trusted origins must receive the echoed allow-origin header."""
    with _client() as c:
        r = c.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin", "")
        assert allow_origin == origin, (
            f"Expected origin {origin!r} to be echoed, got {allow_origin!r}"
        )
