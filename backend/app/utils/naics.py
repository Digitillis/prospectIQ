"""NAICS code utilities for manufacturing sub-sector classification."""

from backend.app.core.config import get_manufacturing_ontology


def classify_sub_sector(naics_code: str | None, industry: str | None = None) -> dict:
    """Classify a company's manufacturing sub-sector from NAICS code.

    Args:
        naics_code: NAICS code string (e.g., '333', '3364', '332710')
        industry: Industry string from Apollo (fallback classification)

    Returns:
        Dict with: tier, label, sub_sector, digitillis_fit, common_equipment
    """
    result = {
        "tier": None,
        "label": None,
        "sub_sector": None,
        "digitillis_fit": "unknown",
        "common_equipment": [],
    }

    if not naics_code:
        # Try to classify from industry string
        if industry:
            return _classify_from_industry(industry)
        return result

    ontology = get_manufacturing_ontology()
    naics_map = ontology.get("naics_mapping", {})

    # Try exact match first, then progressively shorter prefixes
    code = str(naics_code).strip()
    for prefix_len in [len(code), 4, 3]:
        prefix = code[:prefix_len]
        if prefix in naics_map:
            mapping = naics_map[prefix]
            result["tier"] = mapping.get("tier")
            result["label"] = mapping.get("label")
            result["sub_sector"] = mapping.get("sub_sectors", [None])[0]
            result["digitillis_fit"] = mapping.get("digitillis_fit", "unknown")
            result["common_equipment"] = mapping.get("common_equipment", [])
            return result

    return result


def _classify_from_industry(industry: str) -> dict:
    """Fallback classification from Apollo's industry string."""
    industry_lower = industry.lower()

    # Mapping of industry keywords to tiers
    keyword_tiers = {
        "machinery": ("1a", "Industrial Machinery & Heavy Equipment"),
        "industrial": ("1a", "Industrial Machinery & Heavy Equipment"),
        "automotive": ("1b", "Automotive Parts & Components"),
        "motor vehicle": ("1b", "Automotive Parts & Components"),
        "metal": ("2", "Metal Fabrication & Precision Machining"),
        "fabricat": ("2", "Metal Fabrication & Precision Machining"),
        "plastics": ("3", "Plastics & Injection Molding"),
        "rubber": ("3", "Plastics & Injection Molding"),
        "semiconductor": ("4", "Electronics Assembly & Semiconductor"),
        "electronic": ("4", "Electronics Assembly & Semiconductor"),
        "computer hardware": ("4", "Electronics Assembly & Semiconductor"),
        "aerospace": ("5", "Aerospace Components"),
        "aviation": ("5", "Aerospace Components"),
        "defense": ("5", "Aerospace Components"),
    }

    for keyword, (tier, label) in keyword_tiers.items():
        if keyword in industry_lower:
            return {
                "tier": tier,
                "label": label,
                "sub_sector": None,
                "digitillis_fit": "medium",
                "common_equipment": [],
            }

    # If it contains "manufacturing" but doesn't match specific sectors
    if "manufactur" in industry_lower:
        return {
            "tier": "2",
            "label": "General Manufacturing",
            "sub_sector": None,
            "digitillis_fit": "medium",
            "common_equipment": [],
        }

    return {
        "tier": None,
        "label": None,
        "sub_sector": None,
        "digitillis_fit": "unknown",
        "common_equipment": [],
    }


def is_manufacturing_naics(naics_code: str | None) -> bool:
    """Check if a NAICS code falls within manufacturing (31-33)."""
    if not naics_code:
        return False
    code = str(naics_code).strip()
    return code[:2] in ("31", "32", "33")
