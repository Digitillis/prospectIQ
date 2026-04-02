"""Signal Monitor Agent — detects buying signals for manufacturing companies.

Watches for events that indicate a company is more likely to buy NOW:
- Job postings (operations, engineering, IT/OT roles)
- Funding rounds
- Technology stack changes / ERP migrations
- News mentions and press activity
- Leadership changes (new VP Ops, COO, CTO, Plant Manager)
- Facility expansions
- Explicit pain signals found in research summaries
- Regulatory / compliance events
- New partnerships or customer announcements

Signals are scored 0.0–1.0 and assigned urgency:
  immediate  → act within 48 h
  near_term  → act within 2 weeks
  background → informational, no urgency
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings
from backend.app.core.signal_models import (
    BatchScanResult,
    CompanySignal,
    ManualSignalInput,
    SignalStats,
    SignalSummary,
    SignalType,
    SignalUrgency,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Urgency ordering for ranking
# ---------------------------------------------------------------------------
_URGENCY_RANK = {
    SignalUrgency.IMMEDIATE: 0,
    SignalUrgency.NEAR_TERM: 1,
    SignalUrgency.BACKGROUND: 2,
}

# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

_SIGNAL_SYSTEM = """You are a buying-signal analyst for an AI-powered manufacturing software company.

Your job is to read a company's research summary and Apollo data, then detect signals that indicate
the company is actively looking to buy or evaluate new technology solutions NOW.

Signal types to detect:
- job_posting: hiring roles in operations, engineering, IT/OT, digital transformation, ERP/MES/CMMS
- funding: recent investment rounds, PE backing, strategic investment
- tech_change: mentions of ERP migration, legacy system replacement, technology modernization
- news_mention: notable press coverage, awards, rankings, customer wins
- leadership_change: new VP Operations, COO, CTO, Plant Manager, CDO, or Director hired/promoted recently
- expansion: new facility, plant opening, geographic expansion, capacity increase
- pain_signal: explicit mentions of downtime, quality issues, manual processes, maintenance backlogs
- regulatory: compliance mandate, safety audit, ISO certification, sustainability reporting requirement
- partnership: new strategic partner, system integrator engagement, vendor announcement

For each signal detected, assign urgency:
- immediate: very strong buying signal, company likely evaluating vendors NOW (e.g., active ERP migration, pain expressed with budget)
- near_term: moderate signal, company likely planning in next quarter (e.g., new operations leader, expansion announced)
- background: weak/informational signal, good to know but no urgency

Assign signal_score 0.0–1.0:
- 0.8–1.0: strong, specific, time-sensitive evidence
- 0.5–0.79: moderate evidence, somewhat specific
- 0.2–0.49: weak inference, general industry pattern

Rules:
- Only detect signals with factual basis in the text provided
- Do NOT fabricate signals
- Deduplicate: only one signal per logical event
- Return empty array if no genuine signals found
- description must be 1–3 sentences, specific and factual

Return ONLY valid JSON array. No markdown, no explanation."""

_SIGNAL_USER = """Analyze this company and detect buying signals.

COMPANY: {company_name}
INDUSTRY: {industry}
EMPLOYEES: {employee_count}
LOCATION: {city}, {state}

RESEARCH SUMMARY:
{research_summary}

APOLLO DATA:
{apollo_data}

Return a JSON array of detected signals. Each signal must follow this exact schema:
[
  {{
    "signal_type": "<one of: job_posting|funding|tech_change|news_mention|leadership_change|expansion|pain_signal|regulatory|partnership>",
    "urgency": "<immediate|near_term|background>",
    "title": "<short, specific title, max 80 chars>",
    "description": "<1-3 sentence factual description of the signal>",
    "source_name": "<Apollo|Research|News|LinkedIn|Manual>",
    "signal_score": <0.0 to 1.0>
  }}
]

