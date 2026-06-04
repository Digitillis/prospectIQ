"""SEC-005: WorkspaceMiddleware must refuse to trust unsigned JWTs when
SUPABASE_JWT_SECRET is not configured. A crafted unsigned JWT with a real
user's sub must NOT result in workspace context being set.
"""

from __future__ import annotations

import base64
import json
import os
import pytest
from unittest.mock import patch


def _make_unsigned_jwt(sub: str) -> str:
    """Craft a base64url-encoded unsigned JWT with the given sub claim."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "email": "evil@example.com"}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}."


def _clear_settings_cache():
    from backend.app.core.config import get_settings
    get_settings.cache_clear()


def test_unsigned_jwt_does_not_set_workspace():
    """When SUPABASE_JWT_SECRET is unset, a crafted unsigned JWT must not populate WorkspaceContext."""
    from backend.app.core.workspace_middleware import WorkspaceMiddleware

    mw = WorkspaceMiddleware(app=None)
    token = _make_unsigned_jwt("real-user-id-123")

    _clear_settings_cache()
    try:
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": ""}):
            _clear_settings_cache()
            result = mw._workspace_from_jwt(token)
            assert result is None, (
                f"Expected None when JWT secret unset, got workspace_id={result!r}. "
                "An unverified JWT must never resolve to a workspace."
            )
    finally:
        _clear_settings_cache()


def test_unsigned_jwt_would_have_succeeded_without_fix():
    """Verify the test logic: the unsigned JWT does parse without verification.

    This confirms the test is meaningful — the old code path (verify_signature=False)
    would have extracted the sub and looked up the workspace.
    """
    import jwt as pyjwt
    token = _make_unsigned_jwt("real-user-id-123")
    decoded = pyjwt.decode(token, options={"verify_signature": False})
    assert decoded["sub"] == "real-user-id-123", "JWT decoding without verification should work"
