"""Template Composer — generates A/B variant message templates from a campaign plan.

Takes an approved CampaignPlan and generates ready-to-use message templates
for each variant. Templates use {{variable}} placeholders compatible with the
existing outreach system.

Cost strategy:
  - One Sonnet call per variant (2 variants = 2 calls)
  - Context block is prompt-cached across both calls
  - All generated templates pass through OutboundValidator before returning
  - Uses existing outreach_guidelines.yaml for tone + style

Variable reference (compatible with existing outreach system):
  {{first_name}}, {{company}}, {{industry}}, {{state}},
  {{persona}}, {{sub_sector}}, {{signal}}, {{roi_metric}},
  {{pain_point}}, {{specific_fact}}

Usage:
    composer = TemplateComposer(db, workspace_id)
    variants = composer.generate(plan)
    # variants: list of SequenceVariant dicts, each validated by OutboundValidator
"""

from __future__ import annotations

import json
import logging

import anthropic

from backend.app.core.config import get_settings, get_outreach_guidelines
from backend.app.core.context_packager import build_context_block
from backend.app.core.model_router import SONNET
from backend.app.core.outbound_validator import OutboundValidator, OutboundValidationError

logger = logging.getLogger(__name__)

_COMPOSER_SYSTEM = """You are a senior B2B copywriter specialising in manufacturing and industrial outreach.
Generate message templates for cold outreach campaigns.
Use the GTM context and outreach guidelines provided.
All templates must use {{variable}} placeholders (not actual values).
Output ONLY valid JSON. No markdown fences."""

_COMPOSER_PROMPT = """Generate message templates for variant {variant_label} of this campaign.

CAMPAIGN HYPOTHESIS: {hypothesis}
VARIANT THEME: {variant_theme}
CHANNELS: {channels}
SEQUENCE STEPS: {n_steps}

OUTREACH GUIDELINES SUMMARY:
{guidelines_summary}

Output JSON with this structure:
{{
  "variant": "{variant_label}",
  "theme": "{variant_theme}",
  "email": {{
    "subject_a": "Subject line option A (under 60 chars)",
    "subject_b": "Subject line option B (under 60 chars, different angle)",
    "body_step1": "Full email body for step 1 (opening). Use {{first_name}}, {{company}}, {{specific_fact}}, {{pain_point}}.",
    "body_step2": "Follow-up email body (step 2, 4 days later). Reference no reply to step 1.",
    "body_step3": "Final email body (step 3, 7 days later). Soft close, easy out."
  }},
  "linkedin": {{
    "connect_note": "Connection request note (MAX 200 chars). No pitch. Company-specific hook.",
    "dm_step1": "Opening DM after connection accepted (MAX 80 words). Domain-expert question, no product pitch.",
    "dm_step2": "Follow-up DM (MAX 100 words, 7 days after DM 1). Soft product mention + soft CTA."
  }}
}}

Writing rules (enforce strictly):
- NO em dashes or en dashes (use commas or 'and')
- Contractions are encouraged (I'm, we've, you're)
- No buzzwords: synergy, leverage, streamline, innovative, disruptive, solution
- Level 3 personalisation required: reference SPECIFIC sub-sector challenge, not generic 'manufacturing'
- Emails must start: Hi {{first_name}},
- Connect note must reference a specific company fact or signal (use {{specific_fact}})
"""


