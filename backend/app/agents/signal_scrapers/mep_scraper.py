"""MEP Grant Signal Scraper — modernization investment targeting signal.

Manufacturing Extension Partnership (MEP) is an NIST program that funds
small/mid-size manufacturers to modernize operations. A company receiving
an MEP engagement signals:
  - Active modernization investment (budget is moving)
  - Leadership that is receptive to new technology
  - NIST MEP centers are often the first stop before a larger digital investment

Source: NIST MEP public impact data (published annually).
NIST also publishes a directory of MEP Center contacts.

Half-life: 365 days — MEP engagements signal a multi-year modernization posture.

Note: NIST MEP does not publish a real-time API. This scraper fetches from the
annual impact data CSV and the MEP Center directory. Run annually or when NIST
releases new data. The scraper also accepts a manual CSV path for fresh data.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Public NIST MEP annual impact data (company-level, published annually)
MEP_IMPACT_CSV_URL = "https://www.nist.gov/system/files/documents/2024/05/01/mep-national-network-fy2023-client-impact.csv"
DECAY_HALF_LIFE = 365  # days


class MEPGrantScraper:
    def __init__(self, db: Any):
        self._db = db

    def run(self, csv_path: str | None = None) -> dict:
        """Fetch MEP client impact data and match to companies in DB.

        Args:
            csv_path: Local path to MEP CSV (overrides URL fetch).
                      Use this when NIST has updated the annual release
                      and you've downloaded the new file manually.

        Returns:
            Dict with processed, matched, skipped, errors counts.
        """
        result = {"processed": 0, "matched": 0, "skipped": 0, "errors": 0}

        # Load data from local file or URL
        rows: list[dict] = []
        if csv_path and Path(csv_path).exists():
            rows = self._load_csv_file(csv_path)
        else:
            rows = self._fetch_csv_url()

        if not rows:
            logger.warning("MEP scraper: no data loaded")
            return result

        logger.info("MEP scraper: processing %d records", len(rows))

        for row in rows:
            result["processed"] += 1
            try:
                company_name = row.get("company_name") or row.get("client_name") or row.get("Company") or ""
                state = row.get("state") or row.get("State") or ""
                mep_center = row.get("center_name") or row.get("Center") or ""
                fiscal_year = row.get("fiscal_year") or row.get("FY") or ""
                investment = row.get("client_investment") or row.get("Investment") or ""

                if not company_name:
                    result["skipped"] += 1
                    continue

                company_id = self._match_company(company_name, state)
                if not company_id:
                    result["skipped"] += 1
                    continue

                signal_text = (
                    f"MEP engagement: {company_name} ({state}) received NIST MEP services "
                    f"from {mep_center or 'MEP Center'}"
                    + (f" in FY{fiscal_year}" if fiscal_year else "")
                    + (f" — client investment: ${investment}" if investment else "")
                    + ". Signals active modernization investment."
                )

                source_id = f"{company_name.lower()[:30]}_{state}_{fiscal_year}"

                self._upsert_signal(
                    company_id=company_id,
                    signal_type="mep_grant",
                    source="mep",
                    source_id=source_id,
                    signal_text=signal_text,
                    value={
                        "company_name": company_name,
                        "state": state,
                        "mep_center": mep_center,
                        "fiscal_year": fiscal_year,
                        "client_investment": investment,
                    },
                    observed_at=None,
                    source_url="https://www.nist.gov/mep",
                )
                result["matched"] += 1

            except Exception as e:
                logger.warning("Error processing MEP row: %s", e)
                result["errors"] += 1

        logger.info(
            "MEP scraper complete: %d processed, %d matched, %d skipped, %d errors",
            result["processed"], result["matched"], result["skipped"], result["errors"],
        )
        return result

    def _load_csv_file(self, path: str) -> list[dict]:
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        except Exception as e:
            logger.error("Could not read MEP CSV from %s: %s", path, e)
            return []

    def _fetch_csv_url(self) -> list[dict]:
        try:
            import httpx
            resp = httpx.get(MEP_IMPACT_CSV_URL, timeout=60, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning("MEP CSV URL returned %s — data may have moved", resp.status_code)
                return []
            return list(csv.DictReader(io.StringIO(resp.text)))
        except Exception as e:
            logger.warning("Could not fetch MEP CSV from URL: %s", e)
            return []

    def _match_company(self, company_name: str, state: str) -> str | None:
        name_lower = company_name.lower().strip()
        for suffix in (" llc", " inc", " corp", " company", " co.", " ltd", " limited"):
            name_lower = name_lower.replace(suffix, "")
        name_lower = name_lower.strip(" ,.")
        if len(name_lower) < 3:
            return None

        try:
            rows = (
                self._db.client.table("companies")
                .select("id,name,hq_state")
                .ilike("name", f"%{name_lower[:40]}%")
                .limit(5)
                .execute()
                .data or []
            )
            if not rows:
                return None
            if state:
                for row in rows:
                    if (row.get("hq_state") or "").upper() == state.upper():
                        return row["id"]
            return rows[0]["id"]
        except Exception as e:
            logger.warning("Company match failed for %r: %s", company_name, e)
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
            "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        }
        if workspace_id:
            row["workspace_id"] = workspace_id
        try:
            self._db.client.table("company_signals").upsert(
                row, on_conflict="company_id,source,source_id"
            ).execute()
        except Exception as e:
            logger.warning("Could not upsert MEP signal for company %s: %s", company_id, e)
