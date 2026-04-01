"""ProspectIQ Pipeline Analytics Dashboard.

Rich terminal dashboard showing a full view of the outreach funnel,
hot accounts, reply rate breakdowns, weekly trends, and action queue.

Usage:
    python -m backend.scripts.pipeline_dashboard
    python -m backend.scripts.pipeline_dashboard --campaign tier0-mfg-pdm-roi
    python -m backend.scripts.pipeline_dashboard --weeks 12
    python -m backend.scripts.pipeline_dashboard --report        # plain-text Slack report
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from backend.app.core.database import Database
from backend.app.analytics.funnel import FunnelAnalytics, _FUNNEL_STAGES
from backend.app.analytics.reports import CampaignReporter

console = Console()

# Color thresholds
_GREEN_REPLY_RATE = 5.0   # >=5% reply rate is healthy
_YELLOW_REPLY_RATE = 2.0  # 2–5% is ok
# Red = below 2%


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _rate_color(rate: float) -> str:
    """Return a Rich color string based on a reply rate percentage."""
    if rate >= _GREEN_REPLY_RATE:
        return "green"
    if rate >= _YELLOW_REPLY_RATE:
        return "yellow"
    return "red"


def _colored_rate(rate: float, suffix: str = "%") -> Text:
    color = _rate_color(rate)
    return Text(f"{rate:.1f}{suffix}", style=f"bold {color}")


def _bar(value: float, total: float, width: int = 20) -> str:
    """ASCII progress bar for compact tables."""
    if total <= 0:
        return " " * width
    filled = int(value / total * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_header(campaign_name: str | None, weeks: int) -> None:
    today = date.today().strftime("%A, %B %d %Y")
    title = f"ProspectIQ Pipeline Dashboard — {today}"
    if campaign_name:
        title += f"  [dim]({campaign_name})[/dim]"
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    console.print()


def render_funnel(funnel: dict, funnel_30: dict) -> None:
    """Render funnel stage counts with inline conversion arrows."""
    table = Table(
        title="[bold]Funnel Overview[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_justify="left",
        expand=False,
    )
    table.add_column("Stage", min_width=22)
    table.add_column("7d Count", justify="right", min_width=9)
    table.add_column("30d Count", justify="right", min_width=9)
    table.add_column("30d Bar", min_width=22)
    table.add_column("Conv. Rate", justify="right", min_width=10)

    stages_to_show = [
        "discovered", "enriched", "sequenced",
        "touch_1_sent", "touch_2_sent", "touch_3_sent",
        "touch_4_sent", "touch_5_sent",
        "replied", "demo_scheduled", "closed_won",
    ]

    # Find max for bar scaling
    max_count = max((funnel_30.get(s, 0) for s in stages_to_show), default=1) or 1

    conv_rates = funnel_30.get("conversion_rates", {})
    stage_labels = {
        "discovered": "Discovered",
        "enriched": "Enriched",
        "sequenced": "Sequenced",
        "touch_1_sent": "Touch 1 Sent",
        "touch_2_sent": "Touch 2 Sent",
        "touch_3_sent": "Touch 3 Sent",
        "touch_4_sent": "Touch 4 Sent",
        "touch_5_sent": "Touch 5 Sent",
        "replied": "Replied",
        "demo_scheduled": "Demo Scheduled",
        "closed_won": "Closed Won",
    }

    prev_stage = None
    for stage in stages_to_show:
        count_7d = funnel.get(stage, 0)
        count_30d = funnel_30.get(stage, 0)
        label = stage_labels.get(stage, stage.replace("_", " ").title())
        bar = _bar(count_30d, max_count, width=20)

        # Conversion rate from previous to this stage
        conv_key = f"{prev_stage}_to_{stage}" if prev_stage else None
        conv_str = ""
        if conv_key and conv_key in conv_rates:
            rate = conv_rates[conv_key]
            color = "green" if rate >= 50 else ("yellow" if rate >= 20 else "red")
            conv_str = f"[{color}]{rate:.1f}%[/{color}]"

        # Color the count
        count_color = "white"
        if stage == "replied":
            rate_val = funnel_30.get("overall_reply_rate", 0.0)
            count_color = _rate_color(rate_val)
        elif stage == "closed_won":
            count_color = "green" if count_30d > 0 else "dim"

        table.add_row(
            label,
            str(count_7d) if count_7d else "[dim]0[/dim]",
            f"[{count_color}]{count_30d}[/{count_color}]" if count_30d else "[dim]0[/dim]",
            f"[cyan]{bar}[/cyan]",
            conv_str,
        )
        prev_stage = stage

    console.print(table)

    # Summary rates inline
    rate_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    rate_table.add_column("metric", style="dim", min_width=30)
    rate_table.add_column("value", min_width=12)

    reply_rate = funnel_30.get("overall_reply_rate", 0.0)
    demo_rate = funnel_30.get("demo_from_reply_rate", 0.0)
    win_rate = funnel_30.get("win_rate", 0.0)

    rate_table.add_row("Reply rate (30d)", _colored_rate(reply_rate))
    rate_table.add_row("Demo / Reply rate (30d)", _colored_rate(demo_rate))
    rate_table.add_row("Win rate (demo → won)", _colored_rate(win_rate))

    console.print(Panel(rate_table, title="[bold]Conversion Rates[/bold]",
                        border_style="cyan", expand=False))


def render_breakdowns(by_persona: list[dict], by_vertical: list[dict], by_touch: list[dict]) -> None:
    """Three side-by-side breakdown tables."""

    # -- Persona table --
    persona_table = Table(
        title="By Persona",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=False,
    )
    persona_table.add_column("Persona", min_width=20)
    persona_table.add_column("Sent", justify="right", min_width=6)
    persona_table.add_column("Reply %", justify="right", min_width=8)

    for row in by_persona[:8]:
        persona = row["persona_type"].replace("_", " ").title()
        rate = row["reply_rate_pct"]
        color = _rate_color(rate)
        persona_table.add_row(
            persona,
            str(row["total_sequenced"]),
            f"[{color}]{rate:.1f}%[/{color}]",
        )
    if not by_persona:
        persona_table.add_row("[dim]No data[/dim]", "", "")

    # -- Vertical table --
    vertical_table = Table(
        title="By Vertical / Campaign",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=False,
    )
    vertical_table.add_column("Vertical", min_width=22)
    vertical_table.add_column("Sent", justify="right", min_width=6)
    vertical_table.add_column("Reply %", justify="right", min_width=8)

    for row in by_vertical[:8]:
        vertical = (row["vertical"] or "unknown").replace("-", " ").title()
        rate = row["reply_rate_pct"]
        color = _rate_color(rate)
        vertical_table.add_row(
            vertical,
            str(row["total_sequenced"]),
            f"[{color}]{rate:.1f}%[/{color}]",
        )
    if not by_vertical:
        vertical_table.add_row("[dim]No data[/dim]", "", "")

    # -- Touch table --
    touch_table = Table(
        title="By Touch Number",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        expand=False,
    )
    touch_table.add_column("Touch", min_width=8)
    touch_table.add_column("Sent", justify="right", min_width=6)
    touch_table.add_column("Replied", justify="right", min_width=8)
    touch_table.add_column("Rate", justify="right", min_width=7)

    for row in by_touch:
        rate = row["reply_rate_pct"]
        color = _rate_color(rate)
        touch_table.add_row(
            f"Touch {row['touch_number']}",
            str(row["emails_sent"]),
            str(row["replies_from_touch"]),
            f"[{color}]{rate:.1f}%[/{color}]",
        )
    if not by_touch:
        touch_table.add_row("[dim]No data[/dim]", "", "", "")

    console.print(
        Columns(
            [
                Panel(persona_table, border_style="blue"),
                Panel(vertical_table, border_style="blue"),
                Panel(touch_table, border_style="blue"),
            ],
            equal=False,
            expand=False,
        )
    )


def render_hot_accounts(hot_accounts: list[dict]) -> None:
    """Top hot accounts table."""
    table = Table(
        title="[bold]Hot Accounts[/bold]  [dim](composite signal score)[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold yellow",
        title_justify="left",
        expand=False,
    )
    table.add_column("Company", min_width=28)
    table.add_column("Tier", justify="center", min_width=5)
    table.add_column("Score", justify="right", min_width=7)
    table.add_column("Intent", justify="right", min_width=7)
    table.add_column("Signals", min_width=22)
    table.add_column("Opens", justify="right", min_width=6)

    if not hot_accounts:
        table.add_row("[dim]No hot accounts yet — keep sending![/dim]", "", "", "", "", "")
    else:
        for acc in hot_accounts[:10]:
            name = acc["company_name"][:27]
            tier = str(acc.get("tier", "?"))
            score = f"[bold yellow]{acc['composite_score']:.0f}[/bold yellow]"
            intent = str(acc.get("intent_score", 0)) if acc.get("intent_score") else "[dim]—[/dim]"

            signals = []
            if acc.get("won"):
                signals.append(f"[green]WON({acc['won']})[/green]")
            if acc.get("demo"):
                signals.append(f"[cyan]DEMO({acc['demo']})[/cyan]")
            if acc.get("replied"):
                signals.append(f"[blue]REPLY({acc['replied']})[/blue]")
            if acc.get("active_intent_signals"):
                signals.append(f"[yellow]INTENT({acc['active_intent_signals']})[/yellow]")
            signals_str = "  ".join(signals) if signals else "[dim]—[/dim]"

            opens = str(acc.get("total_opens", 0))
            table.add_row(name, tier, score, intent, signals_str, opens)

    console.print(table)


def render_weekly_trend(weekly: list[dict]) -> None:
    """Weekly activity trend as a mini bar chart table."""
    table = Table(
        title="[bold]Weekly Activity Trend[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        title_justify="left",
        expand=False,
    )
    table.add_column("Week", min_width=12)
    table.add_column("Added", justify="right", min_width=7)
    table.add_column("Sequenced", justify="right", min_width=10)
    table.add_column("Replied", justify="right", min_width=8)
    table.add_column("Trend (replied)", min_width=24)

    max_replied = max((w.get("replied", 0) for w in weekly), default=1) or 1

    if not weekly:
        table.add_row("[dim]No weekly data yet[/dim]", "", "", "", "")
    else:
        for wk in weekly:
            week_label = wk["week_start"]
            added = wk.get("contacts_added", 0)
            sequenced = wk.get("sequenced", 0)
            replied = wk.get("replied", 0)
            bar = _bar(replied, max_replied, width=20)
            replied_str = f"[green]{replied}[/green]" if replied else "[dim]0[/dim]"
            table.add_row(
                week_label,
                str(added),
                str(sequenced),
                replied_str,
                f"[cyan]{bar}[/cyan]",
            )

    console.print(table)


def render_velocity(velocity: dict) -> None:
    """Pipeline velocity panel."""
    v_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    v_table.add_column("metric", style="dim", min_width=36)
    v_table.add_column("value", min_width=12)

    e2s = velocity.get("enriched_to_sequenced_days", 0.0)
    s2r = velocity.get("sequenced_to_replied_days", 0.0)
    total = velocity.get("overall_discovery_to_reply_days", 0.0)
    n = velocity.get("contacts_with_reply", 0)

    color_s2r = "green" if s2r <= 7 else ("yellow" if s2r <= 21 else "red")

    v_table.add_row("Enriched → Sequenced (avg days)", f"{e2s:.1f} d")
    v_table.add_row("Sequenced → First Reply (avg days)", f"[{color_s2r}]{s2r:.1f} d[/{color_s2r}]")
    v_table.add_row("Overall: Discovery → Reply (avg)", f"{total:.1f} d")
    v_table.add_row("Contacts with at least one reply", str(n))

    console.print(Panel(v_table, title="[bold]Pipeline Velocity[/bold]", border_style="magenta"))


def render_intent_impact(impact: dict) -> None:
    """Show intent signal lift panel."""
    if not impact:
        return

    i_table = Table(box=box.SIMPLE, show_header=True, header_style="bold", padding=(0, 2))
    i_table.add_column("Segment", min_width=24)
    i_table.add_column("Sequenced", justify="right", min_width=10)
    i_table.add_column("Replied", justify="right", min_width=8)
    i_table.add_column("Reply %", justify="right", min_width=8)

    with_i = impact.get("with_intent", {})
    without_i = impact.get("without_intent", {})
    lift = impact.get("lift_pct", 0.0)

    lift_color = "green" if lift > 3 else ("yellow" if lift > 0 else "red")

    i_table.add_row(
        "[yellow]With intent signals[/yellow]",
        str(with_i.get("total", 0)),
        str(with_i.get("replied", 0)),
        _colored_rate(with_i.get("reply_rate_pct", 0.0)),
    )
    i_table.add_row(
        "Without intent signals",
        str(without_i.get("total", 0)),
        str(without_i.get("replied", 0)),
        _colored_rate(without_i.get("reply_rate_pct", 0.0)),
    )

    footer = f"[bold {lift_color}]Intent lift: +{lift:.1f}pp[/bold {lift_color}]"
    if not impact.get("has_meaningful_data"):
        footer += "  [dim](not enough data for statistical confidence)[/dim]"

    console.print(Panel(
        i_table,
        title="[bold]Intent Signal Impact[/bold]",
        subtitle=footer,
        border_style="yellow",
    ))


def render_action_queue(db: Database, campaign_name: str | None) -> None:
    """Today's action queue — contacts needing human attention."""
    today = date.today().isoformat()
    try:
        items = db.get_action_queue(
            scheduled_date=today,
            status="pending",
            limit=15,
        )
        if campaign_name:
            items = [
                i for i in items
                if (i.get("companies") or {}).get("campaign_name") == campaign_name
            ]
    except Exception as exc:
        console.print(f"[dim]Could not load action queue: {exc}[/dim]")
        return

    table = Table(
        title=f"[bold]Today's Action Queue[/bold]  [dim]({today})[/dim]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white",
        title_justify="left",
        expand=False,
    )
    table.add_column("Priority", justify="center", min_width=8)
    table.add_column("Company", min_width=28)
    table.add_column("Contact", min_width=22)
    table.add_column("Title", min_width=20)
    table.add_column("Action", min_width=18)
    table.add_column("PQS", justify="right", min_width=5)

    if not items:
        table.add_row("[dim]Queue empty — nothing pending today[/dim]", "", "", "", "", "")
    else:
        priority_icons = {1: "[bold red]!!!  [/bold red]", 2: "[yellow]!!   [/yellow]", 3: "[blue]!    [/blue]"}
        for item in items:
            priority = item.get("priority", 3)
            company = item.get("companies") or {}
            contact = item.get("contacts") or {}
            action = (item.get("action_type") or "").replace("_", " ").title()
            pqs = str(item.get("pqs_at_queue_time") or company.get("pqs_total") or "—")
            icon = priority_icons.get(priority, "     ")
            table.add_row(
                icon,
                (company.get("name") or "Unknown")[:27],
                (contact.get("full_name") or "Unknown")[:21],
                (contact.get("title") or "")[:19],
                action,
                pqs,
            )

    console.print(table)


