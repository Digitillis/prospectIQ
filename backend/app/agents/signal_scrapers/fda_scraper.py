"""FDA Recall Signal Scraper — food & beverage targeting signal.

Pulls FDA food enforcement actions and recall announcements via the
openFDA public API (no key required for reasonable volumes).

Why this matters: an FDA recall is a direct signal that a food/bev plant
has a process control or quality problem right now. It is the highest-quality
targeting signal for the F&B vertical because:
  1. It is public and verifiable — no fabrication risk
  2. It is time-sensitive — plants in active remediation have budget urgency
  3. Competitors using Apollo alone cannot see it

Half-life: 180 days (remediation windows typically 3-6 months post-recall).

Runs weekly via scheduler. Deduplication by openfda recall_number.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

FDA_ENFORCEMENT_URL = "https://api.fda.gov/food/enforcement.json"
DECAY_HALF_LIFE = 180  # days


class FDARecallScraper:
    def __init__(self, db: Any):
        self._db = db

    def run(self, days_back: int = 90, limit: int = 100) -> dict:
        """Fetch recent FDA food enforcement actions and match to companies in DB.

        Args:
            days_back: How many days back to search.
            limit: Max records per API call (max 100 for openFDA).

        Returns:
            Dict with processed, matched, skipped counts.
        """
        result = {"processed": 0, "matched": 0, "skipped": 0, "errors": 0}

        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d")

        try:
            import httpx
            params = {
                "search": f"report_date:[{since}+TO+99999999]",
                "limit": limit,
                "sort": "report_date:desc",
            }
            resp = httpx.get(FDA_ENFORCEMENT_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("FDA API request failed: %s", e)
            result["errors"] += 1
            return result

        records = data.get("results", [])
        logger.info("FDA scraper: fetched %d enforcement records", len(records))

        for record in records:
            result["processed"] += 1
            try:
                recall_number = record.get("recall_number", "")
                firm_name = record.get("recalling_firm", "")
                city = record.get("city", "")
                state = record.get("state", "")
                reason = record.get("reason_for_recall", "")
                product = record.get("product_description", "")
                report_date = record.get("report_date", "")
                status = record.get("status", "")

                if not firm_name:
                    result["skipped"] += 1
                    continue

                # Try to match to a company in our DB by name similarity
                company_id = self._match_company(firm_name, city, state)
                if not company_id:
                    result["skipped"] += 1
                    continue

                # Format report_date to ISO
                observed_at = None
                if report_date and len(report_date) == 8:
                    try:
                        observed_at = datetime.strptime(report_date, "%Y%m%d").replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                    except ValueError:
                        pass

                signal_text = (
                    f"FDA recall ({status}): {firm_name} — {reason[:200] if reason else 'reason unknown'}. "
                    f"Product: {product[:100] if product else 'unspecified'}."
                )

                self._upsert_signal(
                    company_id=company_id,
                    signal_type="fda_recall",
                    source="fda",
                    source_id=recall_number,
                    signal_text=signal_text,
                    observed_at=observed_at,
                    value={
                        "recall_number": recall_number,
                        "firm_name": firm_name,
                        "reason": reason,
                        "product": product,
                        "status": status,
                        "city": city,
                        "state": state,
                    },
                    source_url=f"https://www.accessdata.fda.gov/scripts/enforcement/enforce_rpt-Product-Tabs.cfm",
                )
                result["matched"] += 1

            except Exception as e:
                logger.warning("Error processing FDA record %s: %s", record.get("recall_number"), e)
                result["errors"] += 1

        logger.info(
            "FDA scraper complete: %d processed, %d matched, %d skipped, %d errors",
            result["processed"], result["matched"], result["skipped"], result["errors"],
        )
        return result

    def _match_company(self, firm_name: str, city: str, state: str) -> str | None:
        """Fuzzy match firm name to companies in DB. Returns company_id or None."""
        if not firm_name:
            return None

        # Normalize firm name for search
        firm_lower = firm_name.lower().strip()
        # Remove common suffixes that differ between FDA records and CRM names
        for suffix in (" llc", " inc", " corp", " company", " co.", " ltd", " limited"):
            firm_lower = firm_lower.replace(suffix, "")
        firm_lower = firm_lower.strip(" ,.")

        try:
            # Search by partial name match — Supabase ilike
            rows = (
                self._db.client.table("companies")
                .select("id,name,hq_city,hq_state")
                .ilike("name", f"%{firm_lower[:40]}%")
                .limit(5)
                .execute()
                .data or []
            )

            if not rows:
                return None

            # Prefer city+state match when multiple candidates
            if state:
                for row in rows:
                    if (row.get("hq_state") or "").upper() == state.upper():
                        return row["id"]

            # Fall back to first name match
            return rows[0]["id"]

        except Exception as e:
            logger.warning("Company match failed for %r: %s", firm_name, e)
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
            logger.warning("Could not upsert FDA signal for company %s: %s", company_id, e)
