"""Per-workspace encrypted credential storage.

Credentials (Apollo API key, Resend key, Gmail password, etc.) are stored
encrypted in the workspace_credentials table. The encryption key lives only
in the CREDENTIAL_ENCRYPTION_KEY environment variable — never in the DB.

Usage:
    store = CredentialStore(workspace_id)
    store.set("apollo", "api_key", "apk_...")
    key = store.get("apollo", "api_key")          # returns plaintext or None
    store.delete("apollo", "api_key")
    all_creds = store.list_providers()            # [{"provider": "apollo", ...}]

Fallback:
    When workspace_id is None or the credential is not found, get() falls back
    to the corresponding environment variable so the existing single-tenant
    pipeline keeps working without any migration.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encryption helpers (Fernet / AES-128-CBC with HMAC-SHA256)
# ---------------------------------------------------------------------------

def _get_fernet():
    """Return a Fernet instance using CREDENTIAL_ENCRYPTION_KEY env var."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError(
            "cryptography package required for credential storage. "
            "Run: pip install cryptography"
        )
    raw = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY env var is not set")
    # Accept raw key or base64url-encoded key
    try:
        key = raw.encode() if len(raw) == 44 else base64.urlsafe_b64encode(raw.encode()[:32].ljust(32, b'\0'))
        return Fernet(key)
    except Exception:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key (44 base64url chars)")


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# Environment variable fallbacks — single-tenant backward compat
# ---------------------------------------------------------------------------

_ENV_FALLBACKS: dict[tuple[str, str], str] = {
    ("apollo",      "api_key"):       "APOLLO_API_KEY",
    ("resend",      "api_key"):       "RESEND_API_KEY",
    ("gmail",       "app_password"):  "GMAIL_APP_PASSWORD",
    ("gmail",       "user"):          "GMAIL_USER",
    ("perplexity",  "api_key"):       "PERPLEXITY_API_KEY",
    ("anthropic",   "api_key"):       "ANTHROPIC_API_KEY",
    ("stripe",      "secret_key"):    "STRIPE_SECRET_KEY",
    ("stripe",      "webhook_secret"):"STRIPE_WEBHOOK_SECRET",
}


def _env_fallback(provider: str, key_name: str) -> str | None:
    env_var = _ENV_FALLBACKS.get((provider, key_name))
    return os.environ.get(env_var) if env_var else None


# ---------------------------------------------------------------------------
# CredentialStore
# ---------------------------------------------------------------------------

class CredentialStore:
    """Read/write credentials for a specific workspace."""

    def __init__(self, workspace_id: str | None = None):
        self.workspace_id = workspace_id

    def _client(self):
        from backend.app.core.database import get_supabase_client
        return get_supabase_client()

    def get(self, provider: str, key_name: str) -> str | None:
        """Return plaintext credential, or None if not found.

        Falls back to environment variable when workspace_id is unset
        or the credential has not been configured yet.
        """
        if self.workspace_id:
            try:
                row = (
                    self._client()
                    .table("workspace_credentials")
                    .select("ciphertext")
                    .eq("workspace_id", self.workspace_id)
                    .eq("provider", provider)
                    .eq("key_name", key_name)
                    .limit(1)
                    .execute()
                ).data
                if row:
                    return _decrypt(row[0]["ciphertext"])
            except Exception as exc:
                logger.warning("CredentialStore.get failed for %s/%s: %s", provider, key_name, exc)

        # Fall back to env var (single-tenant / unconfigured workspace)
        return _env_fallback(provider, key_name)

    def set(self, provider: str, key_name: str, plaintext: str) -> None:
        """Encrypt and store a credential for this workspace."""
        if not self.workspace_id:
            raise ValueError("workspace_id required to store credentials")
        ciphertext = _encrypt(plaintext)
        hint = plaintext[-4:] if len(plaintext) >= 4 else "****"
        self._client().table("workspace_credentials").upsert({
            "workspace_id": self.workspace_id,
            "provider": provider,
            "key_name": key_name,
            "ciphertext": ciphertext,
            "hint": hint,
        }, on_conflict="workspace_id,provider,key_name").execute()

    def delete(self, provider: str, key_name: str) -> None:
        """Remove a credential."""
        if not self.workspace_id:
            return
        self._client().table("workspace_credentials").delete().eq(
            "workspace_id", self.workspace_id
        ).eq("provider", provider).eq("key_name", key_name).execute()

    def list_providers(self) -> list[dict[str, Any]]:
        """Return stored credential metadata (no plaintext) for this workspace."""
        if not self.workspace_id:
            return []
        rows = (
            self._client()
            .table("workspace_credentials")
            .select("provider,key_name,hint,updated_at")
            .eq("workspace_id", self.workspace_id)
            .execute()
        ).data or []
        return rows

    def has(self, provider: str, key_name: str) -> bool:
        """Return True if credential exists in DB or env fallback."""
        return self.get(provider, key_name) is not None


# ---------------------------------------------------------------------------
# Module-level convenience — resolves workspace from context automatically
# ---------------------------------------------------------------------------

def get_credential(provider: str, key_name: str, workspace_id: str | None = None) -> str | None:
    """Return plaintext credential for the current (or given) workspace.

    Resolves workspace_id from WorkspaceContext if not provided.
    Falls back to environment variables if credential not in DB.
    """
    if workspace_id is None:
        try:
            from backend.app.core.workspace import get_workspace_id
            workspace_id = get_workspace_id()
        except Exception:
            pass
    return CredentialStore(workspace_id).get(provider, key_name)
