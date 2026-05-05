"""Model router for ProspectIQ.

Centralises model selection so we spend Sonnet tokens only where the
quality uplift is worth the cost.

Cost profile (per 1M tokens, approximate):
  claude-haiku-4-5-20251001   $0.80 input / $4.00 output
  claude-sonnet-4-6           $3.00 input / $15.00 output
  → Haiku is ~6× cheaper per call at typical ProspectIQ token volumes.

Approved routing policy (2026-05-02):
  outreach_step1    → Sonnet  (cold opens — first impression, user cannot uplift)
  outreach_step2plus → Haiku  (follow-ups — formulaic, prospect has context)
  draft_score       → Haiku   (classification task, merged into draft call)
  research          → Sonnet  (deep synthesis for high-PQS; Haiku for low-PQS via research.py)
  linkedin_msg      → Haiku
  thread_class      → Haiku
  thread_gen        → Sonnet  (reply generation quality matters)
  content           → Sonnet  (thought leadership)
  learning          → Sonnet  (analysis + recommendations)
  default           → Sonnet  (fail-safe)
"""

from __future__ import annotations

SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"

# Explicit task → model mapping.  Add new task types here as needed.
_TASK_MODEL: dict[str, str] = {
    # Outreach drafts — step-aware routing
    "outreach_step1": SONNET,         # Cold opens: first impression, highest quality bar
    "outreach_step2plus": HAIKU,      # Follow-ups: shorter, formulaic, prospect has context
    "draft_score": HAIKU,             # Quality scoring: classification task, merged into draft call
    # Legacy key — kept for any callers not yet migrated
    "outreach": SONNET,
    # Research
    "research": SONNET,
    # Comms
    "linkedin_msg": HAIKU,
    "thread_class": HAIKU,
    "thread_gen": SONNET,
    "content": SONNET,
    "learning": SONNET,
    # LLM qualification gates
    "llm_qualify_title": HAIKU,
    "llm_qualify_research": SONNET,
    # Planning
    "campaign_plan": SONNET,
    "template_compose": SONNET,
    "confidence_summary": HAIKU,
}


def get_model(task: str) -> str:
    """Return the model ID to use for a given task type.

    Args:
        task: One of the task keys defined in _TASK_MODEL.

    Returns:
        Model ID string ready to pass to the Anthropic client.
    """
    return _TASK_MODEL.get(task, SONNET)


def get_model_for_outreach(
    sequence_step: int,
    open_count: int = 0,
    click_count: int = 0,
) -> str:
    """Engagement-aware model selection for outreach drafts.

    Step 1 always uses Sonnet — cold opens, first impression.
    Step 2+: Sonnet if contact has opened or clicked (warm signal),
             Haiku otherwise (cold follow-up, formulaic, cost-efficient).

    Why: opened/clicked contacts have shown intent; a higher-quality
    personalised message at step 2 is worth ~6x the token cost.
    """
    if sequence_step <= 1:
        return SONNET
    if open_count > 0 or click_count > 0:
        return SONNET
    return HAIKU
