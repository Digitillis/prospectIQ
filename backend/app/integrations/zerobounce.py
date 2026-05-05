"""ZeroBounce Email Finder integration.

Used as a fallback enrichment path when Apollo People Match returns
no email for a contact. Requires a domain + first/last name.
Cost: 1 ZeroBounce credit per call.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

_FINDER_URL = "https://api.zerobounce.net/v2/guessformat"


class ZeroBounceClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_settings().zerobounce_api_key
        if not self.api_key:
            raise ValueError("ZEROBOUNCE_API_KEY is not set")

    def find_email(
        self,
        domain: str,
        first_name: str,
        last_name: str,
        timeout: int = 10,
    ) -> dict:
        """Call /v2/guessformat to find a likely email for a person at a domain.

        Returns a dict with at minimum:
          - email: str | None   — the guessed address (None if not found)
          - status: str         — e.g. "Valid", "Invalid", "Catch-All", "Unknown"
          - confidence: str     — e.g. "High", "Medium", "Low"
        """
        params = {
            "api_key": self.api_key,
            "domain": domain,
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
        }
        try:
            resp = requests.get(_FINDER_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning(f"ZeroBounce request failed: {exc}")
            return {"email": None, "status": "error", "confidence": "None"}

        # ZeroBounce returns an array of guesses sorted by confidence.
        # Pick the first one that is not Invalid/Abuse.
        guesses = data if isinstance(data, list) else [data]
        for guess in guesses:
            status = (guess.get("status") or "").lower()
            if status not in ("invalid", "abuse", "do_not_mail", "spamtrap"):
                return {
                    "email": guess.get("email"),
                    "status": guess.get("status", ""),
                    "confidence": guess.get("confidence", ""),
                }

        return {"email": None, "status": "not_found", "confidence": "None"}
