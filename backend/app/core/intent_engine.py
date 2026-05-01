"""Intent Signal Engine — detects and scores buying signals for target companies.

Signal types and point values:
  - job_posting (maintenance/quality/ops role):  +15 pts
  - fda_warning_letter (last 24 months):          +25 pts
  - fda_warning_letter_fsma (last 24 months):     +45 pts  — FSMA 204 enforcement
  - fda_recall (last 18 months):                  +20 pts
  - osha_citation (last 12 months):               +15 pts
  - funding_event (last 18 months):               +10 pts
  - linkedin_activity (manual log):               +10 pts

FSMA enforcement multiplier: for F&B tier companies, signals with FSMA context
score 1.3x above the base value (enforcement is live post-Jan 20, 2026).

Intent score is added on top of contact priority_score at queue time.
Companies with intent_score >= 20 are considered "hot" and get prioritised.

The intent score is cached on companies.intent_score and refreshed via
recompute_all_intent_scores() or implicitly after each log_* / detect_* call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.database import Database

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Point values per signal type
# ------------------------------------------------------------------

SIGNAL_POINTS: dict[str, int] = {
    "job_posting": 15,
    "fda_warning_letter": 25,
    "fda_warning_letter_fsma": 45,   # FSMA 204 enforcement — highest-value signal
    "fda_recall": 20,
    "osha_citation": 15,
    "funding_event": 10,
    "linkedin_activity": 10,
}

MAX_INTENT_SCORE = 60   # raised from 50 to accommodate FSMA signal value
HOT_THRESHOLD = 20

# F&B tier prefixes — FSMA enforcement multiplier applies to these
_FB_TIER_PREFIXES = ("fb_", "fb1", "fb2", "fb3", "fb4")

# Signals that qualify for the FSMA enforcement multiplier on F&B companies
_FSMA_ENFORCEMENT_SIGNALS = frozenset({
    "fda_warning_letter_fsma", "fda_warning_letter", "fda_recall",
})

# ------------------------------------------------------------------
# Buyer-signal job titles (case-insensitive keyword matching)
# ------------------------------------------------------------------

BUYER_SIGNAL_TITLES: list[str] = [
    "maintenance engineer",
    "reliability engineer",
    "maintenance manager",
    "quality manager",
    "food safety manager",
    "quality engineer",
    "vp operations",
    "director of operations",
    "plant manager",
    "ehs manager",
    "safety manager",
    "maintenance supervisor",
    "predictive maintenance",
    "condition monitoring",
]

# Deduplicate job postings seen within this many days
_JOB_POSTING_DEDUP_DAYS = 7


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class IntentEngine:
    """Detects and scores buying intent signals for companies in the pipeline."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Job Posting Detection (Apollo)
    # ------------------------------------------------------------------

    def detect_job_postings(
        self,
        company_id: str,
        company_name: str,
        domain: str | None = None,
        apollo_org_id: str | None = None,
    ) -> list[dict]:
        """Search Apollo for buyer-signal job postings at this company.

        Uses the ApolloClient organizations/job_postings endpoint when an
        apollo_org_id is available, otherwise falls back to the people
        search (searching for the buyer-signal titles at the company).

        Deduplicates against existing signals in the last 7 days to
        avoid re-inserting the same posting on repeated scans.

        Returns a list of newly inserted signal dicts.
        """
        try:
            from backend.app.core.config import get_settings
            settings = get_settings()
            if not settings.apollo_api_key:
                logger.warning("[intent] APOLLO_API_KEY not set — skipping job posting scan")
                return []
        except Exception as exc:
            logger.warning(f"[intent] Could not load settings: {exc}")
            return []

        new_signals: list[dict] = []

        try:
            postings = self._fetch_apollo_job_postings(
                company_name=company_name,
                apollo_org_id=apollo_org_id,
            )
        except Exception as exc:
            logger.warning(
                f"[intent] Apollo job posting fetch failed for {company_name}: {exc}"
            )
            return []

        if not postings:
            logger.debug(f"[intent] No buyer-signal job postings found for {company_name}")
            return []

        # Check existing signals for dedup window
        cutoff = (_now_utc() - timedelta(days=_JOB_POSTING_DEDUP_DAYS)).isoformat()
        try:
            existing = (
                self.db.client.table("company_intent_signals")
                .select("signal_detail")
                .eq("company_id", company_id)
                .eq("signal_type", "job_posting")
                .eq("is_active", True)
                .gte("detected_at", cutoff)
                .execute()
                .data
            )
            existing_details = {r.get("signal_detail", "").lower() for r in existing}
        except Exception as exc:
            logger.warning(f"[intent] Could not fetch existing signals for dedup: {exc}")
            existing_details = set()

        for posting in postings:
            title = posting.get("title", "").strip()
            detail_key = title.lower()
            if detail_key in existing_details:
                logger.debug(f"[intent] Skipping duplicate posting '{title}' for {company_name}")
                continue

            signal = {
                "company_id": company_id,
                "signal_type": "job_posting",
                "signal_detail": title,
                "detected_at": _now_utc().isoformat(),
                "source": "apollo",
                "raw_data": posting,
                "is_active": True,
                "expires_at": None,
            }
            try:
                inserted = self.db.upsert_intent_signal(signal)
                new_signals.append(inserted)
                existing_details.add(detail_key)
            except Exception as exc:
                logger.warning(f"[intent] Failed to insert job posting signal: {exc}")

        if new_signals:
            logger.info(
                f"[intent] {len(new_signals)} new job posting signal(s) for {company_name}"
            )
            self._refresh_company_score(company_id)

        return new_signals

    def _fetch_apollo_job_postings(
        self,
        company_name: str,
        apollo_org_id: str | None,
    ) -> list[dict]:
        """Call Apollo to get job postings and filter for buyer-signal titles.

        Strategy:
        1. If apollo_org_id is available, call the organizations/jobs endpoint.
        2. Otherwise, search people by buyer-signal titles at the named company.

        Returns raw posting dicts that matched at least one buyer-signal keyword.
        """
        import httpx
        from backend.app.core.config import get_settings

        api_key = get_settings().apollo_api_key
        matched: list[dict] = []

        if apollo_org_id:
            # Prefer the dedicated org job postings endpoint (free, no credits)
            url = "https://api.apollo.io/api/v1/organizations/jobs"
            try:
                resp = httpx.get(
                    url,
                    params={"organization_id": apollo_org_id},
                    headers={"X-Api-Key": api_key, "Cache-Control": "no-cache"},
                    timeout=20.0,
                )
                resp.raise_for_status()
                data = resp.json()
                jobs: list[dict] = data.get("jobs", []) or data.get("job_postings", []) or []
                for job in jobs:
                    title = (job.get("title") or "").lower()
                    if any(keyword in title for keyword in BUYER_SIGNAL_TITLES):
                        matched.append({
                            "title": job.get("title", ""),
                            "url": job.get("url") or job.get("job_url"),
                            "posted_at": job.get("posted_at"),
                            "location": job.get("location"),
                            "apollo_org_id": apollo_org_id,
                        })
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 422:
                    # Org ID not recognised — fall through to people search
                    logger.debug(
                        f"[intent] Apollo org job postings 422 for org_id={apollo_org_id}, "
                        "falling back to people search"
                    )
                else:
                    raise

        if not matched:
            # Fallback: use people search for buyer-signal titles at this company
            # This does NOT consume credits (search_people is free)
            from backend.app.integrations.apollo import ApolloClient
            try:
                client = ApolloClient()
                results = client.search_people(
                    person_titles=BUYER_SIGNAL_TITLES[:10],  # Apollo limits payload
                    q_organization_name=company_name,
                    per_page=25,
                    page=1,
                )
                people = results.get("people", []) or []
                seen_titles: set[str] = set()
                for person in people:
                    title = (person.get("title") or "").strip()
                    title_lower = title.lower()
                    if title_lower in seen_titles:
                        continue
                    if any(keyword in title_lower for keyword in BUYER_SIGNAL_TITLES):
                        seen_titles.add(title_lower)
                        matched.append({
                            "title": title,
                            "url": person.get("linkedin_url"),
                            "posted_at": None,
                            "location": person.get("city"),
                            "source_type": "people_search",
                        })
                client.close()
            except Exception as exc:
                logger.warning(f"[intent] Apollo people search fallback failed: {exc}")

        return matched

    # ------------------------------------------------------------------
    # Manual signal loggers
    # ------------------------------------------------------------------

    def log_fda_warning_letter(
        self,
        company_id: str,
        company_name: str,
        letter_date: str,
        detail: str | None = None,
    ) -> dict:
        """Log an FDA warning letter for a company.

        Args:
            company_id: Company UUID.
            company_name: Company name (for log messages).
            letter_date: ISO date string of the letter (e.g. "2024-06-15").
            detail: Human-readable description (e.g. "FSMA 204 records violation").

        Returns:
            Inserted signal dict.
        """
        # Expires 24 months from the letter date
        try:
            issued = datetime.fromisoformat(letter_date).replace(tzinfo=timezone.utc)
        except Exception:
            issued = _now_utc()
        expires_at = (issued + timedelta(days=730)).isoformat()

        signal = {
            "company_id": company_id,
            "signal_type": "fda_warning_letter",
            "signal_detail": detail or f"FDA warning letter issued {letter_date}",
            "detected_at": _now_utc().isoformat(),
            "source": "manual",
            "raw_data": {"letter_date": letter_date},
            "is_active": True,
            "expires_at": expires_at,
        }
        result = self.db.upsert_intent_signal(signal)
        logger.info(f"[intent] FDA warning letter logged for {company_name}")
        self._refresh_company_score(company_id)
        return result

    def log_fda_warning_letter_fsma(
        self,
        company_id: str,
        company_name: str,
        letter_date: str,
        detail: str | None = None,
    ) -> dict:
        """Log an FSMA 204 / traceability-specific FDA warning letter.

        Scores 45 pts (vs 25 for a general warning letter) and gets a 1.3x
        multiplier when the company is an F&B tier, making this the highest-
        value single signal in the system for F&B prospects.

        Args:
            company_id: Company UUID.
            company_name: Company name (for log messages).
            letter_date: ISO date string of the letter (e.g. "2026-02-14").
            detail: Human-readable description (e.g. "FSMA 204 traceability records violation").
        """
        try:
            issued = datetime.fromisoformat(letter_date).replace(tzinfo=timezone.utc)
        except Exception:
            issued = _now_utc()
        expires_at = (issued + timedelta(days=730)).isoformat()

        signal = {
            "company_id": company_id,
            "signal_type": "fda_warning_letter_fsma",
            "signal_detail": detail or f"FSMA 204 warning letter issued {letter_date}",
            "detected_at": _now_utc().isoformat(),
            "source": "manual",
            "raw_data": {"letter_date": letter_date},
            "is_active": True,
            "expires_at": expires_at,
        }
        result = self.db.upsert_intent_signal(signal)
        logger.info(f"[intent] FSMA warning letter logged for {company_name}")
        self._refresh_company_score(company_id)
        return result

    def log_osha_citation(
        self,
        company_id: str,
        citation_date: str,
        detail: str | None = None,
    ) -> dict:
        """Log an OSHA citation for a company.

        Args:
            company_id: Company UUID.
            citation_date: ISO date string of the citation.
            detail: Description (e.g. "Lockout/tagout violation, $15K fine").

        Returns:
            Inserted signal dict.
        """
        try:
            issued = datetime.fromisoformat(citation_date).replace(tzinfo=timezone.utc)
        except Exception:
            issued = _now_utc()
        expires_at = (issued + timedelta(days=365)).isoformat()  # 12 months

        signal = {
            "company_id": company_id,
            "signal_type": "osha_citation",
            "signal_detail": detail or f"OSHA citation issued {citation_date}",
            "detected_at": _now_utc().isoformat(),
            "source": "manual",
            "raw_data": {"citation_date": citation_date},
            "is_active": True,
            "expires_at": expires_at,
        }
        result = self.db.upsert_intent_signal(signal)
        logger.info(f"[intent] OSHA citation logged for company {company_id}")
        self._refresh_company_score(company_id)
        return result

    def log_funding_event(
        self,
        company_id: str,
        amount: str | None = None,
        detail: str | None = None,
    ) -> dict:
        """Log a funding event for a company.

        Args:
            company_id: Company UUID.
            amount: Optional funding amount string (e.g. "$25M Series B").
            detail: Description (e.g. "Growth equity for plant expansion").

        Returns:
            Inserted signal dict.
        """
        now = _now_utc()
        expires_at = (now + timedelta(days=548)).isoformat()  # 18 months

        label = amount or "Funding event"
        description = detail or label

        signal = {
            "company_id": company_id,
            "signal_type": "funding_event",
            "signal_detail": description,
            "detected_at": now.isoformat(),
            "source": "manual",
            "raw_data": {"amount": amount},
            "is_active": True,
            "expires_at": expires_at,
        }
        result = self.db.upsert_intent_signal(signal)
        logger.info(f"[intent] Funding event logged for company {company_id}")
        self._refresh_company_score(company_id)
        return result

    def log_linkedin_activity(
        self,
        company_id: str,
        contact_id: str,
        detail: str,
    ) -> dict:
        """Log a LinkedIn buying signal (e.g. exec post about pain point).

        Args:
            company_id: Company UUID.
            contact_id: Contact UUID who posted / engaged.
            detail: What was observed (e.g. "VP Ops posted about unplanned downtime costs").

        Returns:
            Inserted signal dict.
        """
        signal = {
            "company_id": company_id,
            "signal_type": "linkedin_activity",
            "signal_detail": detail,
            "detected_at": _now_utc().isoformat(),
            "source": "manual",
            "raw_data": {"contact_id": contact_id},
            "is_active": True,
            "expires_at": None,  # Never expires
        }
        result = self.db.upsert_intent_signal(signal)
        logger.info(f"[intent] LinkedIn activity logged for company {company_id}")
        self._refresh_company_score(company_id)
        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_company_intent_score(self, company_id: str, company_tier: str | None = None) -> int:
        """Sum active intent signals and return the total score (capped at MAX_INTENT_SCORE).

        For F&B tier companies, FSMA-related signals carry a 1.3x multiplier —
        enforcement is live post-Jan 20, 2026 and urgency is materially higher.

        Also updates companies.intent_score, intent_score_updated_at, and
        last_intent_signal_at on the company record.

        Returns:
            The computed intent score (0–MAX_INTENT_SCORE).
        """
        signals = self.db.get_active_intent_signals(company_id)

        # Resolve tier if not passed in — needed for FSMA multiplier
        tier = company_tier or ""
        if not tier:
            try:
                row = (
                    self.db.client.table("companies")
                    .select("tier")
                    .eq("id", company_id)
                    .limit(1)
                    .execute()
                    .data or [{}]
                )[0]
                tier = row.get("tier") or ""
            except Exception:
                pass

        is_fb = any(tier.startswith(p) for p in _FB_TIER_PREFIXES)

        # Expire signals whose expires_at has passed
        now = _now_utc()
        active_signals: list[dict] = []
        to_expire: list[str] = []
        for s in signals:
            expires_at = s.get("expires_at")
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(
                        expires_at.replace("Z", "+00:00")
                    )
                    if exp_dt < now:
                        to_expire.append(s["id"])
                        continue
                except Exception:
                    pass
            active_signals.append(s)

        # Deactivate expired signals in DB
        for sid in to_expire:
            try:
                self.db.client.table("company_intent_signals").update(
                    {"is_active": False}
                ).eq("id", sid).execute()
            except Exception as exc:
                logger.warning(f"[intent] Failed to deactivate expired signal {sid}: {exc}")

        # Sum points — apply FSMA multiplier for F&B companies
        raw_score = 0
        for s in active_signals:
            pts = SIGNAL_POINTS.get(s.get("signal_type", ""), 0)
            if is_fb and s.get("signal_type") in _FSMA_ENFORCEMENT_SIGNALS:
                pts = int(pts * 1.3)
            raw_score += pts

        score = min(raw_score, MAX_INTENT_SCORE)

        # Update company record
        self.db.update_company_intent_score(company_id, score)

        return score

    def recompute_all_intent_scores(self, campaign_name: str | None = None) -> dict:
        """Recompute intent scores for all companies in the pipeline.

        Args:
            campaign_name: Optional filter to limit to one campaign.

        Returns:
            Dict with keys 'updated' and 'total_signals'.
        """
        companies = self.db.get_companies_for_intent_scan(campaign_name=campaign_name)
        updated = 0
        total_signals = 0

        for company in companies:
            cid = company["id"]
            tier = company.get("tier") or ""
            try:
                signals = self.db.get_active_intent_signals(cid)
                total_signals += len(signals)
                self.compute_company_intent_score(cid, company_tier=tier)
                updated += 1
            except Exception as exc:
                logger.warning(
                    f"[intent] Failed to recompute score for company {cid}: {exc}"
                )

        logger.info(
            f"[intent] Recomputed intent scores for {updated} companies "
            f"({total_signals} active signals total)"
        )
        return {"updated": updated, "total_signals": total_signals}

    def get_hot_companies(self, min_intent_score: int = HOT_THRESHOLD) -> list[dict]:
        """Return companies with intent_score >= threshold, ordered by score descending."""
        result = (
            self.db.client.table("companies")
            .select("id, name, domain, campaign_name, tier, intent_score, last_intent_signal_at")
            .gte("intent_score", min_intent_score)
            .order("intent_score", desc=True)
            .execute()
        )
        return result.data or []

    def run_job_posting_scan(self, campaign_name: str | None = None) -> dict:
        """Scan all pipeline companies for new buyer-signal job postings via Apollo.

        Iterates all companies (filtered by campaign_name when provided),
        calls detect_job_postings for each, deduplicates, and refreshes intent scores.

        Returns:
            Summary dict: {scanned, new_signals, companies_boosted}.
        """
        companies = self.db.get_companies_for_intent_scan(campaign_name=campaign_name)
        scanned = 0
        new_signals = 0
        companies_boosted = 0

        for company in companies:
            cid = company["id"]
            name = company.get("name", "Unknown")
            domain = company.get("domain")
            apollo_org_id = company.get("apollo_org_id") or company.get("apollo_id")

            try:
                signals = self.detect_job_postings(
                    company_id=cid,
                    company_name=name,
                    domain=domain,
                    apollo_org_id=apollo_org_id,
                )
                scanned += 1
                if signals:
                    new_signals += len(signals)
                    companies_boosted += 1
            except Exception as exc:
                logger.warning(f"[intent] Job scan failed for {name}: {exc}")
                scanned += 1  # Still count as scanned

        logger.info(
            f"[intent] Job posting scan complete — scanned={scanned}, "
            f"new_signals={new_signals}, companies_boosted={companies_boosted}"
        )
        return {
            "scanned": scanned,
            "new_signals": new_signals,
            "companies_boosted": companies_boosted,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_company_score(self, company_id: str) -> None:
        """Recompute and persist intent score for a single company (best-effort)."""
        try:
            self.compute_company_intent_score(company_id)
        except Exception as exc:
            logger.warning(f"[intent] Could not refresh intent score for {company_id}: {exc}")
