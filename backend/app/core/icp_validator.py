"""ICP configuration validator.

Validates icp.yaml on startup to catch mismatches between the config
and the actual GTM strategy before they corrupt a discovery run.

Run standalone:  python -m backend.app.core.icp_validator
Called from:     backend/app/agents/discovery.py (at run() start)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

# ── Ground-truth GTM constraints ──────────────────────────────────────────────
# These are the actual target market parameters for Digitillis.
# Any icp.yaml value that deviates from these ranges raises an error.

GTM_EMPLOYEE_MIN = 51
GTM_EMPLOYEE_MAX = 500
GTM_REVENUE_MIN_M = 10      # $10M
GTM_REVENUE_MAX_M = 500     # $500M

# DB-level tier names that must match what icp.yaml uses.
# Key = icp.yaml tier value, Value = set of acceptable DB tier column values.
VALID_TIER_NAMES = {"mfg1", "fb1", "1a", "1b", "2", "3", "4", "5"}

REQUIRED_TOP_KEYS = {"company_filters", "contact_filters", "discovery"}
REQUIRED_COMPANY_FILTER_KEYS = {"industries", "employee_count", "geography"}
REQUIRED_CONTACT_FILTER_KEYS = {"titles", "seniority"}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_icp(icp: dict[str, Any], strict: bool = True) -> ValidationResult:
    """Validate an ICP config dict.

    Args:
        icp: Parsed contents of icp.yaml.
        strict: If True, employee/revenue mismatches are errors. If False, warnings.

    Returns:
        ValidationResult with any errors and warnings found.
    """
    r = ValidationResult()

    # 1. Required top-level keys
    for key in REQUIRED_TOP_KEYS:
        if key not in icp:
            r.error(f"Missing required top-level key: '{key}'")

    if "company_filters" not in icp:
        return r  # Can't validate further without company_filters

    cf = icp["company_filters"]

    # 2. Required company_filter keys
    for key in REQUIRED_COMPANY_FILTER_KEYS:
        if key not in cf:
            r.error(f"company_filters missing required key: '{key}'")

    # 3. Employee count range
    if "employee_count" in cf:
        emp = cf["employee_count"]
        emp_min = emp.get("min", 0)
        emp_max = emp.get("max", 0)
        if emp_min > GTM_EMPLOYEE_MAX or emp_max < GTM_EMPLOYEE_MIN:
            msg = (
                f"employee_count range [{emp_min:,}–{emp_max:,}] does not overlap "
                f"GTM target [{GTM_EMPLOYEE_MIN}–{GTM_EMPLOYEE_MAX}]. "
                f"Update icp.yaml or GTM_EMPLOYEE_MIN/MAX in icp_validator.py."
            )
            if strict:
                r.error(msg)
            else:
                r.warn(msg)
        elif emp_min < GTM_EMPLOYEE_MIN or emp_max > GTM_EMPLOYEE_MAX:
            r.warn(
                f"employee_count [{emp_min:,}–{emp_max:,}] is wider than GTM target "
                f"[{GTM_EMPLOYEE_MIN}–{GTM_EMPLOYEE_MAX}]. Discovery may pull non-ICP companies."
            )

        # Apollo ranges sanity check
        apollo_ranges = emp.get("apollo_ranges", [])
        if apollo_ranges:
            # Verify at least one range covers the GTM window
            covers_gtm = any(
                _range_covers(r_str, GTM_EMPLOYEE_MIN, GTM_EMPLOYEE_MAX)
                for r_str in apollo_ranges
            )
            if not covers_gtm:
                r.warn(
                    f"apollo_ranges {apollo_ranges} don't appear to cover the GTM target "
                    f"[{GTM_EMPLOYEE_MIN}–{GTM_EMPLOYEE_MAX}]."
                )

    # 4. Revenue range
    if "revenue" in cf:
        rev = cf["revenue"]
        rev_min_m = rev.get("min", 0) / 1_000_000
        rev_max_m = rev.get("max", 0) / 1_000_000
        if rev_min_m > GTM_REVENUE_MAX_M or rev_max_m < GTM_REVENUE_MIN_M:
            msg = (
                f"revenue range [${rev_min_m:.0f}M–${rev_max_m:.0f}M] does not overlap "
                f"GTM target [${GTM_REVENUE_MIN_M}M–${GTM_REVENUE_MAX_M}M]."
            )
            if strict:
                r.error(msg)
            else:
                r.warn(msg)

    # 5. Tier names
    if "industries" in cf:
        for ind in cf["industries"]:
            tier = ind.get("tier", "")
            if tier and str(tier) not in VALID_TIER_NAMES:
                r.warn(
                    f"Industry '{ind.get('label', '?')}' uses tier='{tier}' which is not in "
                    f"VALID_TIER_NAMES {sorted(VALID_TIER_NAMES)}. "
                    f"DB records use 'mfg1'/'fb1' — ensure campaign code maps correctly."
                )

    # 6. Geography — at least one US state
    if "geography" in cf:
        states = cf["geography"].get("primary_states", [])
        if not states:
            r.error("company_filters.geography.primary_states is empty — no geography filter.")
        elif len(states) < 3:
            r.warn(f"Only {len(states)} state(s) configured. Midwest target typically needs 7+.")

    # 7. Contact filters
    if "contact_filters" in icp:
        ctf = icp["contact_filters"]
        include_titles = ctf.get("titles", {}).get("include", [])
        if not include_titles:
            r.error("contact_filters.titles.include is empty — no title filter.")
        seniority = ctf.get("seniority", [])
        if not seniority:
            r.warn("contact_filters.seniority is empty — Apollo will return all seniority levels.")

    # 8. Discovery settings
    if "discovery" in icp:
        disc = icp["discovery"]
        pages = disc.get("pages_per_tier", 0)
        if pages > 20:
            r.warn(f"pages_per_tier={pages} is very high — this will consume many Apollo credits.")
        if not disc.get("default_campaign_name"):
            r.warn("discovery.default_campaign_name not set — will use fallback 'prospectiq'.")

    return r


def _range_covers(range_str: str, min_val: int, max_val: int) -> bool:
    """Check if an Apollo-style '51,500' range string covers [min_val, max_val]."""
    try:
        parts = range_str.split(",")
        lo = int(parts[0])
        hi = int(parts[1]) if len(parts) > 1 else 10_000_000
        return lo <= max_val and hi >= min_val
    except (ValueError, IndexError):
        return False


def validate_and_exit_on_error(icp: dict[str, Any], strict: bool = True) -> None:
    """Validate ICP and raise SystemExit if errors found. For use at agent startup."""
    result = validate_icp(icp, strict=strict)
    if result.warnings:
        for w in result.warnings:
            console.print(f"[yellow]⚠  ICP WARNING: {w}[/yellow]")
    if not result.ok:
        console.print("\n[bold red]❌ ICP CONFIG ERRORS — fix icp.yaml before running discovery:[/bold red]")
        for e in result.errors:
            console.print(f"[red]   • {e}[/red]")
        sys.exit(1)


def print_validation_report(result: ValidationResult) -> None:
    """Print a formatted validation report to the console."""
    if result.ok and not result.warnings:
        console.print("[bold green]✅ icp.yaml validation passed — no issues found.[/bold green]")
        return

    if result.errors:
        console.print(f"\n[bold red]❌ {len(result.errors)} ERROR(S):[/bold red]")
        for e in result.errors:
            console.print(f"  [red]• {e}[/red]")

    if result.warnings:
        console.print(f"\n[bold yellow]⚠  {len(result.warnings)} WARNING(S):[/bold yellow]")
        for w in result.warnings:
            console.print(f"  [yellow]• {w}[/yellow]")

    if result.ok:
        console.print("\n[green]Validation passed (with warnings).[/green]")
    else:
        console.print("\n[red]Validation FAILED. Fix errors before running discovery.[/red]")


if __name__ == "__main__":
    from backend.app.core.config import get_icp_config
    console.print("[cyan]Validating icp.yaml...[/cyan]\n")
    icp_cfg = get_icp_config()
    vr = validate_icp(icp_cfg, strict=True)
    print_validation_report(vr)
    sys.exit(0 if vr.ok else 1)