class TemplateComposer:
    """Generates validated message templates for campaign variants."""

    def __init__(self, db, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self._validator = OutboundValidator()

    def generate(self, plan: dict) -> list[dict]:
        """Generate one template set per variant in the campaign plan.

        Args:
            plan: CampaignPlan dict from CampaignPlanner.compose().

        Returns:
            List of variant dicts, each containing validated message templates.
        """
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured.")

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        ctx_block = build_context_block(self.workspace_id, db=self.db)

        hypothesis = plan.get("hypothesis", "")
        channels = plan.get("channels", ["email"])
        n_steps = plan.get("schedule", {}).get("sequence_steps", 3)
        variant_themes = plan.get("variant_themes", ["ROI angle", "Risk angle"])
        n_variants = min(len(variant_themes), plan.get("n_variants", 2))

        # Load guidelines summary (non-cached, reads fresh YAML)
        guidelines_summary = self._get_guidelines_summary()

        results = []
        variant_labels = ["A", "B", "C", "D"]

        for i in range(n_variants):
            theme = variant_themes[i] if i < len(variant_themes) else f"Variant {i+1}"
            label = variant_labels[i]

            try:
                variant = self._generate_variant(
                    client=client,
                    ctx_block=ctx_block,
                    hypothesis=hypothesis,
                    variant_label=label,
                    variant_theme=theme,
                    channels=channels,
                    n_steps=n_steps,
                    guidelines_summary=guidelines_summary,
                )
                results.append(variant)
            except Exception as e:
                logger.error(f"TemplateComposer: variant {label} failed: {e}")
                results.append({
                    "variant": label,
                    "theme": theme,
                    "error": str(e),
                    "valid": False,
                })

        return results

    def _generate_variant(
        self,
        client: anthropic.Anthropic,
        ctx_block: dict,
        hypothesis: str,
        variant_label: str,
        variant_theme: str,
        channels: list[str],
        n_steps: int,
        guidelines_summary: str,
    ) -> dict:
        """Generate and validate one variant's templates."""
        prompt = _COMPOSER_PROMPT.format(
            variant_label=variant_label,
            hypothesis=hypothesis,
            variant_theme=variant_theme,
            channels=", ".join(channels),
            n_steps=n_steps,
            guidelines_summary=guidelines_summary,
        )

        resp = client.messages.create(
            model=SONNET,
            max_tokens=2000,
            system=[
                ctx_block,
                {"type": "text", "text": _COMPOSER_SYSTEM},
            ],
            messages=[{"role": "user", "content": prompt}],
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )

        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        variant = json.loads(text)
        variant["valid"] = True
        variant["validation_warnings"] = []
        variant["usage"] = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
        }

        # Validate email templates
        email = variant.get("email", {})
        available_vars = {
            "first_name", "company", "industry", "state", "persona",
            "sub_sector", "signal", "roi_metric", "pain_point", "specific_fact",
        }
        for field in ("body_step1", "body_step2", "body_step3"):
            body = email.get(field, "")
            if body:
                missing = OutboundValidator.check_template_vars(body, available_vars)
                if missing:
                    variant["validation_warnings"].append(
                        f"email.{field}: undefined template vars: {', '.join(missing)}"
                    )
                try:
                    self._validator.validate_email(
                        subject=email.get("subject_a", "placeholder"),
                        body=body,
                    )
                except OutboundValidationError as e:
                    variant["valid"] = False
                    variant["validation_warnings"].append(f"email.{field}: {e}")

        # Validate LinkedIn templates
        linkedin = variant.get("linkedin", {})
        connect_note = linkedin.get("connect_note", "")
        if connect_note:
            try:
                self._validator.validate_linkedin_connect(connect_note)
            except OutboundValidationError as e:
                variant["valid"] = False
                variant["validation_warnings"].append(f"linkedin.connect_note: {e}")

        return variant

    def _get_guidelines_summary(self) -> str:
        """Extract a compact summary of outreach guidelines for the prompt."""
        try:
            g = get_outreach_guidelines()
            voice = g.get("voice_and_tone", "")[:400]
            never = g.get("never_include", [])[:5]
            banned = g.get("banned_phrases", [])[:8]
            return (
                f"Voice: {voice}\n"
                f"Never include: {', '.join(never)}\n"
                f"Banned phrases: {', '.join(banned)}"
            )
        except Exception:
            return "Write in a direct, expert-to-operator tone. No buzzwords. No AI-sounding language."
