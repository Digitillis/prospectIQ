---
name: Product Design Decisions
description: UI design decisions locked in April 1 session — threads, sequences, HITL, billing surface, navigation
type: project
---

Comprehensive UI redesign approved by Avanish on 2026-04-01. ProspectIQ is positioned as a standalone AI-native outbound intelligence product, not just a pipeline tool.

## Navigation Structure (locked)
1. Command Center (home)
2. Outreach Hub (approved/pending/in-flight/done tabs)
3. Threads (split-pane)
4. Sequences (library + builder)
5. Segments (ICP config as UI — replaces icp.yaml)
6. Signals (buying/intent signal feed)
7. Intelligence (analytics)
8. Settings → Billing, Team, API Keys, ICP

## Key Design Decisions

**Thread Library**: Split-pane layout — master list on left, full thread on right. Not a separate page per thread.

**Sequences Library**: Pre-built templates (by cluster/persona) + ability to save custom templates to the library for reuse later.

**Progress Tracking**: Weekly Cadence Tracker widget on Command Center — shows pipeline velocity, reply rates, funnel movement week-over-week.

**HITL (Human-in-the-Loop)**: Attention bar at top of Command Center surfaces pending HITL items prominently. Not buried in a separate page. Items: approve outreach drafts, classify replies, confirm sends.

**Billing**: Usage widget on Command Center (companies researched, seats used, % of plan). Upgrade CTA inline. Full billing page in Settings.

## Background Agent Build
Agent `aa307d75e76e4c5f7` launched 2026-04-01 to build all 12 UI components. Check output before starting next session's UI work.
