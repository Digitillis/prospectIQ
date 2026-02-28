"""Select a research batch using the 5-step ICP filter methodology.

Applies filters in priority order to select ~19 companies for the first
research batch:

  Step 1 — Sub-sector / tier:   1b (Automotive) → 1a (Industrial Machinery)
                                → 5 (Aerospace) → 2 (Metal Fabrication)
  Step 2 — Geography:           Primary states first, secondary if needed
  Step 3 — Contact quality:     VP Digital / COO / CIO > VP Ops > Director > Plant Mgr
  Step 4 — Employee count:      Prefer 1,000–8,000
  Step 5 — Founded year:        Prefer < 2000 (legacy infrastructure)

Usage:
  python -m backend.scripts.select_batch
  python -m backend.scripts.select_batch --dry-run
  python -m backend.scripts.select_batch --batch-id batch1_feb2026 --target 19
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

console = Console()
app = typer.Typer(help="Select a research batch using the 5-step ICP filter.")

# ---------------------------------------------------------------------------
# Contact quality tiers
# "transformation-titled contact" signals budget mandate — Tier A
# ---------------------------------------------------------------------------
_CONTACT_TIER_A = {"digital_transformation", "coo", "cio"}   # mandate + budget
_CONTACT_TIER_B = {"vp_ops", "vp_supply_chain"}              # operations authority
_CONTACT_TIER_C = {"director_ops"}                            # operational entry
_CONTACT_TIER_D = {"plant_manager"}                           # possible, harder entry

_CQ_SCORE: dict[str, int] = {p: 4 for p in _CONTACT_TIER_A}
_CQ_SCORE.update({p: 3 for p in _CONTACT_TIER_B})
_CQ_SCORE.update({p: 2 for p in _CONTACT_TIER_C})
_CQ_SCORE.update({p: 1 for p in _CONTACT_TIER_D})

# ---------------------------------------------------------------------------
# Target batch distribution
# ---------------------------------------------------------------------------
TARGET_DISTRIBUTION = [
    {
        "label": "Tier 1b — Automotive",
        "tier": "1b",
        "primary_states": {"MI", "OH", "IN"},
        "secondary_states": {"IL"},
        "target_min": 6,
        "target_max": 7,
    },
    {
        "label": "Tier 1a — Industrial Machinery",
        "tier": "1a",
        "primary_states": {"OH", "MI"},
        "secondary_states": {"IL"},
        "target_min": 6,
        "target_max": 7,
    },
    {
        "label": "Tier 2 — Metal Fabrication",
        "tier": "2",
        "primary_states": {"IN", "MI"},
        "secondary_states": {"OH", "IL"},
        "target_min": 4,
        "target_max": 5,
    },
]

# Statuses that are eligible (not yet in outreach pipeline)
_ELIGIBLE_STATUSES = {"discovered", "researched", "qualified"}

# Step 4 — preferred employee band
_EMP_MIN = 1_000
_EMP_MAX = 8_000

# Step 5 — legacy infrastructure threshold
_LEGACY_YEAR = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _best_contact_score(contacts: list[dict]) -> int:
    """Return the highest contact quality score (0–4) across all contacts."""
    return max((_CQ_SCORE.get(c.get("persona_type", ""), 0) for c in contacts), default=0)


def _best_contact_title(contacts: list[dict]) -> str:
    """Return the title of the highest-quality contact."""
    best_score = 0
    best_title = "—"
    for c in contacts:
        score = _CQ_SCORE.get(c.get("persona_type", ""), 0)
        if score > best_score:
            best_score = score
            best_title = c.get("title") or c.get("persona_type") or "—"
    return best_title


def _sort_key(company: dict, cq: int) -> tuple:
    """Sort key for ranking within a state pool (lower = higher priority).

    Order: contact quality → employee band → legacy age → PQS score
    """
    employees = company.get("employee_count") or 0
    in_band = 0 if _EMP_MIN <= employees <= _EMP_MAX else 1
    founded = company.get("founded_year") or 9999
    is_legacy = 0 if founded < _LEGACY_YEAR else 1
    pqs = company.get("pqs_total") or 0
    return (-cq, in_band, is_legacy, -pqs)


def _select_group(
    pool: list[dict],
    contacts_map: dict[str, list[dict]],
    primary_states: set[str],
    secondary_states: set[str],
    target_min: int,
    target_max: int,
) -> list[tuple[dict, int, bool]]:
    """Select up to target_max companies for one tier group.

    Returns list of (company, contact_quality_score, is_primary_state).
    Fills from primary states first; adds secondary states if below target_min.
    """
    selected: list[tuple[dict, int, bool]] = []
    seen: set[str] = set()

    def _fill(states: set[str], is_primary: bool, include_unknown: bool = False) -> None:
        """Fill from a given state set.

        include_unknown=True also pulls companies with no state stored.
        This handles the case where Apollo did not return location data —
        companies discovered via Midwest-filtered searches are still Midwest
        even if state=NULL in the database.
        """
        candidates = [
            c for c in pool
            if (
                (c.get("state") or "").upper() in states
                or (include_unknown and not c.get("state"))
            )
            and c["id"] not in seen
        ]
        scored = [(c, _best_contact_score(contacts_map.get(c["id"], []))) for c in candidates]
        scored.sort(key=lambda x: _sort_key(x[0], x[1]))
        for company, cq in scored:
            if len(selected) >= target_max:
                break
            selected.append((company, cq, is_primary))
            seen.add(company["id"])

    all_states_null = all(not c.get("state") for c in pool)

    # Primary pass: known primary-state companies, plus NULL-state if no state data available
    _fill(primary_states, is_primary=True, include_unknown=all_states_null)
    if len(selected) < target_min:
        # Secondary pass: known secondary-state companies only (NULLs already consumed above)
        _fill(secondary_states, is_primary=False, include_unknown=False)

    return selected[:target_max]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@app.command()
def main(
    batch_id: Optional[str] = typer.Option(
        None,
        "--batch-id",
        help="Batch ID to tag selected companies. Auto-generated if not set.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview selection without writing to the database.",
    ),
    target: int = typer.Option(
        19,
        "--target",
        help="Approximate target number of companies to select.",
    ),
) -> None:
    """Select ~19 companies for the next research batch using the 5-step ICP filter."""
    from backend.app.core.database import Database

    db = Database()
    effective_batch_id = (
        batch_id or f"batch1_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )

    console.print(f"\n[bold blue]{'=' * 66}[/bold blue]")
    console.print(f"[bold blue]  ProspectIQ — Batch Selection[/bold blue]")
    console.print(f"[bold blue]  Batch ID : {effective_batch_id}[/bold blue]")
    console.print(f"[bold blue]  Target   : {target} companies[/bold blue]")
    console.print(f"[bold blue]  Dry run  : {dry_run}[/bold blue]")
    console.print(f"[bold blue]{'=' * 66}[/bold blue]\n")

    # ------------------------------------------------------------------
    # 1. Load all eligible companies (paginated)
    # ------------------------------------------------------------------
    console.print("[cyan]Step 1 — Loading companies from database...[/cyan]")
    all_companies: list[dict] = []
    page_size = 200
    offset = 0
    while True:
        page = db.get_companies(limit=page_size, offset=offset)
        if not page:
            break
        all_companies.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    eligible = [c for c in all_companies if (c.get("status") or "") in _ELIGIBLE_STATUSES]
    console.print(
        f"  Total in database : [bold]{len(all_companies)}[/bold]\n"
        f"  Eligible (pre-outreach) : [bold]{len(eligible)}[/bold]\n"
    )

    if not eligible:
        console.print("[red]No eligible companies found. Run discovery first.[/red]")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # 1b. Diagnostics — show what tier and state values actually exist
    # ------------------------------------------------------------------
    from collections import Counter
    tier_counts = Counter((c.get("tier") or "NULL") for c in eligible)
    state_counts = Counter((c.get("state") or "NULL") for c in eligible)
    console.print("[dim]Tier distribution in eligible companies:[/dim]")
    for t, n in sorted(tier_counts.items()):
        console.print(f"  tier=[bold]{t}[/bold] : {n}")
    console.print("[dim]Top states:[/dim]")
    for s, n in state_counts.most_common(10):
        console.print(f"  state=[bold]{s}[/bold] : {n}")
    console.print()

    # ------------------------------------------------------------------
    # 2. Pre-load contacts for all eligible companies
    # ------------------------------------------------------------------
    console.print("[cyan]Step 2 — Loading contacts...[/cyan]")
    contacts_map: dict[str, list[dict]] = {}
    for company in eligible:
        contacts_map[company["id"]] = db.get_contacts_for_company(company["id"])

    with_dm = sum(1 for cid, cs in contacts_map.items() if any(
        c.get("is_decision_maker") for c in cs
    ))
    console.print(
        f"  Companies with a decision-maker contact : [bold]{with_dm}[/bold] / {len(eligible)}\n"
    )

    # ------------------------------------------------------------------
    # 3. Apply 5-step selection per distribution group
    # ------------------------------------------------------------------
    console.print("[cyan]Steps 3–5 — Applying filters by group...[/cyan]")
    selected: list[tuple[dict, int, bool, str]] = []  # (company, cq, is_primary, label)
    selected_ids: set[str] = set()

    for group in TARGET_DISTRIBUTION:
        tier_pool = [
            c for c in eligible
            if (c.get("tier") or "") == group["tier"] and c["id"] not in selected_ids
        ]
        group_selected = _select_group(
            pool=tier_pool,
            contacts_map=contacts_map,
            primary_states=group["primary_states"],
            secondary_states=group["secondary_states"],
            target_min=group["target_min"],
            target_max=group["target_max"],
        )
        for company, cq, is_primary in group_selected:
            selected.append((company, cq, is_primary, group["label"]))
            selected_ids.add(company["id"])

        t_min, t_max = group["target_min"], group["target_max"]
        n = len(group_selected)
        status_color = "green" if n >= t_min else "yellow"
        console.print(
            f"  [{status_color}]{group['label']}[/{status_color}] : "
            f"[bold]{n}[/bold] selected  (target {t_min}–{t_max})"
        )

    console.print()

    # ------------------------------------------------------------------
    # 4. Print results table
    # ------------------------------------------------------------------
    _CQ_LABEL = {4: "A", 3: "B", 2: "C", 1: "D", 0: "—"}
    _CQ_COLOR = {4: "bold green", 3: "green", 2: "yellow", 1: "dim", 0: "red"}

    table = Table(title=f"Batch Selection — {effective_batch_id}", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Company", min_width=28)
    table.add_column("Group", min_width=22)
    table.add_column("St", width=4)
    table.add_column("Geo", width=9)
    table.add_column("Employees", justify="right", width=10)
    table.add_column("Founded", justify="right", width=8)
    table.add_column("Best Contact", min_width=26)
    table.add_column("CQ", width=4, justify="center")
    table.add_column("PQS", justify="right", width=5)

    for i, (company, cq, is_primary, label) in enumerate(selected, 1):
        # Employee count — highlight if in preferred band
        emp = company.get("employee_count")
        emp_str = f"{emp:,}" if emp else "—"
        if emp and _EMP_MIN <= emp <= _EMP_MAX:
            emp_str = f"[green]{emp_str}[/green]"

        # Founded year — highlight if legacy
        founded = company.get("founded_year")
        founded_str = str(founded) if founded else "—"
        if founded and founded < _LEGACY_YEAR:
            founded_str = f"[green]{founded_str}[/green]"

        cq_label = _CQ_LABEL[cq]
        cq_color = _CQ_COLOR[cq]
        geo = "Primary" if is_primary else "Secondary"

        table.add_row(
            str(i),
            company.get("name") or "—",
            label,
            company.get("state") or "—",
            geo,
            emp_str,
            founded_str,
            _best_contact_title(contacts_map.get(company["id"], [])),
            f"[{cq_color}]{cq_label}[/{cq_color}]",
            str(company.get("pqs_total") or 0),
        )

    console.print(table)

    # ------------------------------------------------------------------
    # 5. Summary
    # ------------------------------------------------------------------
    cq_counts = {4: 0, 3: 0, 2: 0, 1: 0, 0: 0}
    for _, cq, _, _ in selected:
        cq_counts[cq] += 1

    console.print("[bold]Contact Quality Distribution:[/bold]")
    console.print(
        f"  [bold green]A[/bold green] Digital/COO/CIO : {cq_counts[4]}  |  "
        f"[green]B[/green] VP Ops           : {cq_counts[3]}  |  "
        f"[yellow]C[/yellow] Director         : {cq_counts[2]}  |  "
        f"[dim]D[/dim] Plant Mgr        : {cq_counts[1]}  |  "
        f"[red]—[/red] None             : {cq_counts[0]}"
    )

    secondary_count = sum(1 for _, _, is_primary, _ in selected if not is_primary)
    if secondary_count:
        console.print(
            f"\n[yellow]Note: {secondary_count} companies pulled from secondary states "
            f"(insufficient primary-state coverage for their tier).[/yellow]"
        )

    # ------------------------------------------------------------------
    # 6. Write batch_id to database (unless dry run)
    # ------------------------------------------------------------------
    if dry_run:
        console.print(
            f"\n[yellow]DRY RUN — {len(selected)} companies identified "
            f"but not tagged in database.[/yellow]\n"
        )
        return

    console.print(
        f"\n[cyan]Tagging {len(selected)} companies "
        f"with batch_id=[bold]{effective_batch_id}[/bold]...[/cyan]"
    )
    tagged = 0
    for company, _, _, _ in selected:
        try:
            db.update_company(company["id"], {"batch_id": effective_batch_id})
            tagged += 1
        except Exception as e:
            console.print(f"  [red]Error tagging {company.get('name')}: {e}[/red]")

    console.print(f"[bold green]Done. {tagged}/{len(selected)} companies tagged.[/bold green]")
    console.print(
        f"\n[dim]Next step — run research on this batch:[/dim]\n"
        f"  [bold]python -m backend.scripts.run_research "
        f"--batch-id {effective_batch_id}[/bold]\n"
    )


if __name__ == "__main__":
    app()
