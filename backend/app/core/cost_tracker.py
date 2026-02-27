"""API cost tracking for ProspectIQ.

Logs every API call's token usage and estimated cost to the api_costs table.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# Cost per 1M tokens (approximate, as of Feb 2026)
COST_TABLE = {
    "anthropic": {
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-20250414": {"input": 0.80, "output": 4.00},
        "claude-opus-4-20250515": {"input": 15.00, "output": 75.00},
        # Fallback for unknown model versions
        "default": {"input": 3.00, "output": 15.00},
    },
    "perplexity": {
        "sonar-pro": {"input": 3.00, "output": 15.00},
        "sonar": {"input": 1.00, "output": 1.00},
        "default": {"input": 3.00, "output": 15.00},
    },
    "apollo": {
        "people_search": {"per_call": 0.0},  # Free
        "people_enrichment": {"per_call": 0.01},  # ~$0.01 per credit
        "default": {"per_call": 0.0},
    },
}


def estimate_cost(
    provider: str,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimate cost in USD for an API call.

    Args:
        provider: API provider name (anthropic, perplexity, apollo)
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Estimated cost in USD.
    """
    provider_costs = COST_TABLE.get(provider, {})
    model_costs = provider_costs.get(model, provider_costs.get("default", {}))

    if "per_call" in model_costs:
        return model_costs["per_call"]

    input_cost = (input_tokens / 1_000_000) * model_costs.get("input", 0)
    output_cost = (output_tokens / 1_000_000) * model_costs.get("output", 0)
    return round(input_cost + output_cost, 6)


def log_cost(
    provider: str,
    model: str | None = None,
    endpoint: str | None = None,
    company_id: str | None = None,
    batch_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Log an API cost to the database.

    Args:
        provider: API provider (anthropic, perplexity, apollo, instantly)
        model: Model name
        endpoint: API endpoint called
        company_id: Company this call was for (if applicable)
        batch_id: Batch identifier
        input_tokens: Input token count
        output_tokens: Output token count
    """
    cost = estimate_cost(provider, model, input_tokens, output_tokens)

    try:
        db = Database()
        db.log_api_cost({
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "company_id": company_id,
            "batch_id": batch_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
        })
    except Exception as e:
        # Don't let cost tracking failures break the pipeline
        logger.warning(f"Failed to log API cost: {e}")


def get_batch_cost_summary(batch_id: str) -> dict:
    """Get cost summary for a batch.

    Returns:
        Dict with total_cost, by_provider breakdown, and call_count.
    """
    db = Database()
    costs = db.get_api_costs_summary(batch_id=batch_id)

    summary = {"total_cost": 0.0, "by_provider": {}, "call_count": len(costs)}
    for cost in costs:
        provider = cost.get("provider", "unknown")
        amount = float(cost.get("estimated_cost_usd", 0))
        summary["total_cost"] += amount
        summary["by_provider"][provider] = summary["by_provider"].get(provider, 0) + amount

    summary["total_cost"] = round(summary["total_cost"], 4)
    for k in summary["by_provider"]:
        summary["by_provider"][k] = round(summary["by_provider"][k], 4)

    return summary
