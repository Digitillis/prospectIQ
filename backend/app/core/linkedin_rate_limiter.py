"""LinkedIn rate limiter — DB-backed token bucket per workspace per day.

LinkedIn enforces soft limits that get accounts restricted when exceeded:
  - Connection requests: ~20/day (enforced here)
  - Direct messages: ~50/day (enforced here)

All limits reset at midnight UTC.

Usage:
    limiter = LinkedInRateLimiter(db, workspace_id)
    if limiter.can_send("linkedin_connect"):
        limiter.consume("linkedin_connect")
        # ... send the connection request
    else:
        remaining_until = limiter.reset_time("linkedin_connect")
        logger.warning(f"LinkedIn daily connect limit reached. Resets at {remaining_until}")
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

# Default daily limits — conservative to stay within LinkedIn's informal safety thresholds
_DEFAULT_LIMITS: dict[str, int] = {
    "linkedin_connect": 20,
    "linkedin_dm": 50,
    "email": 500,
}


class LinkedInRateLimiter:
    """DB-backed token bucket with daily reset window."""

    def __init__(self, db, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def can_send(self, provider: str) -> bool:
        """Return True if tokens are available for this provider today."""
        row = self._get_or_create(provider)
        return row["tokens_used"] < row["daily_limit"]

    def consume(self, provider: str, count: int = 1) -> bool:
        """Consume tokens. Returns False if rate limit already exceeded."""
        row = self._get_or_create(provider)
        if row["tokens_used"] + count > row["daily_limit"]:
            logger.warning(
                f"RateLimiter: {provider} daily limit reached for "
                f"workspace {self.workspace_id} "
                f"({row['tokens_used']}/{row['daily_limit']})"
            )
            return False

        try:
            self.db.client.table("provider_rate_limits").update({
                "tokens_used": row["tokens_used"] + count,
            }).eq("id", row["id"]).execute()
            return True
        except Exception as e:
            logger.error(f"RateLimiter.consume: update failed: {e}")
            return False

    def remaining(self, provider: str) -> int:
        """Return number of tokens remaining today for this provider."""
        row = self._get_or_create(provider)
        return max(0, row["daily_limit"] - row["tokens_used"])

    def usage(self) -> dict[str, dict]:
        """Return current usage for all providers."""
        result: dict[str, dict] = {}
        for provider, limit in _DEFAULT_LIMITS.items():
            row = self._get_or_create(provider)
            result[provider] = {
                "used": row["tokens_used"],
                "limit": row["daily_limit"],
                "remaining": max(0, row["daily_limit"] - row["tokens_used"]),
                "window_date": row["window_date"],
            }
        return result

    def reset_time(self, provider: str) -> str:
        """ISO timestamp of when the window resets (midnight UTC)."""
        from datetime import timedelta
        tomorrow = date.today() + timedelta(days=1)
        reset_dt = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
        return reset_dt.isoformat()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create(self, provider: str) -> dict:
        """Fetch today's rate limit row or create it if missing."""
        today = date.today().isoformat()
        try:
            result = (
                self.db.client.table("provider_rate_limits")
                .select("*")
                .eq("workspace_id", self.workspace_id)
                .eq("provider", provider)
                .eq("window_date", today)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.error(f"RateLimiter._get_or_create: select failed: {e}")

        # Create a fresh row for today
        default_limit = _DEFAULT_LIMITS.get(provider, 100)
        try:
            row = {
                "workspace_id": self.workspace_id,
                "provider": provider,
                "tokens_used": 0,
                "daily_limit": default_limit,
                "window_date": today,
            }
            result = self.db.client.table("provider_rate_limits").insert(row).execute()
            return result.data[0] if result.data else {**row, "id": None}
        except Exception as e:
            # Might fail due to UNIQUE constraint race — retry select
            logger.warning(f"RateLimiter._get_or_create: insert race, retrying select: {e}")
            try:
                result = (
                    self.db.client.table("provider_rate_limits")
                    .select("*")
                    .eq("workspace_id", self.workspace_id)
                    .eq("provider", provider)
                    .eq("window_date", today)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    return result.data[0]
            except Exception:
                pass
            # Final fallback: return in-memory row (won't persist)
            return {
                "id": None,
                "workspace_id": self.workspace_id,
                "provider": provider,
                "tokens_used": 0,
                "daily_limit": default_limit,
                "window_date": today,
            }
