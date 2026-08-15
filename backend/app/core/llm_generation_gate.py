"""Single gate for LLM-driven CONTENT GENERATION — research, outreach-draft
generation, and personalization (trigger/hook) generation — as distinct
from classification and reporting, which stay on the metered API and are
not covered by this gate.

Why the distinction: CLAUDE.md's own doctrine states "Email generation:
ALWAYS via Claude Code workflow, NEVER the backend ... Pro Max session --
no Anthropic API spend." The doctrine is specifically about GENERATING
content (research findings, draft copy, personalization hooks), not about
cheap, genuinely runtime-reactive classification (title_classifier,
reply_classifier) or reporting (daily_report) — those stay exactly as
they were.

Three scheduler jobs reached generation directly despite that doctrine and
despite the SAME doctrine already having disabled the equivalent
draft-generation scheduler job for the identical stated reason
(main.py:3301's own comment: "All email generation now runs via the
Claude Code 'generate-outreach-emails' workflow"). See the 2026-08-15
send-path reconciliation, finding 9, and the follow-up subscription-
migration work that added this gate.

llm_generation_enabled defaults False in the deployed service
(backend/app/core/config.py). When False, OutreachAgent.run(),
ResearchAgent.run(), and PersonalizationBatch.run_batch() all skip their
generation work and return a clean, zero-processed result rather than
raising or silently proceeding to spend API tokens. This affects every
caller of those three entry points uniformly — the three named scheduler
jobs, but also the CLI scripts (run_research.py, run_sequence.py,
weekend_run.py, backend/scripts/run_outreach.py) and the on-demand HTTP
routes (/api/outreach/generate, /api/personalization/refresh, etc.) that
share the same classes. That is intentional, not scope creep: a manual
API call or a locally-run script is exactly as much "the backend
generating" as a cron job is. An operator who wants metered generation
from any of those paths sets LLM_GENERATION_ENABLED=true explicitly --
the same conscious-choice pattern SEND_ENABLED already establishes for
sending.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generation_enabled() -> bool:
    from backend.app.core.config import get_settings

    return bool(get_settings().llm_generation_enabled)


def log_generation_skipped(caller: str, detail: str = "") -> None:
    logger.info(
        "llm_generation.skipped caller=%s detail=%s -- LLM_GENERATION_ENABLED is "
        "false; generate via the Claude Code workflow instead "
        "(.claude/workflows/generate-outreach-emails.js et al.), or set "
        "LLM_GENERATION_ENABLED=true to use the metered API deliberately.",
        caller,
        detail,
    )
