"""Discovery Agent — Apollo lead discovery.

Searches Apollo for companies + contacts matching the ICP.
No LLM calls — pure API + data processing.
"""

from __future__ import annotations

import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_icp_config
from backend.app.core.icp_validator import validate_and_exit_on_error
from backend.app.integrations.apollo import ApolloClient
from backend.app.utils.territory import get_territory, is_midwest
from backend.app.utils.naics import classify_sub_sector

console = Console()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier → campaign cluster mapping (mirrors the icp.yaml segment structure)
# ---------------------------------------------------------------------------
_TIER_TO_CLUSTER: dict[str, str] = {
    # Discrete manufacturing — machinery cluster
    "mfg1": "machinery",  # Industrial Machinery
    "mfg2": "machinery",  # Metal Fabrication
    "mfg4": "machinery",  # Electrical Equipment
    "mfg5": "machinery",  # Electronics / Semiconductor
    "mfg8": "machinery",  # Plastics & Rubber
    # Discrete manufacturing — specific clusters
    "mfg3": "auto",       # Automotive Parts
    "mfg7": "metals",     # Primary Metals (steel, aluminum)
    "mfg6": "watchlist",  # Aerospace — vendor qual wall
    # Process manufacturing
    "pmfg1": "chemicals",  # Chemical Manufacturing
    "pmfg3": "process",    # Petroleum Refining
    "pmfg4": "process",    # Mining
    "pmfg7": "process",    # Paper & Pulp
    "pmfg8": "process",    # Cement, Glass, Ceramics
    "pmfg2": "watchlist",  # Oil & Gas — enterprise procurement
    "pmfg5": "watchlist",  # Utilities — regulated monopoly
    "pmfg6": "watchlist",  # Pharma — vendor qual wall
    # Food & Beverage
    "fb1": "fb",
    "fb2": "fb",
    "fb3": "fb",
    "fb4": "fb",
    "fb5": "fb",
}

# Employee count → tranche proxy (used when revenue data is unavailable)
# T1: $100M–$400M ≈ 300–1,000 employees
# T2: $400M–$1B   ≈ 1,001–3,000 employees
# T3: $1B–$2B     ≈ 3,001–5,000 employees
def _assign_tranche(employee_count: int | None, revenue: float | None = None) -> str | None:
    """Assign revenue tranche based on employee count (proxy) or revenue."""
    if revenue:
        if revenue < 400_000_000:
            return "T1"
        elif revenue < 1_000_000_000:
            return "T2"
        else:
            return "T3"
    if employee_count:
        if employee_count <= 1000:
            return "T1"
        elif employee_count <= 3000:
            return "T2"
        else:
            return "T3"
    return None  # Not enough data — will be set by research backfill


