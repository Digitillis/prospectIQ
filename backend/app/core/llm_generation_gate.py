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
(backend/app/core/config.py). When False, generation is refused at every
entry point that reaches the Anthropic API for content generation:

  - backend/app/agents/outreach.py:OutreachAgent.run() -- returns a clean,
    zero-processed AgentResult. Reached by the three named scheduler jobs
    (below) and CLI scripts (run_research.py, run_sequence.py,
    weekend_run.py, backend/scripts/run_outreach.py).
  - backend/app/agents/research.py:ResearchAgent.run() -- same pattern.
  - backend/app/core/personalization_batch.py:PersonalizationBatch.run_batch()
    -- returns a clean, zero-processed BatchResult. Reached by
    _run_personalization_refresh and POST /api/personalization/run-batch.
  - backend/app/core/personalization_engine.py:PersonalizationEngine.
    run_full_pipeline() -- raises RuntimeError (caught -> HTTP 503 by its
    route). Reached directly by POST /api/personalization/run/{company_id},
    a DIFFERENT caller than run_batch() above -- both had to be gated
    separately since neither wraps the other on this path.
  - backend/app/agents/outreach_agent.py:OutreachAgent.generate_draft() /
    .generate_batch() -- raises/returns empty (caught -> HTTP 503 by their
    routes). This is a SEPARATE class, also named OutreachAgent, unrelated
    to outreach.py's class of the same name. Reached by
    POST /api/outreach/generate and /api/outreach/generate-batch.

Two of the five were missed in this gate's first version and found by an
independent adversarial review before merge: the review traced
POST /api/outreach/generate to outreach.py's OutreachAgent and found it
actually resolves to the unrelated class in outreach_agent.py; a route
this docstring's first version cited as gated
(/api/personalization/refresh) does not exist at all, and the route that
does exist for single-company personalization
(/api/personalization/run/{company_id}) calls PersonalizationEngine
directly, not through the batch runner this gate already covered.

Gating on-demand HTTP routes and CLI scripts, not just the three
scheduler jobs, is intentional, not scope creep: a manual API call or a
locally-run script is exactly as much "the backend generating" as a cron
job is. An operator who wants metered generation from any of these paths
sets LLM_GENERATION_ENABLED=true explicitly -- the same conscious-choice
pattern SEND_ENABLED already establishes for sending.

score_draft_quality() (also in outreach_agent.py) is deliberately NOT
gated -- it evaluates an already-generated, human-reviewable draft, the
same kind of evaluative call as classification, not content generation.
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
