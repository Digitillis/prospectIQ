"""SEC-007: _get_fernet() must reject keys that are not exactly 44 base64url chars.

Short/padded keys must raise RuntimeError, not silently null-pad and accept.
A valid 44-char Fernet key must succeed.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch


def _clear_fernet_cache():
    # _get_fernet is not cached, but if there's any module-level state, clear it.
    pass


@pytest.mark.parametrize(
    "bad_key",
    [
        "a",
        "short",
        "a" * 16,
        "a" * 32,
        "a" * 43,
        "a" * 45,
    ],
)
def test_get_fernet_rejects_bad_key_length(bad_key):
    """Non-44-char keys must raise RuntimeError mentioning '44'."""
    from backend.app.core import credential_store

    with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": bad_key}):
        with pytest.raises(RuntimeError, match="44"):
            credential_store._get_fernet()


def test_get_fernet_rejects_empty_key():
    """Empty key must raise RuntimeError (unset, not wrong length)."""
    from backend.app.core import credential_store

    with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": ""}):
        with pytest.raises(RuntimeError):
            credential_store._get_fernet()


def test_get_fernet_accepts_valid_key():
    """A valid Fernet key (44 base64url chars) must succeed."""
    from cryptography.fernet import Fernet

    valid_key = Fernet.generate_key().decode()
    assert len(valid_key) == 44, (
        f"Fernet.generate_key() should produce 44 chars, got {len(valid_key)}"
    )

    from backend.app.core import credential_store

    with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": valid_key}):
        f = credential_store._get_fernet()
        assert f is not None


def test_old_null_pad_behaviour_is_gone():
    """The old code null-padded keys shorter than 44 chars. This must no longer work."""
    short_key = "short_key_12345678"
    assert len(short_key) < 44
    from backend.app.core import credential_store

    with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": short_key}):
        with pytest.raises(RuntimeError):
            credential_store._get_fernet()
