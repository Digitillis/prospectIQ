"""Settings routes — expose YAML configuration to the dashboard."""

from fastapi import APIRouter, HTTPException

from backend.app.core.config import get_icp_config, get_scoring_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    """Return current ICP and scoring configuration."""
    try:
        icp = get_icp_config()
        scoring = get_scoring_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "data": {
            "icp": {
                "target_market": icp.get("target_market", {}),
                "revenue": icp.get("company_filters", {}).get("revenue", {}),
                "employee_count": icp.get("company_filters", {}).get("employee_count", {}),
                "geography": icp.get("company_filters", {}).get("geography", {}),
                "industries": icp.get("company_filters", {}).get("industries", []),
                "contact_titles_include": (
                    icp.get("contact_filters", {}).get("titles", {}).get("include", [])
                ),
                "seniority": icp.get("contact_filters", {}).get("seniority", []),
                "discovery": icp.get("discovery", {}),
            },
            "scoring": {
                "dimensions": {
                    name: {
                        "max_points": dim.get("max_points"),
                        "signals": {
                            sig_name: {
                                "points": sig.get("points"),
                                "description": sig.get("description", ""),
                                "evaluation": sig.get("evaluation", ""),
                            }
                            for sig_name, sig in dim.get("signals", {}).items()
                        },
                    }
                    for name, dim in scoring.get("dimensions", {}).items()
                },
                "thresholds": scoring.get("thresholds", {}),
                "min_firmographic_for_research": scoring.get(
                    "min_firmographic_for_research", 10
                ),
            },
        }
    }
