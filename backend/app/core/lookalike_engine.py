"""Lookalike Discovery Engine for ProspectIQ.

Given a set of converted/high-performing seed companies, computes similarity
against the full company database and surfaces the top lookalike targets.

Pure heuristic scoring — no AI required, sub-second for 10k+ companies.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adjacent cluster mapping — for partial cluster credit
# ---------------------------------------------------------------------------

_ADJACENT_CLUSTERS: dict[str, set[str]] = {
    "machinery":  {"metals", "auto", "process"},
    "auto":       {"machinery", "metals"},
    "chemicals":  {"process", "fb"},
    "metals":     {"machinery", "auto"},
    "process":    {"chemicals", "fb", "machinery"},
    "fb":         {"process", "chemicals"},
    "other":      set(),
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SeedProfile(BaseModel):
    seed_company_ids: list[str]
    seed_company_count: int
    dominant_cluster: str
    dominant_tranche: str
    employee_count_range: tuple[int, int]
    revenue_ranges: list[str]
    top_technologies: list[str]
    top_pain_themes: list[str]
    avg_pqs: float


class LookalikeMatch(BaseModel):
    company_id: str
    company_name: str
    domain: Optional[str] = None
    cluster: Optional[str] = None
    tranche: Optional[str] = None
    employee_count: Optional[int] = None
    revenue_range: Optional[str] = None
    similarity_score: float
    matching_factors: list[str]
    pqs_total: float
    status: str
    has_contact: bool


class LookalikeResult(BaseModel):
    seed_profile: SeedProfile
    matches: list[LookalikeMatch]
    total_scored: int
    generated_at: str


class LookalikeRunSummary(BaseModel):
    id: str
    created_at: str
    match_count: int
    seed_count: int
    dominant_cluster: str
    dominant_tranche: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class LookalikeEngine:
    """Scores companies for similarity against a seed cohort."""

    def __init__(self, workspace_id: str | None = None):
        self.db = Database(workspace_id=workspace_id)
        self.workspace_id = workspace_id

    # ------------------------------------------------------------------
    # Seed profile construction
    # ------------------------------------------------------------------

    def build_seed_profile(
        self,
        company_ids: list[str],
        workspace_id: str | None = None,
    ) -> SeedProfile:
        """Load seed companies and compute aggregate profile."""
        ws = workspace_id or self.workspace_id

        companies: list[dict] = []
        for cid in company_ids:
            row = self.db.client.table("companies").select("*").eq("id", cid).execute()
            if row.data:
                companies.append(row.data[0])

        if not companies:
            return SeedProfile(
                seed_company_ids=company_ids,
                seed_company_count=0,
                dominant_cluster="unknown",
                dominant_tranche="T2",
                employee_count_range=(0, 10000),
                revenue_ranges=[],
                top_technologies=[],
                top_pain_themes=[],
                avg_pqs=0.0,
            )

        # Cluster
        clusters = [c.get("campaign_cluster") or "other" for c in companies]
        dominant_cluster = Counter(clusters).most_common(1)[0][0]

        # Tranche
        tranches = [c.get("tranche") or "T2" for c in companies]
        dominant_tranche = Counter(tranches).most_common(1)[0][0]

        # Employee count range
        emp_counts = [c.get("employee_count") for c in companies if c.get("employee_count")]
        if emp_counts:
            emp_min = int(min(emp_counts) * 0.5)
            emp_max = int(max(emp_counts) * 1.5)
        else:
            emp_min, emp_max = 0, 10000

        # Revenue ranges
        rev_ranges = [c.get("revenue_range") for c in companies if c.get("revenue_range")]
        revenue_ranges = list(dict.fromkeys(rev_ranges))  # preserve order, deduplicate

        # Technology signals (flatten arrays)
        tech_counter: Counter = Counter()
        for c in companies:
            raw = c.get("technology_stack") or []
            if isinstance(raw, list):
                for t in raw:
                    if t:
                        tech_counter[str(t).strip()] += 1
        top_technologies = [t for t, _ in tech_counter.most_common(10)]

        # Pain themes
        pain_counter: Counter = Counter()
        for c in companies:
            raw = c.get("pain_signals") or []
            if isinstance(raw, list):
                for p in raw:
                    if p:
                        pain_counter[str(p).strip()] += 1
        top_pain_themes = [p for p, _ in pain_counter.most_common(10)]

        # Avg PQS
        pqs_vals = [c.get("pqs_total") or 0 for c in companies]
        avg_pqs = round(sum(pqs_vals) / len(pqs_vals), 1) if pqs_vals else 0.0

        return SeedProfile(
            seed_company_ids=company_ids,
            seed_company_count=len(companies),
            dominant_cluster=dominant_cluster,
            dominant_tranche=dominant_tranche,
            employee_count_range=(emp_min, emp_max),
            revenue_ranges=revenue_ranges,
            top_technologies=top_technologies,
            top_pain_themes=top_pain_themes,
            avg_pqs=avg_pqs,
        )

    # ------------------------------------------------------------------
    # Single-company scorer
    # ------------------------------------------------------------------

    def score_company(self, company: dict, seed: SeedProfile) -> tuple[float, list[str]]:
        """Score a single candidate company against the seed profile.

        Returns (score 0-100, list of matching_factors for display).
        """
        score = 0.0
        factors: list[str] = []

        # 1. Cluster match (+25 exact, +10 adjacent)
        company_cluster = (company.get("campaign_cluster") or "other").lower()
        seed_cluster = seed.dominant_cluster.lower()
        if company_cluster == seed_cluster:
            score += 25
            factors.append(f"Same cluster ({company_cluster})")
        elif company_cluster in _ADJACENT_CLUSTERS.get(seed_cluster, set()):
            score += 10
            factors.append(f"Adjacent cluster ({company_cluster})")

        # 2. Tranche match (+20 if T1 match, +10 if T2 match)
        company_tranche = company.get("tranche") or ""
        if company_tranche == seed.dominant_tranche:
            pts = 20 if seed.dominant_tranche == "T1" else 10
            score += pts
            factors.append(f"{company_tranche} tranche match")
        elif company_tranche and seed.dominant_tranche:
            # Partial credit for being within one tier
            t_order = {"T1": 1, "T2": 2, "T3": 3}
            if abs(t_order.get(company_tranche, 2) - t_order.get(seed.dominant_tranche, 2)) == 1:
                score += 5
                factors.append(f"Near-tier ({company_tranche})")

        # 3. PQS score (0-20 points)
        pqs = float(company.get("pqs_total") or 0)
        pqs_pts = min(20.0, pqs / 100.0 * 20.0)
        score += pqs_pts
        if pqs >= 70:
            factors.append(f"High PQS ({int(pqs)})")
        elif pqs >= 50:
            factors.append(f"Strong PQS ({int(pqs)})")

        # 4. Employee count range match (+15)
        emp = company.get("employee_count")
        if emp is not None and seed.employee_count_range[0] <= emp <= seed.employee_count_range[1]:
            score += 15
            factors.append("Similar company size")

        # 5. Revenue range match (+10)
        rev = company.get("revenue_range")
        if rev and rev in seed.revenue_ranges:
            score += 10
            factors.append("Matching revenue range")

        # 6. Technology overlap (+2 per match, max +10)
        company_techs = {str(t).strip().lower() for t in (company.get("technology_stack") or []) if t}
        seed_techs = {t.lower() for t in seed.top_technologies}
        overlap = company_techs & seed_techs
        tech_pts = min(10.0, len(overlap) * 2.0)
        if tech_pts > 0:
            score += tech_pts
            matched = list(overlap)[:3]
            factors.append(f"Matching tech: {', '.join(matched)}")

        return round(min(100.0, score), 1), factors

    # ------------------------------------------------------------------
    # Main discovery run
    # ------------------------------------------------------------------

    def find_lookalikes(
        self,
        seed_company_ids: list[str],
        workspace_id: str | None = None,
        limit: int = 50,
        exclude_status: list[str] | None = None,
    ) -> LookalikeResult:
        """Find the top lookalike companies for the given seed cohort."""
        ws = workspace_id or self.workspace_id

        seed = self.build_seed_profile(seed_company_ids, workspace_id=ws)

        # Fetch all scoreable candidates (not in seed set, not in excluded statuses)
        seed_set = set(seed_company_ids)

        query = self.db.client.table("companies").select(
            "id, name, domain, campaign_cluster, tranche, employee_count, "
            "revenue_range, pqs_total, technology_stack, pain_signals, status"
        )

        rows = query.execute().data or []

        # Fetch contact presence (bulk: just check which company_ids have contacts)
        contact_rows = self.db.client.table("contacts").select("company_id").execute().data or []
        companies_with_contacts = {r["company_id"] for r in contact_rows if r.get("company_id")}

        excluded_statuses = set(exclude_status or [])

        scored: list[tuple[float, list[str], dict]] = []
        for row in rows:
            cid = row.get("id")
            if cid in seed_set:
                continue
            if row.get("status") in excluded_statuses:
                continue
            score, factors = self.score_company(row, seed)
            scored.append((score, factors, row))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        matches: list[LookalikeMatch] = []
        for sim_score, factors, row in top:
            matches.append(LookalikeMatch(
                company_id=row["id"],
                company_name=row.get("name") or "",
                domain=row.get("domain"),
                cluster=row.get("campaign_cluster"),
                tranche=row.get("tranche"),
                employee_count=row.get("employee_count"),
                revenue_range=row.get("revenue_range"),
                similarity_score=sim_score,
                matching_factors=factors,
                pqs_total=float(row.get("pqs_total") or 0),
                status=row.get("status") or "discovered",
                has_contact=row["id"] in companies_with_contacts,
            ))

        return LookalikeResult(
            seed_profile=seed,
            matches=matches,
            total_scored=len(scored),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Auto-seed from best performers
    # ------------------------------------------------------------------

    def auto_seed_from_best_performers(
        self,
        workspace_id: str | None = None,
        min_status: str = "replied",
    ) -> list[str]:
        """Return IDs of companies with high engagement status, to use as seed."""
        high_value_statuses = [
            "replied", "interested", "demo_booked", "customer",
            # Also map to CompanyStatus equivalents present in the DB
            "engaged", "meeting_scheduled", "pilot_discussion",
            "pilot_signed", "active_pilot", "converted",
        ]

        result = (
            self.db.client.table("companies")
            .select("id, status")
            .in_("status", high_value_statuses)
            .order("pqs_total", desc=True)
            .limit(50)
            .execute()
        )
        return [r["id"] for r in (result.data or [])]

    # ------------------------------------------------------------------
    # Save run to DB
    # ------------------------------------------------------------------

    def save_run(self, result: LookalikeResult, workspace_id: str | None = None) -> dict:
        """Persist a LookalikeResult to lookalike_runs. Returns the saved row."""
        ws = workspace_id or self.workspace_id or "00000000-0000-0000-0000-000000000001"
        row = {
            "workspace_id": ws,
            "seed_company_ids": result.seed_profile.seed_company_ids,
            "seed_profile": result.seed_profile.model_dump(),
            "matches": [m.model_dump() for m in result.matches],
            "total_scored": result.total_scored,
        }
        saved = self.db.client.table("lookalike_runs").insert(row).execute()
        return saved.data[0] if saved.data else {}

    # ------------------------------------------------------------------
    # Load past runs
    # ------------------------------------------------------------------

    def list_runs(self, workspace_id: str | None = None) -> list[dict]:
        """List past lookalike runs, newest first."""
        ws = workspace_id or self.workspace_id
        query = self.db.client.table("lookalike_runs").select(
            "id, created_at, total_scored, seed_profile, matches"
        )
        if ws:
            query = query.eq("workspace_id", ws)
        rows = query.order("created_at", desc=True).limit(50).execute().data or []

        summaries = []
        for r in rows:
            profile = r.get("seed_profile") or {}
            matches = r.get("matches") or []
            summaries.append({
                "id": r["id"],
                "created_at": r["created_at"],
                "match_count": len(matches),
                "seed_count": profile.get("seed_company_count", 0),
                "dominant_cluster": profile.get("dominant_cluster", ""),
                "dominant_tranche": profile.get("dominant_tranche", ""),
            })
        return summaries

    def get_run(self, run_id: str, workspace_id: str | None = None) -> dict | None:
        """Load a full lookalike run by ID."""
        ws = workspace_id or self.workspace_id
        query = self.db.client.table("lookalike_runs").select("*").eq("id", run_id)
        if ws:
            query = query.eq("workspace_id", ws)
        result = query.execute()
        return result.data[0] if result.data else None
