"""Weekend pipeline run — continuous enrichment, research, qualification, and draft generation.

Runs the full pipeline chain non-stop until a stop condition is hit.
Nothing sends — all output queues for approval.

Stop conditions:
    - Pending draft buffer >= DRAFT_BUFFER_TARGET
    - Monthly API spend >= SPEND_HARD_LIMIT_USD
    - Research spend >= RESEARCH_HARD_LIMIT_USD
    - Apollo credits <= APOLLO_MIN_BUFFER
    - Enrichment companies processed >= ENRICHMENT_CAP
    - Consecutive error cycles >= MAX_ERROR_CYCLES

Usage:
    python weekend_run.py --test     # 3-company validation run, no loop
    python weekend_run.py            # Full continuous run until stop condition
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
logger = logging.getLogger("weekend_run")

# ---------------------------------------------------------------------------
# Configuration — all limits in one place
# ---------------------------------------------------------------------------

WORKSPACE_ID       = "00000000-0000-0000-0000-000000000001"

DRAFT_BUFFER_TARGET     = 600    # Stop when pending+approved drafts reach this
SPEND_HARD_LIMIT_USD    = 270.0  # Stop at 90% of $300 monthly cap
RESEARCH_HARD_LIMIT_USD = 135.0  # Stop research at 90% of $150 research cap
APOLLO_MIN_BUFFER       = 2000   # Stop enrichment when Apollo credits <= this
ENRICHMENT_CAP          = 1000   # Max companies per run (Apollo credit guard is the real stop)
MAX_ERROR_CYCLES        = 5      # Stop after this many consecutive all-error cycles

# Batch sizes — smaller = more frequent guard checks
RESEARCH_BATCH      = 10
QUALIFY_BATCH       = 20
ENRICH_BATCH        = 15
OUTREACH_BATCH      = 10

# Pause between pipeline steps (seconds) — avoids API rate limit bursts
INTER_STEP_SLEEP    = 3
INTER_CYCLE_SLEEP   = 10  # Between full pipeline cycles

# Log file
LOG_PATH = Path(__file__).parent / "weekend_run.log"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH),
        ],
    )


def _get_db():
    from backend.app.core.database import get_supabase_client
    return get_supabase_client()


def _get_monthly_spend(client) -> float:
    """Total API spend this calendar month."""
    from datetime import datetime, timezone
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = (
        client.table("api_costs")
        .select("estimated_cost_usd")
        .eq("workspace_id", WORKSPACE_ID)
        .gte("created_at", month_start)
        .execute()
    ).data or []
    return sum(float(r.get("estimated_cost_usd") or 0) for r in rows)


def _get_research_spend(client) -> float:
    """Research-specific spend this month (batch_id LIKE 'research%')."""
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = (
        client.table("api_costs")
        .select("estimated_cost_usd")
        .eq("workspace_id", WORKSPACE_ID)
        .gte("created_at", month_start)
        .like("batch_id", "research%")
        .execute()
    ).data or []
    return sum(float(r.get("estimated_cost_usd") or 0) for r in rows)


def _get_draft_buffer(client) -> int:
    """Count of pending + approved unsent drafts."""
    drafts = (
        client.table("outreach_drafts")
        .select("approval_status")
        .eq("workspace_id", WORKSPACE_ID)
        .is_("sent_at", "null")
        .execute()
    ).data or []
    return sum(1 for d in drafts if d["approval_status"] in ("pending", "approved"))


def _get_pipeline_counts(client) -> dict:
    """Company counts by status."""
    from collections import Counter
    rows = (
        client.table("companies")
        .select("status")
        .eq("workspace_id", WORKSPACE_ID)
        .execute()
    ).data or []
    return dict(Counter(r["status"] for r in rows))


def _get_enrichment_processed(client) -> int:
    ws = client.table("workspaces").select("settings").eq("id", WORKSPACE_ID).single().execute()
    s = (ws.data or {}).get("settings") or {}
    return int(s.get("enrichment_companies_processed", 0))


def _increment_enrichment_count(client, delta: int) -> None:
    ws = client.table("workspaces").select("settings").eq("id", WORKSPACE_ID).single().execute()
    s = (ws.data or {}).get("settings") or {}
    s["enrichment_companies_processed"] = int(s.get("enrichment_companies_processed", 0)) + delta
    client.table("workspaces").update({"settings": s}).eq("id", WORKSPACE_ID).execute()


def _apollo_credits_ok() -> bool:
    from backend.app.core.workspace_scheduler import apollo_credits_ok
    return apollo_credits_ok(workspace_id=WORKSPACE_ID, min_buffer=APOLLO_MIN_BUFFER)


# ---------------------------------------------------------------------------
# Email notifications — hourly updates + 75% limit alerts
# ---------------------------------------------------------------------------

NOTIFY_EMAIL = "avi@digitillis.io"
HOURLY_INTERVAL = 3600  # seconds

_last_hourly_email: float = 0.0
_alerts_sent: set = set()  # tracks which 75% alerts have already fired


def _get_apollo_remaining() -> int:
    """Return Apollo credits remaining, or large number if unavailable."""
    try:
        from backend.app.core.workspace_scheduler import apollo_credits_ok
        import httpx, os
        key = os.environ.get("APOLLO_API_KEY", "")
        if not key:
            return 9999
        r = httpx.get(
            "https://api.apollo.io/v1/auth/health",
            headers={"X-Api-Key": key},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            return int(data.get("credits_used_this_month", {}).get("remaining", 9999))
    except Exception:
        pass
    return 9999


def _contacts_with_email(client) -> int:
    r = client.table("contacts").select("id", count="exact").eq("workspace_id", WORKSPACE_ID).not_.is_("email", "null").execute()
    return r.count or 0


def _build_status_html(client, cycle: int, session_spend: float, subject_prefix: str = "") -> tuple[str, str]:
    """Build HTML email body and subject line for status update."""
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%b %-d at %-I:%M %p UTC")

    monthly_spend  = _get_monthly_spend(client)
    research_spend = _get_research_spend(client)
    draft_buffer   = _get_draft_buffer(client)
    counts         = _get_pipeline_counts(client)
    enriched       = _get_enrichment_processed(client)
    contacts_email = _contacts_with_email(client)

    spend_pct     = monthly_spend / SPEND_HARD_LIMIT_USD * 100
    research_pct  = research_spend / RESEARCH_HARD_LIMIT_USD * 100
    enrich_pct    = enriched / ENRICHMENT_CAP * 100 if ENRICHMENT_CAP else 0
    buffer_pct    = draft_buffer / DRAFT_BUFFER_TARGET * 100

    def bar(pct):
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled) + f" {pct:.0f}%"

    def row(label, val, limit, pct, bg=""):
        color = "#dc2626" if pct >= 90 else "#f59e0b" if pct >= 75 else "#16a34a"
        style = f'background:{bg};' if bg else ''
        return (
            f'<tr style="{style}">'
            f'<td style="padding:7px 10px;border-top:1px solid #e5e7eb">{label}</td>'
            f'<td style="text-align:right;padding:7px 10px;border-top:1px solid #e5e7eb"><b>{val}</b></td>'
            f'<td style="text-align:right;padding:7px 10px;border-top:1px solid #e5e7eb">{limit}</td>'
            f'<td style="text-align:right;padding:7px 10px;border-top:1px solid #e5e7eb;color:{color};font-weight:600">{pct:.0f}%</td>'
            f'</tr>'
        )

    html = f"""<html><body style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;color:#111;padding:20px">
