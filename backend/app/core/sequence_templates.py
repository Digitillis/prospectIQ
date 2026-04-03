"""Sequence Template Manager — (vertical, persona) → sequence configuration.

Templates drive subject line A/B variants, touch schedules, personalization
hints, and from-name guidance so each persona gets a tailored sequence rather
than a generic blast.

Templates are intentionally stored as plain dicts (no database) so sales can
edit them quickly without a migration.

Usage:
    from backend.app.core.sequence_templates import SequenceTemplateManager

    mgr = SequenceTemplateManager()
    template = mgr.get_template("fb", "vp_quality_food_safety")
    subject  = mgr.get_subject_variant("fb", "vp_quality_food_safety", touch_num=1, a_or_b="a")
    hints    = mgr.get_personalization_hints("mfg", "maintenance_leader")
    cta      = ContentEngine().get_cta_for_touch(1)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Touch schedule (day offsets from send day 1)
# ---------------------------------------------------------------------------
_DEFAULT_TOUCH_SCHEDULE = [1, 4, 8, 13, 19, 26]

# ---------------------------------------------------------------------------
# Template definitions
# Each key is (vertical_bucket, persona_type).
# ---------------------------------------------------------------------------
SEQUENCE_TEMPLATES: dict[tuple[str, str], dict] = {

    # -----------------------------------------------------------------------
    # F&B — Operations personas (messaging: equipment uptime, NOT FSMA)
    # VP Quality / Director Quality are de-prioritised in F&B targeting.
    # When they appear in the queue anyway, use the same ops/uptime angle —
    # FSMA compliance is NOT our core value proposition.
    # -----------------------------------------------------------------------
    ("fb", "vp_quality_food_safety"): {
        "name": "F&B VP Quality — Line Uptime (ops angle)",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "oee_uptime",
        "subject_variants": [
            "Production line downtime at {company} — quick question",
            "{first_name} — how many unplanned stops did {company} have last quarter?",
            "Preventing the next emergency shutdown at {company}",
        ],
        "personalization_hints": [
            "Do NOT lead with FSMA or compliance — this is an ops/uptime pitch",
            "Ask about equipment reliability on their highest-volume production line",
            "Reference cost-per-hour of downtime on food processing lines (~$15-40K/hr)",
            "Mention that quality issues often trace back to equipment degradation",
        ],
        "from_name": "the sender",
        "signature_variant": "ops",
    },

    ("fb", "director_quality_food_safety"): {
        "name": "F&B Director Quality — Equipment Reliability (ops angle)",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "oee_uptime",
        "subject_variants": [
            "Quality defects from equipment wear at {company} — quick question",
            "{first_name} — are equipment issues driving quality variation at {company}?",
            "One thing most food manufacturers miss before a quality escape",
        ],
        "personalization_hints": [
            "Do NOT lead with FSMA or compliance — this is an equipment reliability pitch",
            "Connect quality escapes back to equipment degradation (CNC wear, fill head drift)",
            "Ask whether they can predict quality issues before they reach the line",
            "Position as equipment intelligence, not compliance software",
        ],
        "from_name": "the sender",
        "signature_variant": "ops",
    },

    # -----------------------------------------------------------------------
    # F&B — Operations
    # -----------------------------------------------------------------------
    ("fb", "vp_ops"): {
        "name": "F&B VP Ops — OEE & Uptime",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "oee_uptime",
        "subject_variants": [
            "Unplanned downtime at {company} — what's it costing per hour?",
            "How {company} could prevent the next line stoppage",
            "{first_name} — one thing most F&B ops leaders overlook",
        ],
        "personalization_hints": [
            "Reference their production volume or number of facilities if known",
            "Mention seasonal capacity pressures if their product is seasonal",
            "Lead with maintenance cost reduction angle over pure uptime",
        ],
        "from_name": "the sender",
        "signature_variant": "ops",
    },

    ("fb", "plant_manager"): {
        "name": "F&B Plant Manager — Floor-Level Reliability",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "floor_reliability",
        "subject_variants": [
            "What {company} plant managers told us about their biggest headache",
            "{first_name} — quick question about reactive vs predictive maintenance",
            "Preventing the next emergency shutdown at {company}",
        ],
        "personalization_hints": [
            "Be direct — plant managers respond to specifics, not abstractions",
            "Mention shift handoff pain or overnight equipment failures",
            "Reference maintenance crew size and how that affects coverage",
        ],
        "from_name": "the sender",
        "signature_variant": "ops",
    },

    ("fb", "maintenance_leader"): {
        "name": "F&B Maintenance Leader — PdM Pilot",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "pdm_tech",
        "subject_variants": [
            "Predicting filler/conveyor failure before it stops the line at {company}",
            "{first_name} — condition monitoring on {company}'s critical processing equipment?",
            "One sensor setup that caught a $90K failure before it happened",
        ],
        "personalization_hints": [
            "Lead with technical specifics — maintenance leaders in F&B see a lot of generic outreach",
            "Mention high-wear assets: fillers, conveyors, mixers, pumps, heat exchangers",
            "Offer to start with one critical asset or one line as a pilot",
            "Reference vibration, temperature, and motor current as primary signals",
            "Do NOT lead with FSMA — they own equipment uptime, not compliance filings",
        ],
        "from_name": "the sender",
        "signature_variant": "pdm_tech",
    },

    ("fb", "director_ops"): {
        "name": "F&B Director Ops — Cost & Throughput",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "oee_uptime",
        "subject_variants": [
            "Throughput improvement I noticed at {company}",
            "{first_name} — how are you tracking OEE across your lines?",
            "One metric most F&B ops directors aren't tracking (yet)",
        ],
        "personalization_hints": [
            "Ask about their current OEE baseline if unknown",
            "Reference throughput constraints by food category",
            "Connect to their CAPEX cycle if it's a plant expansion year",
        ],
        "from_name": "the sender",
        "signature_variant": "ops",
    },

    # -----------------------------------------------------------------------
    # Manufacturing — Operations
    # -----------------------------------------------------------------------
    ("mfg", "vp_ops"): {
        "name": "Mfg VP Ops — Predictive Maintenance ROI",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "pdm_roi",
        "subject_variants": [
            "Unplanned downtime at {company} — what's the cost per hour?",
            "{first_name} — how much is reactive maintenance costing {company}?",
            "Quick question about {company}'s maintenance strategy",
        ],
        "personalization_hints": [
            "Lead with ROI payback period (4.2 months average) upfront",
            "Reference their industry sub-vertical (automotive, aerospace, etc.)",
            "If they're NAICS 332/333, mention CNC and spindle failure as examples",
        ],
        "from_name": "the sender",
        "signature_variant": "pdm",
    },

    ("mfg", "plant_manager"): {
        "name": "Mfg Plant Manager — Floor Reliability",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "floor_reliability",
        "subject_variants": [
            "Emergency shutdowns at {company} — what's causing them?",
            "{first_name} — predictive vs reactive: where does {company} sit?",
            "One thing most plant managers tell us before they sign",
        ],
        "personalization_hints": [
            "Be concrete — plant managers tune out generic pitches fast",
            "Ask about their worst recurring failure mode",
            "Reference overnight or weekend crew coverage gaps",
        ],
        "from_name": "the sender",
        "signature_variant": "pdm",
    },

    ("mfg", "director_ops"): {
        "name": "Mfg Director Ops — Cost Reduction",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "pdm_roi",
        "subject_variants": [
            "$180K/year — what {company} could save on maintenance",
            "{first_name} — quick question about {company}'s maintenance budget",
            "How {company} compares to industry benchmarks on downtime",
        ],
        "personalization_hints": [
            "Use $180K/year maintenance savings stat specifically",
            "Tie to their budgeting cycle if it's Q4",
            "Mention integration with their existing CMMS",
        ],
        "from_name": "the sender",
        "signature_variant": "pdm",
    },

    # -----------------------------------------------------------------------
    # Manufacturing — Maintenance / Reliability
    # -----------------------------------------------------------------------
    ("mfg", "maintenance_leader"): {
        "name": "Mfg Maintenance Leader — PdM Pilot",
        "touches": 6,
        "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
        "value_prop": "pdm_tech",
        "subject_variants": [
            "Predicting bearing failure before it takes down the line at {company}",
            "{first_name} — are you running condition monitoring on {company}'s critical assets?",
            "One sensor setup that caught a $200K failure before it happened",
        ],
        "personalization_hints": [
            "Lead with technical credibility — they can smell a generic sales email",
            "Mention specific failure modes relevant to their equipment type",
            "Offer to start with one asset or one line as a pilot",
            "Reference vibration analysis and thermal monitoring specifically",
        ],
        "from_name": "the sender",
        "signature_variant": "pdm_tech",
    },
}

# ---------------------------------------------------------------------------
# Fallback template used when no exact match is found
# ---------------------------------------------------------------------------
_FALLBACK_TEMPLATE: dict = {
    "name": "General Manufacturing — Ops",
    "touches": 6,
    "touch_schedule": _DEFAULT_TOUCH_SCHEDULE,
    "value_prop": "pdm_roi",
    "subject_variants": [
        "Quick question about {company}'s maintenance strategy",
        "{first_name} — one thing most ops leaders are missing",
        "Reducing unplanned downtime at {company}",
    ],
    "personalization_hints": [
        "Identify the specific equipment types they run before reaching out",
        "Lead with cost avoidance rather than features",
    ],
    "from_name": "Avanish @ Digitillis",
    "signature_variant": "ops",
}


class SequenceTemplateManager:
    """Resolves the appropriate sequence template for a (vertical, persona) pair."""

    def get_template(self, vertical: str, persona_type: str | None) -> dict:
        """Return the sequence template for a vertical + persona combination.

        Falls back to the general fallback template when no exact match exists.

        Args:
            vertical: 'fb' or 'mfg'.
            persona_type: Persona classification string (e.g. 'vp_ops').

        Returns:
            Template dict with 'name', 'touches', 'touch_schedule',
            'subject_variants', 'personalization_hints', etc.
        """
        key = (vertical.lower(), (persona_type or "").lower())
        template = SEQUENCE_TEMPLATES.get(key)
        if template is None:
            logger.debug(
                f"[templates] No template for ({vertical}, {persona_type}) — using fallback"
            )
            return _FALLBACK_TEMPLATE
        return template

    def get_subject_variant(
        self,
        vertical: str,
        persona_type: str | None,
        touch_num: int,
        a_or_b: str = "a",
    ) -> str:
        """Return a subject line variant for a specific touch in the sequence.

        Rotates through the subject_variants list based on touch number.
        'a' selects the primary index, 'b' selects the next variant (if it exists).

        Args:
            vertical: 'fb' or 'mfg'.
            persona_type: Persona classification string.
            touch_num: 1-based touch number.
            a_or_b: 'a' for primary, 'b' for alternate.

        Returns:
            Subject line template string (with {company} / {first_name} placeholders).
        """
        template = self.get_template(vertical, persona_type)
        variants = template.get("subject_variants", [])
        if not variants:
            return "Following up about {company}"

        # Touch 1 uses index 0, touch 2 uses index 1, etc. Wraps if needed.
        base_index = (touch_num - 1) % len(variants)
        if a_or_b == "b":
            alt_index = (base_index + 1) % len(variants)
            return variants[alt_index]
        return variants[base_index]

    def get_personalization_hints(
        self,
        vertical: str,
        persona_type: str | None,
    ) -> list[str]:
        """Return the list of personalization hints for a (vertical, persona) pair.

        Args:
            vertical: 'fb' or 'mfg'.
            persona_type: Persona classification string.

        Returns:
            List of hint strings for the SDR to use when crafting first-line copy.
        """
        template = self.get_template(vertical, persona_type)
        return template.get("personalization_hints", [])

    def list_all_templates(self) -> list[dict]:
        """Return a flat list of all templates with their vertical and persona key.

        Useful for CLI display or admin review.

        Returns:
            List of dicts with 'vertical', 'persona_type', and merged template fields.
        """
        output = []
        for (vertical, persona_type), tmpl in SEQUENCE_TEMPLATES.items():
            output.append({
                "vertical": vertical,
                "persona_type": persona_type,
                **tmpl,
            })
        return output


# ---------------------------------------------------------------------------
# CLI — list templates
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.console import Console
    from rich.table import Table

    console = Console()
    mgr = SequenceTemplateManager()
    templates = mgr.list_all_templates()

    table = Table(show_header=True, header_style="bold green", title="Sequence Templates")
    table.add_column("Vertical", min_width=6)
    table.add_column("Persona", min_width=28)
    table.add_column("Name", min_width=36)
    table.add_column("Touches", justify="center", min_width=7)
    table.add_column("Value Prop", min_width=18)

    for t in templates:
        table.add_row(
            t["vertical"].upper(),
            t["persona_type"],
            t["name"],
            str(t["touches"]),
            t.get("value_prop", "—"),
        )

    console.print(table)
    console.print(f"\n[bold]{len(templates)} templates defined[/bold]")
