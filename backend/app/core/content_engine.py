"""Content Engine — proof points, objection handlers, case study snippets, and CTAs.

Provides static content assets referenced during sequence writing and SDR call prep.
All content is stored as Python dicts so it can be updated without a migration.

Usage:
    from backend.app.core.content_engine import ContentEngine

    engine = ContentEngine()
    stats  = engine.get_proof_points("fb")
    reply  = engine.get_objection_handler("too_expensive")
    snip   = engine.get_case_study_snippet("mfg", "maintenance_leader")
    cta    = engine.get_cta_for_touch(1)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proof points (vertical-specific stats for email copy)
# ---------------------------------------------------------------------------
PROOF_POINTS: dict[str, dict] = {
    "fb": {
        "stat_1": (
            "F&B manufacturers catch FDA violations 3× faster with real-time sensor monitoring"
        ),
        "stat_2": (
            "Average FSMA audit prep time reduced from 3 weeks to 4 days"
        ),
        "stat_3": (
            "Prevented 2 Class II recalls worth an estimated $4.2M in a 12-month period"
        ),
        "stat_4": (
            "CCP deviation alerts reach supervisors in under 90 seconds — vs 8 minutes manually"
        ),
        "stat_5": (
            "Customers reduced food safety corrective actions (CAPAs) by 41% in year one"
        ),
    },
    "mfg": {
        "stat_1": (
            "Unplanned downtime reduced 67% in the first 90 days on average"
        ),
        "stat_2": (
            "Maintenance costs down $180K/year per facility"
        ),
        "stat_3": (
            "ROI payback period: 4.2 months across 12 deployments"
        ),
        "stat_4": (
            "Bearing failure predicted 11–14 days in advance — avoiding $200K+ emergency repairs"
        ),
        "stat_5": (
            "Teams go from reactive to predictive maintenance with as few as 3 sensors per asset"
        ),
    },
}

# ---------------------------------------------------------------------------
# Objection handlers (brief SDR talking-point scripts)
# ---------------------------------------------------------------------------
OBJECTION_HANDLERS: dict[str, str] = {
    "too_expensive": (
        "Most pilots pay for themselves in the first prevented downtime event. "
        "We typically see ROI in 4–6 weeks — and we can start with just one asset "
        "to keep the initial investment minimal. Want to see the math on your specific case?"
    ),
    "already_have_cmms": (
        "We integrate with your existing CMMS — we sit on top of it and feed it better data. "
        "Your team keeps the workflow they know; we just give them earlier warnings. "
        "Which CMMS are you on? We've likely connected to it before."
    ),
    "not_the_right_time": (
        "The best time to start monitoring is before the next failure, not after it. "
        "We can get sensors on your most critical asset in a week — no IT project required. "
        "Even a 30-day pilot gives you enough data to decide."
    ),
    "need_to_talk_to_it": (
        "We've built the integration layer specifically to minimise IT burden. "
        "Most deployments don't touch your OT network at all — sensors connect over cellular. "
        "Happy to put together a one-pager for your IT team so you walk in prepared."
    ),
    "we_already_do_this": (
        "Walk me through what you're currently using — I'd love to understand the gap. "
        "Most teams we talk to are doing something reactive today and want to get ahead of it. "
        "What does your current alert-to-work-order workflow look like?"
    ),
    "send_me_info": (
        "Happy to send something over. Before I do — what's the one asset or line "
        "that keeps your team up at night? I'll make sure what I send is actually relevant."
    ),
    "not_a_priority": (
        "Totally fair. Out of curiosity — is it more of a budget timing issue, "
        "or is downtime just not the biggest fire right now? "
        "We work with a few companies that felt the same way until the next major failure hit."
    ),
    "need_board_approval": (
        "Makes sense. We can help you build the business case — "
        "we have a simple ROI model that maps your asset count to expected savings. "
        "Would a one-page summary for the board be useful?"
    ),
}

# ---------------------------------------------------------------------------
# Case study snippets — 2-line references to drop in emails
# ---------------------------------------------------------------------------
_CASE_STUDIES: dict[tuple[str, str], str] = {
    ("fb", "vp_quality_food_safety"): (
        "A regional dairy processor cut FSMA audit prep from 18 days to 4 days "
        "after deploying our sensor monitoring on their pasteurisation lines."
    ),
    ("fb", "director_quality_food_safety"): (
        "We helped a ready-to-eat manufacturer eliminate 3 recurring CCP deviations "
        "that were flagging in FDA inspections — all within 60 days of going live."
    ),
    ("fb", "vp_ops"): (
        "A snack food company with 4 facilities reduced unplanned line stoppages by 58% "
        "in the first quarter, saving roughly $1.1M in lost throughput."
    ),
    ("fb", "plant_manager"): (
        "A plant manager at a frozen food facility told us they went from 'fighting fires' "
        "to catching problems 2 weeks early — they haven't had an overnight emergency since."
    ),
    ("fb", "director_ops"): (
        "A beverage bottler improved OEE from 72% to 81% across two lines "
        "after adding predictive monitoring to their filling and capping equipment."
    ),
    ("mfg", "vp_ops"): (
        "A contract manufacturer running 24/7 reduced maintenance spend by $180K/year "
        "and hit ROI in under 5 months — without replacing any existing CMMS."
    ),
    ("mfg", "plant_manager"): (
        "A plant manager at a precision parts facility said the first prevented spindle failure "
        "alone covered the entire year's cost of the platform."
    ),
    ("mfg", "director_ops"): (
        "A Tier 1 automotive supplier cut unplanned downtime from 14% to under 5% "
        "on their stamping lines — translating to $340K saved in the first year."
    ),
    ("mfg", "maintenance_leader"): (
        "A reliability engineer at a metal fabrication shop started with 3 sensors on their "
        "most problematic press — caught a bearing failure 11 days out and avoided a $220K repair."
    ),
    ("mfg", "vp_supply_chain"): (
        "A discrete manufacturer reduced schedule variability by 31% after gaining visibility "
        "into which bottleneck assets were most likely to cause line delays."
    ),
}

_FALLBACK_CASE_STUDY = (
    "One of our customers — a mid-size manufacturer — saw $180K in maintenance savings "
    "in year one and had full ROI within 4 months of deployment."
)

# ---------------------------------------------------------------------------
# CTA escalation ladder (touch 1 → casual, touch 6 → specific close)
# ---------------------------------------------------------------------------
_CTA_BY_TOUCH: dict[int, str] = {
    1: "Worth a 15-minute coffee chat to see if it's a fit?",
    2: "Happy to show you a 20-minute demo tailored to your equipment. Does next week work?",
    3: "Can I ask — what does your current maintenance workflow look like for critical assets?",
    4: "Would it help to see the ROI model for a facility your size?",
    5: "I'll keep this short — is there a better person to loop in on this, or is this in your wheelhouse?",
    6: "Last note from me — if the timing is ever right, happy to pick this back up. Worth a quick call to close the loop?",
}
_CTA_DEFAULT = "Worth a quick call to explore this further?"


class ContentEngine:
    """Provides content assets for sequence personalisation and SDR call prep."""

    def get_proof_points(self, vertical: str) -> dict:
        """Return the proof point stats for a vertical.

        Args:
            vertical: 'fb' or 'mfg'.

        Returns:
            Dict of stat_1 … stat_N strings.
        """
        v = vertical.lower()
        if v not in PROOF_POINTS:
            logger.debug(f"[content] Unknown vertical '{vertical}' — using mfg stats")
            v = "mfg"
        return PROOF_POINTS[v]

    def get_objection_handler(self, objection_key: str) -> str:
        """Return the talking-point script for a specific objection.

        Args:
            objection_key: One of the keys in OBJECTION_HANDLERS.

        Returns:
            Objection handler string, or a generic fallback if key not found.
        """
        handler = OBJECTION_HANDLERS.get(objection_key.lower())
        if handler is None:
            logger.debug(f"[content] No handler for objection '{objection_key}'")
            return "Tell me more about the concern — I want to make sure I understand before responding."
        return handler

    def get_case_study_snippet(
        self,
        vertical: str,
        persona_type: str | None,
    ) -> str:
        """Return a 2-line case study reference for a (vertical, persona) pair.

        Falls back to a generic case study if no specific one is defined.

        Args:
            vertical: 'fb' or 'mfg'.
            persona_type: Persona classification string.

        Returns:
            Short case study reference string suitable for inline use in an email.
        """
        key = (vertical.lower(), (persona_type or "").lower())
        return _CASE_STUDIES.get(key, _FALLBACK_CASE_STUDY)

    def get_cta_for_touch(self, touch_num: int) -> str:
        """Return the appropriate call-to-action for a given touch number.

        CTAs escalate from casual (touch 1) to specific (touch 6).

        Args:
            touch_num: 1-based touch number.

        Returns:
            CTA string.
        """
        return _CTA_BY_TOUCH.get(touch_num, _CTA_DEFAULT)

    def list_objection_keys(self) -> list[str]:
        """Return all defined objection handler keys."""
        return list(OBJECTION_HANDLERS.keys())


# ---------------------------------------------------------------------------
# CLI — review content
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from rich.console import Console
    from rich.panel import Panel

    parser = argparse.ArgumentParser(description="Review ProspectIQ content assets")
    parser.add_argument("--vertical", default="mfg", choices=["fb", "mfg"])
    parser.add_argument("--persona", default="vp_ops")
    parser.add_argument("--objection", default=None)
    args = parser.parse_args()

    console = Console()
    engine = ContentEngine()

    console.print(Panel(f"[bold]Proof Points — {args.vertical.upper()}[/bold]"))
    for k, v in engine.get_proof_points(args.vertical).items():
        console.print(f"  [cyan]{k}[/cyan]: {v}")

    console.print()
    console.print(Panel(f"[bold]Case Study — ({args.vertical}, {args.persona})[/bold]"))
    console.print(f"  {engine.get_case_study_snippet(args.vertical, args.persona)}")

    console.print()
    console.print(Panel("[bold]CTAs by touch[/bold]"))
    for touch in range(1, 7):
        console.print(f"  Touch {touch}: {engine.get_cta_for_touch(touch)}")

    if args.objection:
        console.print()
        console.print(Panel(f"[bold]Objection Handler — {args.objection}[/bold]"))
        console.print(f"  {engine.get_objection_handler(args.objection)}")

    console.print()
    console.print(f"[dim]All objection keys: {', '.join(engine.list_objection_keys())}[/dim]")