<h2 style="color:#1d4ed8;margin-bottom:2px">ProspectIQ Weekend Run</h2>
<p style="color:#6b7280;margin-top:0;font-size:13px">Cycle {cycle} &mdash; {now_str}</p>

<h3 style="margin-bottom:6px;font-size:14px;color:#374151">Pipeline State</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px">
  <tr style="background:#f3f4f6;font-size:12px;font-weight:600;color:#374151">
    <td style="padding:6px 10px">Stage</td><td style="text-align:right;padding:6px 10px">Count</td>
  </tr>
  <tr><td style="padding:6px 10px;border-top:1px solid #e5e7eb">Discovered</td><td style="text-align:right;padding:6px 10px;border-top:1px solid #e5e7eb"><b>{counts.get("discovered",0):,}</b></td></tr>
  <tr style="background:#f9fafb"><td style="padding:6px 10px;border-top:1px solid #e5e7eb">Qualified</td><td style="text-align:right;padding:6px 10px;border-top:1px solid #e5e7eb"><b>{counts.get("qualified",0):,}</b></td></tr>
  <tr><td style="padding:6px 10px;border-top:1px solid #e5e7eb">Outreach Pending</td><td style="text-align:right;padding:6px 10px;border-top:1px solid #e5e7eb"><b>{counts.get("outreach_pending",0):,}</b></td></tr>
  <tr style="background:#f9fafb"><td style="padding:6px 10px;border-top:1px solid #e5e7eb">Contacts w/ Email</td><td style="text-align:right;padding:6px 10px;border-top:1px solid #e5e7eb"><b>{contacts_email:,}</b></td></tr>
  <tr><td style="padding:6px 10px;border-top:1px solid #e5e7eb">Draft Buffer (pending+approved)</td><td style="text-align:right;padding:6px 10px;border-top:1px solid #e5e7eb"><b>{draft_buffer:,}</b></td></tr>
