"""FDA Warning Letter Scraper — FSMA 204 enforcement signal.

Scrapes FDA warning letters issued to food & beverage companies and classifies
them as either FSMA-specific (fda_warning_letter_fsma) or general food safety
(fda_warning_letter), based on subject-line keyword matching.

Why this matters vs. the FDA recall scraper:
  - Recalls = product/quality failure (reactive)
  - Warning letters = FDA has formally cited the facility (regulatory relationship)
  - FSMA warning letters post Jan-20-2026 = direct signal that a company is
    under active enforcement pressure for the exact problem Digitillis solves

Half-life: 90 days (shorter than recall 180d — enforcement windows typically
resolve within one FDA inspection cycle after the letter).

Signal types emitted:
  - fda_warning_letter_fsma  (45 pts) — FSMA 204 / traceability / recordkeeping
  - fda_warning_letter       (25 pts) — other food safety violations

Data source: FDA RSS feed + openFDA other/warning_letters endpoint (fallback).

Runs weekly via scheduler. Deduplication by letter URL slug or posted date + firm.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)

# FDA warning letters RSS — published in near-real-time, no auth required
FDA_WL_RSS_URL = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/warning-letters/rss.xml"

# openFDA other/warning_letters endpoint (covers broader history)
FDA_WL_API_URL = "https://api.fda.gov/other/warning_letters.json"

DECAY_HALF_LIFE_FSMA = 90   # days — FSMA enforcement window
DECAY_HALF_LIFE_GENERAL = 120  # days — general food safety letter

# FSMA 204 / traceability keywords — any match → fda_warning_letter_fsma
_FSMA_KEYWORDS = frozenset({
    "traceability", "section 204", "fsma 204", "204(d)", "food traceability list",
    "critical tracking event", "key data element", "cte", "kde",
    "1-step forward", "1-step back", "one step forward", "one step back",
    "recordkeeping", "records access", "21 cfr part 1", "part 1 subpart s",
    "supply chain traceability", "lot code traceability",
})

# Food safety subject keywords — must be present to process (skip non-food letters)
_FOOD_SUBJECT_KEYWORDS = frozenset({
    "food", "beverage", "dairy", "seafood", "produce", "meat", "poultry",
    "juice", "infant formula", "dietary supplement", "allergen", "sanitation",
    "haccp", "cgmp", "current good manufacturing", "adulterated",
    "misbranded", "foreign matter", "listeria", "salmonella", "e. coli",
    "ready-to-eat", "rte", "pasteurization", "fsma",
})


def _is_fsma_letter(subject: str, body: str) -> bool:
    combined = (subject + " " + body).lower()
    return any(kw in combined for kw in _FSMA_KEYWORDS)


def _is_food_letter(subject: str, body: str) -> bool:
    combined = (subject + " " + body).lower()
    return any(kw in combined for kw in _FOOD_SUBJECT_KEYWORDS)


class FDAWarningLetterScraper:
    def __init__(self, db: Any):
        self._db = db

    def run(self, days_back: int = 90, limit: int = 100) -> dict:
        """Fetch recent FDA warning letters and match to F&B companies in DB.

        Tries RSS feed first (most recent ~50 letters); falls back to openFDA
        API for broader date range. Only processes food/beverage-related letters.

        Returns:
            Dict with processed, matched, skipped, fsma_signals, general_signals counts.
        """
        result = {
            "processed": 0, "matched": 0, "skipped": 0,
            "fsma_signals": 0, "general_signals": 0, "errors": 0,
        }

        letters = self._fetch_letters_rss(days_back=days_back)
        if not letters:
            letters = self._fetch_letters_api(days_back=days_back, limit=limit)

        logger.info("FDA warning letter scraper: fetched %d letters", len(letters))

        for letter in letters:
            result["processed"] += 1
            try:
                firm_name = letter.get("firm_name") or letter.get("company_name", "")
                subject = letter.get("subject", "")
                issued_at = letter.get("issued_at")
                source_id = letter.get("source_id", "")
                source_url = letter.get("source_url")
                city = letter.get("city", "")
                state = letter.get("state", "")
                body_excerpt = letter.get("body_excerpt", "")

                if not firm_name:
                    result["skipped"] += 1
                    continue

                # Only process food / beverage letters
                if not _is_food_letter(subject, body_excerpt):
                    result["skipped"] += 1
                    continue

                company_id = self._match_company(firm_name, city, state)
                if not company_id:
                    result["skipped"] += 1
                    continue

                # Classify: FSMA-specific or general food safety
                is_fsma = _is_fsma_letter(subject, body_excerpt)
                signal_type = "fda_warning_letter_fsma" if is_fsma else "fda_warning_letter"
                decay = DECAY_HALF_LIFE_FSMA if is_fsma else DECAY_HALF_LIFE_GENERAL

                signal_text = (
                    f"FDA warning letter ({signal_type}): {firm_name} — "
                    f"{subject[:200] if subject else 'subject unknown'}."
                )

                self._upsert_signal(
                    company_id=company_id,
                    signal_type=signal_type,
                    source="fda",
                    source_id=source_id,
                    signal_text=signal_text,
                    observed_at=issued_at,
                    decay=decay,
                    source_url=source_url,
                    value={
                        "firm_name": firm_name,
                        "subject": subject,
                        "city": city,
                        "state": state,
                        "is_fsma": is_fsma,
                    },
                )
                result["matched"] += 1
                if is_fsma:
                    result["fsma_signals"] += 1
                else:
                    result["general_signals"] += 1

            except Exception as e:
                logger.warning("Error processing warning letter: %s", e)
                result["errors"] += 1

        logger.info(
            "FDA WL scraper complete: %d processed, %d matched (%d fsma / %d general), "
            "%d skipped, %d errors",
            result["processed"], result["matched"], result["fsma_signals"],
            result["general_signals"], result["skipped"], result["errors"],
        )
        return result

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    def _fetch_letters_rss(self, days_back: int = 90) -> list[dict]:
        """Parse the FDA warning letters RSS feed."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        letters: list[dict] = []

        try:
            import httpx
            resp = httpx.get(FDA_WL_RSS_URL, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            logger.warning("FDA WL RSS fetch failed: %s", e)
            return []

        # Minimal XML parse — avoids lxml/defusedxml dependency
        items = re.findall(r"<item>(.*?)</item>", content, re.DOTALL)
        for item in items:
            try:
                title = _xml_text(item, "title")
                link = _xml_text(item, "link")
                pub_date_str = _xml_text(item, "pubDate")
                description = _xml_text(item, "description")

                # Parse pub date
                issued_at = None
                if pub_date_str:
                    try:
                        dt = parsedate_to_datetime(pub_date_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue  # Too old
                        issued_at = dt.isoformat()
                    except Exception:
                        pass

                # Extract firm name and state from title pattern:
                # "Company Name, City, State 00/00/00" or "Company Name 00/00/00"
                firm_name, city, state = _parse_wl_title(title)

                source_id = _slug_from_url(link) if link else f"wl-{hash(title)}"

                letters.append({
                    "firm_name": firm_name,
                    "subject": title or "",
                    "body_excerpt": (description or "")[:500],
                    "issued_at": issued_at,
                    "source_id": source_id,
                    "source_url": link,
                    "city": city,
                    "state": state,
                })
            except Exception as e:
                logger.debug("RSS item parse error: %s", e)

        logger.debug("FDA WL RSS: parsed %d items", len(letters))
        return letters

    def _fetch_letters_api(self, days_back: int = 90, limit: int = 100) -> list[dict]:
        """Fetch from openFDA other/warning_letters endpoint (broader history)."""
        letters: list[dict] = []
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d")

        try:
            import httpx
            params = {
                "search": f"date_posted:[{since}+TO+99999999]",
                "limit": min(limit, 100),
                "sort": "date_posted:desc",
            }
            resp = httpx.get(FDA_WL_API_URL, params=params, timeout=30)
            if resp.status_code in (404, 422):
                # Endpoint not available for this openFDA instance
                logger.debug("openFDA warning_letters endpoint returned %d", resp.status_code)
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("FDA WL API fetch failed: %s", e)
            return []

        for record in data.get("results", []):
            try:
                firm_name = record.get("company_name") or record.get("recalling_firm", "")
                subject = record.get("subject") or record.get("letter_subject", "")
                issued_str = record.get("date_posted") or record.get("letter_date", "")
                issued_at = None
                if issued_str and len(issued_str) == 8:
                    try:
                        issued_at = datetime.strptime(issued_str, "%Y%m%d").replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                    except ValueError:
                        pass
                elif issued_str:
                    try:
                        issued_at = datetime.fromisoformat(issued_str).isoformat()
                    except ValueError:
                        pass

                letters.append({
                    "firm_name": firm_name,
                    "subject": subject,
                    "body_excerpt": record.get("body", "")[:500],
                    "issued_at": issued_at,
                    "source_id": record.get("id") or record.get("recall_number", ""),
                    "source_url": record.get("url"),
                    "city": record.get("city", ""),
                    "state": record.get("state", ""),
                })
            except Exception as e:
                logger.debug("API record parse error: %s", e)

        return letters

    # ------------------------------------------------------------------
    # Company matching — mirrors fda_scraper.py pattern
    # ------------------------------------------------------------------

    def _match_company(self, firm_name: str, city: str, state: str) -> str | None:
        if not firm_name:
            return None
        firm_lower = firm_name.lower().strip()
        for suffix in (" llc", " inc", " corp", " company", " co.", " ltd", " limited",
                       " foods", " food", " industries", " group", " farms", " processing"):
            firm_lower = firm_lower.replace(suffix, "")
        firm_lower = firm_lower.strip(" ,.")

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
                .ilike("name", f"%{firm_lower[:40]}%")
                .limit(5)
                .execute()
                .data or []
            )
            hit = _best(rows)
            if hit:
                return hit

            for kw in [w for w in firm_lower.split() if len(w) >= 5][:2]:
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
            logger.warning("Company match failed for %r: %s", firm_name, e)
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _upsert_signal(
        self, company_id: str, signal_type: str, source: str, source_id: str,
        signal_text: str, value: dict, observed_at: str | None,
        decay: int, source_url: str | None,
    ) -> None:
        workspace_id = getattr(self._db, "workspace_id", None)
        row: dict = {
            "company_id": company_id,
            "signal_type": signal_type,
            "source": source,
            "source_id": source_id,
            "signal_text": signal_text,
            "value": value,
            "decay_half_life_days": decay,
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
            logger.warning("Could not upsert FDA WL signal for company %s: %s", company_id, e)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _xml_text(xml: str, tag: str) -> str:
    """Extract first occurrence of <tag>text</tag> from an XML fragment."""
    m = re.search(rf"<{tag}[^>]*>(<!\[CDATA\[)?(.*?)(\]\]>)?</{tag}>", xml, re.DOTALL)
    return m.group(2).strip() if m else ""


def _parse_wl_title(title: str) -> tuple[str, str, str]:
    """Extract (firm_name, city, state) from an FDA warning letter title.

    Typical formats:
      "Acme Foods, Inc., Chicago, IL 01/15/26"
      "Acme Dairy LLC 02/28/26"
      "Acme Seafood Processing (Close-Out) 03/10/26"
    """
    if not title:
        return "", "", ""
    # Strip trailing date (MM/DD/YY or MM/DD/YYYY)
    clean = re.sub(r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", "", title).strip()
    # Strip parenthetical suffixes like (Close-Out)
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", clean).strip()

    parts = [p.strip() for p in clean.split(",")]
    if len(parts) >= 3:
        firm = parts[0]
        city = parts[-2]
        state_raw = parts[-1].strip()
        state = state_raw[:2].upper() if len(state_raw) >= 2 else state_raw
        return firm, city, state
    elif len(parts) == 2:
        return parts[0], "", parts[1][:2].upper()
    return clean, "", ""


def _slug_from_url(url: str) -> str:
    """Extract a stable identifier from an FDA warning letter URL."""
    if not url:
        return ""
    # URLs are typically .../warning-letters/company-name-YYMMDD
    slug = url.rstrip("/").split("/")[-1]
    return slug[:100]
