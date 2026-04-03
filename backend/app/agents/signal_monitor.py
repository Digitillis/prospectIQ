"""Signal Monitor Agent — Real-time buying signal detection.

Runs on a schedule (daily for Growth+, weekly for Starter) to re-research
tracked companies for new buying signals via Perplexity web search.

Detects 9 manufacturing-specific signals + generic trigger events.
When a signal fires:
  - Creates/updates a company_intent_signals record
  - Recalculates PQS timing dimension with signal weight
  - Re-queues company for research refresh if research is >14 days old (2.9)
  - Logs a Slack notification for high-value signals

Designed to run as a scheduled background job or triggered via API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

import anthropic
from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, load_yaml_config
from backend.app.core.model_router import get_model

console = Console()
logger = logging.getLogger(__name__)

# Statuses where we should monitor for new signals
_MONITOR_STATUSES = [
    "qualified", "outreach_pending", "contacted", "engaged",
    "meeting_scheduled", "not_interested",
]

# How many days back to search for new signals
_SIGNAL_LOOKBACK_DAYS = 30

SIGNAL_SYSTEM = """You are a manufacturing industry intelligence analyst.
Your job is to search for recent buying signals for a specific manufacturing company
that indicate readiness to evaluate AI/predictive maintenance platforms.

Search the web for evidence of the specified signal types in the LAST 30 DAYS ONLY.
Be factual and specific. Only report what you actually find with high confidence.
Do not fabricate events. If you find nothing credible, say so.

Output ONLY valid JSON. No markdown, no preamble."""


def _build_signal_prompt(company: dict, signal_types: list[str]) -> str:
    company_name = company.get("name", "")
    industry = company.get("sub_sector") or company.get("industry", "manufacturing")
    location = ", ".join(filter(None, [company.get("city"), company.get("state")]))
    website = company.get("website", "")

    signal_descriptions = "\n".join(f"- {s}" for s in signal_types)

    return f"""Search for recent buying signals for this manufacturing company.

COMPANY: {company_name}
INDUSTRY: {industry}
LOCATION: {location}
WEBSITE: {website}

SIGNAL TYPES TO SEARCH FOR (last 30 days only):
{signal_descriptions}

For each signal found, extract:
- signal_type: exact key from the list above
- description: factual description of what happened
- date_approx: approximate date (YYYY-MM or "Unknown")
- source: where you found this (news article, press release, job posting, etc.)
- confidence: "high" | "medium" | "low"
- outreach_angle: one sentence on why this creates an opening