def classify_persona(title: str | None) -> tuple[str | None, bool]:
    """Classify a contact's persona type from their title.

    Returns:
        Tuple of (persona_type, is_decision_maker).
    """
    if not title:
        return None, False

    title_lower = title.lower()

    # Order matters: more specific rules first (F&B food safety before generic ops)
    persona_rules = [
        # F&B — Food Safety & Quality personas (primary FSMA buyer)
        (["vp food safety", "vice president food safety", "vp of food safety",
          "vp quality and food safety", "vp food safety & quality",
          "vp food safety and quality", "vice president quality and food safety",
          "vp quality assurance and food safety",
          "vice president of quality and food safety",
          "vice president, food safety", "vp, food safety",
          "senior vice president - food safety", "svp food safety",
          "vice president, food safety, quality"], "vp_quality_food_safety", True),
        (["director food safety", "director of food safety",
          "director food safety & quality", "director food safety and quality",
          "director of food safety and quality", "director of food safety & quality",
          "sr director of food safety", "senior director of food safety",
          "corporate director of food safety",
          "director quality and food safety", "director of quality and food safety",
          "director, food safety", "director | food safety"],
         "director_quality_food_safety", True),
        # F&B — Quality-only personas (secondary FSMA buyer)
        (["vp quality", "vice president quality", "vp of quality",
          "vp quality assurance", "vice president quality assurance",
          "vice president of quality", "vp, quality"],
         "vp_quality_food_safety", True),
        (["director of quality", "director quality", "director quality assurance",
          "director of quality assurance", "quality and food safety director",
          "food safety and quality assurance director",
          "director, quality assurance", "director, quality",
          "director | quality", "director of qa", "director qa",
          "director, qa", "director- quality", "director-quality",
          "food safety and quality director", "food safety and qa director",
          "director of production, quality", "director of production quality"],
         "director_quality_food_safety", True),
        # F&B — Regulatory
        (["vp regulatory", "director regulatory", "director of regulatory"],
         "director_quality_food_safety", True),
        # Maintenance / Reliability (discrete mfg buyer)
        (["director of maintenance", "vp maintenance", "director maintenance",
          "maintenance manager", "reliability manager", "director of reliability",
          "director reliability"], "maintenance_leader", True),
        # C-suite
        (["chief operating", "chief operations", "coo"], "coo", True),
        (["chief executive", "president and ceo", "president & ceo",
          "president/ceo"], "coo", True),
        (["chief manufacturing", "chief production"], "coo", True),
        (["chief information", "cio"], "cio", True),
        (["chief technology", "cto"], "cio", True),
        # VP Operations / Manufacturing
        (["vp operations", "vice president operations", "vp of operations",
          "vice president of operations", "vp, operations", "vp - operations",
          "vice president, operations"], "vp_ops", True),
        (["vp manufacturing", "vice president manufacturing", "vp of manufacturing",
          "vice president of manufacturing", "vice president, manufacturing",
          "vp, manufacturing", "vp - manufacturing", "vp manufacturing operations",
          "vp, manufacturing operations", "vice president manufacturing operations"], "vp_ops", True),
        (["vp engineering", "vice president engineering", "vp of engineering",
          "vice president of engineering", "vp, engineering", "vp - engineering",
          "vice president, engineering"], "vp_ops", True),
        (["vp supply chain", "vice president supply chain",
          "vice president of supply chain", "vp, supply chain"], "vp_supply_chain", True),
        # Plant / General Manager
        (["plant manager", "factory manager", "general manager",
          "site manager", "operations manager", "machine shop operations manager",
          "manufacturing manager"], "plant_manager", True),
        # President (standalone — owner/operator of mid-market plant)
        (["president"], "plant_manager", True),
        # Digital / Industry 4.0
        (["digital transformation", "industry 4.0", "smart factory",
          "innovation manager"], "digital_transformation", True),
        # Director Operations / Manufacturing
        (["director of operations", "director operations", "director of operation"], "director_ops", True),
        (["director of manufacturing", "director manufacturing",
          "director, manufacturing", "director of production"], "director_ops", True),
        (["director of engineering", "director engineering"], "director_ops", True),
        (["director supply chain"], "vp_supply_chain", False),
        # EHS / Safety (adjacent buyer — often controls compliance spend)
        (["director, ehs", "director of ehs", "director ehs",
          "ehs director", "ehs manager"], "director_quality_food_safety", False),
    ]

    import re

    for keywords, persona, is_dm in persona_rules:
        for kw in keywords:
            # For short keywords (<=3 chars like "coo"), use word-boundary matching
            # to avoid false positives (e.g., "cto" inside "director")
            if len(kw) <= 4:
                if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
                    return persona, is_dm
            else:
                if kw in title_lower:
                    return persona, is_dm

    return None, False


