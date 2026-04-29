"""LLM Qualification Agent — 7-gate explainable qualification pipeline.

Augments the existing rule-based PQS scoring with LLM-driven reasoning.
Gates 1–2 are rule-based (zero LLM cost). Gates 3–7 use Claude.
The pipeline short-circuits on any hard-fail gate — saves tokens.

Model strategy (cost-optimised):
  Gates 1–2: pure Python rules — $0
  Gate 3 (title scoring): Haiku — cheap classification
  Gates 4–7 (research, persona, stage, objections): Sonnet — complex reasoning

Prompt caching: the GTM context block is cached across all gate calls.
A full 7-gate run for one contact costs approximately:
  ~$0.004 with Haiku for gate 3
  ~$0.025 with Sonnet for gates 4-7
  → ~$0.029 total per contact for LLM qualification

The rule-based PQS engine costs $0.00 and runs first.
LLM qualification is an optional additive layer, not a replacement.

Usage:
    agent = LLMQualificationAgent(workspace_id="...")
    result = agent.qualify_contact(company_id="...", contact_id="...")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import anthropic

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_icp_config
from backend.app.core.context_packager import build_context_block
from backend.app.core.model_router import HAIKU, SONNET

logger = logging.getLogger(__name__)

_GATE_LABELS = [
    "dedup",
    "headline_prerule",
    "title_score",
    "company_research",
    "buyer_persona",
    "stage_fit",
    "objection_precheck",
]

# Keywords that immediately disqualify on title (gate 2, rule-based)
_PRERULE_DISQUALIFY_TITLES = [
    "intern", "student", "trainee", "junior", "assistant", "coordinator",
    "receptionist", "hr ", "human resources", "recruiter", "marketing",
    "sales representative", "sdr", "bdr", "account executive",
]


class LLMQualificationAgent(BaseAgent):
    """7-gate LLM-enhanced qualification for a single contact."""

    agent_name = "llm_qualification"

    def run(
        self,
        company_ids: list[str] | None = None,
        limit: int = 50,
    ) -> AgentResult:
        """Batch-qualify contacts for a set of companies.

        Args:
            company_ids: Specific companies to qualify. If None, picks top
                         unqualified companies by PQS score.
            limit: Max contacts to qualify.
        """
        result = AgentResult()
        settings = get_settings()

        if not settings.anthropic_api_key:
            logger.error("LLMQualificationAgent: ANTHROPIC_API_KEY not set.")
            result.success = False
            return result

        if company_ids:
            companies = [self.db.get_company(cid) for cid in company_ids if cid]
            companies = [c for c in companies if c]
        else:
            companies = self.db.get_companies(
                status="qualified",
                min_pqs=40,
                limit=limit,
            )
            # Skip recently LLM-qualified (within last 7 days)
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            companies = [
                c for c in companies
                if not c.get("llm_qualified_at") or c["llm_qualified_at"] < cutoff
            ]

        for company in companies[:limit]:
            company_id = company["id"]
            contacts = self.db.get_contacts(company_id=company_id, limit=3)
            if not contacts:
                result.skipped += 1
                continue

            # Qualify primary contact (highest persona priority)
            contact = contacts[0]
            try:
                qual_result = self.qualify_contact(
                    company=company,
                    contact=contact,
                )
                # Persist result to companies table
                self.db.client.table("companies").update({
                    "llm_qualification_result": qual_result,
                    "llm_qualified_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", company_id).execute()

                result.processed += 1
                result.add_detail(
                    company["name"],
                    "qualified" if qual_result.get("passed") else "disqualified",
                    f"score={qual_result.get('score', 0)}, "
                    f"fail_gate={qual_result.get('fail_gate', 'none')}",
                )
            except Exception as e:
                logger.error(f"LLMQualificationAgent: {company['name']} failed: {e}")
                result.errors += 1
                result.add_detail(company["name"], "error", str(e))

        return result

    def qualify_contact(
        self,
        company: dict,
        contact: dict,
    ) -> dict:
        """Run all 7 gates for a single company + contact pair.

        Returns a qualification result dict with gate-by-gate breakdown.
        Short-circuits on the first hard-fail gate.
        """
        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        gates: list[dict] = []
        passed = True
        fail_gate = None
        score = 0

        # Build context block once — cached across all 5 LLM gate calls
        ctx_block = build_context_block(self.workspace_id, db=self.db)

        # --- Gate 1: Dedup (rule) ---
        g1 = self._gate_dedup(contact)
        gates.append(g1)
        if g1["result"] == "fail":
            passed, fail_gate = False, "dedup"
            return self._build_result(gates, passed, fail_gate, score=0)

        # --- Gate 2: Headline pre-rule (rule) ---
        g2 = self._gate_headline_prerule(contact)
        gates.append(g2)
        if g2["result"] == "fail":
            passed, fail_gate = False, "headline_prerule"
            return self._build_result(gates, passed, fail_gate, score=5)

        # --- Gate 3: Title score (Haiku — cheap classification) ---
        g3 = self._gate_title_score(client, ctx_block, contact)
        gates.append(g3)
        self._track_llm_cost("gate3_title", g3.get("usage", {}))
        if g3["result"] == "fail":
            passed, fail_gate = False, "title_score"
            return self._build_result(gates, passed, fail_gate, score=10 + g3.get("numeric", 0))

        # --- Gate 4: Company research (Sonnet) ---
        research = self._get_research(company["id"])
        g4 = self._gate_company_research(client, ctx_block, company, research)
        gates.append(g4)
        self._track_llm_cost("gate4_company", g4.get("usage", {}))
        if g4["result"] == "fail":
            passed, fail_gate = False, "company_research"
            return self._build_result(gates, passed, fail_gate, score=20 + g4.get("numeric", 0))

        # --- Gate 5: Buyer persona match (Sonnet) ---
        g5 = self._gate_buyer_persona(client, ctx_block, company, contact, research)
        gates.append(g5)
        self._track_llm_cost("gate5_persona", g5.get("usage", {}))
        if g5["result"] == "fail":
            passed, fail_gate = False, "buyer_persona"
            return self._build_result(gates, passed, fail_gate, score=40 + g5.get("numeric", 0))

        # --- Gate 6: Stage fit (Sonnet) ---
        g6 = self._gate_stage_fit(client, ctx_block, company, research)
        gates.append(g6)
        self._track_llm_cost("gate6_stage", g6.get("usage", {}))
        if g6["result"] == "fail":
            passed, fail_gate = False, "stage_fit"
            return self._build_result(gates, passed, fail_gate, score=60 + g6.get("numeric", 0))

        # --- Gate 7: Objection pre-check (Sonnet) ---
        g7 = self._gate_objection_check(client, ctx_block, company, contact, research)
        gates.append(g7)
        self._track_llm_cost("gate7_objections", g7.get("usage", {}))

        # Compute final score (weighted average of gate scores)
        scores = [g.get("numeric", 5) for g in gates if g.get("numeric") is not None]
        final_score = int(sum(scores) / len(scores) * 10) if scores else 50

        return self._build_result(gates, passed=True, fail_gate=None, score=final_score)

    # ------------------------------------------------------------------
    # Gate implementations
    # ------------------------------------------------------------------

    def _gate_dedup(self, contact: dict) -> dict:
        """Gate 1: Block if this contact was contacted within the last 90 days."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        try:
            result = (
                self.db.client.table("outreach_drafts")
                .select("id")
                .eq("contact_id", contact["id"])
                .not_.is_("sent_at", "null")
                .gte("sent_at", cutoff)
                .limit(1)
                .execute()
            )
            recently_contacted = bool(result.data)
        except Exception:
            recently_contacted = False

        return {
            "gate": "dedup",
            "result": "fail" if recently_contacted else "pass",
            "reasoning": (
                "Contact was emailed within the last 90 days."
                if recently_contacted
                else "No recent outreach — safe to contact."
            ),
            "numeric": 10,
        }

    def _gate_headline_prerule(self, contact: dict) -> dict:
        """Gate 2: Hard block on clearly disqualifying titles (rule-based, $0)."""
        title = (contact.get("title") or "").lower()
        for kw in _PRERULE_DISQUALIFY_TITLES:
            if kw in title:
                return {
                    "gate": "headline_prerule",
                    "result": "fail",
                    "reasoning": f"Title '{contact.get('title')}' indicates non-decision-maker role.",
                    "matched_keyword": kw,
                    "numeric": 2,
                }
        return {
            "gate": "headline_prerule",
            "result": "pass",
            "reasoning": "Title passes pre-qualification keyword check.",
            "numeric": 8,
        }

    def _gate_title_score(
        self, client: anthropic.Anthropic, ctx_block: dict, contact: dict
    ) -> dict:
        """Gate 3: Score title fit 1-10 against ICP personas (Haiku)."""
        icp = get_icp_config()
        target_titles = icp.get("contact_filters", {}).get("title_patterns", [])[:15]

        prompt = (
            f"Rate how well this job title fits the Ideal Customer Profile on a scale of 1-10.\n\n"
            f"JOB TITLE: {contact.get('title', 'Unknown')}\n"
            f"SENIORITY: {contact.get('seniority', 'Unknown')}\n"
            f"DEPARTMENT: {contact.get('department', 'Unknown')}\n\n"
            f"TARGET TITLES (for reference): {', '.join(target_titles[:10])}\n\n"
            f"Respond with ONLY valid JSON:\n"
            f'{{"score": 7, "result": "pass", "reasoning": "VP Operations matches primary buying committee."}}\n'
            f'result must be "pass" (score >= 5) or "fail" (score < 5).'
        )
        try:
            resp = client.messages.create(
                model=HAIKU,
                max_tokens=150,
                system=[
                    ctx_block,
                    {"type": "text", "text": "You are a B2B sales qualification expert. Respond only with valid JSON."},
                ],
                messages=[{"role": "user", "content": prompt}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            data = json.loads(resp.content[0].text)
            return {
                "gate": "title_score",
                "result": data.get("result", "pass"),
                "reasoning": data.get("reasoning", ""),
                "numeric": min(10, max(1, int(data.get("score", 5)))),
                "usage": {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                },
            }
        except Exception as e:
            logger.error(f"Gate 3 title_score failed: {e}")
            return {"gate": "title_score", "result": "pass", "reasoning": "LLM unavailable — defaulting pass.", "numeric": 5}

    def _gate_company_research(
        self, client: anthropic.Anthropic, ctx_block: dict, company: dict, research: dict
    ) -> dict:
        """Gate 4: Evaluate company against ICP firmographic + strategic fit (Sonnet)."""
        prompt = (
            f"Evaluate this company against the ICP. Respond with JSON only.\n\n"
            f"COMPANY: {company.get('name')}\n"
            f"INDUSTRY: {company.get('industry', 'Unknown')}\n"
            f"EMPLOYEES: {company.get('employee_count', 'Unknown')}\n"
            f"REVENUE: {company.get('revenue_range', 'Unknown')}\n"
            f"STATE: {company.get('state', 'Unknown')}\n"
            f"RESEARCH SUMMARY: {str(research.get('web_research', ''))[:600]}\n\n"
            f"Respond: {{\"score\": 8, \"result\": \"pass\", \"reasoning\": \"...\"}}\n"
            f"result = 'pass' (score >= 5) or 'fail' (score < 5)."
        )
        return self._llm_gate(client, ctx_block, "company_research", prompt, model=SONNET)

    def _gate_buyer_persona(
        self, client: anthropic.Anthropic, ctx_block: dict,
        company: dict, contact: dict, research: dict
    ) -> dict:
        """Gate 5: Does this contact match the buying committee persona? (Sonnet)"""
        prompt = (
            f"Does this contact match the buying committee for our product?\n\n"
            f"CONTACT: {contact.get('title')} at {company.get('name')}\n"
            f"DEPARTMENT: {contact.get('department', 'Unknown')}\n"
            f"SENIORITY: {contact.get('seniority', 'Unknown')}\n"
            f"COMPANY SIZE: {company.get('employee_count', '?')} employees\n"
            f"JOB POSTINGS CONTEXT: {str(research.get('job_postings', ''))[:400]}\n\n"
            f"Respond: {{\"score\": 7, \"result\": \"pass\", \"reasoning\": \"...\"}}\n"
            f"result = 'pass' (score >= 5) or 'warn' (3-4) or 'fail' (score < 3)."
        )
        return self._llm_gate(client, ctx_block, "buyer_persona", prompt, model=SONNET)

    def _gate_stage_fit(
        self, client: anthropic.Anthropic, ctx_block: dict, company: dict, research: dict
    ) -> dict:
        """Gate 6: Is the company at the right maturity to adopt our product? (Sonnet)"""
        prompt = (
            f"Is this company at the right operational maturity to buy our product now?\n\n"
            f"COMPANY: {company.get('name')}, {company.get('industry')}\n"
            f"EMPLOYEES: {company.get('employee_count', '?')}\n"
            f"REVENUE: {company.get('revenue_range', '?')}\n"
            f"FUNDING EVENTS: {str(research.get('funding_events', ''))[:300]}\n"
            f"INTENT SIGNALS: {str(research.get('intent_signals', ''))[:300]}\n\n"
            f"Consider: too small = not ready, too large = too complex to land.\n"
            f"Respond: {{\"score\": 8, \"result\": \"pass\", \"reasoning\": \"...\"}}\n"
            f"result = 'pass' (score >= 5) or 'fail' (score < 5)."
        )
        return self._llm_gate(client, ctx_block, "stage_fit", prompt, model=SONNET)

    def _gate_objection_check(
        self, client: anthropic.Anthropic, ctx_block: dict,
        company: dict, contact: dict, research: dict
    ) -> dict:
        """Gate 7: Pre-flag known objections and blockers (Sonnet, non-blocking)."""
        prompt = (
            f"Identify potential objections or blockers for this prospect.\n\n"
            f"COMPANY: {company.get('name')}, {company.get('industry')}\n"
            f"CONTACT: {contact.get('title')}\n"
            f"RESEARCH: {str(research.get('web_research', ''))[:400]}\n\n"
            f"Common blockers: legacy ERP lock-in, union constraints, recent system purchase,\n"
            f"budget freeze, M&A transition, hostile IT environment.\n\n"
            f"Respond: {{\"score\": 7, \"result\": \"pass\", \"objections\": [\"...\"], \"reasoning\": \"...\"}}\n"
            f"result = 'pass' (score >= 4, manageable objections) or 'warn' (2-3) or 'fail' (score < 2)."
        )
        return self._llm_gate(client, ctx_block, "objection_precheck", prompt, model=SONNET)

    def _llm_gate(
        self,
        client: anthropic.Anthropic,
        ctx_block: dict,
        gate_name: str,
        prompt: str,
        model: str = SONNET,
    ) -> dict:
        """Execute a single LLM gate call and parse the result."""
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=250,
                system=[
                    ctx_block,
                    {"type": "text", "text": "You are a B2B sales qualification expert. Respond ONLY with valid JSON."},
                ],
                messages=[{"role": "user", "content": prompt}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            data = json.loads(resp.content[0].text)
            return {
                "gate": gate_name,
                "result": data.get("result", "pass"),
                "reasoning": data.get("reasoning", ""),
                "objections": data.get("objections", []),
                "numeric": min(10, max(1, int(data.get("score", 5)))),
                "usage": {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                },
            }
        except Exception as e:
            logger.error(f"LLM gate {gate_name} failed: {e}")
            return {
                "gate": gate_name,
                "result": "pass",
                "reasoning": f"LLM unavailable — defaulting pass. Error: {str(e)[:100]}",
                "numeric": 5,
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_research(self, company_id: str) -> dict:
        try:
            result = (
                self.db.client.table("research_intelligence")
                .select("*")
                .eq("company_id", company_id)
                .single()
                .execute()
            )
            return result.data or {}
        except Exception:
            return {}

    def _build_result(
        self, gates: list[dict], passed: bool, fail_gate: str | None, score: int
    ) -> dict:
        return {
            "passed": passed,
            "score": score,
            "fail_gate": fail_gate,
            "gates": gates,
            "qualified_at": datetime.now(timezone.utc).isoformat(),
        }

    def _track_llm_cost(self, task: str, usage: dict) -> None:
        if not usage:
            return
        self.track_cost(
            provider="anthropic",
            model=HAIKU if "gate3" in task else SONNET,
            endpoint=f"llm_qualify/{task}",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
