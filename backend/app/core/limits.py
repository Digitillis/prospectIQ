"""Centralized limits loader.

Reads config/limits.yaml and exposes typed constants so every script
pulls from the same source. Import this instead of hardcoding values.

Usage:
    from backend.app.core.limits import L
    if spend >= L.monthly_hard_limit_usd:
        ...
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_LIMITS_PATH = Path(__file__).parent.parent.parent.parent / "config" / "limits.yaml"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with open(_LIMITS_PATH) as f:
        return yaml.safe_load(f)


class _Limits:
    """Typed accessors for every value in config/limits.yaml."""

    # -- Spend ----------------------------------------------------------------
    @property
    def monthly_cap_usd(self) -> float:
        return float(_load()["spend"]["monthly_cap_usd"])

    @property
    def monthly_hard_limit_usd(self) -> float:
        return float(_load()["spend"]["monthly_hard_limit_usd"])

    @property
    def research_cap_usd(self) -> float:
        return float(_load()["spend"]["research_cap_usd"])

    @property
    def research_hard_limit_usd(self) -> float:
        return float(_load()["spend"]["research_hard_limit_usd"])

    @property
    def workspace_monthly_default_usd(self) -> float:
        return float(_load()["spend"]["workspace_monthly_default_usd"])

    @property
    def workspace_research_default_usd(self) -> float | None:
        v = _load()["spend"]["workspace_research_default_usd"]
        return float(v) if v is not None else None

    # -- QC alerts ------------------------------------------------------------
    @property
    def acct_warn_usd(self) -> float:
        return float(_load()["qc_alerts"]["acct_warn_usd"])

    @property
    def acct_urgent_usd(self) -> float:
        return float(_load()["qc_alerts"]["acct_urgent_usd"])

    @property
    def cap_warn_usd(self) -> float:
        return float(_load()["qc_alerts"]["cap_warn_usd"])

    @property
    def research_alert_usd(self) -> float:
        return float(_load()["qc_alerts"]["research_alert_usd"])

    @property
    def open_rate_min_pct(self) -> float:
        return float(_load()["qc_alerts"]["open_rate_min_pct"])

    @property
    def stuck_threshold_days(self) -> int:
        return int(_load()["qc_alerts"]["stuck_threshold_days"])

    @property
    def outreach_pnd_max(self) -> int:
        return int(_load()["qc_alerts"]["outreach_pnd_max"])

    # -- Pipeline guards ------------------------------------------------------
    @property
    def draft_buffer_target(self) -> int:
        return int(_load()["pipeline"]["draft_buffer_target"])

    @property
    def enrichment_cap(self) -> int:
        return int(_load()["pipeline"]["enrichment_cap"])

    @property
    def apollo_min_buffer(self) -> int:
        return int(_load()["pipeline"]["apollo_min_buffer"])

    @property
    def max_error_cycles(self) -> int:
        return int(_load()["pipeline"]["max_error_cycles"])

    # -- Batch sizes ----------------------------------------------------------
    @property
    def batch_research(self) -> int:
        return int(_load()["batch_sizes"]["research"])

    @property
    def batch_qualify(self) -> int:
        return int(_load()["batch_sizes"]["qualify"])

    @property
    def batch_enrich(self) -> int:
        return int(_load()["batch_sizes"]["enrich"])

    @property
    def batch_outreach(self) -> int:
        return int(_load()["batch_sizes"]["outreach"])

    # -- Sleep ----------------------------------------------------------------
    @property
    def sleep_inter_step(self) -> int:
        return int(_load()["sleep_seconds"]["inter_step"])

    @property
    def sleep_inter_cycle(self) -> int:
        return int(_load()["sleep_seconds"]["inter_cycle"])

    # -- Outreach -------------------------------------------------------------
    @property
    def daily_send_limit(self) -> int:
        return int(_load()["outreach"]["daily_send_limit"])

    # -- Send config (outreach_send_config table defaults) --------------------
    @property
    def send_config_onboarding_daily_limit(self) -> int:
        return int(_load()["send_config"]["onboarding_daily_limit"])

    @property
    def send_config_onboarding_batch_size(self) -> int:
        return int(_load()["send_config"]["onboarding_batch_size"])

    @property
    def send_config_fallback_daily_limit(self) -> int:
        return int(_load()["send_config"]["fallback_daily_limit"])

    @property
    def send_config_fallback_batch_size(self) -> int:
        return int(_load()["send_config"]["fallback_batch_size"])

    @property
    def send_config_fallback_min_gap_minutes(self) -> int:
        return int(_load()["send_config"]["fallback_min_gap_minutes"])

    @property
    def send_config_ramp_daily_limit(self) -> int:
        return int(_load()["send_config"]["ramp_daily_limit"])

    @property
    def send_config_ramp_batch_size(self) -> int:
        return int(_load()["send_config"]["ramp_batch_size"])

    # -- Queue ----------------------------------------------------------------
    @property
    def priority_score_batch(self) -> int:
        return int(_load()["queue"]["priority_score_batch"])

    # -- Agent kill switches (P1.5) ------------------------------------------
    @staticmethod
    def _agent_block(name: str) -> dict:
        agents = (_load() or {}).get("agents") or {}
        return agents.get(name) or {}

    @property
    def discovery_enabled(self) -> bool:
        return bool(self._agent_block("discovery").get("enabled", True))

    @property
    def discovery_required_naics_match(self) -> bool:
        return bool(self._agent_block("discovery").get("required_naics_match", False))

    @property
    def enrichment_enabled(self) -> bool:
        return bool(self._agent_block("enrichment").get("enabled", True))

    # -- Outreach reviewer cap (P1.4) ----------------------------------------
    @property
    def max_approvals_per_reviewer_per_day(self) -> int:
        return int(_load()["outreach"].get("max_approvals_per_reviewer_per_day", 30))

    # -- Notifications --------------------------------------------------------
    @property
    def workspace_owner_email(self) -> str:
        return str(
            _load().get("notifications", {}).get("workspace_owner_email", "avi@digitillis.com")
        )

    @property
    def reply_sla_hours(self) -> int:
        return int(_load().get("notifications", {}).get("reply_sla_hours", 24))

    @property
    def notify_on_positive(self) -> bool:
        return bool(_load().get("notifications", {}).get("notify_on_positive", True))

    @property
    def notify_on_question(self) -> bool:
        return bool(_load().get("notifications", {}).get("notify_on_question", True))


L = _Limits()


def reload_limits() -> None:
    """Drop the cached config so the next access re-reads limits.yaml.

    Used by tests and any caller that needs to pick up an in-memory edit.
    """
    _load.cache_clear()