def render_recommendations(recs: list[str]) -> None:
    """Render optimization recommendations panel."""
    lines = []
    for i, rec in enumerate(recs, 1):
        lines.append(f"  {i}. {rec}")

    content = "\n".join(lines) if lines else "  No recommendations yet."
    console.print(Panel(content, title="[bold]Optimization Recommendations[/bold]",
                        border_style="green"))


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ProspectIQ Pipeline Analytics Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--campaign", help="Filter by campaign name")
    parser.add_argument("--weeks", type=int, default=8, help="Weeks for trend chart (default: 8)")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print plain-text weekly report (Slack-safe, no colors)",
    )
    args = parser.parse_args()

    db = Database()

    # Plain-text report mode
    if args.report:
        reporter = CampaignReporter(db)
        print(reporter.generate_weekly_report(campaign_name=args.campaign))
        return

    # --- Full Rich dashboard ---
    fa = FunnelAnalytics(db)
    reporter = CampaignReporter(db)

    render_header(args.campaign, args.weeks)

    with console.status("[bold cyan]Loading funnel data...[/bold cyan]"):
        funnel_7d = fa.get_funnel_counts(campaign_name=args.campaign, days=7)
        funnel_30d = fa.get_funnel_counts(campaign_name=args.campaign, days=30)

    render_funnel(funnel_7d, funnel_30d)

    with console.status("[bold cyan]Loading breakdowns...[/bold cyan]"):
        by_persona = fa.get_reply_rate_by_persona(days=30)
        by_vertical = fa.get_reply_rate_by_vertical(days=30)
        by_touch = fa.get_reply_rate_by_touch(days=30)

    render_breakdowns(by_persona, by_vertical, by_touch)

    with console.status("[bold cyan]Loading hot accounts...[/bold cyan]"):
        hot_accounts = reporter.get_hot_accounts_report(threshold=10)

    render_hot_accounts(hot_accounts)

    with console.status("[bold cyan]Loading weekly trend...[/bold cyan]"):
        weekly = fa.get_weekly_activity(weeks=args.weeks)

    render_weekly_trend(weekly)

    with console.status("[bold cyan]Loading velocity + intent...[/bold cyan]"):
        velocity = fa.get_pipeline_velocity(campaign_name=args.campaign)
        impact = fa.get_intent_signal_impact()

    render_velocity(velocity)
    render_intent_impact(impact)

    with console.status("[bold cyan]Loading action queue...[/bold cyan]"):
        pass  # Loaded inside render_action_queue

    render_action_queue(db, args.campaign)

    with console.status("[bold cyan]Computing recommendations...[/bold cyan]"):
        recs = reporter.get_optimization_recommendations()

    render_recommendations(recs)

    console.print()
    console.rule(
        f"[dim]Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"• Run [bold]--report[/bold] for Slack-pasteable text[/dim]"
    )
    console.print()


if __name__ == "__main__":
    main()