class DiscoveryAgent(BaseAgent):
    """Discover manufacturing prospects from Apollo matching the ICP."""

    agent_name = "discovery"

    def run(
        self,
        max_pages: int | None = None,
        campaign_name: str | None = None,
        tiers: list[str] | None = None,
        dry_run: bool = False,
    ) -> AgentResult:
        """Run the discovery pipeline.

        Args:
            max_pages: Max pages per tier to fetch from Apollo (default from config).
            campaign_name: Campaign name to tag records with.
            tiers: Specific tiers to search (default: all tiers from ICP).
            dry_run: If True, fetch from Apollo but do not write to database.

        Returns:
            AgentResult with processing stats.
        """
        result = AgentResult()
        icp = get_icp_config()

        # Validate ICP config against GTM ground truth — exits on hard errors
        validate_and_exit_on_error(icp)

        if dry_run:
            console.print("[yellow][DRY-RUN] No database writes will occur.[/yellow]")

        campaign = campaign_name or icp.get("discovery", {}).get("default_campaign_name", "prospectiq")
        pages = max_pages or icp.get("discovery", {}).get("pages_per_tier", 5)
        target_tiers = tiers or [ind["tier"] for ind in icp["company_filters"]["industries"]]

        console.print(f"[cyan]Campaign: {campaign}[/cyan]")
        console.print(f"[cyan]Tiers: {target_tiers}[/cyan]")
        console.print(f"[cyan]Max pages per tier: {pages}[/cyan]")

        with ApolloClient() as apollo:
            for industry_config in icp["company_filters"]["industries"]:
                tier = industry_config["tier"]
                if tier not in target_tiers:
                    continue

                label = industry_config["label"]
                console.print(f"\n[bold yellow]Searching Tier {tier}: {label}[/bold yellow]")

                # Build search filters from ICP
                contact_filters = icp["contact_filters"]
                company_filters = icp["company_filters"]

                # Build revenue filter from ICP config
                revenue_config = company_filters.get("revenue", {})
                revenue_filter = None
                if revenue_config.get("min") or revenue_config.get("max"):
                    revenue_filter = {}
                    if revenue_config.get("min"):
                        revenue_filter["min"] = revenue_config["min"]
                    if revenue_config.get("max"):
                        revenue_filter["max"] = revenue_config["max"]

                # Use "United States" as location instead of individual states
                # — individual states create an OR filter that's too broad
                org_locations = company_filters["geography"].get("countries", ["United States"])

                people = apollo.search_people_paginated(
                    max_pages=pages,
                    person_titles=contact_filters["titles"]["include"],
                    person_not_titles=contact_filters["titles"]["exclude"],
                    person_seniorities=contact_filters["seniority"],
                    organization_locations=org_locations,
                    organization_num_employees_ranges=(
                        company_filters["employee_count"].get("apollo_ranges")
                        or [f"{company_filters['employee_count']['min']},{company_filters['employee_count']['max']}"]
                    ),
                    revenue_range=revenue_filter,
                    q_organization_keyword_tags=[industry_config.get("apollo_industry", label)],
                )

                self.track_cost(
                    provider="apollo",
                    model="people_search",
                    endpoint="/mixed_people/api_search",
                    input_tokens=0,
                    output_tokens=0,
                )

                console.print(f"  Found {len(people)} people records")

                # Process each person — extract company + contact, deduplicate, insert
                companies_seen = set()
                for person in people:
                    try:
                        company_data = ApolloClient.extract_company_data(person)
                        contact_data = ApolloClient.extract_contact_data(person)

                        if not company_data.get("name"):
                            result.skipped += 1
                            continue

                        # Subsidiary filter — skip if parent company already in pipeline
                        parent_name = company_data.get("parent_company_name")
                        if parent_name:
                            existing_parent = self.db.get_company_by_name(parent_name)
                            if existing_parent:
                                console.print(f"  [dim]Skipping {company_data['name']} — subsidiary of {parent_name} (already in pipeline)[/dim]")
                                result.skipped += 1
                                continue

                        # --- Company deduplication and insertion ---
                        company_id = None
                        org_apollo_id = company_data.get("apollo_id")
                        domain = company_data.get("domain")

                        # Check if already processed in this batch
                        dedup_key = org_apollo_id or domain or company_data["name"]
                        if dedup_key in companies_seen:
                            # Company already handled this batch — just link contact
                            existing = (
                                self.db.get_company_by_apollo_id(org_apollo_id)
                                if org_apollo_id
                                else self.db.get_company_by_domain(domain)
                            )
                            company_id = existing["id"] if existing else None
                        else:
                            companies_seen.add(dedup_key)

                            # Check database for existing company
                            existing = None
                            if org_apollo_id:
                                existing = self.db.get_company_by_apollo_id(org_apollo_id)
                            if not existing and domain:
                                existing = self.db.get_company_by_domain(domain)

                            if existing:
                                company_id = existing["id"]
                                result.skipped += 1
                            else:
                                # Classify sub-sector and territory
                                classification = classify_sub_sector(
                                    company_data.get("naics_code"),
                                    company_data.get("industry"),
                                )
                                state = company_data.get("state")
                                territory = get_territory(state) if state else None

                                # Calculate initial firmographic PQS
                                firmographic_score = self._calc_firmographic_score(
                                    company_data, classification, icp
                                )

                                effective_tier = classification.get("tier") or tier
                                cluster = _TIER_TO_CLUSTER.get(effective_tier, "other")
                                tranche = _assign_tranche(
                                    company_data.get("employee_count"),
                                    company_data.get("estimated_revenue"),
                                )
                                # outreach_mode: watchlist tiers go manual; all others auto
                                outreach_mode = "manual" if cluster == "watchlist" else "auto"

                                insert_data = {
                                    **company_data,
                                    "sub_sector": classification.get("label"),
                                    "tier": effective_tier,
                                    "territory": territory,
                                    "pqs_firmographic": firmographic_score,
                                    "pqs_total": firmographic_score,
                                    "status": "discovered",
                                    "campaign_name": campaign,
                                    "batch_id": self.batch_id,
                                    # Routing metadata — stored in custom_tags until
                                    # migration 014 adds dedicated columns
                                    "custom_tags": {
                                        "campaign_cluster": cluster,
                                        "outreach_mode": outreach_mode,
                                        **({"tranche": tranche} if tranche else {}),
                                    },
                                }

                                if dry_run:
                                    company_id = f"dry-run-{company_data['name']}"
                                    result.processed += 1
                                    result.add_detail(
                                        company_data["name"],
                                        "would-create",
                                        f"Tier {classification.get('tier') or tier}, PQS_firm={firmographic_score}",
                                    )
                                    console.print(
                                        f"  [DRY-RUN] Would insert company: {company_data['name']} "
                                        f"(Tier {classification.get('tier') or tier})"
                                    )
                                else:
                                    new_company = self.db.insert_company(insert_data)
                                    company_id = new_company.get("id")
                                    result.processed += 1
                                    result.add_detail(
                                        company_data["name"],
                                        "created",
                                        f"Tier {classification.get('tier') or tier}, PQS_firm={firmographic_score}",
                                    )

                        # --- Contact deduplication and insertion ---
                        if company_id and contact_data.get("apollo_id"):
                            existing_contact = (
                                None if dry_run
                                else self.db.get_contact_by_apollo_id(contact_data["apollo_id"])
                            )
                            if not existing_contact:
                                persona_type, is_dm = classify_persona(contact_data.get("title"))
                                contact_insert = {
                                    **contact_data,
                                    "company_id": company_id,
                                    "persona_type": persona_type,
                                    "is_decision_maker": is_dm,
                                }
                                if dry_run:
                                    console.print(
                                        f"    [DRY-RUN] Would insert contact: "
                                        f"{contact_data.get('full_name', '?')} ({contact_data.get('title', '?')})"
                                    )
                                else:
                                    self.db.insert_contact(contact_insert)

                    except Exception as e:
                        result.errors += 1
                        logger.error(f"Error processing person {person.get('name', '?')}: {e}")
                        result.add_detail(
                            person.get("name", "Unknown"),
                            "error",
                            str(e)[:200],
                        )

        return result

    def _calc_firmographic_score(
        self, company_data: dict, classification: dict, icp: dict
    ) -> int:
        """Calculate initial firmographic PQS score from Apollo data.

        This is a quick score using only data available at discovery time.
        """
        score = 0
        scoring = icp.get("company_filters", {})

        # Tier bonus — primary mfg tiers score higher than secondary F&B tiers
        tier = classification.get("tier") or ""
        if tier.startswith("mfg"):
            score += 7   # Primary vertical — discrete manufacturing
        elif tier.startswith("fb"):
            score += 3   # Secondary vertical — F&B

        # Revenue range
        revenue = company_data.get("estimated_revenue")
        if revenue:
            rev_min = scoring.get("revenue", {}).get("min", 0)
            rev_max = scoring.get("revenue", {}).get("max", float("inf"))
            if rev_min <= revenue <= rev_max:
                score += 5

        # Manufacturing belt states — higher density of target companies
        state = company_data.get("state")
        if state and is_midwest(state):
            score += 5
        elif state in {"Pennsylvania", "Kentucky", "Tennessee", "North Carolina",
                       "Alabama", "Texas", "Georgia", "South Carolina", "Virginia"}:
            score += 2  # Secondary manufacturing states still valuable

        # Employee count in sweet spot
        employees = company_data.get("employee_count")
        if employees:
            emp_min = scoring.get("employee_count", {}).get("min", 0)
            emp_max = scoring.get("employee_count", {}).get("max", float("inf"))
            if emp_min <= employees <= emp_max:
                score += 3

        # Private company (bonus)
        # Apollo doesn't always provide this; skip if unknown

        return min(score, 25)  # Cap at dimension max


if __name__ == "__main__":
    import argparse
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run ProspectIQ discovery")
    parser.add_argument("--campaign", required=True, help="Campaign name")
    parser.add_argument(
        "--tiers",
        help="Comma-separated tier list e.g. mfg1,mfg2,mfg3",
    )
    parser.add_argument("--max-pages", type=int, help="Max pages per tier")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tiers = args.tiers.split(",") if args.tiers else None
    agent = DiscoveryAgent()
    result = agent.execute(
        campaign_name=args.campaign,
        tiers=tiers,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
    )

    from rich.console import Console as _Console
    _Console().print(result.summary())
