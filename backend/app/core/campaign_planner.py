"""Campaign Planner — natural language → structured campaign plan.

Takes a free-text description of what you want to accomplish and returns a
structured campaign plan (hypothesis, target segment, channels, variants,
success metrics, schedule). The plan is presented to the user for approval
before anything is executed.

Cost strategy:
  - Uses Sonnet (plan quality matters here)
  - Context block is prompt-cached (ICP + proven learnings)
  - Memory store retrieves relevant knowledge (what worked before)
  - One Claude call per plan — no iterative back-and-forth

Usage:
    planner = CampaignPlanner(db, workspace_id)
    plan = planner.compose("find 20 Tier 1 manufacturers that hired a VP Sales
                            and send a 3-step sequence about predictive maintenance ROI")
    # Returns CampaignPlan dict for user review
"""

from __future__ import annotations

import json
import logging

import anthropic

from backend.app.core.config import get_settings
from backend.app.core.context_packager import build_context_block, build_context_string
from backend.app.core.memory_store import MemoryStore
from backend.app.core.model_router import SONNET

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM = """You are a GTM strategy expert helping design B2B outreach campaigns.
Given a natural language campaign description, produce a structured campaign plan.
Use the GTM context provided. Be specific and actionable.
Output ONLY valid JSON. No markdown fences, no explanation outside the JSON."""

_PLANNER_PROMPT = """Design a campaign plan based on this request:

REQUEST: {request}

{memory_context}

Output a JSON campaign plan with this exact structure:
{{
  "hypothesis": "One-sentence testable hypothesis (e.g. 'Tier 1 discrete mfg VPs who recently hired a Maintenance Manager will respond to PdM ROI messaging within 2 touches')",
  "target_segment": {{
    "description": "Plain English description",
    "filters": {{
      "tiers": ["mfg1", "mfg2"],
      "statuses": ["qualified"],
      "min_pqs": 45,
      "personas": ["vp_ops", "plant_manager"],
      "signal_keywords": ["maintenance manager", "reliability engineer"]
    }},
    "estimated_reach": 150
  }},
  "channels": ["email", "linkedin"],
  "n_variants": 2,
  "variant_themes": [
    "ROI / cost savings angle",
    "Operational risk / downtime angle"
  ],
  "success_metrics": {{
    "primary": "reply_rate",
    "target_pct": 8,
    "secondary": "meeting_rate",
    "target_secondary_pct": 2
  }},
  "schedule": {{
    "send_days": ["monday", "tuesday", "wednesday"],
    "sequence_steps": 3,
    "step_wait_days": [0, 4, 7]
  }},
  "rationale": "2-3 sentence explanation of why this approach will work"
}}
"""


class CampaignPlanner:
    """Turns natural language into a structured, reviewable campaign plan."""

    def __init__(self, db, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self._memory = MemoryStore(db, workspace_id)

    def compose(self, request: str) -> dict:
        """Generate a campaign plan from a natural language request.

        Args:
            request: Free-text description of the campaign goal.

        Returns:
            CampaignPlan dict — structured plan for user review.
        """
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured.")

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        # Retrieve relevant knowledge (what worked for similar campaigns)
        memory_results = self._memory.retrieve(request, k=4)
        memory_context = self._memory.format_for_prompt(memory_results, max_chars=1200)

        # Build prompt
        user_prompt = _PLANNER_PROMPT.format(
            request=request,
            memory_context=memory_context,
        )

        # Context block is cached — charged at ~10% on repeat calls
        ctx_block = build_context_block(self.workspace_id, db=self.db)

        try:
            resp = client.messages.create(
                model=SONNET,
                max_tokens=1200,
                system=[
                    ctx_block,
                    {"type": "text", "text": _PLANNER_SYSTEM},
                ],
                messages=[{"role": "user", "content": user_prompt}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            plan_text = resp.content[0].text.strip()

            # Strip markdown fences if model added them
            if plan_text.startswith("```"):
                plan_text = plan_text.split("```")[1]
                if plan_text.startswith("json"):
                    plan_text = plan_text[4:]

            plan = json.loads(plan_text)
            plan["original_request"] = request
            plan["usage"] = {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
            }
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"CampaignPlanner: JSON parse failed: {e}")
            raise ValueError(f"Campaign plan generation failed: invalid JSON response.")
        except Exception as e:
            logger.error(f"CampaignPlanner.compose failed: {e}")
            raise

    def estimate_reach(self, filters: dict) -> int:
        """Estimate how many contacts match the campaign segment filters."""
        try:
            query = (
                self.db.client.table("contacts")
                .select("id", count="exact")
                .eq("workspace_id", self.workspace_id)
            )
            if filters.get("min_pqs"):
                query = query.gte("pqs_persona", filters["min_pqs"])
            if filters.get("personas"):
                query = query.in_("persona", filters["personas"])
            result = query.execute()
            return result.count or 0
        except Exception as e:
            logger.warning(f"CampaignPlanner.estimate_reach: {e}")
            return 0