OUTPUT FORMAT:
{{
    "company_name": "{company_name}",
    "signals_found": [
        {{
            "signal_type": "string",
            "description": "string",
            "date_approx": "string",
            "source": "string",
            "confidence": "high|medium|low",
            "outreach_angle": "string"
        }}
    ],
    "search_notes": "brief note on what you searched and what you found or didn't find"
}}"""


class SignalMonitorAgent(BaseAgent):
    """Monitor tracked companies for new manufacturing buying signals."""

    agent_name = "signal_monitor"

    def run(
        self,
        company_ids: list[str] | None = None,
        limit: int = 50,
        min_pqs: int = 30,
        statuses: list[str] | None = None,
        tier: str | None = None,
    ) -> AgentResult:
        """Run signal monitoring for tracked companies.

        Args:
            company_ids: Specific company IDs to monitor (overrides query).
            limit: Max companies to scan.
            min_pqs: Only scan companies above this PQS threshold.
            statuses: Company statuses to include (default: qualified/contacted/engaged).
            tier: Filter by tier.

        Returns:
            AgentResult with signal detection stats.
        """
        result = AgentResult()
        settings = get_settings()

        if not settings.perplexity_api_key and not settings.anthropic_api_key:
            console.print("[red]No Perplexity or Anthropic API key configured.[/red]")
            result.success = False
            return result

        # Load signal weights config
        try:
            signal_config = load_yaml_config("signal_weights.yaml")
        except FileNotFoundError:
            signal_config = {}

        mfg_signals = signal_config.get("manufacturing_signals", {})
        signal_type_descriptions = [
            f"{key}: {cfg.get('description', '')}"
            for key, cfg in mfg_signals.items()
        ]

        # Add generic trigger events to monitoring list
        signal_type_descriptions += [
            "leadership_change: New VP Operations, COO, Plant Manager, CDO hired/promoted",
            "capex_investment: New production line, facility expansion, major equipment purchase",
            "competitor_displacement: Stated dissatisfaction with or removal of a competing vendor",
            "operational_incident: Equipment failure, unplanned shutdown, product recall in press",
        ]

        # Fetch companies to monitor
        statuses_to_check = statuses or _MONITOR_STATUSES
        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids]
            companies = [c for c in companies if c]
        else:
            all_companies = []
            for status in statuses_to_check:
                batch = self.db.get_companies(
                    status=status,
                    tier=tier,
                    min_pqs=min_pqs,
                    limit=limit // len(statuses_to_check) + 1,
                )
                all_companies.extend(batch)
            companies = all_companies[:limit]

        if not companies:
            console.print("[yellow]No companies to monitor.[/yellow]")
            return result

        console.print(f"[cyan]Signal monitor scanning {len(companies)} companies...[/cyan]")

        # Use Perplexity if available (web search), otherwise Claude with training data
        use_perplexity = bool(settings.perplexity_api_key)

        if use_perplexity:
            import requests
            api_key = settings.perplexity_api_key
        else:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        for company in companies:
            company_id = company["id"]
            company_name = company.get("name", "Unknown")

            try:
                prompt = _build_signal_prompt(company, signal_type_descriptions)

                if use_perplexity:
                    response = requests.post(
                        "https://api.perplexity.ai/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "sonar-pro",
                            "messages": [
                                {"role": "system", "content": SIGNAL_SYSTEM},
                                {"role": "user", "content": prompt},
                            ],
                            "max_tokens": 1500,
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"].strip()
                    # Estimate Perplexity cost (~$0.005 per call)
                    self._cost_accumulator += 0.005
                else:
                    _model = get_model("research")
                    resp = client.messages.create(
                        model=_model,
                        max_tokens=1500,
                        system=SIGNAL_SYSTEM,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    self.track_cost(
                        provider="anthropic",
                        model=_model,
                        endpoint="/messages",
                        company_id=company_id,
                        input_tokens=resp.usage.input_tokens,
                        output_tokens=resp.usage.output_tokens,
                    )
                    content = resp.content[0].text.strip()

                # Strip markdown fences if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()

                parsed = json.loads(content)
                signals_found = parsed.get("signals_found", [])

                if not signals_found:
                    console.print(f"  [dim]{company_name}: No new signals.[/dim]")
                    result.skipped += 1
                    continue

                # Process each signal
                new_signals = 0
                pqs_delta = 0

                for signal in signals_found:
                    sig_type = signal.get("signal_type", "")
                    confidence = signal.get("confidence", "low")
                    if confidence == "low":
                        continue  # Skip low-confidence signals

                    # Upsert into company_intent_signals
                    _upsert_intent_signal(
                        db=self.db,
                        company_id=company_id,
                        signal_type=sig_type,
                        signal_data=signal,
                    )

                    # Calculate PQS delta from signal weights
                    weight = _get_signal_weight(signal_config, sig_type)
                    pqs_delta += weight
                    new_signals += 1

                if new_signals > 0:
                    # Recalculate PQS timing dimension
                    _recalculate_pqs_timing(self.db, company, pqs_delta)

                    # Auto-refresh research if stale (2.9)
                    _maybe_queue_research_refresh(self.db, company)

                    # Slack notification for high-value signals
                    if pqs_delta >= 10:
                        try:
                            from backend.app.utils.notifications import notify_slack
                            notify_slack(
                                f"*Signal detected for {company_name}* (+{pqs_delta} PQS). "
                                f"{new_signals} signal(s) found. Check `/signals` page.",
                                emoji=":signal_strength:",
                            )
                        except Exception:
                            pass

                    result.processed += 1
                    result.add_detail(
                        company_name,
                        "signals_found",
                        f"{new_signals} signal(s), +{pqs_delta} PQS timing",
                    )
                    console.print(
                        f"  [green]{company_name}: {new_signals} signal(s) → +{pqs_delta} PQS[/green]"
                    )
                else:
                    result.skipped += 1

            except json.JSONDecodeError as e:
                logger.warning(f"Signal parse error for {company_name}: {e}")
                result.errors += 1
            except Exception as e:
                logger.error(f"Signal monitor error for {company_name}: {e}", exc_info=True)
                result.errors += 1

        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_intent_signal(db, company_id: str, signal_type: str, signal_data: dict) -> None:
    """Insert or update a company_intent_signals record."""
    try:
        db.client.table("company_intent_signals").upsert(
            {
                "company_id": company_id,
                "signal_type": signal_type,
                "strength": signal_data.get("confidence", "medium"),
                "source": signal_data.get("source", "signal_monitor"),
                "evidence": signal_data.get("description", ""),
                "outreach_angle": signal_data.get("outreach_angle", ""),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "metadata": signal_data,
            },
            on_conflict="company_id,signal_type",
        ).execute()
    except Exception as exc:
        logger.warning(f"Failed to upsert intent signal for {company_id}: {exc}")


def _get_signal_weight(signal_config: dict, signal_type: str) -> int:
    """Return PQS delta for a signal type from config."""
    # Check manufacturing signals first
    mfg = signal_config.get("manufacturing_signals", {})
    if signal_type in mfg:
        return mfg[signal_type].get("delta_pqs", 5)
    # Check trigger events
    te = signal_config.get("trigger_events", {})
    if signal_type in te:
        return te[signal_type].get("delta_pqs", 5)
    return 5  # default


def _recalculate_pqs_timing(db, company: dict, delta: int) -> None:
    """Add delta to PQS timing score, capped at the dimension max (30)."""
    company_id = company["id"]
    current_timing = company.get("pqs_timing", 0) or 0
    current_total = company.get("pqs_total", 0) or 0

    new_timing = min(current_timing + delta, 30)
    actual_delta = new_timing - current_timing
    new_total = current_total + actual_delta

    if actual_delta > 0:
        db.update_company(company_id, {
            "pqs_timing": new_timing,
            "pqs_total": new_total,
        })
        logger.info(
            f"PQS recalculated for {company.get('name')}: "
            f"timing {current_timing}→{new_timing}, total {current_total}→{new_total}"
        )


def _maybe_queue_research_refresh(db, company: dict) -> None:
    """Queue company for research refresh if last research is stale (>14 days)."""
    company_id = company["id"]

    # Check when company was last researched
    research = db.get_research(company_id)
    if not research:
        return

    updated_at = research.get("updated_at") or research.get("created_at")
    if not updated_at:
        return

    try:
        if isinstance(updated_at, str):
            last_research = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        else:
            last_research = updated_at

        age_days = (datetime.now(timezone.utc) - last_research).days
        if age_days > 14:
            # Re-queue for research by setting status back to discovered
            # only if company is in a pre-outreach status
            if company.get("status") in ("qualified", "not_interested"):
                db.update_company(company_id, {"status": "discovered"})
                logger.info(
                    f"Research refresh queued for {company.get('name')} "
                    f"(last research {age_days} days ago)"
                )
    except Exception as exc:
        logger.debug(f"Could not check research age for {company_id}: {exc}")
