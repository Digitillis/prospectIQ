"""Discovery Agent — Apollo lead discovery.

Searches Apollo for companies + contacts matching the ICP.
No LLM calls — pure API + data processing.
"""

from __future__ import annotations

import logging

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_icp_config
from backend.app.integrations.apollo import ApolloClient
from backend.app.utils.territory import get_territory, is_midwest
from backend.app.utils.naics import classify_sub_sector

console = Console()
logger = logging.getLogger(__name__)


def classify_persona(title: str | None) -> tuple[str | None, bool]:
    """Classify a contact's persona type from their title.

    Returns:
        Tuple of (persona_type, is_decision_maker).
    """
    if not title:
        return None, False

    title_lower = title.lower()

    persona_rules = [
        (["chief operating", "coo"], "coo", True),
        (["chief information", "cio"], "cio", True),
        (["chief technology", "cto"], "cio", True),
        (["vp operations", "vice president operations", "vp of operations"], "vp_ops", True),
        (["vp manufacturing", "vice president manufacturing", "vp of manufacturing"], "vp_ops", True),
        (["vp engineering", "vice president engineering"], "vp_ops", True),
        (["vp supply chain", "vice president supply chain"], "vp_supply_chain", True),
        (["plant manager", "factory manager", "general manager"], "plant_manager", True),
        (["digital transformation", "industry 4.0", "smart factory", "innovation"], "digital_transformation", True),
        (["director of operations", "director operations"], "director_ops", True),
        (["director of manufacturing", "director manufacturing"], "director_ops", True),
        (["director of engineering", "director engineering"], "director_ops", True),
        (["director supply chain"], "vp_supply_chain", False),
    ]

    for keywords, persona, is_dm in persona_rules:
        for kw in keywords:
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
    ) -> AgentResult:
        """Run the discovery pipeline.

        Args:
            max_pages: Max pages per tier to fetch from Apollo (default from config).
            campaign_name: Campaign name to tag records with.
            tiers: Specific tiers to search (default: all tiers from ICP).

        Returns:
            AgentResult with processing stats.
        """
        result = AgentResult()
        icp = get_icp_config()

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

                people = apollo.search_people_paginated(
                    max_pages=pages,
                    person_titles=contact_filters["titles"]["include"],
                    person_not_titles=contact_filters["titles"]["exclude"],
                    person_seniorities=contact_filters["seniority"],
                    organization_locations=company_filters["geography"]["primary_states"],
                    organization_num_employees_ranges=[
                        f"{company_filters['employee_count']['min']},{company_filters['employee_count']['max']}"
                    ],
                    q_organization_keyword_tags=[industry_config.get("apollo_industry", label)],
                )

                self.track_cost(
                    provider="apollo",
                    model="people_search",
                    endpoint="/mixed_people/search",
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

                                insert_data = {
                                    **company_data,
                                    "sub_sector": classification.get("label"),
                                    "tier": classification.get("tier") or tier,
                                    "territory": territory,
                                    "pqs_firmographic": firmographic_score,
                                    "pqs_total": firmographic_score,
                                    "status": "discovered",
                                    "campaign_name": campaign,
                                    "batch_id": self.batch_id,
                                }

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
                            existing_contact = self.db.get_contact_by_apollo_id(
                                contact_data["apollo_id"]
                            )
                            if not existing_contact:
                                persona_type, is_dm = classify_persona(contact_data.get("title"))
                                contact_insert = {
                                    **contact_data,
                                    "company_id": company_id,
                                    "persona_type": persona_type,
                                    "is_decision_maker": is_dm,
                                }
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

        # Discrete manufacturing (NAICS 31-33)
        if classification.get("tier"):
            score += 5

        # Revenue range
        revenue = company_data.get("estimated_revenue")
        if revenue:
            rev_min = scoring.get("revenue", {}).get("min", 0)
            rev_max = scoring.get("revenue", {}).get("max", float("inf"))
            if rev_min <= revenue <= rev_max:
                score += 5

        # Midwest US
        state = company_data.get("state")
        if state and is_midwest(state):
            score += 5

        # Employee count
        employees = company_data.get("employee_count")
        if employees:
            emp_min = scoring.get("employee_count", {}).get("min", 0)
            emp_max = scoring.get("employee_count", {}).get("max", float("inf"))
            if emp_min <= employees <= emp_max:
                score += 3

        # Private company (bonus)
        # Apollo doesn't always provide this; skip if unknown

        return min(score, 25)  # Cap at dimension max