If no signals detected: return []"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SignalMonitorAgent(BaseAgent):
    """Scans companies for buying signals using Claude + Apollo data."""

    agent_name = "signal_monitor"

    # ------------------------------------------------------------------
    # scan_company — detect signals for one company
    # ------------------------------------------------------------------

    def scan_company(self, company_id: str, workspace_id: str) -> list[CompanySignal]:
        """Detect buying signals for a single company.

        Loads company record + research summary, calls Claude claude-haiku-4-5-20251001 to
        detect implicit signals, also checks Apollo data for job postings /
        funding, then saves new signals to company_signals table.

        Returns list of newly-created CompanySignal objects.
        """
        company = self.db.get_company(company_id)
        if not company:
            logger.warning(f"scan_company: company {company_id} not found")
            return []

        research_summary = company.get("research_summary") or ""
        apollo_data = self._build_apollo_summary(company)

        # Skip if no useful data to analyze
        if not research_summary and not apollo_data:
            logger.info(f"scan_company: skipping {company.get('name')} — no research data")
            return []

        # Prompt Claude
        detected_raw = self._call_claude(company, research_summary, apollo_data)

        # Also generate rule-based signals from Apollo fields
        rule_signals = self._extract_apollo_signals(company)

        all_raw = detected_raw + rule_signals

        new_signals: list[CompanySignal] = []
        for raw in all_raw:
            sig = self._save_signal(raw, company_id, workspace_id)
            if sig:
                new_signals.append(sig)

        # Stamp company with last_signal_scan_at
        try:
            self.db.client.table("companies").update({
                "last_signal_scan_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", company_id).execute()
        except Exception as e:
            logger.warning(f"scan_company: failed to stamp scan time: {e}")

        return new_signals

    # ------------------------------------------------------------------
    # scan_batch — scan multiple companies
    # ------------------------------------------------------------------

    def scan_batch(self, workspace_id: str, limit: int = 100) -> BatchScanResult:
        """Scan up to `limit` companies that haven't been scanned in 3 days.

        Targets companies with research_summary IS NOT NULL.
        Returns a BatchScanResult with stats.
        """
        from datetime import timedelta

        result = BatchScanResult(batch_id=self.batch_id)
        start = time.time()

        # Query companies with research data, not recently scanned
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        try:
            query = (
                self.db.client.table("companies")
                .select("id, name, last_signal_scan_at")
                .not_.is_("research_summary", "null")
                .limit(limit * 2)  # fetch more to filter
                .execute()
            )
            rows = query.data or []
        except Exception as e:
            logger.error(f"scan_batch: failed to query companies: {e}")
            result.errors = 1
            return result

        # Filter to those not scanned recently
        candidates = []
        for row in rows:
            last = row.get("last_signal_scan_at")
            if not last or last < cutoff:
                candidates.append(row)
            if len(candidates) >= limit:
                break

        for company_row in candidates:
            try:
                new_sigs = self.scan_company(company_row["id"], workspace_id)
                result.companies_scanned += 1
                result.signals_created += len(new_sigs)
            except Exception as e:
                logger.error(f"scan_batch: error scanning {company_row.get('name')}: {e}")
                result.errors += 1

        result.cost_usd = round(self._cost_accumulator, 4)
        result.duration_seconds = round(time.time() - start, 2)
        return result

    # ------------------------------------------------------------------
    # get_hot_prospects — ranked by composite signal score
    # ------------------------------------------------------------------

    def get_hot_prospects(self, workspace_id: str, limit: int = 20) -> list[SignalSummary]:
        """Return top companies ranked by signal strength.

        Groups unactioned signals by company, ranks by:
        1. Has immediate signals (rank 0)
        2. Composite score descending
        """
        try:
            result = (
                self.db.client.table("company_signals")
                .select(
                    "company_id, signal_type, urgency, title, description, "
                    "source_name, signal_score, is_read, is_actioned, detected_at, id"
                )
                .eq("is_actioned", False)
                .order("detected_at", desc=True)
                .limit(2000)
                .execute()
            )
            rows = result.data or []
        except Exception as e:
            logger.error(f"get_hot_prospects: query failed: {e}")
            return []

        # Group by company_id
        by_company: dict[str, list[dict]] = {}
        for row in rows:
            cid = row["company_id"]
            if cid not in by_company:
                by_company[cid] = []
            by_company[cid].append(row)

        if not by_company:
            return []

        # Fetch company metadata
        company_ids = list(by_company.keys())
        try:
            companies_result = (
                self.db.client.table("companies")
                .select("id, name, campaign_cluster, cluster, sub_sector")
                .in_("id", company_ids[:200])
                .execute()
            )
            company_meta = {r["id"]: r for r in (companies_result.data or [])}
        except Exception as e:
            logger.error(f"get_hot_prospects: company fetch failed: {e}")
            company_meta = {}

        summaries: list[SignalSummary] = []
        for company_id, signals in by_company.items():
            meta = company_meta.get(company_id, {})
            cluster = (
                meta.get("campaign_cluster")
                or meta.get("cluster")
                or meta.get("sub_sector")
                or "unknown"
            )

            urgencies = [s["urgency"] for s in signals]
            max_urg = "background"
            if "immediate" in urgencies:
                max_urg = "immediate"
            elif "near_term" in urgencies:
                max_urg = "near_term"

            composite = sum(s.get("signal_score", 0.5) for s in signals)
            unread = sum(1 for s in signals if not s.get("is_read", False))

            latest_at_str = max(s["detected_at"] for s in signals)
            try:
                latest_at = datetime.fromisoformat(latest_at_str.replace("Z", "+00:00"))
            except Exception:
                latest_at = datetime.now(timezone.utc)

            signal_objs = []
            for s in signals[:10]:  # cap signals per company
                try:
                    det = datetime.fromisoformat(s["detected_at"].replace("Z", "+00:00"))
                    signal_objs.append(CompanySignal(
                        id=s["id"],
                        company_id=company_id,
                        workspace_id=workspace_id,
                        signal_type=SignalType(s["signal_type"]),
                        urgency=SignalUrgency(s["urgency"]),
                        title=s["title"],
                        description=s.get("description") or "",
                        source_name=s.get("source_name") or "system",
                        signal_score=s.get("signal_score") or 0.5,
                        is_read=s.get("is_read", False),
                        is_actioned=s.get("is_actioned", False),
                        detected_at=det,
                    ))
                except Exception:
                    pass

            summaries.append(SignalSummary(
                company_id=company_id,
                company_name=meta.get("name") or company_id,
                cluster=cluster,
                total_signals=len(signals),
                unread_signals=unread,
                max_urgency=max_urg,
                composite_score=round(composite, 3),
                latest_signal_at=latest_at,
                signals=signal_objs,
            ))

        # Sort: immediate first, then by composite score desc
        summaries.sort(key=lambda s: (
            _URGENCY_RANK.get(SignalUrgency(s.max_urgency), 2),
            -s.composite_score,
        ))
        return summaries[:limit]

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def mark_signal_read(self, signal_id: str, workspace_id: str) -> None:
        """Mark a signal as read."""
        self.db.client.table("company_signals").update({
            "is_read": True
        }).eq("id", signal_id).execute()

    def mark_signal_actioned(self, signal_id: str, workspace_id: str) -> None:
        """Mark a signal as actioned and stamp actioned_at."""
        self.db.client.table("company_signals").update({
            "is_actioned": True,
            "is_read": True,
            "actioned_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", signal_id).execute()

    def add_manual_signal(self, inp: ManualSignalInput, workspace_id: str) -> CompanySignal | None:
        """Insert a manually-observed signal."""
        now = datetime.now(timezone.utc)
        row = {
            "company_id": inp.company_id,
            "workspace_id": workspace_id,
            "signal_type": inp.signal_type,
            "urgency": inp.urgency,
            "title": inp.title,
            "description": inp.description,
            "source_url": inp.source_url,
            "source_name": inp.source_name,
            "signal_score": inp.signal_score,
            "is_read": False,
            "is_actioned": False,
            "detected_at": now.isoformat(),
        }
        try:
            result = self.db.client.table("company_signals").insert(row).execute()
            saved = result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"add_manual_signal: insert failed: {e}")
            return None

        if not saved:
            return None

        return CompanySignal(
            id=saved["id"],
            company_id=saved["company_id"],
            workspace_id=saved["workspace_id"],
            signal_type=SignalType(saved["signal_type"]),
            urgency=SignalUrgency(saved["urgency"]),
            title=saved["title"],
            description=saved.get("description") or "",
            source_name=saved.get("source_name") or "Manual",
            signal_score=saved.get("signal_score") or 0.5,
            is_read=False,
            is_actioned=False,
            detected_at=now,
        )

    def get_signal_stats(self, workspace_id: str) -> SignalStats:
        """Return aggregate stats for the signals dashboard."""
        try:
            result = (
                self.db.client.table("company_signals")
                .select("urgency, signal_type, is_read, is_actioned, company_id")
                .eq("is_actioned", False)
                .execute()
            )
            rows = result.data or []
        except Exception as e:
            logger.error(f"get_signal_stats: query failed: {e}")
            return SignalStats()

        by_urgency = {"immediate": 0, "near_term": 0, "background": 0}
        by_type: dict[str, int] = {}
        total_unread = 0
        hot_companies: set[str] = set()

        for row in rows:
            urgency = row.get("urgency", "background")
            sig_type = row.get("signal_type", "unknown")
            is_read = row.get("is_read", True)
            cid = row.get("company_id")

            by_urgency[urgency] = by_urgency.get(urgency, 0) + 1
            by_type[sig_type] = by_type.get(sig_type, 0) + 1
            if not is_read:
                total_unread += 1
            if urgency == "immediate" and cid:
                hot_companies.add(cid)

        return SignalStats(
            total_unread=total_unread,
            by_urgency=by_urgency,
            by_type=by_type,
            hot_companies=len(hot_companies),
        )

    # ------------------------------------------------------------------
    # BaseAgent.run — for scheduled batch execution
    # ------------------------------------------------------------------

    def run(self, workspace_id: str | None = None, limit: int = 50, **kwargs) -> AgentResult:
        ws = workspace_id or self.workspace_id
        result = AgentResult()
        scan = self.scan_batch(workspace_id=ws, limit=limit)
        result.processed = scan.companies_scanned
        result.errors = scan.errors
        result.total_cost_usd = scan.cost_usd
        result.add_detail("batch", "ok", f"signals_created={scan.signals_created}")
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_claude(self, company: dict, research_summary: str, apollo_data: str) -> list[dict]:
        """Call Claude claude-haiku-4-5-20251001 to detect signals from research text."""
        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning("_call_claude: ANTHROPIC_API_KEY not set — skipping AI signal scan")
            return []

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

            user_msg = _SIGNAL_USER.format(
                company_name=company.get("name", "Unknown"),
                industry=company.get("industry") or company.get("sub_sector") or "Manufacturing",
                employee_count=company.get("employee_count") or "Unknown",
                city=company.get("city") or "Unknown",
                state=company.get("state") or "Unknown",
                research_summary=research_summary[:3000],
                apollo_data=apollo_data[:1000],
            )

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                system=_SIGNAL_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )

            raw_text = response.content[0].text.strip()

            # Track cost
            usage = response.usage
            self.track_cost(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                endpoint="signal_scan",
                company_id=company.get("id"),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            # Parse JSON
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            signals = json.loads(raw_text)
            if isinstance(signals, list):
                return signals
            return []

        except json.JSONDecodeError as e:
            logger.warning(f"_call_claude: JSON parse error: {e}")
            return []
        except Exception as e:
            logger.error(f"_call_claude: API call failed: {e}")
            return []

    def _build_apollo_summary(self, company: dict) -> str:
        """Build a concise Apollo data string to include in the Claude prompt."""
        parts: list[str] = []

        job_count = company.get("job_postings_count") or company.get("open_job_count") or 0
        if job_count:
            parts.append(f"Open job postings: {job_count}")

        emp = company.get("employee_count")
        if emp:
            parts.append(f"Employee count: {emp}")

        founded = company.get("founded_year")
        if founded:
            parts.append(f"Founded: {founded}")

        funding = company.get("funding_status") or company.get("latest_funding_stage")
        if funding:
            parts.append(f"Funding status: {funding}")

        revenue = company.get("revenue_range") or company.get("estimated_revenue")
        if revenue:
            parts.append(f"Revenue: {revenue}")

        return "\n".join(parts) if parts else "No Apollo data available"

    def _extract_apollo_signals(self, company: dict) -> list[dict]:
        """Generate rule-based signals from Apollo fields without LLM call."""
        signals: list[dict] = []

        # Job postings signal
        job_count = company.get("job_postings_count") or company.get("open_job_count") or 0
        if isinstance(job_count, int) and job_count >= 5:
            urgency = "immediate" if job_count >= 20 else "near_term"
            score = min(0.9, 0.4 + (job_count / 50))
            signals.append({
                "signal_type": "job_posting",
                "urgency": urgency,
                "title": f"Active hiring — {job_count} open positions",
                "description": (
                    f"{company.get('name')} currently has {job_count} open job postings, "
                    "indicating active growth and potential technology investment budget. "
                    "Operations and engineering roles suggest expansion activity."
                ),
                "source_name": "Apollo",
                "signal_score": round(score, 2),
            })

        # Funding signal
        funding_stage = company.get("funding_status") or company.get("latest_funding_stage")
        if funding_stage and funding_stage.lower() not in ("bootstrapped", "unknown", "not found", ""):
            signals.append({
                "signal_type": "funding",
                "urgency": "near_term",
                "title": f"Funding: {funding_stage}",
                "description": (
                    f"{company.get('name')} has received {funding_stage} funding. "
                    "Post-funding periods often trigger technology evaluations and new vendor relationships."
                ),
                "source_name": "Apollo",
                "signal_score": 0.65,
            })

        return signals

    def _save_signal(self, raw: dict, company_id: str, workspace_id: str) -> CompanySignal | None:
        """Validate raw signal dict and insert into company_signals, deduplicating by title."""
        try:
            signal_type_str = raw.get("signal_type", "")
            urgency_str = raw.get("urgency", "background")
            title = (raw.get("title") or "").strip()
            description = (raw.get("description") or "").strip()
            source_name = raw.get("source_name") or "system"
            signal_score = float(raw.get("signal_score", 0.5))

            # Validate enums
            try:
                signal_type = SignalType(signal_type_str)
                urgency = SignalUrgency(urgency_str)
            except ValueError:
                logger.debug(f"_save_signal: invalid enum values: {signal_type_str}/{urgency_str}")
                return None

            if not title:
                return None

            # Dedup: check if a similar signal exists for this company + type + title prefix
            existing = (
                self.db.client.table("company_signals")
                .select("id")
                .eq("company_id", company_id)
                .eq("signal_type", signal_type.value)
                .ilike("title", f"{title[:40]}%")
                .limit(1)
                .execute()
            )
            if existing.data:
                return None  # duplicate

            now = datetime.now(timezone.utc)
            row = {
                "company_id": company_id,
                "workspace_id": workspace_id,
                "signal_type": signal_type.value,
                "urgency": urgency.value,
                "title": title[:200],
                "description": description[:1000],
                "source_name": source_name,
                "signal_score": max(0.0, min(1.0, signal_score)),
                "is_read": False,
                "is_actioned": False,
                "detected_at": now.isoformat(),
            }

            result = self.db.client.table("company_signals").insert(row).execute()
            saved = result.data[0] if result.data else None
            if not saved:
                return None

            return CompanySignal(
                id=saved["id"],
                company_id=company_id,
                workspace_id=workspace_id,
                signal_type=signal_type,
                urgency=urgency,
                title=title,
                description=description,
                source_name=source_name,
                signal_score=signal_score,
                is_read=False,
                is_actioned=False,
                detected_at=now,
            )

        except Exception as e:
            logger.error(f"_save_signal: failed to save signal: {e}")
            return None