</table>

<h3 style="margin-bottom:6px;font-size:14px;color:#374151">Limits</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px">
  <tr style="background:#f3f4f6;font-size:12px;font-weight:600;color:#374151">
    <td style="padding:6px 10px">Limit</td>
    <td style="text-align:right;padding:6px 10px">Used</td>
    <td style="text-align:right;padding:6px 10px">Cap</td>
    <td style="text-align:right;padding:6px 10px">%</td>
  </tr>
  {row("API Spend (May)", f"${monthly_spend:.2f}", f"${SPEND_HARD_LIMIT_USD:.0f}", spend_pct)}
  {row("Research Spend", f"${research_spend:.2f}", f"${RESEARCH_HARD_LIMIT_USD:.0f}", research_pct, "#f9fafb")}
  {row("Enrichment Companies", f"{enriched:,}", f"{ENRICHMENT_CAP:,}", enrich_pct)}
  {row("Draft Buffer Progress", f"{draft_buffer:,}", f"{DRAFT_BUFFER_TARGET:,}", buffer_pct, "#f9fafb")}
</table>

<p style="font-size:11px;color:#9ca3af;margin-top:20px">Session spend: ${session_spend:.2f} &nbsp;|&nbsp; Log: weekend_run_may2.log</p>
</body></html>"""

    subject = f"PIQ Run &mdash; Cycle {cycle} | {draft_buffer} drafts | ${monthly_spend:.2f} spent | {now_str}"
    return html, subject


async def _send_email_async(subject: str, html: str) -> None:
    import httpx, os
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.post(
            "https://api.resend.com/emails",
            json={"from": os.environ.get("FROM_EMAIL", "avi@digitillis.io"),
                  "to": [NOTIFY_EMAIL], "subject": subject, "html": html},
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        )
        logger.info("Status email sent: HTTP %s", r.status_code)


def _send_notification(subject: str, html: str) -> None:
    import asyncio
    try:
        asyncio.run(_send_email_async(subject, html))
    except Exception as e:
        logger.warning("Failed to send notification email: %s", e)


def _check_and_notify(client, cycle: int, session_spend: float) -> None:
    """Send hourly update and/or 75% limit alerts as needed."""
    global _last_hourly_email, _alerts_sent
    import time as _time

    monthly_spend  = _get_monthly_spend(client)
    research_spend = _get_research_spend(client)
    enriched       = _get_enrichment_processed(client)
    draft_buffer   = _get_draft_buffer(client)

    # --- 75% alerts (fire once per limit breach, not every cycle) ---
    limits = {
        "spend":    (monthly_spend,  SPEND_HARD_LIMIT_USD,    "API spend"),
        "research": (research_spend, RESEARCH_HARD_LIMIT_USD, "Research spend"),
        "enrich":   (enriched,       ENRICHMENT_CAP,          "Enrichment cap"),
    }
    for key, (used, cap, label) in limits.items():
        if cap and used / cap >= 0.75 and key not in _alerts_sent:
            _alerts_sent.add(key)
            pct = used / cap * 100
            html, _ = _build_status_html(client, cycle, session_spend)
            subject = f"PIQ ALERT: {label} at {pct:.0f}% ({used:.0f}/{cap:.0f})"
            logger.warning("75%% alert triggered: %s", subject)
            _send_notification(subject, html)

    # --- Hourly update ---
    now = _time.time()
    if now - _last_hourly_email >= HOURLY_INTERVAL:
        _last_hourly_email = now
        html, subject = _build_status_html(client, cycle, session_spend)
        _send_notification(subject, html)


def _print_status(client, cycle: int, session_spend: float) -> None:
    monthly_spend = _get_monthly_spend(client)
    research_spend = _get_research_spend(client)
    draft_buffer = _get_draft_buffer(client)
    counts = _get_pipeline_counts(client)
    enriched = _get_enrichment_processed(client)

    table = Table(title=f"Cycle {cycle} — {datetime.now().strftime('%H:%M:%S')}", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Draft buffer (pending+approved)", str(draft_buffer))
    table.add_row("Discovered", str(counts.get("discovered", 0)))
    table.add_row("Researched", str(counts.get("researched", 0)))
    table.add_row("Qualified", str(counts.get("qualified", 0)))
    table.add_row("Outreach pending", str(counts.get("outreach_pending", 0)))
    table.add_row("Enrichment processed", f"{enriched}/{ENRICHMENT_CAP}")
    table.add_row("Monthly API spend", f"${monthly_spend:.2f} / ${SPEND_HARD_LIMIT_USD:.0f}")
    table.add_row("Research spend", f"${research_spend:.2f} / ${RESEARCH_HARD_LIMIT_USD:.0f}")
    table.add_row("This session spend", f"${session_spend:.2f}")

    console.print(table)


# ---------------------------------------------------------------------------
# Guard checks — return (ok: bool, reason: str)
# ---------------------------------------------------------------------------

def _check_guards(client) -> tuple[bool, str]:
    """Check all stop conditions. Returns (should_continue, stop_reason)."""
    monthly_spend = _get_monthly_spend(client)
    if monthly_spend >= SPEND_HARD_LIMIT_USD:
        return False, f"Monthly spend ${monthly_spend:.2f} >= hard limit ${SPEND_HARD_LIMIT_USD:.0f}"

    draft_buffer = _get_draft_buffer(client)
    if draft_buffer >= DRAFT_BUFFER_TARGET:
        return False, f"Draft buffer {draft_buffer} >= target {DRAFT_BUFFER_TARGET}"

    enriched = _get_enrichment_processed(client)
    if enriched >= ENRICHMENT_CAP:
        return False, f"Enrichment cap reached ({enriched}/{ENRICHMENT_CAP})"

    return True, ""


def _check_research_ok(client) -> bool:
    research_spend = _get_research_spend(client)
    if research_spend >= RESEARCH_HARD_LIMIT_USD:
        console.print(f"[yellow]Research budget exhausted (${research_spend:.2f}) — skipping research this cycle[/yellow]")
        return False
    return True


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_research(client, test_mode: bool = False) -> list[str]:
    """Research discovered companies. Returns list of company IDs that were researched."""
    from backend.app.agents.research import ResearchAgent
    limit = 10 if test_mode else RESEARCH_BATCH
    console.print(f"[cyan]  Research: processing up to {limit} companies...[/cyan]")

    # Snapshot which companies are in researched state before the run
    pre = {r["id"] for r in (
        client.table("companies").select("id")
        .eq("workspace_id", WORKSPACE_ID).eq("status", "researched").execute().data or []
    )}

    result = ResearchAgent(workspace_id=WORKSPACE_ID).run(limit=limit)
    console.print(f"  Research done: {result.processed} processed, {result.errors} errors")

    # Return IDs of companies that moved to researched status during this run
    post = {r["id"] for r in (
        client.table("companies").select("id")
        .eq("workspace_id", WORKSPACE_ID).eq("status", "researched").execute().data or []
    )}
    newly_researched = list(post - pre)
    if newly_researched:
        console.print(f"  Newly researched: {len(newly_researched)} companies queued for qualification")
    return newly_researched


def step_qualify(client, company_ids: list[str] | None = None, test_mode: bool = False) -> int:
    """Score researched companies. Returns count qualified.

    Passes company_ids explicitly when provided — this bypasses the
    'skip if pqs_total already set' filter in QualificationAgent, ensuring
    freshly-researched companies get full 4-dimension scoring even if they
    had a firmographic pre-filter score from the discovery phase.
    """
    from backend.app.agents.qualification import QualificationAgent

    # If no explicit IDs, fall back to all unscored researched companies
    if not company_ids:
        rows = (
            client.table("companies").select("id, pqs_total")
            .eq("workspace_id", WORKSPACE_ID).eq("status", "researched").execute().data or []
        )
        # Include companies with a prior pqs_total (from pre-filter) so they get full scoring
        company_ids = [r["id"] for r in rows] or None

    limit = 15 if test_mode else QUALIFY_BATCH
    if company_ids:
        console.print(f"[cyan]  Qualification: scoring {len(company_ids)} researched companies...[/cyan]")
        result = QualificationAgent(workspace_id=WORKSPACE_ID).run(company_ids=company_ids)
    else:
        console.print(f"[cyan]  Qualification: scoring up to {limit} companies...[/cyan]")
        result = QualificationAgent(workspace_id=WORKSPACE_ID).run(limit=limit)

    console.print(f"  Qualification done: {result.processed} processed, {result.errors} errors")
    return result.processed


def _get_already_attempted_company_ids(client) -> set[str]:
    """Return company IDs where Apollo was tried for all contacts and no email found.

    These companies have contacts with enrichment_status='failed' or 'no_email'
    and no contact with a real email — skip them to avoid burning Apollo credits
    re-trying the same dead ends every cycle.
    """
    try:
        # Contacts with a failed/attempted enrichment and still no email
        rows = (
            client.table("contacts")
            .select("company_id, email, enrichment_status")
            .eq("workspace_id", WORKSPACE_ID)
            .in_("enrichment_status", ["failed", "no_email", "attempted"])
            .execute()
        ).data or []

        from collections import defaultdict
        by_company: dict[str, dict] = defaultdict(lambda: {"has_email": False, "has_failed": False})
        for r in rows:
            cid = r["company_id"]
            if r.get("email"):
                by_company[cid]["has_email"] = True
            if r.get("enrichment_status") in ("failed", "no_email", "attempted"):
                by_company[cid]["has_failed"] = True

        # Skip only companies where all contacts failed AND none have email
        return {cid for cid, s in by_company.items() if s["has_failed"] and not s["has_email"]}
    except Exception:
        return set()


def step_enrich(client, test_mode: bool = False) -> int:
    """Enrich contacts at qualified companies. Returns count enriched."""
    if not _apollo_credits_ok():
        console.print("[yellow]  Enrichment: Apollo credit guard triggered — skipping[/yellow]")
        return 0

    enriched_so_far = _get_enrichment_processed(client)
    if enriched_so_far >= ENRICHMENT_CAP:
        console.print(f"[yellow]  Enrichment: cap reached ({enriched_so_far}/{ENRICHMENT_CAP}) — skipping[/yellow]")
        return 0

    # Get company IDs where Apollo was already tried and failed — skip them
    skip_ids = _get_already_attempted_company_ids(client)
    if skip_ids:
        console.print(f"  Enrichment: skipping {len(skip_ids)} already-attempted companies")

    from backend.app.agents.enrichment import EnrichmentAgent
    limit = 10 if test_mode else ENRICH_BATCH

    # Pull qualified companies, exclude already-failed ones, pass explicit IDs
    pool = (
        client.table("companies")
        .select("id")
        .eq("workspace_id", WORKSPACE_ID)
        .eq("status", "qualified")
        .order("pqs_total", desc=True)
        .limit(limit * 3)  # over-fetch to account for skips
        .execute()
    ).data or []

    candidate_ids = [r["id"] for r in pool if r["id"] not in skip_ids][:limit]

    if not candidate_ids:
        console.print("[yellow]  Enrichment: no new companies to enrich after skipping attempted ones[/yellow]")
        return 0

    console.print(f"[cyan]  Enrichment: processing {len(candidate_ids)} companies...[/cyan]")
    result = EnrichmentAgent(workspace_id=WORKSPACE_ID).run(company_ids=candidate_ids)
    console.print(f"  Enrichment done: {result.processed} processed, {result.errors} errors")

    if result.processed > 0:
        _increment_enrichment_count(client, result.processed)

    return result.processed


def step_draft(test_mode: bool = False) -> int:
    """Generate outreach drafts. Returns count generated."""
    from backend.app.agents.outreach import OutreachAgent
    limit = 10 if test_mode else OUTREACH_BATCH
    console.print(f"[cyan]  Draft generation: writing up to {limit} drafts...[/cyan]")
    result = OutreachAgent(workspace_id=WORKSPACE_ID).run(
        sequence_name="email_value_first",
        sequence_step=1,
        limit=limit,
    )
    console.print(f"  Drafts generated: {result.processed} created, {result.errors} errors")
    return result.processed


# ---------------------------------------------------------------------------
# Test run — validates the full chain on 3 companies
# ---------------------------------------------------------------------------

def run_test(client) -> bool:
    """Run one small pass through the full pipeline. Returns True if chain is healthy."""
    console.print(Panel("[bold cyan]TEST RUN — 10 companies through full chain[/bold cyan]"))

    pre_buffer = _get_draft_buffer(client)
    pre_counts = _get_pipeline_counts(client)
    pre_spend = _get_monthly_spend(client)

    console.print(f"  Pre-test state: discovered={pre_counts.get('discovered',0)}, "
                  f"qualified={pre_counts.get('qualified',0)}, "
                  f"draft_buffer={pre_buffer}, spend=${pre_spend:.2f}")

    errors = 0

    console.print("\n[bold]Step 1: Research[/bold]")
    newly_researched: list[str] = []
    if _check_research_ok(client):
        try:
            newly_researched = step_research(client, test_mode=True)
            researched = len(newly_researched)
        except Exception as e:
            console.print(f"[red]  Research FAILED: {e}[/red]")
            errors += 1
            researched = 0
    else:
        researched = 0

    time.sleep(INTER_STEP_SLEEP)

    console.print("\n[bold]Step 2: Qualification[/bold]")
    try:
        qualified = step_qualify(client, company_ids=newly_researched or None, test_mode=True)
    except Exception as e:
        console.print(f"[red]  Qualification FAILED: {e}[/red]")
        errors += 1
        qualified = 0

    time.sleep(INTER_STEP_SLEEP)

    console.print("\n[bold]Step 3: Enrichment[/bold]")
    try:
        enriched = step_enrich(client, test_mode=True)
    except Exception as e:
        console.print(f"[red]  Enrichment FAILED: {e}[/red]")
        errors += 1
        enriched = 0

    time.sleep(INTER_STEP_SLEEP)

    console.print("\n[bold]Step 4: Draft generation[/bold]")
    try:
        drafted = step_draft(test_mode=True)
    except Exception as e:
        console.print(f"[red]  Draft generation FAILED: {e}[/red]")
        errors += 1
        drafted = 0

    # Results
    post_buffer = _get_draft_buffer(client)
    post_counts = _get_pipeline_counts(client)
    post_spend = _get_monthly_spend(client)
    test_cost = post_spend - pre_spend

    console.print(Panel(
        f"[bold]TEST RESULTS[/bold]\n\n"
        f"  Researched:    {len(newly_researched) if newly_researched else researched}\n"
        f"  Qualified:     {qualified}\n"
        f"  Enriched:      {enriched}\n"
        f"  Drafts added:  {drafted} (buffer: {pre_buffer} → {post_buffer})\n"
        f"  Step errors:   {errors}\n"
        f"  Test cost:     ${test_cost:.4f}\n\n"
        f"  Pipeline state after test:\n"
        f"    discovered={post_counts.get('discovered',0)}, "
        f"researched={post_counts.get('researched',0)}, "
        f"qualified={post_counts.get('qualified',0)}",
        title="Test Complete",
        border_style="green" if errors == 0 else "yellow",
    ))

    if errors >= 3:
        console.print("[red]Too many step failures in test — do not proceed to full run.[/red]")
        return False

    return True


# ---------------------------------------------------------------------------
# Full continuous run
# ---------------------------------------------------------------------------

def run_full(client) -> None:
    """Run the pipeline continuously until a stop condition is hit."""
    console.print(Panel("[bold green]FULL PIPELINE RUN — running until stop condition[/bold green]"))
    console.print(f"  Stop conditions: draft_buffer>={DRAFT_BUFFER_TARGET} | "
                  f"spend>=${SPEND_HARD_LIMIT_USD} | enrichment>={ENRICHMENT_CAP}\n")

    cycle = 0
    consecutive_empty_cycles = 0
    session_start_spend = _get_monthly_spend(client)

    while True:
        cycle += 1
        session_spend = _get_monthly_spend(client) - session_start_spend

        console.print(f"\n[bold cyan]━━━ Cycle {cycle} ━━━[/bold cyan]")
        _print_status(client, cycle, session_spend)

        # Guard check
        ok, reason = _check_guards(client)
        if not ok:
            console.print(Panel(f"[bold green]STOP: {reason}[/bold green]", title="Pipeline Complete"))
            html, _ = _build_status_html(client, cycle, session_spend)
            _send_notification(f"PIQ Run COMPLETE: {reason}", html)
            break

        cycle_output = 0

        # Step 1: Research (if budget allows)
        newly_researched: list[str] = []
        if _check_research_ok(client):
            try:
                newly_researched = step_research(client)
                cycle_output += len(newly_researched)
            except Exception as e:
                console.print(f"[red]  Research error: {e}[/red]")
                logger.error("Research step error", exc_info=True)

        time.sleep(INTER_STEP_SLEEP)

        # Step 2: Qualify — pass freshly researched IDs to force full scoring
        try:
            n = step_qualify(client, company_ids=newly_researched or None)
            cycle_output += n
        except Exception as e:
            console.print(f"[red]  Qualification error: {e}[/red]")
            logger.error("Qualification step error", exc_info=True)

        time.sleep(INTER_STEP_SLEEP)

        # Step 3: Enrich
        try:
            n = step_enrich(client)
            cycle_output += n
        except Exception as e:
            console.print(f"[red]  Enrichment error: {e}[/red]")
            logger.error("Enrichment step error", exc_info=True)

        time.sleep(INTER_STEP_SLEEP)

        # Step 4: Draft generation
        try:
            n = step_draft()
            cycle_output += n
        except Exception as e:
            console.print(f"[red]  Draft generation error: {e}[/red]")
            logger.error("Draft generation step error", exc_info=True)

        # Hourly email + 75% limit alerts
        _check_and_notify(client, cycle, session_spend)

        # Track stall — if nothing is moving, stop to avoid spinning
        if cycle_output == 0:
            consecutive_empty_cycles += 1
            console.print(f"[yellow]  Empty cycle ({consecutive_empty_cycles}/{MAX_ERROR_CYCLES}) — pipeline may be starved[/yellow]")
            if consecutive_empty_cycles >= MAX_ERROR_CYCLES:
                console.print(Panel(
                    f"[bold yellow]STOP: {MAX_ERROR_CYCLES} consecutive empty cycles — pipeline starved or all guards triggered.[/bold yellow]\n"
                    "Check: Apollo credits, discovered company pool, research budget.",
                    title="Pipeline Stalled"
                ))
                html, _ = _build_status_html(client, cycle, session_spend)
                _send_notification("PIQ Run STALLED — pipeline starved, check credits/pool", html)
                break
        else:
            consecutive_empty_cycles = 0

        console.print(f"  Cycle {cycle} complete — {cycle_output} total outputs. "
                      f"Sleeping {INTER_CYCLE_SLEEP}s...")
        time.sleep(INTER_CYCLE_SLEEP)

    # Final summary
    final_spend = _get_monthly_spend(client) - session_start_spend
    final_buffer = _get_draft_buffer(client)
    console.print(Panel(
        f"[bold]WEEKEND RUN COMPLETE[/bold]\n\n"
        f"  Cycles run:       {cycle}\n"
        f"  Session spend:    ${final_spend:.2f}\n"
        f"  Draft buffer now: {final_buffer} drafts awaiting approval\n"
        f"  Log:              {LOG_PATH}",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(description="ProspectIQ weekend pipeline run")
    parser.add_argument("--test", action="store_true", help="Run test only (3 companies), then exit")
    args = parser.parse_args()

    client = _get_db()

    if args.test:
        success = run_test(client)
        sys.exit(0 if success else 1)
    else:
        # Always test first, then proceed to full run
        console.print("[bold]Running test validation before full run...[/bold]")
        success = run_test(client)
        if not success:
            console.print("[red]Test failed — aborting full run. Fix errors above first.[/red]")
            sys.exit(1)

        console.print("\n[bold green]Test passed. Starting full run in 5 seconds...[/bold green]")
        time.sleep(5)
        run_full(client)


if __name__ == "__main__":
    main()
