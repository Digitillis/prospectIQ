"""OSHA Citation Signal Scraper — manufacturing reliability targeting signal.

Pulls OSHA inspection and citation data via the public OSHA Enforcement API.
OSHA citations at manufacturing plants directly signal:
  - Maintenance / reliability gaps (machine guarding, lockout-tagout failures)
  - Process safety failures (PSM citations)
  - Equipment condition issues (citation descriptions often name specific assets)

These are high-value targeting signals for predictive maintenance outreach.
Half-life: 120 days (OSHA abatement windows are typically 30-90 days).

NAICS codes targeted (manufacturing):
  31-33 — all manufacturing
  311x  — food manufacturing (primary for F&B vertical)
  332x  — fabricated metal products
  333x  — machinery manufacturing

Uses the DOL OSHA public enforcement dataset.
API: https://enforcements.dol.gov/api/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

OSHA_ESTABLISHMENTS_URL = "https://data.dol.gov/get/full_inspection/rows/100/offset/0/format/json"
OSHA_API_URL = "https://enforcements.dol.gov/api/2/full_inspection.json"
DECAY_HALF_LIFE = 120  # days

# NAICS prefixes to filter (manufacturing sectors)
TARGET_NAICS_PREFIXES = ("31", "32", "33")


class OSHACitationScraper:
    def __init__(self, db: Any):
        self._db = db

    def run(self, days_back: int = 60, limit: int = 200) -> dict:
        """Fetch recent OSHA inspections with citations for manufacturing NAICSs.

        Args:
            days_back: How many days back to search for inspections.
            limit: Max records per request.

        Returns:
            Dict with processed, matched, skipped, errors counts.
        """
        result = {"processed": 0, "matched": 0, "skipped": 0, "errors": 0}

        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        try:
            import httpx
            # DOL public API — no key required
            params = {
                "date_opened": f">{since}",
                "nr_in_viol_penalty": ">0",  # has citations with penalties
                "limit": limit,
            }
            resp = httpx.get(OSHA_API_URL, params=params, timeout=60)
            if resp.status_code == 404:
                # API endpoint changed — fall back gracefully
                logger.warning("OSHA API returned 404 — endpoint may have changed")
                return result
            resp.raise_for_status()
            records = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
        except Exception as e:
            logger.error("OSHA API request failed: %s", e)
            result["errors"] += 1
            return result

        logger.info("OSHA scraper: fetched %d inspection records", len(records))

        for record in records:
            result["processed"] += 1
            try:
                naics = str(record.get("naics_code", "") or "")
                if not any(naics.startswith(p) for p in TARGET_NAICS_PREFIXES):
                    result["skipped"] += 1
                    continue

                est_name = record.get("establishment_name", "")
                city = record.get("site_city", "")
                state = record.get("site_state", "")
                activity_nr = str(record.get("activity_nr", "") or "")
                nr_viol = record.get("nr_in_viol_penalty", 0)
                penalty = record.get("total_penalty", 0)
                date_opened = record.get("date_opened", "")
                citation_types = record.get("citation_types", "")

                if not est_name:
                    result["skipped"] += 1
                    continue

                company_id = self._match_company(est_name, city, state)
                if not company_id:
                    result["skipped"] += 1
                    continue

                observed_at = None
                if date_opened:
                    try:
                        observed_at = datetime.fromisoformat(date_opened).replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                    except ValueError:
                        pass

                signal_text = (
                    f"OSHA inspection: {est_name} ({city}, {state}) — "
                    f"{nr_viol} violations, ${penalty:,} penalty. "
                    f"Citation types: {citation_types or 'unspecified'}."
                )

                self._upsert_signal(
                    company_id=company_id,
                    signal_type="osha_citation",
                    source="osha",
                    source_id=activity_nr,
                    signal_text=signal_text,
                    value={
                        "establishment_name": est_name,
                        "naics_code": naics,
                        "nr_violations": nr_viol,
                        "total_penalty": penalty,
                        "citation_types": citation_types,
                        "city": city,
                        "state": state,
                    },
                    observed_at=observed_at,
                    source_url="https://www.osha.gov/ords/imis/establishment.html",
                )
                result["matched"] += 1

            except Exception as e:
                logger.warning("Error processing OSHA record: %s", e)
                result["errors"] += 1

        logger.info(
            "OSHA scraper complete: %d processed, %d matched, %d skipped, %d errors",
            result["processed"], result["matched"], result["skipped"], result["errors"],
        )
        return result

    def _match_company(self, establishment_name: str, city: str, state: str) -> str | None:
        if not establishment_name:
            return None
        name_lower = establishment_name.lower().strip()
        for suffix in (" llc", " inc", " corp", " company", " co.", " ltd", " limited",
                       " manufacturing", " industries", " group"):
            name_lower = name_lower.replace(suffix, "")
        name_lower = name_lower.strip(" ,.")

        def _best(rows: list) -> str | None:
            if not rows:
                return None
            if state:
                for row in rows:
                    if (row.get("hq_state") or row.get("state") or "").upper() == state.upper():
                        return row["id"]
            return rows[0]["id"]

        try:
            rows = (
                self._db.client.table("companies")
                .select("id,name,domain,hq_state,state")
                .ilike("name", f"%{name_lower[:40]}%")
                .limit(5)
                .execute()
                .data or []
            )
            hit = _best(rows)
            if hit:
                return hit
            # Domain keyword fallback
            for kw in [w for w in name_lower.split() if len(w) >= 5][:2]:
                rows = (
                    self._db.client.table("companies")
                    .select("id,name,domain,hq_state,state")
                    .ilike("domain", f"%{kw}%")
                    .limit(5)
                    .execute()
                    .data or []
                )
                hit = _best(rows)
                if hit:
                    return hit
        except Exception as e:
            logger.warning("Company match failed for %r: %s", establishment_name, e)
        return None

    def _upsert_signal(self, company_id: str, signal_type: str, source: str,
                       source_id: str, signal_text: str, value: dict,
                       observed_at: str | None, source_url: str | None) -> None:
        workspace_id = getattr(self._db, "workspace_id", None)
        row: dict = {
            "company_id": company_id,
            "signal_type": signal_type,
            "source": source,
            "source_id": source_id,
            "signal_text": signal_text,
            "value": value,
            "decay_half_life_days": DECAY_HALF_LIFE,
            "source_url": source_url,
        }
        if observed_at:
            row["observed_at"] = observed_at
        if workspace_id:
            row["workspace_id"] = workspace_id
        try:
            self._db.client.table("company_signals").upsert(
                row, on_conflict="company_id,source,source_id"
            ).execute()
        except Exception as e:
            logger.warning("Could not upsert OSHA signal for company %s: %s", company_id, e)
