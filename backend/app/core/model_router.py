"""Model router for ProspectIQ.

Centralises model selection so we spend Sonnet tokens only where the
quality uplift is worth the cost.

Cost profile (per 1M tokens, approximate):
  claude-haiku-4-5-20251001   $0.80 input / $4.00 output
  claude-sonnet-4-6           $3.00 input / $15.00 output
  → Haiku is ~4× cheaper on input, ~3.75× cheaper on output.

Task routing:
  outreach      → Sonnet  (personalised cold emails — highest quality bar)
  research      → Sonnet  (deep synthesis; errors here cascade downstream)
  linkedin_msg  → Haiku   (short connection notes / DMs; constrained format)
  thread_class  → Haiku   (intent classification, single-label output)
  thread_gen    → Sonnet  (reply generation still benefits from quality)
  content       → Sonnet  (thought leadership posts)
  learning      → Sonnet  (analysis + recommendations)
  default       → Sonnet  (fail-safe: prefer quality over cost when unsure)
"""

from __future__ import annotations

SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"

# Explicit task → model mapping.  Add new task types here as needed.
_TASK_MODEL: dict[str, str] = {
    "outreach": SONNET,
    "research": SONNET,
    "linkedin_msg": HAIKU,
    "thread_class": HAIKU,
    "thread_gen": SONNET,
    "content": SONNET,
    "learning": SONNET,
}


def get_model(task: str) -> str:
    """Return the model ID to use for a given task type.

    Args:
        task: One of the task keys defined in _TASK_MODEL.

    Returns:
        Model ID string ready to pass to the Anthropic client.
    """
    return _TASK_MODEL.get(task, SONNET)
