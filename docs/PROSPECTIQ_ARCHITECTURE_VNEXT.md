# ProspectIQ vNext Architecture
**Status:** DESIGN — not yet implemented
**Date:** 2026-05-14
**Owner:** Avanish Mehrotra
**Prior analysis:** docs/ARCHITECTURE_FAILURE_ANALYSIS.md (Stages 1–5)

## Purpose of this document
ProspectIQ vNext is the redesign of ProspectIQ from a fragile, multi-writer CRUD system into a governed intelligence and orchestration engine. This document defines the target architecture, component design, data model, migration path, and governance model.

This is a prescription document, not a diagnosis. For the failure analysis and stabilization plan, see ARCHITECTURE_FAILURE_ANALYSIS.md.

---

## SECTION A — Core Architecture Thesis

### What ProspectIQ fundamentally IS

ProspectIQ is not a CRM. It is not an email scheduler. It is not a draft generator with a queue attached. It is a **governed intelligence and orchestration engine for outbound revenue manufacturing**. Two things make this distinct from the systems it superficially resembles:

1. **It owns the relationship state** — every prospect, every contact, every conversation thread, every signal is part of one continuous, evolving model that the engine maintains and reasons over. A CRM stores facts; ProspectIQ stores the live state of an evolving relationship between Digitillis and each company.

2. **It owns the decision authority** — the engine decides what should happen next, when, whether it is allowed, whether it needs review, and who or what executes it. A scheduler obeys cron; ProspectIQ obeys evidence, policy, and governance.

The failure analysis (Stages 1–5) documented why the current system cannot do either of these well: lifecycle state is implicit across mutable columns; eight code paths can independently approve a draft; `sent_at` is set before assertions run; webhook handlers double-count events; the same email's history is reconstructable only by joining four tables and trusting that no side-effect write silently failed. The system has the **inputs** of an intelligence engine (research, signals, suppression, replies, sequence orchestration) but the **architecture** of a CRUD app.

### Why two distinct intelligence layers

Trying to fix the current failures by adding more checks at the API layer or more services in the middle does not work. The failures are not about missing checks — they are about **the system not having a coherent picture of any single prospect at any point in time** and **not having a single decision authority that owns lifecycle transitions**.

The fix is two first-class logical layers, each with one job:

- **Context Intelligence Layer.** Owns what the system knows. Before any action runs, this layer assembles every relevant fact about the prospect, contact, company, thread, sibling contacts, prior messages, sequence state, suppression posture, evidence, and risk into one structured object — the `ContextPacket`. The packet is the only input the rest of the system trusts. If two contacts at the same company are running parallel sequences, the packet sees both. If a sibling replied yesterday, the packet sees it. If a fabricated claim was flagged on a prior draft, the packet sees it. The packet prevents disjointed, contradictory, repeated outreach by making the full picture impossible to ignore.

- **Orchestration Layer.** Owns what happens next. Consumes the `ContextPacket`, evaluates governance via the `PolicyEngine`, computes risk, then issues commands: proceed, hold, suppress, escalate, dispatch. Every state transition in the system flows through this layer; every transition writes to `workflow_events`. The orchestrator does not generate content, does not call providers, and does not evaluate policy rules — it composes the services that do those things.

These two layers are not microservices. They are modules inside the monolith with strict boundaries enforced by Postgres roles and module APIs.

### How autonomy, governance, intelligence, and HITL fit together

The four are not in tension. They are layered, and each one strengthens the others when sequenced correctly:

- **Intelligence first**: the Context Packet is the substrate. Without it, nothing else can be trusted.
- **Governance on top**: the `PolicyEngine` reads the packet and answers `PROCEED / HOLD / BLOCK / ESCALATE` against an explicit, versioned policy snapshot. Governance is schema-first, service-second, API-last.
- **Autonomy as the default**: when governance returns `PROCEED` and risk is `LOW`, the engine acts without human involvement. The current system inverts this — every draft requires human approval, which produces shortcut paths that bypass governance. Autonomy is safer than mandatory human approval because it eliminates the shortcuts.
- **HITL as the exception**: humans are pulled in where their judgment is structurally required — positive replies, ambiguous classifications, high-risk content, overrides. HITL is not a queue depth metric to minimize; it is a checkpoint to honor.

### Governing principle

> Every state in the system has one explicit column, one writer, one authority, one transition log, and one evidence chain. Every action that touches a prospect is preceded by a fresh Context Packet and a fresh Policy Decision. Every transition is captured in `workflow_events`. Every external boundary is idempotent. Every claim in every message is grounded in registered evidence.

If a design decision cannot answer "what state column does this write, which service owns the writer, what event is emitted, what context packet was used, and which policy snapshot was in force" — the decision is wrong.

### Eight-layer logical architecture

```
+--------------------------------------------------------------------------+
| L8  OPERATOR CONTROL PLANE                                               |
|     Dashboards, kill switches, overrides, dry-run, quarantine, audit     |
|     reads: all read-side projections; writes: through OrchestrationService|
+--------------------------------------------------------------------------+
                                |
                                v
+--------------------------------------------------------------------------+
| L7  FEEDBACK AND LEARNING                                                |
|     provider_events ingestion, reply classification, signal updates,     |
|     pattern surfacing back to Context Intelligence                       |
+--------------------------------------------------------------------------+
                                |
                                v
+--------------------------------------------------------------------------+
| L6  EXECUTION                                                            |
|     SendWorker, outbox consumer, OutboundProvider adapters,              |
|     reconciliation. NO decisions made here.                              |
+--------------------------------------------------------------------------+
                                |
                                v
+--------------------------------------------------------------------------+
| L5  ORCHESTRATION (decision authority)                                   |
|     OrchestrationService, DecisionEngine, RiskScoringService,            |
|     SequenceCoordinator, SuppressionCoordinator, ReplyCoordinator        |
+--------------------------------------------------------------------------+
                                |       ^
                  consumes      |       |  emits commands +
                  ContextPacket |       |  workflow_events
                                v       |
+----------------------------------+ +----------------------------------+
| L4  GOVERNANCE AND POLICY        | | L3  MESSAGING INTELLIGENCE       |
|     PolicyEngine.evaluate()      | |     DraftGenerator, validators,  |
|     7-layer gate stack,          | |     DraftStrategy, evidence-     |
|     policy_snapshots, overrides  | |     grounded prompts             |
+----------------------------------+ +----------------------------------+
                                |       |
                                +-------+
                                |
                                v
+--------------------------------------------------------------------------+
| L2  CONTEXT INTELLIGENCE                                                 |
|     ContextPacketBuilder.build() — single source of truth assembled      |
|     fresh per action; stored in context_packets; linked to every         |
|     draft, approval, send_attempt                                        |
+--------------------------------------------------------------------------+
                                |
                                v
+--------------------------------------------------------------------------+
| L1  DATA FOUNDATION                                                      |
|     companies, contacts, research_intelligence, interactions,            |
|     engagement_sequences, suppression_events, provider_events,           |
|     outreach_drafts, draft_versions, send_attempts, outbound_queue,      |
|     workflow_events, approval_attestations, policy_snapshots,            |
|     context_packets, risk_scores, autonomy_decisions, learning_signals   |
+--------------------------------------------------------------------------+
```

The data flow is strictly upward through L1 → L2 → L3+L4 → L5 → L6 → L7 → L8 for forward execution. Operator commands enter through L8 and descend to L5 (OrchestrationService) which fans out as needed. There are no diagonal shortcuts. The current architecture's failures all stem from diagonal shortcuts.

---

## SECTION B — Layered Architecture

### B.1 Data Foundation Layer

**What it is:** The raw persistent state of the system. Not a service — just tables. No business logic lives here; the schema enforces invariants and accepts writes from designated services only.

**Tables owned (full list):**

| Table | Purpose |
|---|---|
| `companies` | Company master |
| `contacts` | Contact master |
| `research_intelligence` | Per-company research output |
| `engagement_sequences` | Active sequence anchors |
| `sequence_step_state` | Per-contact-per-step explicit state |
| `interactions` | Read-side projection — analytics only |
| `outreach_drafts` | Draft master, pointers to versions |
| `draft_versions` | Immutable body/subject history |
| `draft_quality_results` | Validator output per version |
| `evidence_registry` | Approved claim catalog |
| `claim_validation_results` | Per-draft claim validation outcomes |
| `approval_attestations` | One row per approval; immutable |
| `autonomy_decisions` | Engine decision log |
| `risk_scores` | Per-draft risk score history |
| `outbound_queue` | Transactional outbox |
| `send_attempts` | Per-attempt delivery state |
| `provider_events` | Idempotent webhook intake |
| `workflow_events` | Authoritative state transition log |
| `suppression_events` | Append-only suppression log |
| `company_holds` | Operator-set company holds |
| `contact_holds` | Operator-set contact holds |
| `sequence_state_transitions` | Sequence lifecycle audit |
| `operator_overrides` | Audited override actions |
| `dead_letter_queue` | Terminal failures |
| `reconciliation_runs` | Drift detection runs |
| `policy_snapshots` | Versioned policy state |
| `learning_signals` | Patterns surfaced for context layer |
| `context_packets` | Per-action context snapshots |
| `campaign_threads`, `thread_messages` | Reply correlation |
| `outreach_send_config` | Per-workspace send caps (single source) |
| `outbound_eligible_contacts` | SQL eligibility view |
| `users` | Workspace operator identity |
| `workspaces` | Tenancy |
| `api_costs` | Provider cost ledger |

**Who can write to each table (Postgres roles):**

| Table | Writer role |
|---|---|
| `outreach_drafts.lifecycle_state` (approval columns) | `prospectiq_writer_approval_svc` only |
| `outreach_drafts.lifecycle_state` (send columns) | `prospectiq_writer_send_worker` only |
| `draft_versions` | `prospectiq_writer_draft_generator` (INSERT only) |
| `approval_attestations` | `prospectiq_writer_approval_svc` (INSERT only) |
| `outbound_queue` | `prospectiq_writer_approval_svc` (INSERT), `prospectiq_writer_send_worker` (UPDATE state) |
| `send_attempts` | `prospectiq_writer_send_worker` |
| `provider_events` | `prospectiq_writer_webhook_svc` |
| `workflow_events` | All writer roles (INSERT only) |
| `suppression_events` | `prospectiq_writer_suppression_svc` (INSERT + revoke UPDATE) |
| `company_holds`, `contact_holds` | `prospectiq_writer_operator_svc` |
| `context_packets` | `prospectiq_writer_context_builder` (INSERT only) |
| `risk_scores` | `prospectiq_writer_risk_svc` (INSERT only) |
| `autonomy_decisions` | All writer roles that emit decisions (INSERT only) |
| `policy_snapshots` | `prospectiq_writer_policy_svc` (INSERT, UPDATE superseded_at only) |
| `evidence_registry` | `prospectiq_writer_evidence_svc` |
| `contacts.lifecycle_state` | `prospectiq_writer_contact_state_svc` |
| `companies.lifecycle_state` | `prospectiq_writer_company_state_svc` |

**What must NOT write here directly:**
- API route handlers (they call services)
- Operator CLI scripts (they call the API)
- Business logic helpers (they call services)
- Webhook handlers (they INSERT into `provider_events` and return; processing is deferred to the worker)
- The `?force=true` query parameter (removed; replaced by override two-step)

**Current assets to keep:**
- `outreach_drafts` (id, FKs, indexes preserved; lifecycle_state added)
- `companies`, `contacts` (preserved; lifecycle_state added; enrichment columns made read-only via grants)
- `research_intelligence` (preserved unchanged)
- `outreach_send_config` (promoted to single send-cap source)
- `campaign_threads`, `thread_messages` (preserved; UNIQUE on provider_message_id added)
- `send_assertions` (preserved as gate evidence; referenced by send_attempts.failed_assertion)
- `outbound_eligible_contacts` (preserved; consulted by ContextPacketBuilder)
- `interactions` (preserved as analytics projection, no longer authoritative)
- `suppression_log` (migrated to `suppression_events`; 30-day dual-write window)
- `workspace_audit_log` (preserved as UI projection of workflow_events)
- Migration 003 sent-draft delete-protect trigger (extended to UPDATE on body/subject)

**Current assets to retire:**
- `outreach_outcomes` writes at draft-gen time (delete; rewrite only on confirmed send)
- `pace_limiter.CAMPAIGN_DEFAULTS` (dead code)
- `workspaces.settings.daily_send_limit` JSONB key (superseded)
- `limits.yaml::outreach.daily_send_limit` (superseded; YAML keeps reviewer cap only)
- Module-level `COMPANY_COOLDOWN_DAYS = 14` aliases in pre_send_assertions.py (read from policy_snapshot)
- The second `OutreachAgent` class in `backend/app/agents/outreach_agent.py`
- `EngagementAgent.process_webhook_event` static method
- One of the two Instantly webhook routers
- `weekly_contact_backup` to `/Volumes/...` path

### B.2 Context Intelligence Layer

**What it is:** The layer that assembles everything the system knows about a company, contact, and thread before any action is taken. Its only output is the `ContextPacket`.

**Responsibility:** Produce a `ContextPacket` for every draft generation, every approval evaluation, and every send-time claim. The packet is built fresh on demand (with a short TTL cache); it is never reconstructed by readers from raw tables.

**Inputs:** All foundation layer tables; specifically:
- `companies`, `contacts` (state, traction, suppression, enrichment)
- `research_intelligence` (pain signals, hooks, technology stack)
- `outreach_drafts` + `draft_versions` (prior messages, prior rejection reasons, prior edits)
- `send_attempts` (delivered timestamps, opens, clicks, bounces)
- `interactions` (engagement projection)
- `campaign_threads`, `thread_messages` (thread continuity)
- `engagement_sequences`, `sequence_step_state` (where in sequence)
- `suppression_events` (active suppressions at contact, company, domain, email scope)
- `company_holds`, `contact_holds` (operator pauses)
- `evidence_registry` (allowed and prohibited claims for this sector)
- `risk_scores` (prior scores)
- `learning_signals` (patterns surfaced for this contact/company/persona)
- `policy_snapshots` (active policy)

**Outputs:** `ContextPacket` object plus a row in `context_packets` table with the serialized packet, version hash, build duration, and the policy_snapshot_id in force.

**Source of truth:** Built fresh on demand with TTL cache per field group; version hash detects staleness. The packet itself is pinned at the moment of an action — every draft, approval, and send_attempt references the exact `context_packet_id` that was its input.

**What it must NOT do:**
- Make decisions (that is the Orchestration Layer)
- Trigger actions (that is the Execution Layer)
- Write to business tables (it only writes to `context_packets`)
- Call any external provider
- Evaluate policy rules (delegates to PolicyEngine via the packet's pre-computed `allowed_claims`/`prohibited_claims`/`risk_dimension_inputs`)

**Current code to reuse:**
- `backend/app/core/channel_coordinator.get_company_traction()` — traction detection logic
- `backend/app/core/channel_coordinator.is_company_locked()` — company lock detection
- `backend/app/core/suppression.is_suppressed()` — suppression check logic (refactored into SuppressionCoordinator but the SQL stays the same)
- `backend/app/agents/outreach.py` — research/hooks/history assembly code (lines 250–800)
- Prior-message lookup logic in `engagement.py` for thread continuity
- `outreach_guidelines.yaml`, `offer_context.yaml` loaders

**Current code to retire or isolate:**
- Implicit state derivation across `outreach_drafts.sent_at + engagement_sequences.current_step + email_sent interactions` (replaced by `sequence_step_state` + packet fields)
- Per-action ad-hoc fetches in `engagement.py:_send_approved_drafts` (lines 593–615) — replaced by the packet
- `_load_send_config` ad-hoc loading (read once per packet build)
- `OutreachAgent.run` inline assembly of company/contact/research data — moved to builder

### B.3 Messaging Intelligence Layer

**What it is:** The layer that determines WHAT to say. Generates the draft using the Context Packet as its only input.

**Responsibility:** Produce a `DraftStrategy` (the plan) and execute it (the LLM call) under governed prompt construction. Persist the resulting body as an immutable `draft_versions` row.

**Inputs:**
- `ContextPacket` (the only contextual input)
- `evidence_registry` rows scoped to the company's sector
- `sequences.yaml` step definition for the target step
- `outreach_guidelines.yaml` voice/tone/anti-patterns
- `policy_snapshot` (validator version, generation model, max_tokens)

**Outputs:**
- Raw draft text (subject + body)
- `DraftStrategy` (the plan: angle, tone, CTA, references, allowed claims)
- `DraftQualityResult` (4-pass validator output: HARD_REJECT / QUARANTINE / PASS plus per-rule issues)
- `claim_ids_referenced` (audit chain back to `evidence_registry`)

**Source of truth:** `context_packet_id` is pinned at draft creation; the LLM call is recorded with its prompt hash, model name, temperature; the resulting body is INSERTed once into `draft_versions` and never mutated.

**What it must NOT do:**
- Read DB tables directly (only the packet)
- Make orchestration decisions
- Send emails
- Call providers other than Anthropic
- Write to `outreach_drafts.lifecycle_state` (DraftService does that)

**Current code to reuse:**
- Prompt construction patterns in `backend/app/agents/outreach.py` (system prompt assembly, guidelines injection)
- The integrity regex (`_INTEGRITY_RULES`) — promoted to one of four validator passes
- `backend/app/core/draft_quality.py::validate_draft` — promoted to the warn-and-quarantine validator pass
- Model router logic for picking step-1 vs step-2+ models

**Current code to retire:**
- The second `OutreachAgent` in `backend/app/agents/outreach_agent.py` — delete the file
- `outreach_outcomes` write at draft-gen (deleted)
- The HTTP path `OutreachAgent.generate_draft` that bypasses gates — rewired through the same DraftGenerator
- Direct `anthropic.Anthropic` calls in multiple places — single call site in DraftGenerator

### B.4 Governance and Policy Layer

**What it is:** The layer that enforces rules. Single source of truth for: eligibility, limits, cooldowns, reviewer requirements, overrides, claim grounding, send-window time-of-day.

**Responsibility:** Expose `PolicyEngine.evaluate(action, context_packet) → PolicyDecision`. Every action that mutates lifecycle state must call this method first.

**Inputs:**
- `policy_snapshots` (active row per workspace)
- `outreach_send_config` (per-workspace daily cap, batch size, send_enabled)
- `risk_scores` (latest per draft, joined via context packet)
- `approval_attestations` (24-hour reviewer cap counts)
- `evidence_registry` (claim coverage check)
- `suppression_events` (active suppressions)
- `company_holds`, `contact_holds`

**Outputs:**
- `PolicyDecision`:
  ```
  PolicyDecision = {
      decision: 'PROCEED' | 'HOLD' | 'BLOCK' | 'ESCALATE',
      blocking_gate: str | None,
      reason: str,
      layer_results: list[GateResult],  # 7-layer stack output
      policy_snapshot_id: UUID,
      evaluated_at: datetime,
      score_inputs: dict,  # passed to RiskScoringService
  }
  ```

**Source of truth:** `policy_snapshots` (versioned, hot-editable, every approval/send/decision references the exact snapshot id). The stale `limits.yaml::outreach.daily_send_limit` is removed; the stale `workspaces.settings.daily_send_limit` is removed; `pace_limiter.CAMPAIGN_DEFAULTS` is deleted. Single source: `outreach_send_config.daily_limit` per workspace + `policy_snapshots.payload.send_limits.*` for the rest.

**What it must NOT do:**
- Mutate records
- Trigger sends
- Call providers
- Run the LLM
- Compute risk scores (it consumes them; RiskScoringService computes them)

**Current code to reuse:**
- `backend/app/core/pre_send_assertions.py` — every assertion function survives unchanged; they become individual `Gate` implementations registered under the policy engine
- `backend/app/core/suppression.py` — `is_suppressed`, `record_suppression`, `maybe_escalate_to_company` (refactored into SuppressionCoordinator + PolicyEngine reads its tables)
- `backend/app/core/channel_coordinator.py` — `is_company_locked`, `can_use_channel` — survive as gates
- `outreach_send_config` table — promoted to the sole send-cap source
- `limits.yaml::send_limits.*` — survives, read via policy snapshot
- The reviewer 24-hour cap logic in `approvals.py:_max_approvals_per_reviewer_per_day`

**Current code to retire:**
- `limits.yaml::outreach.daily_send_limit` (removed; outreach_send_config is authoritative)
- `workspaces.settings.daily_send_limit` JSONB key (removed)
- `workspace_scheduler.workspace_daily_sends_ok` (deleted; the explicit "intentionally not called here" comment at `main.py:189–194` is resolved by removing the function entirely)
- `backend/app/core/pace_limiter.py` — entire file deleted
- Module-level `COMPANY_COOLDOWN_DAYS = 14` legacy alias in `pre_send_assertions.py` (read from policy snapshot)

### B.5 Orchestration Layer

**What it is:** The central decision authority. Owns every lifecycle state transition. Composes the other layers to answer "what happens next for this entity?"

**Responsibility:**
- Decide what happens next for every entity (draft, contact, sequence, reply)
- Own the state machine transitions in Section F
- Write to `workflow_events` on every transition, in the same transaction as the state change
- Delegate policy evaluation to PolicyEngine, risk scoring to RiskScoringService, content generation to DraftGenerator, dispatch to SendWorker

**Inputs:**
- `ContextPacket` (current state of the world)
- `PolicyDecision` (from PolicyEngine, given the packet)
- `RiskScore` (from RiskScoringService, given the packet)
- Current lifecycle state of the target entity

**Outputs:**
- Commands to the Execution Layer (e.g., insert into `outbound_queue`)
- State transitions on the target entity (single-writer Postgres role)
- `workflow_events` rows for the transition
- `autonomy_decisions` rows when the engine acts autonomously

**Source of truth:** `workflow_events` (append-only) plus the current state columns on entities. Every state column has exactly one Postgres role authorized to write it; the orchestration service is the only Python module holding that role's connection.

**What it must NOT do:**
- Generate content (delegates to DraftGenerator)
- Call providers (delegates to SendWorker, which calls the OutboundProvider adapter)
- Evaluate policy rules directly (delegates to PolicyEngine)
- Build the context packet (delegates to ContextPacketBuilder)
- Run LLMs

**Current code to reuse:**
- Sequence-advance logic in `engagement.py:_process_due_sequences` — restructured into `SequenceCoordinator.advance_sequence()`
- The atomic claim pattern in `engagement.py:540–569` — replaced by `SELECT FOR UPDATE SKIP LOCKED` on outbound_queue, but the intent is preserved
- Reply auto-action logic in `webhooks.py:_handle_email_reply` and `webhooks.py:_handle_email_unsubscribed` — restructured into `ReplyCoordinator.process_reply_event()`

**Current code to retire:**
- The in-process APScheduler ticks that embed orchestration logic directly inside the FastAPI request thread (`backend/app/api/main.py:2030–2218`) — moved to a separate worker process
- Direct `db.update_contact_state` calls scattered across webhook handlers — replaced by `ContactStateService` invoked by Orchestrator
- `EngagementAgent.process_webhook_event` static method — deleted
- The compare-and-swap on `sent_at` as the concurrency primitive — replaced by `outbound_queue.draft_id UNIQUE` plus advisory lock

### B.6 Execution Layer

**What it is:** The layer that actually sends things. No decisions made here — only execution of approved commands.

**Responsibility:**
- Consume `outbound_queue` via `SELECT FOR UPDATE SKIP LOCKED`
- Create `send_attempts` row, run last-mile assertions
- Call the OutboundProvider adapter (Resend for email)
- Write provider response, update `send_attempts.state`, project to side tables in a second transaction

**Inputs:**
- `outbound_queue` rows in state `PENDING`
- `send_attempts` rows (own table)

**Outputs:**
- `send_attempts` state transitions (`CLAIMED → ASSERTING → DISPATCHED → DELIVERED | BOUNCED | FAILED`)
- `provider_events` rows (when delivery confirmation arrives via webhook)
- Projections: `interactions` (`email_sent`), `campaign_threads`, `thread_messages`, `sequence_step_state` advance, `contacts.lifecycle_state` advance, `companies.lifecycle_state` advance

**Source of truth:** `send_attempts` table for delivery state; `outbound_queue` for queue state. `outreach_drafts.sent_at` is reduced to a denormalized cache maintained by trigger from `send_attempts`.

**What it must NOT do:**
- Apply governance rules (already applied at approval; last-mile re-check delegated to PolicyEngine.gate_stack)
- Generate content (consumes the pinned `draft_version`)
- Approve drafts
- Make routing decisions about which sequence to use
- Update `lifecycle_state` directly except for the `SENDING / SENT / FAILED` transitions it owns

**Current code to reuse:**
- Resend dispatch call site (`engagement.py:730–740`) — extracted into `ResendAdapter.send()` and called from `SendWorker._dispatch()`
- Sender pool selection (`_pick_sender`) — preserved
- The Resend `idempotency_key=draft.id` pattern (preserved; complemented by DB UNIQUE)
- Plain-to-HTML conversion (`plain_to_html`) — preserved

**Current code to retire:**
- The `sent_at` compare-and-swap that embeds claim + governance + dispatch in one function (engagement.py:540–887) — split into the three transactions in Section J.2
- Six post-send writes wrapped in `try/except` marked "non-fatal" — replaced by the post-send transaction
- The rollback function `_rollback_sent_at` (lines 156–207) — no longer needed once `sent_at` is decoupled

### B.7 Feedback and Learning Layer

**What it is:** The layer that closes the loop — turning provider signals and human behavior into system intelligence.

**Responsibility:**
- Drain `provider_events` (the idempotent webhook intake)
- Classify replies via `ReplyClassifier`
- Update signal state on contacts and companies
- Surface patterns to the Context Intelligence Layer via `learning_signals`
- Surface reviewer feedback (edits, rejections, force-approvals) back to the generator

**Inputs:**
- `provider_events` (received from webhooks)
- `interactions` (engagement projection)
- `workflow_events` (transitions for pattern analysis)
- `outreach_edit_feedback` (reviewer edits)

**Outputs:**
- Signal updates on `contacts` and `companies` (via ContactStateService / CompanyStateService)
- `learning_signals` rows (patterns surfaced for the next generation cycle)
- HITL queue items via `ReplyCoordinator → OrchestrationService`

**Source of truth:** `interactions` (engagement projection — analytics only); `learning_signals` (patterns). Provider events are the input; never the authoritative state.

**What it must NOT do:**
- Directly mutate send state
- Override governance
- Approve drafts
- Call providers (it consumes provider events, doesn't make outbound calls)

### B.8 Operator Control Plane

**What it is:** The operator-facing surface for visibility, control, and override.

**Responsibility:**
- Expose current system state (read-side projections)
- Enable kill switches and overrides with audit
- Show explanations: "why did the engine do X" / "why is draft Y on hold"

**Inputs:** All layers read-only for observation. Writes pass through `OrchestrationService` (for holds, overrides, manual approvals, manual sends) so every operator action lands in `workflow_events`.

**Outputs:** Operator commands routed to `workflow_events` plus the relevant coordinator. Dashboard read models.

**Source of truth:** `workflow_events` for audit. `autonomy_decisions` for engine reasoning. Current state columns for live view.

**What it must NOT do:**
- Bypass governance
- Write directly to business tables
- Call providers
- Mutate suppression state (must go through SuppressionCoordinator)
- Approve drafts without going through ApprovalService

---

## SECTION C — Context Intelligence Layer Design

### C.1 The Context Packet

`ContextPacket` is the system's working memory for one action. Built fresh, pinned at the action, queryable forever after. Every draft generation, every approval evaluation, every send-time gate check consumes one — and only one — `ContextPacket`.

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class TractionState(str, Enum):
    NONE = "NONE"          # No engagement signals at company
    COLD = "COLD"          # Sends in flight, no engagement yet
    WARM = "WARM"          # At least 1 open or human click in past 14 days
    HOT = "HOT"            # Any reply in past 30 days, OR 2+ human events in 7 days

@dataclass(frozen=True)
class SiblingContactSummary:
    contact_id: str
    full_name: str
    title: str
    lifecycle_state: str             # contacts.lifecycle_state
    last_outbound_step: Optional[int]
    last_outbound_at: Optional[datetime]
    last_reply_at: Optional[datetime]
    last_reply_sentiment: Optional[str]  # positive | negative | question | neutral | none
    active_sequence_id: Optional[str]
    active_sequence_step: Optional[int]
    is_active_conversation: bool     # any reply in past 14 days

@dataclass(frozen=True)
class PriorMessageSummary:
    draft_id: str
    sequence_step: int
    sequence_name: str
    subject: str
    body_summary: str                # first 240 chars of body
    body_hash: str                   # sha256(body) — match-detection
    sent_at: datetime
    primary_angle: str               # extracted from draft_versions.generation_metadata
    referenced_claim_ids: list[str]
    open_count: int
    click_count: int
    replied: bool

@dataclass(frozen=True)
class ReplyHistorySummary:
    reply_id: str
    received_at: datetime
    classification: str              # interested | objection | referral | soft_no | oof | bounce | unsubscribe | other
    classifier_confidence: float
    body_summary: str                # first 240 chars of inbound body
    handled: bool                    # actioned or auto-archived
    handled_by: Optional[str]
    handled_action: Optional[str]    # continue_sequence | manual_reply | mark_converted | unsubscribe | archive

@dataclass(frozen=True)
class EvidenceClaim:
    id: str
    claim_type: str                  # PRODUCT_FACT | BENCHMARK_CITATION | OUTCOME_STATEMENT | ANTI_PATTERN
    claim_text: str
    claim_pattern: Optional[str]     # regex for equivalent phrasings
    source: str
    source_url: Optional[str]
    confidence: str                  # high | medium | low
    applicable_sectors: list[str]
    effective_from: datetime
    expires_at: Optional[datetime]

@dataclass(frozen=True)
class ContextPacket:
    # ----- Identity -----
    packet_id: str                   # UUID; persisted to context_packets
    workspace_id: str
    company_id: str
    contact_id: str
    sequence_id: str
    sequence_step: int
    generated_at: datetime
    version_hash: str                # sha256 of ordered key fields; detects staleness
    policy_snapshot_id: str

    # ----- Company intelligence -----
    company_name: str
    company_summary: str             # from research_intelligence (200 chars)
    company_tier: str                # pmfg1 | pmfg2 | pmfg3 | unclassified
    employee_count: Optional[int]
    industry: Optional[str]
    naics_code: Optional[str]
    pain_signals: list[str]
    personalization_hooks: list[str]
    technology_stack: list[str]
    company_traction_state: TractionState
    sibling_contact_history: list[SiblingContactSummary]
    company_hold_active: bool
    company_hold_reason: Optional[str]
    company_hold_expires_at: Optional[datetime]
    company_lifecycle_state: str

    # ----- Contact intelligence -----
    contact_name: str
    contact_title: str
    contact_seniority: str           # ic | manager | director | vp | csuite | owner_founder
    contact_persona: str             # from persona_type
    icp_fit_score: float             # 0–1
    contact_outreach_state: str      # contacts.lifecycle_state
    contact_suppression_state: Optional[str]   # None if CLEAN
    contact_cooldown_active: bool
    contact_cooldown_expires_at: Optional[datetime]
    contact_hold_active: bool
    contact_hold_reason: Optional[str]
    contact_email: str
    contact_email_status: str        # verified | catch_all | invalid | bounce | unverified | unknown

    # ----- Thread / prior message context -----
    prior_messages: list[PriorMessageSummary]   # every sent step for this contact
    last_sent_subject: Optional[str]
    last_sent_body_summary: Optional[str]       # first 240 chars
    last_sent_at: Optional[datetime]
    days_since_last_touch: Optional[int]
    prior_open_count: int
    prior_click_count: int
    reply_history: list[ReplyHistorySummary]
    active_conversation: bool        # True if any reply in last 14 days OR thread state in HOT
    thread_id: Optional[str]
    prior_step_body_hashes: list[str]   # quick set-intersection for anti-repetition

    # ----- Sequence context -----
    sequence_name: str
    sequence_objective: str          # from sequences.yaml
    step_intent: str                 # from sequences.yaml step definition
    step_tone: str                   # from sequences.yaml step definition
    step_max_words: int
    step_anti_patterns: list[str]
    prior_step_reference_allowed: bool   # True for step >= 2
    next_scheduled_step_at: Optional[datetime]

    # ----- Governance -----
    allowed_claims: list[EvidenceClaim]
    prohibited_claims: list[str]     # from evidence_registry + guidelines
    claim_citation_required: bool
    content_risk_score: float        # 0–100 component
    relationship_risk_score: float   # 0–100 component
    send_risk_score: float           # 0–100 component
    overall_risk_score: float        # 0–100 weighted total
    overall_risk_bucket: str         # LOW | MEDIUM | HIGH | BLOCKED
    triggered_risk_dimensions: list[str]
    sender_reputation_score: float   # 0–1, sender bounce rate inverse
    workspace_send_enabled: bool
    workspace_send_cap_remaining: int    # daily_limit minus today's sends

    # ----- Recommended action -----
    recommended_angle: str           # synthesized from personalization_hooks + pain_signals + sequence step intent
    message_objective: str           # what this step should accomplish in plain English
    recommended_next_action: str     # GENERATE | HOLD_FOR_CONTEXT_REFRESH | HOLD_FOR_HUMAN_REVIEW | SUPPRESS | BLOCK | ESCALATE
    required_human_review_reason: Optional[str]
    explanation: str                 # operator-facing one-paragraph summary
```

### C.2 Context Packet Builder

```python
# backend/app/intelligence/context_builder.py

from backend.app.core.database import Database

class ContextPacketBuilder:
    """
    The only entry point for assembling a ContextPacket.
    Connects to the DB via a read-only role; never mutates.
    """

    def __init__(self, db: Database, workspace_id: str, policy_snapshot_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.policy_snapshot_id = policy_snapshot_id
        self._cache = ContextPacketCache(workspace_id)

    def build(self, company_id: str, contact_id: str,
              sequence_id: str, sequence_step: int) -> ContextPacket:
        """
        Returns a freshly assembled ContextPacket. Idempotent: re-running
        the same call produces an identical packet (same version_hash)
        unless the underlying data changed.
        """
        key = (self.workspace_id, company_id, contact_id, sequence_id, sequence_step)
        cached = self._cache.get(key)
        if cached and not self._is_stale(cached):
            return cached

        packet = self._assemble(company_id, contact_id, sequence_id, sequence_step)
        self._persist(packet)
        self._cache.put(key, packet)
        return packet

    def _assemble(self, company_id, contact_id, sequence_id, sequence_step) -> ContextPacket:
        company = self._fetch_company(company_id)
        contact = self._fetch_contact(contact_id)
        research = self._fetch_research(company_id)
        siblings = self._fetch_sibling_contacts(company_id, contact_id)
        prior_msgs = self._fetch_prior_messages(contact_id, sequence_id)
        replies = self._fetch_reply_history(contact_id, sequence_id)
        suppression = self._fetch_suppression_state(contact_id, company_id)
        holds = self._fetch_active_holds(contact_id, company_id)
        sequence_def = self._fetch_sequence_definition(sequence_id, sequence_step)
        evidence = self._fetch_eligible_evidence(company.industry, sequence_step)
        traction = self._compute_traction(company_id, siblings, replies)
        sender_rep = self._fetch_sender_reputation(self.workspace_id)
        send_caps = self._fetch_send_capacity(self.workspace_id)
        return self._materialize(
            company, contact, research, siblings, prior_msgs, replies,
            suppression, holds, sequence_def, evidence, traction,
            sender_rep, send_caps,
        )
```

**DB queries it runs (specific tables, in order):**

1. `companies WHERE id = $company_id` — company master fields
2. `contacts WHERE id = $contact_id` — contact master fields
3. `research_intelligence WHERE company_id = $company_id` — pain signals, hooks, tech stack
4. `contacts WHERE company_id = $company_id AND id != $contact_id` — sibling contacts (limit 25, ordered by last_touch_at)
5. For each sibling: `outreach_drafts JOIN send_attempts WHERE contact_id IN (...) AND send_attempts.state='DELIVERED' ORDER BY delivered_at DESC LIMIT 5 per contact`
6. For each sibling: `provider_events WHERE contact_id IN (...) AND event_type='reply_received' ORDER BY received_at DESC LIMIT 1 per contact`
7. `outreach_drafts JOIN draft_versions JOIN send_attempts WHERE contact_id = $contact_id AND send_attempts.state='DELIVERED' ORDER BY sequence_step ASC` — prior messages
8. `provider_events WHERE contact_id = $contact_id AND event_type IN ('reply_received', 'email_opened', 'email_clicked') ORDER BY received_at DESC LIMIT 50` — reply and engagement history
9. `suppression_events WHERE (contact_id = $contact_id OR company_id = $company_id OR domain = $domain OR email = $email) AND revoked_at IS NULL` — active suppressions
10. `company_holds WHERE company_id = $company_id AND released_at IS NULL`
11. `contact_holds WHERE contact_id = $contact_id AND released_at IS NULL`
12. `engagement_sequences JOIN sequence_step_state WHERE sequence_id = $sequence_id`
13. `evidence_registry WHERE is_active=TRUE AND ($company.industry = ANY(applicable_sectors) OR applicable_sectors IS NULL) AND effective_from <= NOW() AND (expires_at IS NULL OR expires_at > NOW())`
14. `outreach_send_config WHERE workspace_id = $workspace_id` — daily cap
15. `send_attempts WHERE workspace_id = $workspace_id AND state='DELIVERED' AND delivered_at >= today_start` — today's send count
16. `send_attempts WHERE workspace_id = $workspace_id AND state IN ('BOUNCED','COMPLAINED') AND delivered_at >= NOW() - INTERVAL '7 days'` — sender reputation

**Assembly logic per major section:**

- **Company section:** Direct projection from companies + research_intelligence. Traction state computed from siblings' recent engagement (no engagement → NONE; opens only → COLD; click+open → WARM; any reply → HOT).
- **Contact section:** Direct projection from contacts. `contact_cooldown_active` computed by checking last `send_attempts.delivered_at` for this contact vs `policy_snapshot.send_limits.step_gap_days_step_2` if step >= 2 else `company_cooldown_days`.
- **Thread section:** `prior_messages` joins draft + version + send_attempt; one entry per delivered step. `active_conversation` = True if any `reply_history` row in last 14 days OR sibling has a reply in last 14 days at this company.
- **Governance section:** `allowed_claims` filtered by industry + claim_type + effective dates. `prohibited_claims` = `outreach_guidelines.yaml::never_include` + `outreach_guidelines.yaml::banned_phrases` + any claim_pattern from `evidence_registry` where `claim_type='ANTI_PATTERN'`. Risk component scores filled by reading `risk_dimension_inputs` and passing to `RiskScoringService.score_components()`.
- **Recommended action section:** A deterministic function of the above. Logic:
  - If suppression active → `SUPPRESS`
  - If hold active → `BLOCK`
  - If `active_conversation` and step >= 2 → `HOLD_FOR_HUMAN_REVIEW`
  - If sibling has positive reply in last 30 days → `HOLD_FOR_HUMAN_REVIEW`
  - If `overall_risk_bucket = 'BLOCKED'` → `BLOCK`
  - If `overall_risk_bucket = 'HIGH'` → `HOLD_FOR_HUMAN_REVIEW`
  - If step >= 2 and `prior_messages` doesn't include step (sequence_step - 1) → `HOLD_FOR_CONTEXT_REFRESH`
  - Else → `GENERATE`

**`version_hash` computation:**

```python
version_hash = sha256(json_canonical({
    "workspace_id": str(workspace_id),
    "company_id": str(company_id),
    "contact_id": str(contact_id),
    "sequence_id": str(sequence_id),
    "sequence_step": sequence_step,
    "company.updated_at": company.updated_at.isoformat(),
    "contact.updated_at": contact.updated_at.isoformat(),
    "research.updated_at": research.updated_at.isoformat() if research else None,
    "prior_messages.last_id": prior_msgs[-1].draft_id if prior_msgs else None,
    "prior_messages.count": len(prior_msgs),
    "replies.last_id": replies[0].reply_id if replies else None,
    "replies.count": len(replies),
    "suppression.active_ids": sorted([s.id for s in active_suppressions]),
    "holds.active_ids": sorted([h.id for h in active_holds]),
    "policy_snapshot_id": str(policy_snapshot_id),
    "evidence_versions": sorted([(c.id, c.effective_from.isoformat()) for c in evidence]),
})).hexdigest()
```

The hash is computed from values that, if any change, mean the packet's contents could change. Any consumer holding a packet can verify it is still current by re-running the hash against current data.

### C.3 Caching and Staleness

**Cache key:** `(workspace_id, company_id, contact_id, sequence_id, sequence_step)`

**TTL per field group:**

| Field group | TTL | Why |
|---|---|---|
| Company intelligence (name, summary, tier, industry, employee_count, pain_signals, hooks, technology_stack) | 24 hours | Research is expensive; changes slowly |
| Contact intelligence (name, title, seniority, persona, email_status, icp_fit_score) | 4 hours | Apollo refreshes are weekly+; intra-day stability is fine |
| Contact state (lifecycle_state, cooldown, hold) | 60 seconds | Can change on every send/reply |
| Suppression state | 0 (always fresh) | A bounce one minute ago must block the next send |
| Thread context (prior messages, replies) | 60 seconds | Replies arrive any moment |
| Governance (policy snapshot, allowed claims) | 60 seconds | Policy edits propagate quickly |
| Risk score components | 60 seconds | Recomputed per send anyway |
| Sender reputation | 5 minutes | 7-day rolling rate; intra-five-minute precision is unnecessary |

The cache stores the assembled packet but tags each field group with its build timestamp. On retrieval, fields older than their TTL are refreshed in place; if any of the "0 TTL" fields need a refresh, the entire packet is rebuilt.

**Staleness detection:** Every consumer of a stored `context_packet` (e.g., the SendWorker re-checking at claim time) recomputes `version_hash` against current data. If the hash differs, the packet is rebuilt; the old `context_packets` row is preserved (immutable) and a new row is written.

**When to force rebuild:**

- New reply received for the contact or any sibling (`provider_events INSERT WHERE event_type='reply_received'`)
- New suppression event for the contact or company
- Company hold or contact hold set or released
- Policy snapshot superseded
- Sender reputation degrades past a threshold (sender enters `HIGH` risk bucket)
- A previously claimed outbound queue row's send_attempt enters `ASSERT_FAILED` (state changed; rebuild before retry)
- Evidence registry row added/expired in the contact's sector
- `sequence_step_state` transition for this contact

These triggers are not pushed via NOTIFY — they are checked at the next `build()` call via the version hash. The cache TTL plus the hash check means the worst-case staleness is the longest TTL or one consumer call, whichever is shorter.

**Storage:** `context_packets` table (Section G) plus an optional Redis cache for the hot path. The Redis cache is optional because the packet is denormalized and self-contained: rebuilding it from Postgres takes a single round-trip with batched fetches. At current scale (~100 sends/day), Postgres alone is sufficient; Redis is added only if the build takes > 100ms per call under load.

### C.4 How Context Packet Prevents Disjointed Outreach

The current system fails at each of these because the data exists in five different tables and is reassembled differently by each caller, with side-effect writes that may silently fail. The Context Packet makes the full picture impossible to ignore.

**1. Sending a step-2 that repeats the same angle as step-1**

The packet's `prior_messages` list includes step-1's `primary_angle` (from `draft_versions.generation_metadata`) and `body_hash`. The DraftStrategy for step-2 explicitly receives `prior_step_reference_summary` containing step-1's angle. The system prompt for step-2 includes: *"Step 1 used angle '{primary_angle}'. Do NOT use this angle again. Pick a different facet of the prospect's pain."* Validator pass 4 compares step-2's body against `prior_step_body_hashes` for trigram similarity; > 0.7 similarity is `HARD_REJECT`.

**2. Sending to a contact whose colleague just replied**

The packet's `sibling_contact_history` includes every sibling with `last_reply_at`. `company_traction_state` resolves to `HOT` if any sibling replied in 30 days. The `recommended_next_action` logic returns `HOLD_FOR_HUMAN_REVIEW` when `HOT` traction is detected on siblings. The DecisionEngine cannot reach `GENERATE` without the human review. Operator sees "Sibling Sarah at Acme replied 2 days ago — review before sending to Mike."

**3. Sending a claim flagged as fabricated in a prior draft**

The Messaging Intelligence Layer records `claim_ids_referenced` on every `draft_versions` row. When a draft is rejected (`approval_status='rejected'`) with reason category `fabricated_claim`, the affected claim ids are marked as `quarantined` in `learning_signals` for 30 days. The next packet's `prohibited_claims` includes the quarantined claim's pattern. The validator's HARD_REJECT pass rejects any draft body matching the prohibited pattern.

**4. Sending a follow-up to a contact who replied "not interested"**

The packet's `reply_history` includes the classification. If `classification IN ('soft_no', 'negative')` and `classifier_confidence >= 0.85`, ReplyCoordinator auto-suppresses the contact with `suppression_type='NOT_INTERESTED'`. The packet sees `contact_suppression_state='NOT_INTERESTED'`. DecisionEngine returns `SUPPRESS`. If the classifier returned `confidence < 0.85`, ReplyCoordinator routes to HITL and the reply stays `unhandled`. The packet's `recommended_next_action` is `HOLD_FOR_HUMAN_REVIEW` until the reply is handled. The sequence cannot advance until the human responds.

**5. Generating a step-3 that ignores the step-2 thread**

`prior_messages` is ordered by sequence_step ASC and includes both step-1 and step-2. The DraftStrategy for step-3 receives both as `prior_step_reference_summary`. The system prompt: *"Step 1 covered '{step_1.primary_angle}'. Step 2 covered '{step_2.primary_angle}'. Step 3 must NOT repeat either. Acknowledge the thread continuity in tone."* If `sequence_step_state` shows step-2 is not in state `DRAFT_SENT`, DecisionEngine returns `HOLD_FOR_CONTEXT_REFRESH` and the step-3 generation does not happen.

### C.5 Context Packet Audit Trail

**Storage:** Every assembled packet is persisted to `context_packets` (full DDL in Section G):

```sql
CREATE TABLE context_packets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  company_id UUID NOT NULL,
  contact_id UUID NOT NULL,
  sequence_id UUID,
  sequence_step INTEGER,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  version_hash TEXT NOT NULL,
  packet JSONB NOT NULL,                  -- full serialized ContextPacket
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  build_ms INTEGER NOT NULL,              -- how long the build took
  recommended_next_action TEXT NOT NULL,
  overall_risk_score NUMERIC(5,2),
  overall_risk_bucket TEXT,
  used_by_draft_id UUID REFERENCES outreach_drafts(id),
  used_by_approval_id UUID REFERENCES approval_attestations(id),
  used_by_send_attempt_id UUID REFERENCES send_attempts(id)
);
CREATE INDEX idx_cp_contact ON context_packets(contact_id, generated_at DESC);
CREATE INDEX idx_cp_company ON context_packets(company_id, generated_at DESC);
CREATE INDEX idx_cp_hash ON context_packets(version_hash);
```

**Linkage to drafts/approvals/sends:**

- `outreach_drafts.generation_context_packet_id` — the packet used at generation
- `approval_attestations.context_packet_id` — the packet seen by the reviewer (re-built fresh at approval time and pinned)
- `send_attempts.context_packet_id` — the packet seen by the SendWorker at claim time (re-built fresh at claim time and pinned)

These three columns produce a complete audit chain: for any sent email, an operator can retrieve the exact world-view the system had at generation, at approval, and at send. Drift between the three is itself a signal — if the approval packet differs from the generation packet (a reply arrived in between), the policy decision should reflect that.

**Operator inspection:**

The cockpit "Audit Trail" view shows a sent email's chain:

```
Email to mike@acme.com sent 2026-05-14 09:32:17 CDT
  → send_attempts row: a7c2...
    → context_packet at send: v=4 (rebuilt because sibling reply arrived)
       - sibling_contact_history shows Sarah replied 2 days ago — operator manually advanced
       - overall_risk_bucket: MEDIUM
       - recommended_next_action: PROCEED (override audited by avanish 09:30:01)
  → approval_attestation row: ...
    → context_packet at approval: v=2 (built when reviewer opened)
       - overall_risk_bucket: LOW
       - recommended_next_action: GENERATE
  → outreach_draft row: ...
    → context_packet at generation: v=1
       - overall_risk_bucket: LOW
       - recommended_next_action: GENERATE
```

This makes "why was this email sent" answerable in one query, not five table joins.

---

## SECTION D — Messaging Intelligence Layer Design

### D.1 DraftStrategy

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class DraftStrategy:
    sequence_step: int
    step_intent: str                    # from sequences.yaml step.instructions.description
    primary_angle: str                  # chosen hook for THIS step
    secondary_angle: Optional[str]      # backup if primary doesn't work
    tone: str                           # from sequences.yaml step.instructions.tone
    cta_type: str                       # QUESTION | DEMO_REQUEST | INSIGHT_OFFER | SOFT_FOLLOW
    reference_prior_step: bool          # True for step >= 2
    prior_step_reference_summary: Optional[str]   # one-line description of the prior step's angle
    allowed_claims: list[EvidenceClaim]
    prohibited_claims: list[str]        # regex patterns
    personalization_hooks: list[str]
    evidence_required: bool             # True for any step that uses a benchmark or outcome
    continuity_checks: list[str]        # things to verify the draft does NOT repeat
    hallucination_check_patterns: list[str]  # regex for fabricated stats
    reviewer_summary: str               # human-readable "why this message" for the approval queue
    why_this_message: str               # operator-facing explanation
    max_words: int                      # from sequences.yaml
    model_name: str                     # claude-sonnet-X — from policy_snapshot
    temperature: float
```

### D.2 Prompt Construction

`MessagingIntelligenceService.generate(packet: ContextPacket, strategy: DraftStrategy) -> RawDraft`

**System prompt components (in order):**

1. **Identity block** (from `outreach_guidelines.yaml::sender + voice_and_tone`):
   - Sender name, title, company
   - Voice: "Write as the sender — direct, confident, conversational. Short sentences. No corporate jargon. Real person, not AI."
2. **Anti-AI rules** (from `outreach_guidelines.yaml::voice_and_tone::anti_ai_detection`):
   - "Never use em dashes. Never use en dashes. Never start with 'I'm excited to'. Never use 'moreover', 'furthermore'."
3. **Step-specific intent** (from `strategy.step_intent` + `strategy.tone`)
4. **Format requirements** (from `outreach_guidelines.yaml::email_structure`):
   - Subject line rules, opening line rules, CTA rules, signature
5. **Forbidden content** (from `strategy.prohibited_claims` + `outreach_guidelines.yaml::never_include` + `banned_phrases`)

**Context injection (in order):**

1. **Company snapshot**: `packet.company_name`, `packet.company_summary`, `packet.industry`, `packet.employee_count`, top 3 `pain_signals`, top 3 `personalization_hooks`.
2. **Contact snapshot**: `packet.contact_name`, `packet.contact_title`, `packet.contact_seniority`, `packet.contact_persona`.
3. **Sequence and step context**: which step (1–N), step objective, what step-1/2/... covered (one-line summaries).
4. **Prior message awareness** (step >= 2):
   - "Prior messages in this thread:"
   - For each prior step: `"Step {n}: angle={primary_angle}, subject='{subject}', opened={open_count > 0}, clicked={click_count > 0}"`
   - Followed by: *"DO NOT repeat any angle above. DO NOT reference the same hook. Pick a different facet of the prospect's pain."*

**Claim constraints injection:**

```
EVIDENCE LIBRARY (use ONLY these claims):
  [claim_001] PRODUCT_FACT: "Digitillis provides AI-driven OEE and predictive
              maintenance intelligence for manufacturing operations."
              Source: internal product spec
  [claim_017] BENCHMARK_CITATION: "Industry average OEE in F&B is 60%."
              Source: SMRP 2024 Manufacturing Benchmark Study (URL: ...)
  [claim_042] OUTCOME_STATEMENT: "Customer X reduced unplanned downtime by 31%
              in 6 months." Source: case study published 2026-02-15.

PROHIBITED CLAIMS (regex patterns; DO NOT use phrases matching any):
  - "\\d+x"                  (no 10x, 100x claims unless covered)
  - "(\\d{2,3})\\s*%"        (no bare percentages unless covered)
  - "(40|50|60)\\s*[-to]+\\s*(60|65)\\s*%"  (specific banned range)
  - "we typically"
  - "one plant found"
  - "many customers have"

If you need to make a claim, you MUST cite its [claim_id] in your output's
metadata.claim_ids_referenced array. If no relevant claim exists in the
EVIDENCE LIBRARY, write the message WITHOUT making the claim.
```

**Step-specific instructions** (composed into the system prompt):

| Step | Objective | Tone | CTA type | Reference prior | Evidence requirement |
|---|---|---|---|---|---|
| 1 | Open a conversation with a discovery question | Curious peer, like a colleague at a conference | QUESTION (open-ended, demonstrates domain knowledge) | None (no prior steps) | Optional; if used, must be from registry |
| 2 | Deepen the specific pain hinted at in step 1 OR offer a small insight | Thoughtful follow-up, not pushy | INSIGHT_OFFER or QUESTION | Yes; one line acknowledging step 1 happened ("circling back on my question about ...") | Optional |
| 3 | Provide one concrete piece of social proof OR a regulatory/industry signal | Advisor sharing relevant context | INSIGHT_OFFER or DEMO_REQUEST | Yes; brief reference; must NOT repeat step 1 or 2 angles | REQUIRED — every claim from registry |
| 4 | Break pattern — different format (1-line check-in, or a relevant resource link) | Light, low-pressure | SOFT_FOLLOW | Yes | Optional |
| 5 | Final outreach — explicit ask with a closing line | Direct, respectful of their time | DEMO_REQUEST | Yes; signal that this is the last touch in the cadence | Optional |

**Output format requirements:**

The model is instructed to return strict JSON:

```json
{
  "subject": "...",
  "body": "...",
  "primary_angle_used": "...",
  "claim_ids_referenced": ["claim_017", "claim_042"],
  "self_check": {
    "uses_em_dash": false,
    "has_bare_percentage_outside_claims": false,
    "repeats_prior_step_angle": false,
    "first_person_plural_outcome_claim": false,
    "ends_with_cta": true,
    "word_count": 87
  },
  "reviewer_summary": "Asking about CCP documentation burden after FSMA 204; references claim_017 (SMRP benchmark)."
}
```

The system prompt explicitly tells the model: *"Before returning, populate `self_check`. If `self_check` reveals any rule violation, REGENERATE before returning. Returning a draft that violates `self_check` will be auto-rejected."*

### D.3 Step-by-step Behavior

**Step 1 (cold open):**
- Objective: open conversation; demonstrate domain knowledge; ask one question
- Tone: peer, curious, no pitch
- CTA: open-ended question that only someone in their world would ask
- Reference to prior messages: none (no prior steps exist)
- Evidence requirement: optional; most step 1s avoid claims and lead with a question instead

**Step 2 (deepen the angle):**
- Objective: take the implied pain from step 1 deeper, OR offer one specific insight
- Tone: thoughtful follow-up
- CTA: another question OR an offer of an insight document
- Reference to prior: one line acknowledging step 1 ("circling back on my question about CCP documentation...")
- Evidence requirement: optional
- Critical constraint: must NOT restate step 1's angle in different words. Validator pass 4 checks body trigram similarity to step 1's body; > 0.7 is `HARD_REJECT`.

**Step 3 (social proof or regulatory signal):**
- Objective: introduce one piece of evidence — a benchmark, a recent regulatory update, or a customer outcome
- Tone: advisor sharing relevant context
- CTA: meeting request OR a question that surfaces willingness
- Reference to prior: brief; must NOT repeat angles
- Evidence requirement: **REQUIRED** — every quantitative or comparative claim must cite a `claim_id`. Bare "10x ROI", "40-65% improvement", "one plant found" are HARD_REJECT.

**Step 4+ (pattern break or last touch):**
- Step 4: pattern break — different shape (1-line check-in, link to a resource)
- Step 5: direct ask, respectful of their time, signal that this is the last
- Evidence requirement: optional but if used must be registered

### D.4 Multi-contact Coherence

When two contacts at the same company are in active sequences, the packet's `sibling_contact_history` carries the full picture for each sibling. The Messaging Intelligence Layer uses it in three concrete ways:

1. **Angle deduplication.** The DraftStrategy for contact B at company X reads the `primary_angle` used in each prior step to every sibling. The system prompt receives: *"Sibling Sarah received: step 1 using angle 'CCP audit prep'; step 2 using angle 'traceability gaps'. Pick an angle that does NOT overlap."* If no non-overlapping angle exists from `packet.personalization_hooks`, the DraftStrategy emits `recommended_action='ESCALATE'` and the draft is not generated.

2. **Tone consistency.** If a sibling has replied positively, the company state is HOT. New contact outreach to a different sibling at the same company uses a "warmer, account-team" tone: *"My colleague has been talking with Sarah about CCP documentation. Wanted to reach out to you separately since you own [their function]..."* The Generator is instructed to acknowledge the connection rather than pretend it doesn't exist.

3. **Sibling-aware deduplication is partly automated and partly surfaced for human review.**
   - **Automated:** the system prompt always sees sibling history; the LLM is instructed to pick a non-overlapping angle. The validator's pass 4 checks `body_hash` overlap with sibling drafts in the last 30 days at the same company — > 0.5 trigram similarity is `WARN_AND_QUARANTINE`.
   - **Surfaced for human review:** the approval queue UI shows the sibling history alongside the draft. If `traction_state >= WARM`, the draft is `HIGH` risk by default and routes to the dual-review queue. The reviewer can see "Sarah replied 2 days ago" and decide whether the new contact's outreach is appropriate. Without a packet, the reviewer would not see this.

---

## SECTION E — Orchestration Layer Design

### E.1 OrchestrationService

```python
# backend/app/orchestration/orchestration_service.py

from datetime import datetime
from typing import Optional
from backend.app.intelligence.context_builder import ContextPacket

class OrchestrationDecision:
    """Result of decide_next_action — what to do plus why."""
    action: str   # GENERATE | HOLD_FOR_CONTEXT_REFRESH | HOLD_FOR_HUMAN_REVIEW | SUPPRESS | BLOCK | ESCALATE | DISPATCH | DROP
    reason: str
    policy_decision: 'PolicyDecision'
    risk_score: 'RiskScore'
    context_packet_id: str
    correlation_id: str

class ReplyDisposition:
    """Result of processing an inbound reply."""
    action: str   # AUTO_ARCHIVE | AUTO_SUPPRESS | QUEUE_HITL | PAUSE_SEQUENCE | ESCALATE
    classification: str
    confidence: float
    actions_taken: list[str]

class OrchestrationService:
    """
    Central lifecycle authority. All state transitions flow through here.
    No other service may transition lifecycle states directly.

    Holds the prospectiq_writer_orchestrator role, which has UPDATE
    privilege on lifecycle_state columns for outreach_drafts, contacts,
    companies, engagement_sequences, and inbound_replies.
    """

    def __init__(self, db, policy_engine, risk_service, context_builder,
                 send_worker, draft_service, approval_service,
                 suppression_coordinator, sequence_coordinator, reply_coordinator):
        ...

    def decide_next_action(self, context_packet: ContextPacket) -> OrchestrationDecision:
        """
        Inputs: ContextPacket
        Reads: policy_snapshots, risk_scores (latest), outreach_drafts.lifecycle_state
        Writes: autonomy_decisions (always), workflow_events (on transition)
        Emits: 'orchestration_decided' workflow_event
        Returns: OrchestrationDecision
        """

    def process_reply_event(self, reply_event: 'NormalizedReplyEvent') -> ReplyDisposition:
        """
        Inputs: NormalizedReplyEvent from ReplyCoordinator
        Reads: contacts, companies, campaign_threads, provider_events
        Writes: contacts.lifecycle_state (if auto-suppression), suppression_events,
                engagement_sequences.lifecycle_state (if pausing), hitl_queue,
                workflow_events, autonomy_decisions
        Emits: 'reply_classified', 'reply_auto_actioned' or 'reply_hitl_queued'
        Returns: ReplyDisposition
        """

    def process_delivery_event(self, delivery_event: 'NormalizedDeliveryEvent') -> None:
        """
        Inputs: NormalizedDeliveryEvent (delivered | bounced | complained | opened | clicked)
        Reads: send_attempts (by provider_message_id)
        Writes: send_attempts.state, outreach_drafts.lifecycle_state (SENDING -> SENT/FAILED),
                contacts.lifecycle_state (advance to SEQUENCED/WARMING/HOT),
                companies.lifecycle_state (advance to OUTREACH_ACTIVE/ACTIVE_CONVERSATION),
                workflow_events
        Emits: 'send_delivered' or 'send_failed' or 'send_bounced' or 'send_complained'
        Returns: None
        """

    def apply_suppression(self, contact_id: str, suppression_type: str,
                          source: str, reason: str) -> None:
        """
        Inputs: contact_id, suppression_type (BOUNCE|UNSUBSCRIBE|COMPLAINT|NOT_INTERESTED|DEPARTED|DNC),
                source (WEBHOOK|OPERATOR|CLASSIFIER|SYSTEM), reason text
        Reads: suppression_events (escalation check), contacts, companies
        Writes: suppression_events (INSERT), contacts.lifecycle_state, optionally
                companies.lifecycle_state (escalation), pending outbound_queue rows
                marked SUPPRESSED, in-flight send_attempts checked at next claim
        Emits: 'contact_suppressed' (plus 'company_suppressed' on escalation)
        Returns: None
        """

    def resume_sequence(self, sequence_id: str, operator_id: str,
                        reason: str) -> None:
        """
        Inputs: sequence_id, operator_id (must be authenticated), reason
        Reads: engagement_sequences, contacts (suppression check)
        Writes: engagement_sequences.lifecycle_state='ACTIVE',
                sequence_step_state next step PENDING -> DRAFT_GENERATED-eligible,
                workflow_events
        Emits: 'sequence_resumed'
        Returns: None
        """

    def pause_sequence(self, sequence_id: str, reason: str, auto: bool) -> None:
        """
        Inputs: sequence_id, reason, auto flag (True if system-triggered, False operator)
        Reads: engagement_sequences, sequence_step_state
        Writes: engagement_sequences.lifecycle_state='PAUSED' (or 'PAUSED_HUMAN_REPLY'),
                sequence_step_state future steps -> STEP_BLOCKED,
                outbound_queue rows for this sequence -> CANCELLED, workflow_events
        Emits: 'sequence_paused'
        Returns: None
        """

    def hold_company(self, company_id: str, reason: str, set_by: str,
                     expires_at: Optional[datetime]) -> None:
        """
        Inputs: company_id, reason, set_by user_id, expires_at (None = permanent)
        Reads: companies, current outbound_queue rows for this company
        Writes: company_holds (INSERT), outbound_queue rows -> CANCELLED for this
                company's contacts, workflow_events
        Emits: 'company_hold_set'
        Returns: None
        """

    def hold_contact(self, contact_id: str, reason: str, set_by: str,
                     expires_at: Optional[datetime]) -> None:
        """
        Similar to hold_company but contact-scoped.
        """

    def escalate_to_hitl(self, draft_id: str, reason: str) -> None:
        """
        Inputs: draft_id, reason
        Reads: outreach_drafts, context_packets
        Writes: outreach_drafts.lifecycle_state='UNDER_REVIEW' with priority,
                hitl_queue (INSERT), workflow_events
        Emits: 'draft_escalated_to_hitl'
        Returns: None
        """
```

### E.2 DecisionEngine

`DecisionEngine.decide_next_draft_action(context_packet) → DraftAction`

```
DraftAction = GENERATE | HOLD_FOR_CONTEXT_REFRESH | HOLD_FOR_HUMAN_REVIEW | SUPPRESS | BLOCK | ESCALATE
```

Decision tree (evaluated top-to-bottom; first match wins):

```
START
  |
  v
Is contact_suppression_state set and != None?
  YES -> SUPPRESS
  NO  -> v

Is contact_hold_active OR company_hold_active?
  YES -> BLOCK (with hold reason)
  NO  -> v

Is workspace_send_enabled = False?
  YES -> BLOCK (workspace kill switch)
  NO  -> v

Is overall_risk_bucket = 'BLOCKED'?
  YES -> BLOCK
  NO  -> v

Is active_conversation = True for this contact (any reply in last 14 days)?
  YES -> HOLD_FOR_HUMAN_REVIEW (reason: "active conversation in progress")
  NO  -> v

Does any sibling have last_reply_sentiment in ('positive', 'question') in last 30 days?
  YES -> HOLD_FOR_HUMAN_REVIEW (reason: "sibling at company in active conversation")
  NO  -> v

Is overall_risk_bucket = 'HIGH'?
  YES -> HOLD_FOR_HUMAN_REVIEW (reason: "high risk dimensions: <list>")
  NO  -> v

Is content_risk_score requiring claim grounding AND sequence_step >= 3?
  YES AND step has no allowed_claims for this sector -> ESCALATE (reason: "step 3+ requires evidence but registry has none for sector")
  NO  -> v

Is sequence_step >= 2 AND prior step's sequence_step_state.state != 'DRAFT_SENT'?
  YES -> HOLD_FOR_CONTEXT_REFRESH (reason: "prior step not sent")
  NO  -> v

Is contact_cooldown_active = True (within step-gap window or company-cooldown window)?
  YES -> HOLD_FOR_CONTEXT_REFRESH (reason: "cooldown window not elapsed; expires at X")
  NO  -> v

Is workspace_send_cap_remaining = 0?
  YES -> HOLD_FOR_CONTEXT_REFRESH (reason: "daily send cap reached")
  NO  -> v

Is overall_risk_bucket = 'MEDIUM'?
  YES -> GENERATE with review_required=True (routes to human queue after generation)
  NO  -> v

Is overall_risk_bucket = 'LOW' AND content_validator forecast PASS?
  YES -> GENERATE with autonomous_approval_eligible=True
  NO  -> GENERATE with review_required=True (default)
```

### E.3 RiskScoringService

```python
class RiskScoringService:
    def score(self, context_packet: ContextPacket) -> RiskScore:
        """
        Returns a RiskScore with overall_score (0-100), bucket (LOW/MEDIUM/HIGH/BLOCKED),
        per-dimension scores, and the dimensions that contributed > 5 points
        (the "triggered_dimensions" used for explainability).
        """
```

**16-dimension scoring formula:**

For each dimension, `value ∈ {0.0, 0.5, 1.0}` for LOW / MEDIUM / HIGH:

| # | Dimension | Field on packet | Scoring function | Weight |
|---|---|---|---|---|
| 1 | sequence_step | `sequence_step` | step 1 → 0.0; step 2 → 0.5; step 3+ → 1.0 | 8 |
| 2 | account_tier | `company_tier` | pmfg3 → 0.0; pmfg2 → 0.5; pmfg1 → 1.0 | 12 |
| 3 | prospect_seniority | `contact_seniority` | director → 0.0; manager/vp → 0.5; csuite/owner/founder → 1.0 | 8 |
| 4 | company_size | `employee_count` | < 200 → 0.0; 200–1000 → 0.5; > 1000 → 1.0 | 5 |
| 5 | prior_engagement | `prior_open_count`, `prior_click_count`, `reply_history` | 0 opens/clicks → 0.0; 1–2 opens, 0 clicks → 0.5; clicks >= 1 OR any reply → 1.0 | 8 |
| 6 | traction_signal | `company_traction_state` | NONE → 0.0; COLD → 0.0; WARM → 0.5; HOT → 1.0 | 12 |
| 7 | suppression_ambiguity | `contact_suppression_state` history | clean → 0.0; one stale OOO/auto-reply → 0.5; conflicting signals (recent bounce + recent open) → 1.0 | 8 |
| 8 | unverifiable_claims_detected | validator pass 3 forecast | 0 quarantines → 0.0; 1 WARN → 0.5; any HARD-REJECT → 1.0 | 10 |
| 9 | fabricated_statistic_risk | regex match against bare `\d+%` not covered | none → 0.0; one borderline → 0.5; uncovered match → 1.0 | 8 |
| 10 | sender_reputation_risk | `sender_reputation_score` (7d bounce rate inverse) | < 0.5% → 0.0; 0.5–1.5% → 0.5; >= 1.5% → 1.0 | 8 |
| 11 | domain_bounce_risk | prior bounces on contact email domain | 0 → 0.0; 1 (> 30d ago) → 0.5; >= 2 OR recent → 1.0 | 5 |
| 12 | policy_override_in_use | `approval_attestations.is_override` for related approvals | none → 0.0; sibling override in 7d → 0.5; this draft was overridden → 1.0 | 3 |
| 13 | new_sequence_type | sequence_name × tier combo historical send count | > 100 → 0.0; 10–100 → 0.5; < 10 → 1.0 | 5 |
| 14 | new_content_template | template_id use count | > 50 → 0.0; 10–50 → 0.5; < 10 → 1.0 | 3 |
| 15 | manual_edit_after_approval | `edited_body_version_id` differs from approved | no edit → 0.0; < 5% length change → 0.5; >= 5% or claim phrasing changed → 1.0 | 3 |
| 16 | provider_inconsistency | send_attempts vs interactions drift for this contact | match → 0.0; minor → 0.5; major → 1.0 | 2 |

Weights sum to 108 (over 100 because HIGH thresholds compound). Final `overall_score = min(100, sum(value × weight))`.

**Buckets:**
- `LOW`: 0–20
- `MEDIUM`: 21–50
- `HIGH`: 51–80
- `BLOCKED`: 81–100

### E.4 PolicyEvaluationService

```python
class PolicyEvaluationService:
    def evaluate(self, action: str, context_packet: ContextPacket) -> PolicyDecision:
        """
        action: 'generate' | 'approve' | 'enqueue' | 'dispatch'
        Returns PolicyDecision with the 7-layer gate stack result.
        """
```

**7-layer gate stack (executed strictly in order; first BLOCK short-circuits):**

| Layer | Gate name | Source | Behavior |
|---|---|---|---|
| 1 | `schema_constraints` | DB CHECK / FK / UNIQUE / triggers | Cannot be bypassed at all; failure raises before this method is called |
| 2 | `suppression_gate` | `suppression_events`, `contact_holds`, `company_holds` | Active suppression → BLOCK |
| 3 | `policy_gate` | `policy_snapshots`, `outreach_send_config` | Workspace kill, send window, daily cap, step gap, company cooldown |
| 4 | `content_integrity_gate` | validator output on `draft_versions`, `evidence_registry` | HARD_REJECT patterns, claim grounding |
| 5 | `approval_provenance_gate` | `approval_attestations`, `draft_versions.content_hash` | For dispatch action: attestation exists, body hash matches |
| 6 | `provider_readiness_gate` | sender reputation, Resend health, idempotency key uniqueness | Sender in HIGH bucket, provider unhealthy |
| 7 | `send_path_assertions` | all `pre_send_assertions.py::assert_*` functions | All run as a chain |

**Aggregation:** All layers must PASS for `PROCEED`. Any layer's BLOCK returns immediately with `blocking_gate = layer_name`. A layer returning HOLD (e.g., daily cap reached, retry later) returns `HOLD` with `next_eligible_at` populated.

```python
@dataclass(frozen=True)
class GateResult:
    layer: str
    gate: str
    result: str           # PASS | HOLD | BLOCK
    detail: str
    next_eligible_at: Optional[datetime]

@dataclass(frozen=True)
class PolicyDecision:
    decision: str         # PROCEED | HOLD | BLOCK | ESCALATE
    blocking_gate: Optional[str]
    reason: str
    layer_results: list[GateResult]
    policy_snapshot_id: str
    evaluated_at: datetime
    correlation_id: str
```

### E.5 QueueManager

```python
class QueueManager:
    def enqueue(self, draft_id: str, priority: int,
                policy_snapshot_id: str) -> 'OutboundQueueRow':
        """
        Called only by ApprovalService.approve(), inside the same transaction
        as the approval_attestations INSERT.
        Writes: outbound_queue (INSERT)
        Emits: 'draft_enqueued' workflow_event
        """

    def claim_next(self, worker_id: str,
                   workspace_id: str) -> Optional['OutboundQueueRow']:
        """
        SELECT FOR UPDATE SKIP LOCKED. Marks the row CLAIMED with a 10-min lease.
        Writes: outbound_queue.state='CLAIMED', claimed_by_worker, claim_expires_at
        Emits: 'outbox_claimed' workflow_event
        """

    def mark_sent(self, queue_id: str, send_attempt_id: str) -> None:
        """
        Writes: outbound_queue.state='SENT', completed_at
        Emits: 'outbox_completed'
        """

    def mark_failed(self, queue_id: str, error: str, retryable: bool) -> None:
        """
        If retryable: state=QUEUED, attempt_count++, next_attempt_at = now + 5min*2^attempt
        If not retryable OR attempts >= max_attempts: state=DEAD_LETTER + move_to_dead_letter
        Emits: 'outbox_failed_retry' or 'outbox_failed_terminal'
        """

    def move_to_dead_letter(self, queue_id: str,
                            failure_category: str) -> None:
        """
        Inserts dead_letter_queue row, sets outbound_queue.state='DEAD_LETTER'.
        Triggers Slack alert if dead-letter depth > policy_snapshot.dead_letter_alert_threshold
        Emits: 'outbox_dead_lettered'
        """
```

### E.6 SequenceCoordinator

```python
class SequenceCoordinator:
    def advance_sequence(self, contact_id: str, sequence_id: str,
                         completed_step: int) -> 'SequenceAdvanceResult':
        """
        Called by Orchestrator after a send_attempt enters DELIVERED.
        Updates sequence_step_state: completed_step -> DRAFT_SENT,
        next_step -> PENDING with due_at = now + delay_days from sequences.yaml.
        Reads: engagement_sequences, sequence_step_state, sequences.yaml
        Writes: sequence_step_state, engagement_sequences.current_step
        Emits: 'sequence_step_advanced'
        """

    def pause_sequence(self, contact_id: str, reason: str, auto: bool) -> None:
        """
        Called by Orchestrator on reply received or suppression.
        Writes: engagement_sequences.lifecycle_state='PAUSED' (or 'PAUSED_HUMAN_REPLY'),
                future sequence_step_state -> STEP_BLOCKED
        Cancels pending outbound_queue rows for this contact's future steps.
        Emits: 'sequence_paused'
        """

    def should_generate_next_step(self, sequence_id: str) -> bool:
        """
        Reads: engagement_sequences, sequence_step_state, contacts
        Returns: True if sequence is ACTIVE, contact is not suppressed/held,
                 next step's due_at <= now, and no draft already exists.
        """

    def check_sibling_pause(self, company_id: str,
                            exclude_contact_id: str) -> 'SiblingPauseDecision':
        """
        Returns: SiblingPauseDecision indicating whether sibling activity should
        pause the contact's sequence (used by Orchestrator when company traction
        goes HOT mid-sequence).
        """
```

### E.7 SuppressionCoordinator

The single service that applies all suppression signals. Holds the `prospectiq_writer_suppression_svc` role.

**Signals handled:**

| Signal | Source | What it writes |
|---|---|---|
| `BOUNCE` (hard) | Resend webhook `email.bounced` (type=hard) | `suppression_events` row with `suppression_type='BOUNCE', suppression_scope='CONTACT'`; `contacts.lifecycle_state='SUPPRESSED_BOUNCED'`; escalation check (if 2+ siblings bounced → `suppression_scope='COMPANY'` row) |
| `BOUNCE` (soft) | Resend webhook | `suppression_events` row with `suppression_type='BOUNCE_SOFT'`; first soft → cooldown 24h; second soft within 24h → escalates to hard |
| `COMPLAINT` | Resend `email.complained` | `suppression_events` row `suppression_type='COMPLAINT'`; `contacts.lifecycle_state='SUPPRESSED_COMPLAINED'`; immediate company-scope escalation per policy |
| `UNSUBSCRIBE` | Resend `email.unsubscribed` OR reply classifier (high-confidence unsubscribe) | `suppression_events` row + `do_not_contact` table insert; contact + future sibling protection |
| `NOT_INTERESTED` | Reply classifier (high-confidence soft_no) | `suppression_events` row; contact-scope only |
| `DEPARTED` | Reply classifier (auto-reply "no longer here" pattern) or Apollo signal | `suppression_events` row; contact-only — new contact creation may follow |
| `COOLDOWN` | Reply classifier negative sentiment | Time-bound `suppression_events` row with `expires_at = now + 90d` |
| `DNC` | Operator action | `suppression_events` row + `do_not_contact` table |

**How each signal is processed:**

```python
class SuppressionCoordinator:
    def apply(self, suppression_type: str, scope: str, source: str,
              contact_id: Optional[str], company_id: Optional[str],
              email: Optional[str], domain: Optional[str],
              reason: str, provider_event_id: Optional[str]) -> str:
        """
        Single entry point for all suppression. Returns suppression_event_id.

        Transaction (single DB tx):
        1. INSERT suppression_events row
        2. UPDATE contacts.lifecycle_state for matching contact(s)
        3. Run escalation check (escalate to company scope if threshold met)
        4. Cancel pending outbound_queue rows for affected contact(s)
        5. INSERT workflow_events row
        """
```

**Interaction with `suppression_events`:** SuppressionCoordinator is the only Python module with INSERT privilege on the table. Operators do not write directly — they call `apply()`.

**Interaction with pending queue items:** When a suppression is applied, the coordinator runs:

```sql
UPDATE outbound_queue
SET state = 'CANCELLED', last_error = 'suppressed_post_enqueue', completed_at = NOW()
WHERE workspace_id = $1
  AND draft_id IN (
    SELECT id FROM outreach_drafts
    WHERE contact_id = $2 AND lifecycle_state IN ('APPROVED','EDITED','ENQUEUED')
  );
```

This means a suppression event that arrives after approval but before send safely cancels the queued send.

### E.8 ReplyCoordinator

The reply processing flow, in order:

1. **Webhook arrival:** Inbound webhook (Resend, Gmail, Instantly) hits the webhook route. Route inserts `provider_events` row keyed on `(provider, external_event_id)` UNIQUE; returns 200 immediately. Actual processing is deferred to the worker.

2. **Worker pickup:** The worker's `provider_events_processor` job (every 30s) selects rows with `processing_state='received' AND event_type IN ('reply_received', 'inbound_email')` and calls `ReplyCoordinator.process_event(event)`.

3. **Resolution:** ReplyCoordinator resolves the message to a contact (via `provider_message_id` lookup against `thread_messages`, falling back to `to/from` address match against `contacts`). Sets `provider_events.contact_id`, `company_id`, `draft_id`, `send_attempt_id`.

4. **Classification:** Calls `ReplyClassifier.classify(reply_text, thread_context)` → returns `ReplyClassification(intent, confidence, reason)`.

5. **Auto-action paths** (when `confidence >= 0.85`):

| Classification | Action |
|---|---|
| `bounce` | `SuppressionCoordinator.apply('BOUNCE', ...)` |
| `unsubscribe` | `SuppressionCoordinator.apply('UNSUBSCRIBE', ...)` |
| `auto_reply_ooo` | Pause sequence for `min(parsed_return_date, now + 7d)`; no suppression |
| `auto_reply_departed` | `SuppressionCoordinator.apply('DEPARTED', ...)` |
| `soft_no` | If `confidence >= 0.95` → `SuppressionCoordinator.apply('NOT_INTERESTED', ...)`; else HITL |

6. **HITL paths** (when not auto-actioned):

| Classification | Routing | SLA |
|---|---|---|
| `positive` | HITL with HIGH urgency; Slack alert to owner | 1 hour |
| `question` | HITL with MEDIUM urgency | 4 hours |
| `objection` | HITL with MEDIUM urgency | 4 hours |
| `referral` | HITL with HIGH urgency (new contact opportunity) | 4 hours |
| `negative` (low confidence) | HITL with LOW urgency | 24 hours |
| `other` (low confidence) | HITL with LOW urgency | 24 hours |

7. **Sequence pausing — auto:** A reply pauses the contact's active sequence in these cases:
   - Any `positive`, `question`, `objection`, `referral` (until HITL handles)
   - Any `negative` of any confidence (immediate)
   - Any `unsubscribe`, `complaint`, `bounce` (immediate, plus suppression)

   The sequence does NOT auto-pause for `auto_reply_ooo` low confidence — the sequence pauses only until the OOO end date.

8. **Event emission:** Every path emits:
   - `reply_received` (on provider_events row creation)
   - `reply_classified` (after classification)
   - `reply_auto_actioned` OR `reply_hitl_queued`
   - `reply_handled` (after HITL human action) — closes the loop

---

## SECTION F — Lifecycle and State Machine Redesign

Eight explicit state machines. Each is owned by one service; each transition writes a `workflow_events` row in the same transaction as the state column update; each state column has one Postgres role authorized to write it.

### F.1 Draft Lifecycle

```
GENERATING --gen_ok--> DRAFT_READY --reviewer_open--> UNDER_REVIEW
GENERATING --gen_quarantine--> DRAFT_READY (with quarantine flag)
GENERATING --gen_hard_reject--> ARCHIVED*

UNDER_REVIEW --approve--> APPROVED --enqueue_same_tx--> ENQUEUED
UNDER_REVIEW --approve_tier1_first--> DUAL_REVIEW_PENDING
DUAL_REVIEW_PENDING --second_approve--> APPROVED --enqueue_same_tx--> ENQUEUED
UNDER_REVIEW --approve_with_edit--> APPROVED (with edited_body_version) --enqueue_same_tx--> ENQUEUED
UNDER_REVIEW --reject--> ARCHIVED*
UNDER_REVIEW --request_override--> APPROVED_PENDING_AUDIT
APPROVED_PENDING_AUDIT --audit_approve--> APPROVED --enqueue_same_tx--> ENQUEUED
APPROVED_PENDING_AUDIT --audit_reject--> ARCHIVED*

ENQUEUED --worker_claim--> CLAIMED --asserting--> DISPATCHED
CLAIMED --assert_fail--> SUPPRESSED* (assertions failed at last mile)
DISPATCHED --delivery_webhook--> DELIVERED*
DISPATCHED --bounce_webhook--> BOUNCED*
DISPATCHED --complaint_webhook--> FAILED*
DISPATCHED --no_webhook_4h--> DEAD_LETTERED* (reconciliation)

(Any of {DRAFT_READY, UNDER_REVIEW, APPROVED, ENQUEUED, CLAIMED} can move to
 SUPPRESSED* on contact_suppressed signal; the suppression coordinator cancels
 pending outbound_queue rows.)
```

| State | Description | Service that owns the transition |
|---|---|---|
| `GENERATING` | DraftGenerator is composing | DraftGenerator |
| `DRAFT_READY` | Persisted, passed validator, awaiting review | DraftService |
| `UNDER_REVIEW` | Reviewer has opened (soft advisory lock) | ApprovalService |
| `APPROVED` | Attestation written, enqueued in same tx | ApprovalService |
| `DUAL_REVIEW_PENDING` | Tier-1 first reviewer approved | ApprovalService |
| `APPROVED_PENDING_AUDIT` | Override path; awaiting second-user audit | ApprovalService |
| `ENQUEUED` | `outbound_queue` row exists in PENDING | ApprovalService (writes); QueueManager (manages) |
| `CLAIMED` | SendWorker has the lease | SendWorker |
| `DISPATCHED` | Provider returned message_id | SendWorker |
| `DELIVERED` * | Delivery webhook received | OrchestrationService.process_delivery_event |
| `BOUNCED` * | Bounce webhook | OrchestrationService |
| `FAILED` * | Complaint or terminal failure | OrchestrationService |
| `SUPPRESSED` * | Contact suppressed mid-lifecycle | SuppressionCoordinator |
| `DEAD_LETTERED` * | Max retries; manual review | QueueManager |
| `ARCHIVED` * | Rejected or aged out | ApprovalService / Reconciliation |

**DB constraint:** `CHECK (lifecycle_state IN (...))`; state-transition guard trigger blocks illegal moves. `APPROVED` (or any subsequent state) requires `approval_attestation_id IS NOT NULL` via CHECK.

### F.2 Approval Lifecycle

```
SUBMITTED --reviewer_open--> UNDER_REVIEW
UNDER_REVIEW --approve--> APPROVED
UNDER_REVIEW --approve_tier1--> DUAL_REVIEW_PENDING
DUAL_REVIEW_PENDING --second_approve--> APPROVED
DUAL_REVIEW_PENDING --second_reject--> REJECTED
UNDER_REVIEW --reject--> REJECTED
UNDER_REVIEW --request_override--> ESCALATED
ESCALATED --audit_approve--> APPROVED
ESCALATED --audit_reject--> REJECTED
APPROVED --attested--> ATTESTED (terminal — attestation row written)
```

Owner: `ApprovalService` (single writer). DB enforces: every `APPROVED` outcome corresponds to exactly one `approval_attestations` row; the FK from `outreach_drafts.approval_attestation_id` is required. `is_override=TRUE` requires `override_reason NOT NULL` and `override_audited_by NOT NULL`.

### F.3 Send Attempt Lifecycle

```
CREATED --start--> ASSERTING --pass--> DISPATCHED --delivered_webhook--> DELIVERED*
                       |                    |
                       fail               bounce_webhook --> BOUNCED*
                       v                    |
                  ASSERT_FAILED*       complaint_webhook --> COMPLAINED*
                                            |
                                       provider_5xx --> DISPATCH_FAILED_RETRYABLE
                                       provider_4xx --> DISPATCH_FAILED_TERMINAL*
```

Owner: `SendWorker`. DB constraints: partial UNIQUE on `outbound_queue_id WHERE state IN ('CREATED','ASSERTING','DISPATCHED')` ensures only one active attempt per queue row. `DELIVERED` requires `delivery_confirmed_at IS NOT NULL`. `DISPATCHED` requires `provider_message_id IS NOT NULL`.

### F.4 Contact Outreach Lifecycle

```
UNTOUCHED --import--> RAW --enrich_ok--> ENRICHED --qualify_pass--> QUALIFIED
                                                |
                                              eligible_view_pass
                                                v
                                            ELIGIBLE --first_send--> SEQUENCED
                                                                          |
                                              +-------open/click------>WARMING
                                              v                            |
                                         SEQUENCED <---no_engagement_14d---+
                                              |                            |
                                              +---------reply------------> HOT
                                                                            |
                                                                          positive
                                                                            v
                                                                       RESPONDED
                                                                            |
                                                                        booked
                                                                            v
                                                                       CONVERTED*

(any non-converted) --bounce--> SUPPRESSED_BOUNCED*
                    --unsub--> SUPPRESSED_UNSUBSCRIBED*
                    --complaint--> SUPPRESSED_COMPLAINED*
                    --apollo_departed--> SUPPRESSED_DEPARTED*
                    --soft_no--> SUPPRESSED_NOT_INTERESTED
                    --manual_dnc--> SUPPRESSED_DO_NOT_CONTACT*
                    --cooldown_90d--> COOLDOWN --reactivate--> QUALIFIED
```

Owner: `ContactStateService` invoked by Orchestrator. DB constraints: CHECK on enum; FK from suppression states to a `suppression_events` row within 1 minute (enforced by trigger).

### F.5 Company Outreach Lifecycle

```
DISCOVERED --research--> RESEARCHED --qualify_pass--> QUALIFIED
                                                          |
                                          eligible_contact_exists
                                                          v
                                                   OUTREACH_READY
                                                          |
                                                  first_contact_sequenced
                                                          v
                                                   OUTREACH_ACTIVE <--lock_expired--+
                                                          | |                       |
                                              positive_reply| |send_within_lock     |
                                                          v |                       |
                                              ACTIVE_CONVERSATION                LOCKED_TEMPORARY
                                                          |
                                                   meeting_booked
                                                          v
                                                      CONVERTED*

(any active) --domain_dnc--> SUPPRESSED_DOMAIN_DNC*
             --escalated_bounce--> SUPPRESSED_HIGH_BOUNCE*
             --operator_hold--> ON_HOLD (transient; releases back to prior state)
             --wrong_fit_revealed--> DISQUALIFIED*
```

Owner: `CompanyStateService`. `LOCKED_TEMPORARY` is a UI-derived state from `company_outreach_locks` table; the underlying `lifecycle_state` remains `OUTREACH_ACTIVE`. `ON_HOLD` is derived from `company_holds` table similarly.

### F.6 Sequence Lifecycle

```
SCHEDULED --due--> ACTIVE --reply_received_non_terminal--> PAUSED_HUMAN_REPLY
                       |                                          |
                       |                                  reviewer_action
                       |                                          v
                       |                                       RESUMED
                       |                                          |
                       |                                  immediate-> ACTIVE
                       |
                       --reply_negative_or_unsub--> ABANDONED*
                       --bounce_terminal--> ABANDONED*
                       --contact_suppressed--> ABANDONED*
                       --final_step_sent--> COMPLETED*
                       --positive_reply_meeting--> COMPLETED*
                       --auto_pause_30d_no_action--> ABANDONED*
                       --operator_pause--> PAUSED --operator_resume--> ACTIVE
```

States distinguish system pauses (`PAUSED`) from human-reply pauses (`PAUSED_HUMAN_REPLY`). Human-reply pauses require operator action to resume; system pauses (e.g., admin halt) auto-resume when condition clears.

Owner: `SequenceCoordinator`. DB: `engagement_sequences.lifecycle_state` CHECK; `ABANDONED` requires `abandoned_reason` (bounce/unsub/suppression/manual).

### F.7 Reply Lifecycle

```
RECEIVED --dup_detected--> DEDUP_DROPPED*
   |
   v
CLASSIFYING --ok_high_confidence--> CLASSIFIED --auto_actionable--> AUTO_ACTIONED --done--> CLOSED*
   |                                  |
   error                         needs_human
   v                                  v
   +----------------------------> QUEUED_FOR_HITL --reviewer_handle--> ACTIONED --> CLOSED*
                                          |
                                       sla_breach_24h
                                          v
                                      ESCALATED --handle--> ACTIONED --> CLOSED*
```

Owner: `ReplyCoordinator`. DB: `inbound_replies.state` CHECK; UNIQUE on `(provider_message_id)` prevents double-intake; `ESCALATED` requires `escalation_reason`.

### F.8 Suppression Lifecycle

```
CLEAN --soft_bounce--> SOFT_SUPPRESSED (24h) --2nd_soft_24h--> HARD_SUPPRESSED*
                                          \--no_recur_30d--> CLEAN

CLEAN --hard_bounce--> HARD_SUPPRESSED*
      --complaint--> HARD_SUPPRESSED*
      --unsubscribe--> HARD_SUPPRESSED*
      --not_interested--> SOFT_SUPPRESSED (90d cooldown) --expires--> CLEAN
      --departed--> HARD_SUPPRESSED* (no reactivation)
      --manual_dnc--> HARD_SUPPRESSED* (operator only)

HARD_SUPPRESSED --manual_release_with_audit--> MONITORING --14d_no_send--> CLEAN
                                                          --recurrence--> HARD_SUPPRESSED*
```

Owner: `SuppressionCoordinator`. DB: `suppression_events.suppression_state` CHECK; partial UNIQUE on `(contact_id) WHERE revoked_at IS NULL` (one active suppression per contact at a time).

---

## SECTION G — Revised Data Model

For each table: purpose, columns, constraints, role grants, migration, retention.

### G.1 context_packets — NEW

**Purpose:** Per-action serialized ContextPacket. Immutable audit record of the world-view the system used at every draft generation, approval, and send.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `workspace_id` | UUID | NO | Tenancy |
| `company_id` | UUID | NO | FK companies(id) |
| `contact_id` | UUID | NO | FK contacts(id) |
| `sequence_id` | UUID | YES | FK engagement_sequences(id) |
| `sequence_step` | INT | YES | |
| `policy_snapshot_id` | UUID | NO | FK policy_snapshots(id) |
| `version_hash` | TEXT | NO | sha256 of key fields |
| `packet` | JSONB | NO | Full serialized ContextPacket |
| `generated_at` | TIMESTAMPTZ | NO | DEFAULT NOW() |
| `build_ms` | INT | NO | Build duration |
| `recommended_next_action` | TEXT | NO | From packet |
| `overall_risk_score` | NUMERIC(5,2) | YES | |
| `overall_risk_bucket` | TEXT | YES | |

**Constraints:**
```sql
CREATE INDEX idx_cp_contact ON context_packets(contact_id, generated_at DESC);
CREATE INDEX idx_cp_company ON context_packets(company_id, generated_at DESC);
CREATE INDEX idx_cp_hash ON context_packets(version_hash);
REVOKE UPDATE, DELETE ON context_packets FROM PUBLIC;
GRANT INSERT, SELECT ON context_packets TO prospectiq_writer_context_builder;
GRANT SELECT ON context_packets TO prospectiq_app;
```

**Migration:** Additive. Start fresh; no backfill.
**Retention:** Indefinite for forensic audit; old rows can be archived to cold storage after 365 days.

### G.2 draft_versions — NEW

**Purpose:** Immutable version history of draft body/subject.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK outreach_drafts(id) |
| `version_number` | INT | NO | 1 = original; 2+ = edits |
| `subject` | TEXT | NO | |
| `body` | TEXT | NO | |
| `content_hash` | TEXT | NO | sha256(subject \|\| body) |
| `created_at` | TIMESTAMPTZ | NO | |
| `created_by` | TEXT | NO | 'generator:claude-sonnet-4' or 'user:<uuid>' |
| `created_by_type` | TEXT | NO | generator / reviewer_edit / override_rewrite / migration_backfill |
| `generation_metadata` | JSONB | YES | model, temperature, prompt_hash, claim_ids_referenced, primary_angle_used |
| `context_packet_id` | UUID | YES | FK context_packets(id) — for generator rows |

**Constraints:**
```sql
CONSTRAINT dv_unique_version_per_draft UNIQUE (draft_id, version_number),
CONSTRAINT dv_unique_content_per_draft UNIQUE (draft_id, content_hash),
CONSTRAINT dv_created_by_type_check CHECK (created_by_type IN (
  'generator','reviewer_edit','override_rewrite','migration_backfill'))
REVOKE UPDATE, DELETE ON draft_versions FROM PUBLIC;
GRANT INSERT, SELECT ON draft_versions TO prospectiq_writer_draft_generator;
GRANT INSERT, SELECT ON draft_versions TO prospectiq_writer_approval_svc;
GRANT SELECT ON draft_versions TO prospectiq_app;
```

`outreach_drafts.body_version_id` and `edited_body_version_id` FK here.

**Migration:** For every existing `outreach_drafts` row, INSERT one `draft_versions` row with `version_number=1`, `created_by='migration_backfill'`. If `edited_body IS NOT NULL`, INSERT second row.
**Retention:** Indefinite.

### G.3 draft_quality_results — NEW

**Purpose:** Per-version validator output.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_version_id` | UUID | NO | FK draft_versions(id) |
| `validator_version` | TEXT | NO | |
| `overall_result` | TEXT | NO | PASS / WARN_AND_QUARANTINE / HARD_REJECT |
| `pass_1_integrity` | JSONB | NO | regex pass results |
| `pass_2_quality` | JSONB | NO | validate_draft output |
| `pass_3_claim_grounding` | JSONB | NO | per claim_id coverage check |
| `pass_4_continuity` | JSONB | NO | repetition check vs prior steps + siblings |
| `evaluated_at` | TIMESTAMPTZ | NO | |

```sql
REVOKE UPDATE, DELETE ON draft_quality_results FROM PUBLIC;
GRANT INSERT, SELECT ON draft_quality_results TO prospectiq_writer_draft_generator;
GRANT SELECT ON draft_quality_results TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.4 evidence_registry — NEW (renamed from content_claims)

**Purpose:** Approved claim catalog. Generation can only assert what is here.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `claim_type` | TEXT | NO | PRODUCT_FACT / BENCHMARK_CITATION / OUTCOME_STATEMENT / ANTI_PATTERN / REGULATORY_REFERENCE / PUBLIC_SIGNAL |
| `claim_text` | TEXT | NO | Exact approved phrasing |
| `claim_pattern` | TEXT | YES | Regex for equivalent phrasings |
| `confidence` | TEXT | NO | high / medium / low |
| `source` | TEXT | NO | citation text |
| `source_url` | TEXT | YES | |
| `applicable_sectors` | TEXT[] | YES | NAICS prefixes |
| `effective_from` | TIMESTAMPTZ | NO | |
| `expires_at` | TIMESTAMPTZ | YES | |
| `is_active` | BOOL | NO | DEFAULT TRUE |
| `created_at` | TIMESTAMPTZ | NO | |
| `created_by` | UUID | NO | FK users(id) |
| `approved_at` | TIMESTAMPTZ | YES | Second-user approval |
| `approved_by` | UUID | YES | FK users(id) |

```sql
CREATE INDEX idx_er_active_type ON evidence_registry(is_active, claim_type)
  WHERE is_active = TRUE;
REVOKE UPDATE, DELETE ON evidence_registry FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (is_active, expires_at, approved_at, approved_by)
  ON evidence_registry TO prospectiq_writer_evidence_svc;
GRANT SELECT ON evidence_registry TO prospectiq_app;
```

**Migration:** Seed from `offer_context.yaml::product_facts`, `outreach_guidelines.yaml::never_include` (as ANTI_PATTERN rows), validated case studies.
**Retention:** Indefinite.

### G.5 claim_validation_results — NEW

**Purpose:** Per-draft-version claim coverage detail.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_version_id` | UUID | NO | FK draft_versions(id) |
| `claim_id` | UUID | NO | FK evidence_registry(id) |
| `referenced_in_body` | BOOL | NO | |
| `pattern_match_offset` | INT | YES | byte offset in body |
| `validated_at` | TIMESTAMPTZ | NO | |

```sql
REVOKE UPDATE, DELETE ON claim_validation_results FROM PUBLIC;
GRANT INSERT, SELECT ON claim_validation_results TO prospectiq_writer_draft_generator;
GRANT SELECT ON claim_validation_results TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.6 approval_attestations — NEW

**Purpose:** One row per approval. Immutable. Required FK from `outreach_drafts.approval_attestation_id`.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK outreach_drafts(id); UNIQUE |
| `reviewer_id` | UUID | NO | FK users(id) — REAL UUID, not text |
| `second_reviewer_id` | UUID | YES | FK users(id) for tier-1 dual |
| `attested_at` | TIMESTAMPTZ | NO | |
| `attestation_payload` | JSONB | NO | The five booleans |
| `quality_gate_result` | JSONB | NO | validator output |
| `policy_snapshot_id` | UUID | NO | FK policy_snapshots(id) |
| `body_version_id` | UUID | NO | FK draft_versions(id) — what was approved |
| `context_packet_id` | UUID | NO | FK context_packets(id) — what reviewer saw |
| `reviewer_ip` | INET | YES | |
| `reviewer_user_agent` | TEXT | YES | |
| `is_override` | BOOL | NO | DEFAULT FALSE |
| `override_reason` | TEXT | YES | Required when is_override=true |
| `override_audited_by` | UUID | YES | FK users(id) |
| `override_audited_at` | TIMESTAMPTZ | YES | |

```sql
CONSTRAINT override_reason_required CHECK (is_override = FALSE OR override_reason IS NOT NULL),
CONSTRAINT override_audit_consistent
  CHECK ((override_audited_by IS NULL) = (override_audited_at IS NULL)),
REVOKE UPDATE, DELETE ON approval_attestations FROM PUBLIC;
GRANT INSERT, SELECT ON approval_attestations TO prospectiq_writer_approval_svc;
GRANT SELECT ON approval_attestations TO prospectiq_app;
```

**Migration:** Backfill from existing approved drafts where `approved_by` is real UUID; drafts where `approved_by='avanish'` get placeholder rows with `is_override=true, override_reason='migration_backfill_unauthenticated_approval'`.
**Retention:** Indefinite.

### G.7 autonomy_decisions — NEW

**Purpose:** Append-only log of every autonomous decision the engine made.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `workspace_id` | UUID | NO | |
| `entity_type` | TEXT | NO | outreach_draft / contact / company / send_attempt / sequence / inbound_reply / suppression / webhook_event / outbox_row |
| `entity_id` | UUID | NO | |
| `workflow` | TEXT | NO | one of 15 workflows (Section H) |
| `decision` | TEXT | NO | PROCEED / HOLD / BLOCK / ESCALATE (or SHADOW_/SIM_/DRY_RUN_ variants) |
| `risk_score` | NUMERIC(5,2) | YES | |
| `risk_bucket` | TEXT | YES | |
| `gate_results` | JSONB | NO | per-gate pass/fail |
| `policy_snapshot_id` | UUID | NO | FK |
| `validator_version` | TEXT | YES | |
| `worker_instance_id` | TEXT | NO | host:pid:start_epoch |
| `correlation_id` | UUID | YES | |
| `reason` | TEXT | YES | |
| `created_at` | TIMESTAMPTZ | NO | |

```sql
CREATE INDEX idx_ad_entity ON autonomy_decisions(entity_type, entity_id, created_at);
CREATE INDEX idx_ad_workflow_decision ON autonomy_decisions(workflow, decision, created_at);
CREATE INDEX idx_ad_shadow ON autonomy_decisions(workflow, created_at)
  WHERE decision LIKE 'SHADOW_%';
REVOKE UPDATE, DELETE ON autonomy_decisions FROM PUBLIC;
GRANT INSERT, SELECT ON autonomy_decisions TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.8 risk_scores — NEW

**Purpose:** Per-draft computed risk score history.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK outreach_drafts(id) |
| `contact_id` | UUID | NO | |
| `company_id` | UUID | NO | |
| `workspace_id` | UUID | NO | |
| `score` | NUMERIC(5,2) | NO | 0–100 |
| `bucket` | TEXT | NO | LOW / MEDIUM / HIGH / BLOCKED |
| `dimension_scores` | JSONB | NO | per-dimension |
| `triggered_dimensions` | TEXT[] | NO | |
| `scoring_version` | TEXT | NO | |
| `policy_snapshot_id` | UUID | NO | FK |
| `context_packet_id` | UUID | NO | FK context_packets(id) |
| `scored_at` | TIMESTAMPTZ | NO | |

```sql
CREATE INDEX idx_rs_draft_latest ON risk_scores(draft_id, scored_at DESC);
CREATE INDEX idx_rs_bucket_recent ON risk_scores(bucket, scored_at DESC);
CREATE VIEW latest_risk_scores AS
  SELECT DISTINCT ON (draft_id) * FROM risk_scores ORDER BY draft_id, scored_at DESC;
REVOKE UPDATE, DELETE ON risk_scores FROM PUBLIC;
GRANT INSERT, SELECT ON risk_scores TO prospectiq_writer_risk_svc;
GRANT SELECT ON risk_scores TO prospectiq_app;
```

**Migration:** Additive; backfill nothing or run scorer once over existing pending drafts.
**Retention:** Indefinite.

### G.9 outbound_queue — NEW

**Purpose:** Transactional outbox; populated by ApprovalService.approve in same tx as attestation.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK outreach_drafts(id); UNIQUE |
| `workspace_id` | UUID | NO | |
| `state` | TEXT | NO | PENDING / CLAIMED / SENT / FAILED / DEAD_LETTER / CANCELLED |
| `priority_score` | NUMERIC(7,2) | NO | DEFAULT 100 |
| `enqueued_at` | TIMESTAMPTZ | NO | |
| `available_at` | TIMESTAMPTZ | NO | |
| `claimed_at` | TIMESTAMPTZ | YES | |
| `claimed_by_worker` | TEXT | YES | host:pid:start_epoch |
| `claim_expires_at` | TIMESTAMPTZ | YES | |
| `attempt_count` | INT | NO | DEFAULT 0 |
| `max_attempts` | INT | NO | DEFAULT 3 |
| `next_attempt_at` | TIMESTAMPTZ | YES | |
| `last_error` | TEXT | YES | |
| `policy_snapshot_id` | UUID | NO | FK |
| `context_packet_id` | UUID | YES | FK; rebuilt at claim time if stale |
| `completed_at` | TIMESTAMPTZ | YES | |

```sql
CREATE INDEX idx_oq_ready ON outbound_queue(workspace_id, priority_score DESC, enqueued_at ASC)
  WHERE state = 'PENDING' AND available_at <= NOW();
CREATE INDEX idx_oq_orphans ON outbound_queue(state, claim_expires_at)
  WHERE state = 'CLAIMED';
REVOKE UPDATE, DELETE ON outbound_queue FROM PUBLIC;
GRANT INSERT ON outbound_queue TO prospectiq_writer_approval_svc;
GRANT UPDATE (state, claimed_at, claimed_by_worker, claim_expires_at,
              attempt_count, next_attempt_at, last_error, completed_at,
              context_packet_id)
  ON outbound_queue TO prospectiq_writer_send_worker;
GRANT UPDATE (state, last_error, completed_at)
  ON outbound_queue TO prospectiq_writer_suppression_svc;
GRANT SELECT ON outbound_queue TO prospectiq_app;
```

**Migration:** Additive. One-time INSERT from currently-approved-unsent drafts at cutover.
**Retention:** COMPLETED archived after 30d; DEAD_LETTER indefinite.

### G.10 send_attempts — NEW

**Purpose:** Per-attempt delivery state. Decouples delivery from `outreach_drafts.sent_at`.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK outreach_drafts(id) |
| `outbound_queue_id` | UUID | NO | FK outbound_queue(id) |
| `workspace_id` | UUID | NO | |
| `attempt_number` | INT | NO | per draft |
| `state` | TEXT | NO | CREATED / ASSERTING / DISPATCHED / DELIVERED / ASSERT_FAILED / DISPATCH_FAILED_RETRYABLE / DISPATCH_FAILED_TERMINAL / BOUNCED / COMPLAINED |
| `provider` | TEXT | NO | resend / instantly / gmail |
| `provider_message_id` | TEXT | YES | |
| `provider_response` | JSONB | YES | |
| `policy_snapshot_id` | UUID | NO | FK |
| `context_packet_id` | UUID | NO | FK |
| `sender_email` | TEXT | YES | |
| `claimed_at` | TIMESTAMPTZ | NO | |
| `asserting_at` | TIMESTAMPTZ | YES | |
| `dispatched_at` | TIMESTAMPTZ | YES | |
| `delivery_confirmed_at` | TIMESTAMPTZ | YES | |
| `terminal_at` | TIMESTAMPTZ | YES | |
| `failure_reason` | TEXT | YES | |
| `failed_assertion` | UUID | YES | FK send_assertions(id) |

```sql
CONSTRAINT sa_state_check CHECK (state IN (...)),
CONSTRAINT sa_unique_attempt UNIQUE (draft_id, attempt_number);
CREATE UNIQUE INDEX uniq_active_attempt_per_outbox
  ON send_attempts(outbound_queue_id)
  WHERE state IN ('CREATED','ASSERTING','DISPATCHED');
CREATE INDEX idx_sa_state ON send_attempts(state, claimed_at);
CREATE INDEX idx_sa_provider_msg ON send_attempts(provider_message_id)
  WHERE provider_message_id IS NOT NULL;
REVOKE UPDATE, DELETE ON send_attempts FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (state, asserting_at, dispatched_at,
       delivery_confirmed_at, terminal_at, provider_message_id,
       provider_response, failure_reason, failed_assertion)
  ON send_attempts TO prospectiq_writer_send_worker;
GRANT SELECT ON send_attempts TO prospectiq_app;
```

**Migration:** Backfill one row per draft where `sent_at IS NOT NULL` with `state='DELIVERED', delivery_confirmed_at=sent_at, provider_message_id=resend_message_id, attempt_number=1`.
**Retention:** Indefinite.

### G.11 provider_events — NEW

**Purpose:** Normalized inbound webhook events. Idempotent intake. Source for ReplyCoordinator and OrchestrationService.process_delivery_event.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `workspace_id` | UUID | NO | |
| `provider` | TEXT | NO | resend / instantly / gmail / unipile / trigify / apollo / zerobounce |
| `event_type` | TEXT | NO | normalized: email_delivered / email_bounced / reply_received / email_opened / email_clicked / unsubscribe / complaint |
| `external_event_id` | TEXT | NO | provider's id |
| `payload` | JSONB | NO | raw |
| `received_at` | TIMESTAMPTZ | NO | |
| `processed_at` | TIMESTAMPTZ | YES | |
| `processing_state` | TEXT | NO | received / processing / processed / duplicate / failed |
| `signature_verified` | BOOL | NO | DEFAULT FALSE |
| `contact_id` | UUID | YES | resolved during processing |
| `company_id` | UUID | YES | |
| `draft_id` | UUID | YES | |
| `send_attempt_id` | UUID | YES | |
| `correlation_id` | UUID | YES | |
| `error` | TEXT | YES | |

```sql
CONSTRAINT pe_external_unique UNIQUE (provider, external_event_id);
CREATE INDEX idx_pe_unprocessed ON provider_events(provider, received_at)
  WHERE processing_state = 'received';
CREATE INDEX idx_pe_draft ON provider_events(draft_id) WHERE draft_id IS NOT NULL;
REVOKE UPDATE, DELETE ON provider_events FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (processed_at, processing_state, contact_id,
       company_id, draft_id, send_attempt_id, correlation_id, error)
  ON provider_events TO prospectiq_writer_webhook_svc;
GRANT SELECT ON provider_events TO prospectiq_app;
```

`webhook_event_log` is an alias / view over `provider_events` for backward compatibility during migration.

**Migration:** Additive.
**Retention:** 180 days; the UNIQUE constraint protects against re-ingestion within that window.

### G.12 workflow_events — NEW

**Purpose:** Append-only authoritative state-transition log.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `event_id` | UUID | NO | UNIQUE — deterministic from (target_type, target_id, transition, occurred_at) |
| `target_type` | TEXT | NO | outreach_draft / contact / company / send_attempt / sequence / inbound_reply / approval / suppression / webhook |
| `target_id` | UUID | NO | |
| `transition` | TEXT | NO | event name from Section F |
| `from_state` | TEXT | YES | NULL on create |
| `to_state` | TEXT | NO | |
| `actor_type` | TEXT | NO | user / service / webhook / system / autonomy_engine / operator_cli |
| `actor_id` | TEXT | YES | UUID for user; service name for service |
| `workspace_id` | UUID | NO | |
| `occurred_at` | TIMESTAMPTZ | NO | |
| `recorded_at` | TIMESTAMPTZ | NO | |
| `payload` | JSONB | YES | |
| `correlation_id` | UUID | YES | |
| `causation_id` | UUID | YES | |
| `policy_snapshot_id` | UUID | YES | |
| `autonomy_decision_id` | UUID | YES | FK autonomy_decisions(id) |
| `context_packet_id` | UUID | YES | FK context_packets(id) |

```sql
CONSTRAINT we_actor_type_check CHECK (actor_type IN (...));
CREATE INDEX idx_we_target ON workflow_events(target_type, target_id, occurred_at);
CREATE INDEX idx_we_transition ON workflow_events(transition, occurred_at);
CREATE INDEX idx_we_correlation ON workflow_events(correlation_id);
CREATE INDEX idx_we_decision ON workflow_events(autonomy_decision_id)
  WHERE autonomy_decision_id IS NOT NULL;
REVOKE UPDATE, DELETE ON workflow_events FROM PUBLIC;
GRANT INSERT, SELECT ON workflow_events TO prospectiq_app;
```

**Migration:** No backfill; start fresh.
**Retention:** Indefinite.

### G.13 suppression_events — NEW (replaces suppression_log)

**Purpose:** Append-only suppression log; single writer through SuppressionCoordinator.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `workspace_id` | UUID | NO | |
| `contact_id` | UUID | YES | |
| `company_id` | UUID | YES | |
| `email` | TEXT | YES | |
| `domain` | TEXT | YES | |
| `suppression_type` | TEXT | NO | BOUNCE / COMPLAINT / UNSUBSCRIBE / DEPARTED / NOT_INTERESTED / COOLDOWN / DNC / LEGAL_HOLD / COMPETITOR / SYSTEM_RULE |
| `suppression_scope` | TEXT | NO | CONTACT / DOMAIN / COMPANY / EMAIL |
| `suppression_state` | TEXT | NO | CLEAN / SOFT_BOUNCE / HARD_BOUNCE / COMPLAINT / UNSUBSCRIBED / DEPARTED / DOMAIN_DNC / MANUAL_DNC / COOLDOWN / MONITORING |
| `source` | TEXT | NO | WEBHOOK / OPERATOR / IMPORT / SYSTEM_RULE / RECONCILIATION / CLASSIFIER / LEGAL |
| `provider_event_id` | UUID | YES | FK provider_events(id) |
| `triggered_by_contact_id` | UUID | YES | |
| `escalated_from` | UUID | YES | FK suppression_events(id) |
| `reason` | TEXT | NO | |
| `classifier_confidence` | NUMERIC(3,2) | YES | |
| `policy_snapshot_id` | UUID | NO | FK |
| `created_at` | TIMESTAMPTZ | NO | |
| `expires_at` | TIMESTAMPTZ | YES | NULL = permanent |
| `revoked_at` | TIMESTAMPTZ | YES | |
| `revoked_by` | UUID | YES | FK users(id) |
| `revoked_reason` | TEXT | YES | |
| `metadata` | JSONB | YES | |

```sql
CONSTRAINT supp_scope_consistent CHECK (...),
CONSTRAINT supp_revoke_consistent CHECK (...);
CREATE INDEX idx_se_contact_active ON suppression_events(contact_id, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_se_company_active ON suppression_events(company_id, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_se_domain_active ON suppression_events(domain, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_se_email_active ON suppression_events(email, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX uniq_active_suppression_per_contact
  ON suppression_events(contact_id) WHERE revoked_at IS NULL;
REVOKE UPDATE, DELETE ON suppression_events FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (revoked_at, revoked_by, revoked_reason)
  ON suppression_events TO prospectiq_writer_suppression_svc;
GRANT SELECT ON suppression_events TO prospectiq_app;
```

**Migration:** Backfill from `suppression_log`. Dual-write for 30 days; then drop `suppression_log`.
**Retention:** Indefinite.

### G.14 company_holds, contact_holds — NEW

**Purpose:** Operator-initiated holds; distinct from system suppression.

```sql
CREATE TABLE company_holds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  company_id UUID NOT NULL REFERENCES companies(id),
  hold_type TEXT NOT NULL CHECK (hold_type IN (
    'OPERATOR_PAUSE','LEGAL_REVIEW','BILLING_HOLD','RELATIONSHIP_RISK',
    'EXEC_TOUCH_IN_PROGRESS','STRATEGIC_HOLD')),
  reason TEXT NOT NULL,
  metadata JSONB,
  set_by UUID NOT NULL REFERENCES users(id),
  set_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  released_at TIMESTAMPTZ,
  released_by UUID REFERENCES users(id),
  released_reason TEXT,
  CONSTRAINT ch_release_consistent
    CHECK ((released_at IS NULL) = (released_by IS NULL))
);
CREATE INDEX idx_ch_active ON company_holds(workspace_id, company_id)
  WHERE released_at IS NULL;

-- contact_holds: identical shape, contact_id replacing company_id,
-- hold_type in ('OPERATOR_PAUSE','VERIFY_TITLE','VERIFY_EMAIL',
-- 'MEETING_BOOKED','INTERNAL_REFERRAL')

REVOKE UPDATE, DELETE ON company_holds, contact_holds FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (released_at, released_by, released_reason)
  ON company_holds, contact_holds TO prospectiq_writer_operator_svc;
GRANT SELECT ON company_holds, contact_holds TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.15 sequence_state_transitions — NEW

**Purpose:** Audit log of every `engagement_sequences.lifecycle_state` change with reason. Complements `workflow_events`; this table is the projection for the sequence health UI.

```sql
CREATE TABLE sequence_state_transitions (
  id UUID PRIMARY KEY,
  sequence_id UUID NOT NULL REFERENCES engagement_sequences(id),
  workspace_id UUID NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  reason TEXT NOT NULL,
  triggered_by_type TEXT NOT NULL, -- system / operator / reply / suppression
  triggered_by_id TEXT,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sst_sequence ON sequence_state_transitions(sequence_id, occurred_at);
REVOKE UPDATE, DELETE ON sequence_state_transitions FROM PUBLIC;
GRANT INSERT, SELECT ON sequence_state_transitions TO prospectiq_writer_sequence_svc;
GRANT SELECT ON sequence_state_transitions TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.16 operator_overrides — NEW

**Purpose:** Distinct table for audited override actions (override-requested + override-audited pairs). Required because `approval_attestations.is_override` answers "was this an override approval" but not "who escalated which decisions where the engine recommended HOLD/BLOCK."

```sql
CREATE TABLE operator_overrides (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  target_type TEXT NOT NULL,        -- draft / suppression / send_freeze / hold
  target_id UUID NOT NULL,
  override_action TEXT NOT NULL,    -- approve_high_risk / unsuppress / lift_freeze / release_hold / force_send
  requested_by UUID NOT NULL REFERENCES users(id),
  requested_reason TEXT NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  audited_by UUID REFERENCES users(id),
  audit_decision TEXT,              -- approve / reject / expire
  audit_reason TEXT,
  audited_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL,  -- request expires after 24h
  CONSTRAINT oo_distinct_users
    CHECK (audited_by IS NULL OR audited_by != requested_by),
  CONSTRAINT oo_audit_consistent
    CHECK ((audited_by IS NULL) = (audited_at IS NULL))
);
CREATE INDEX idx_oo_pending ON operator_overrides(workspace_id, requested_at)
  WHERE audited_at IS NULL;
REVOKE UPDATE, DELETE ON operator_overrides FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (audited_by, audit_decision, audit_reason, audited_at)
  ON operator_overrides TO prospectiq_writer_operator_svc;
GRANT SELECT ON operator_overrides TO prospectiq_app;
```

**Migration:** Additive.
**Retention:** Indefinite.

### G.17 dead_letter_queue — NEW

```sql
CREATE TABLE dead_letter_queue (
  id UUID PRIMARY KEY,
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id),
  original_queue_entry_id UUID REFERENCES outbound_queue(id),
  workspace_id UUID NOT NULL,
  failure_reason TEXT NOT NULL,
  failure_category TEXT NOT NULL CHECK (failure_category IN (
    'ASSERTION_FAILURE','PROVIDER_ERROR','CONTENT_BLOCKED',
    'POLICY_VIOLATION','SUPPRESSION','MAX_ATTEMPTS_EXCEEDED',
    'PROVIDER_PERMANENT_4XX','WORKER_CRASH','ORPHAN_CLAIM')),
  failure_payload JSONB,
  failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users(id),
  resolution_action TEXT,
  CONSTRAINT dlq_resolution_consistent
    CHECK ((resolved_at IS NULL) = (resolved_by IS NULL))
);
CREATE INDEX idx_dlq_unresolved ON dead_letter_queue(workspace_id, failed_at)
  WHERE resolved_at IS NULL;
REVOKE UPDATE, DELETE ON dead_letter_queue FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (resolved_at, resolved_by, resolution_action)
  ON dead_letter_queue TO prospectiq_writer_send_worker;
GRANT SELECT ON dead_letter_queue TO prospectiq_app;
```

### G.18 reconciliation_runs — NEW

**Purpose:** Per-run record of drift detection results.

```sql
CREATE TABLE reconciliation_runs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  workspace_id UUID,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
  drifts_detected INT NOT NULL DEFAULT 0,
  auto_fixed INT NOT NULL DEFAULT 0,
  alerts_emitted INT NOT NULL DEFAULT 0,
  detail JSONB
);
```

### G.19 policy_snapshots — NEW

**Purpose:** Versioned policy snapshots.

```sql
CREATE TABLE policy_snapshots (
  id UUID PRIMARY KEY,
  version INTEGER NOT NULL,
  workspace_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  superseded_at TIMESTAMPTZ,
  payload JSONB NOT NULL,           -- limits, gaps, cooldowns, sequences config, claim rules
  payload_hash TEXT NOT NULL,
  created_by UUID NOT NULL REFERENCES users(id),
  description TEXT,
  CONSTRAINT ps_unique_version UNIQUE (workspace_id, version)
);
CREATE UNIQUE INDEX uniq_active_policy ON policy_snapshots(workspace_id)
  WHERE superseded_at IS NULL;
REVOKE UPDATE, DELETE ON policy_snapshots FROM PUBLIC;
GRANT INSERT, UPDATE (superseded_at), SELECT
  ON policy_snapshots TO prospectiq_writer_policy_svc;
GRANT SELECT ON policy_snapshots TO prospectiq_app;
```

**Migration:** On first deploy, insert `version=1` capturing current state of `limits.yaml`, `outreach_send_config`, `outreach_guidelines.yaml`, `sequences.yaml`.

### G.20 learning_signals — NEW

**Purpose:** Pattern surfacing back to Context Intelligence (e.g., "fabricated claim regex was flagged 3 times in last 7 days").

```sql
CREATE TABLE learning_signals (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  signal_type TEXT NOT NULL,        -- claim_quarantine / repetition_pattern / hot_persona / dead_sender_pool
  scope_type TEXT NOT NULL,         -- workspace / sector / persona / sequence / contact / company
  scope_id TEXT,
  payload JSONB NOT NULL,
  source TEXT NOT NULL,             -- reviewer_feedback / classifier / reconciliation
  observed_at TIMESTAMPTZ NOT NULL,
  effective_until TIMESTAMPTZ
);
CREATE INDEX idx_ls_active ON learning_signals(workspace_id, signal_type)
  WHERE effective_until > NOW() OR effective_until IS NULL;
```

### G.21 Retained/Modified Existing Tables

| Table | Changes |
|---|---|
| `outreach_drafts` | Add `lifecycle_state TEXT NOT NULL` with CHECK; `body_version_id UUID FK draft_versions(id)`; `edited_body_version_id UUID FK draft_versions(id)`; `approval_attestation_id UUID FK approval_attestations(id)`; `risk_score_id UUID FK risk_scores(id)`; `generation_context_packet_id UUID FK context_packets(id)`. Existing `body`, `subject`, `approval_status`, `approved_by`, `reviewed_at`, `sent_at`, `resend_message_id` retained as denormalized cache, maintained by trigger. UPDATE protection trigger extended to block `body, subject` changes once `lifecycle_state IN ('APPROVED','EDITED',...)` |
| `contacts` | Add `lifecycle_state TEXT NOT NULL` with CHECK; add `suppression_state TEXT` derived from active suppression_events row. Existing columns retained. Postgres role grants restrict UPDATE of `lifecycle_state` and `suppression_state` to specific services |
| `companies` | Add `lifecycle_state TEXT NOT NULL` with CHECK; add `company_traction_state TEXT` derived. Existing columns retained |
| `engagement_sequences` | Add `lifecycle_state TEXT NOT NULL DEFAULT 'SCHEDULED'` with CHECK; add `abandoned_reason TEXT`; CHECK enforces `abandoned_reason NOT NULL when state='ABANDONED'` |
| `sequence_step_state` | New table — see Section G.22 |
| `interactions` | Add `source TEXT` (e.g., 'provider_event:<id>'); remains as read-side projection only. Existing reads continue |
| `suppression_log` | Marked DEPRECATED. Dual-write during 30-day migration; eventual `DROP TABLE` |
| `campaign_threads` | Add `active_conversation_detected BOOL DEFAULT FALSE` (set by ReplyCoordinator on positive reply); add UNIQUE on `(provider_message_id)` of `thread_messages` |
| `outreach_send_config` | No schema change; promoted to the single send-cap source. `limits.yaml::outreach.daily_send_limit` removed; `workspaces.settings.daily_send_limit` JSONB key removed |
| `send_assertions` | Retained as gate evidence. `send_attempts.failed_assertion` FKs here |
| `outbound_eligible_contacts` | Retained; consulted by ContextPacketBuilder rather than at-send-time |

### G.22 sequence_step_state — NEW

```sql
CREATE TABLE sequence_step_state (
  id UUID PRIMARY KEY,
  sequence_id UUID NOT NULL REFERENCES engagement_sequences(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id),
  step_number INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (state IN ('PENDING','DRAFT_GENERATED','DRAFT_APPROVED','DRAFT_SENT',
                     'STEP_SKIPPED','STEP_BLOCKED')),
  draft_id UUID REFERENCES outreach_drafts(id),
  send_attempt_id UUID REFERENCES send_attempts(id),
  due_at TIMESTAMPTZ,
  entered_state_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notes JSONB,
  CONSTRAINT sss_unique UNIQUE (sequence_id, contact_id, step_number)
);
CREATE INDEX idx_sss_due ON sequence_step_state(due_at, state)
  WHERE state IN ('PENDING','STEP_BLOCKED');
```

**Migration:** Backfill from `outreach_drafts` history per sequence/contact.
**Retention:** Indefinite.

---

## SECTION H — Governance and Autonomy Model

For each of 15 workflows: classification, guardrails, escalation trigger.

| Workflow | Classification | Guardrails | Escalation Trigger |
|---|---|---|---|
| prospect_ingestion | AUTONOMOUS_WITH_GUARDRAILS | Apollo daily quota; tenant scoping by import session; bulk > 100 rows requires attestation | Apollo credit < apollo_min_buffer; per-source duplicate rate > 25%; fuzzy-match collision > 5 |
| enrichment | AUTONOMOUS_WITH_GUARDRAILS | Per-contact 30d idempotency; per-day Apollo quota; result quality check (low confidence → ENRICHMENT_PARTIAL) | Apollo 5xx > 10% over 1h; monthly spend > 80%; ZeroBounce fail rate > 50% on Apollo emails |
| qualification | FULLY_AUTONOMOUS | None at action level; cost tracked via api_costs | Anthropic 5xx > 15min; verdict distribution swings > 30% week-over-week |
| research_refresh | AUTONOMOUS_WITH_GUARDRAILS | 14-day idempotency; research_hard_limit_usd cap; only OUTREACH_ACTIVE companies; batch 10/tick | Weekly spend > 90% cap; Perplexity 5 consecutive failures |
| draft_generation | AUTONOMOUS_WITH_GUARDRAILS | Single DraftGenerator (no parallel HTTP path); 4-pass validator pre-persist; only registered claims; cost cap per workspace per day | HARD_REJECT rate > 20% / 24h; QUARANTINE rate > 30% / 24h |
| content_validation | FULLY_AUTONOMOUS | Validator version pinned in policy_snapshot; per-pass evidence row in workflow_events | None — validator escalates to human approval when its confidence falls |
| draft_approval | AUTONOMOUS_WITH_GUARDRAILS (LOW risk only); HUMAN_APPROVAL_REQUIRED (MEDIUM/HIGH); HUMAN_ESCALATION_REQUIRED (BLOCKED) | All 4 validator passes; risk LOW; step <= 2; no sibling traction; sender reputation healthy; all 7 gate layers pre-pass | Risk MEDIUM/HIGH/BLOCKED; QUARANTINE flag; first use of new sequence/template; manual edit after generation |
| send_execution | AUTONOMOUS_WITH_GUARDRAILS | Worker singleton (advisory lock); outbound_queue FOR UPDATE SKIP LOCKED; per-claim re-check of 7-layer gates; outbox lease prevents zombie claims | 3 retries fail (dead-letter); bounce-rate gate fires; Resend health fails; DLQ depth > 10 |
| follow_up_generation | AUTONOMOUS_WITH_GUARDRAILS | sequence_step_state for N-1 in DRAFT_SENT; step gap satisfied; no reply on prior step; no sibling positive reply; not suppressed | Step gap negative or > 30d; step N-1 in DISPATCH_FAILED_TERMINAL |
| reply_classification | AUTONOMOUS_WITH_GUARDRAILS (clear); HUMAN_ESCALATION_REQUIRED (ambiguous or positive) | confidence > 0.85 AND classification in {bounce, ooo, departed, unsubscribe}; auto-suppression bounded to contact scope only | confidence <= 0.85; classification in {positive, question, negative, other}; conflicting classifications within 1h |
| suppression | FULLY_AUTONOMOUS (system signals); HUMAN_APPROVAL_REQUIRED (manual DNC, company-level) | Single SuppressionCoordinator writer; tiered scope (contact → company on threshold); idempotent via provider_events | Conflict with recent positive reply; escalation triggered by < 2 distinct contacts (drift); legal-flagged |
| sequence_pausing_resuming | FULLY_AUTONOMOUS (system pauses); HUMAN_APPROVAL_REQUIRED (resume after positive-reply); BLOCKED_UNLESS_OVERRIDE (resume after unsubscribe) | System pause sets STEP_BLOCKED on future steps; resume from positive-reply pause requires operator action; 30d-paused auto-abandons | Paused > 90d without action |
| sibling_contact_outreach | AUTONOMOUS_WITH_GUARDRAILS (no traction); HUMAN_APPROVAL_REQUIRED (sibling has traction) | 5-business-day company lock; risk dimension traction_signal drives routing; no autonomy if any sibling in RESPONDED | Company in ACTIVE_CONVERSATION |
| company_traction_detection | FULLY_AUTONOMOUS | Computed from interactions + provider_events; materialized as company_traction_state | None — pure derivation |
| re_engagement | AUTONOMOUS_WITH_GUARDRAILS | Original sequence completed > 90d ago; no suppression; no fresh negative signal; ICP still matches; fresh sequence (step counter = 1) | Title churned out of persona; NAICS reclassified; multiple related-domain suppressions since cooldown |

---

## SECTION I — Evidence and Claim Governance

`evidence_registry` (Section G.4) is the registry. The validation pipeline runs at four points:

**Claim types:**
- `PRODUCT_FACT` — what Digitillis is and does
- `BENCHMARK_CITATION` — industry-published statistics with source URL
- `OUTCOME_STATEMENT` — customer outcomes, anonymized, with case-study reference; requires second-user approval before activation
- `REGULATORY_REFERENCE` — FSMA, OSHA, MEP citations with effective date
- `PUBLIC_SIGNAL` — news/signal scraped facts (e.g., "Acme announced $50M plant"); 90-day default expiry
- `ANTI_PATTERN` — banned phrases ("we typically", "one plant found") with regex

**Injection into the generation prompt:**

The DraftGenerator queries `evidence_registry WHERE is_active=TRUE AND (applicable_sectors IS NULL OR $sector = ANY(applicable_sectors)) AND effective_from <= NOW() AND (expires_at IS NULL OR expires_at > NOW())`. The results are formatted as a JSON `EVIDENCE LIBRARY` block at the top of the prompt with claim ids. The prompt instructs the model to cite ids in `metadata.claim_ids_referenced` and tells it explicitly: claims not in the library are prohibited.

`ANTI_PATTERN` rows are emitted as `prohibited_claims` regex patterns separately.

**Post-generation validation:**

1. **Pass 1 (integrity regex):** The current `_INTEGRITY_RULES` patterns plus all `ANTI_PATTERN` claim_patterns. HARD_REJECT on match.
2. **Pass 2 (quality):** Existing `validate_draft` (subject length, banned phrases, banned characters). HARD_REJECT on errors; WARN on warnings.
3. **Pass 3 (claim grounding):**
   - For every claim_id in `metadata.claim_ids_referenced`, the claim must exist and be active.
   - Body scan: any phrase matching a known `claim_pattern` (`\d+%`, `\d+x`, "one plant found", etc.) must be covered by a claim from the referenced set whose pattern matches. Bare matches with no claim coverage → HARD_REJECT.
4. **Pass 4 (continuity):** body trigram similarity vs prior step bodies and sibling drafts in last 30d. Similarity > 0.7 → HARD_REJECT (repetition); > 0.5 → WARN_AND_QUARANTINE.

**Hard-reject vs quarantine thresholds:**

- HARD_REJECT: never reaches the approval queue. Logged with rejection_reason. Counted in autonomy_decisions for the prompt regression alert.
- WARN_AND_QUARANTINE: enters `DRAFT_READY` with `quarantine_flags` set. Reviewer sees the flagged phrases. Cannot be auto-approved (forces MEDIUM risk minimum).

**Linking approved claims to sent drafts:**

`draft_versions.generation_metadata.claim_ids_referenced` is the audit trail. `claim_validation_results` rows pin each claim_id to a draft_version_id at validation time. A single SQL query joins `send_attempts → outreach_drafts → draft_versions → claim_validation_results → evidence_registry` to retrieve the complete claim chain for any sent message.

**Registry maintenance:**

- New claims added by marketing or research via cockpit "Evidence Library" view
- Every new claim requires a second-user approval before `approved_at IS NOT NULL` is set (the only state in which the claim becomes injectable into prompts)
- Quarterly review surfaces expired and stale claims
- Reviewer feedback (rejection categorized as `fabricated_claim`) emits a `learning_signals` row; the next claim review session sees these surfaced

---

## SECTION J — Worker and Execution Architecture

### J.1 Procfile

```
web:    pip install -r backend/requirements.txt && \
        uvicorn backend.app.api.main:app --host 0.0.0.0 \
          --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'

worker: pip install -r backend/requirements.txt && \
        python -m backend.app.worker.main
```

The `web:` process loses the lifespan scheduler startup. The `worker:` process is new.

### J.2 Advisory-lock startup

```python
# backend/app/worker/main.py
import os, sys, time, logging, hashlib
from apscheduler.schedulers.blocking import BlockingScheduler
from backend.app.core.database import get_supabase_client
from backend.app.worker.jobs import register_all_jobs
from backend.app.worker.send_worker import SendWorker

LOCK_KEY = int(hashlib.sha256(b"prospectiq_worker_v1").hexdigest()[:15], 16) % (2**31)

def main():
    client = get_supabase_client()
    acquired = bool(client.rpc("pg_try_advisory_lock", {"key": LOCK_KEY}).execute().data)
    if not acquired:
        logger.critical("worker_singleton_failed", extra={"lock_key": LOCK_KEY})
        sys.exit(0)   # clean exit; Railway restarts on schedule
    logger.info("worker_singleton_acquired", extra={"lock_key": LOCK_KEY})
    try:
        scheduler = BlockingScheduler(timezone="America/Chicago")
        register_all_jobs(scheduler)
        send_worker = SendWorker()
        scheduler.add_job(send_worker.poll_outbox, "interval", seconds=10,
                          id="send_outbox_poll", max_instances=1, coalesce=True)
        scheduler.start()
    finally:
        try:
            client.rpc("pg_advisory_unlock", {"key": LOCK_KEY}).execute()
        except Exception:
            pass
```

### J.3 Outbound Queue Consumer Loop (pseudocode)

```python
class SendWorker:
    POLL_INTERVAL_S = 10
    LEASE_S = 600

    def poll_outbox(self):
        while True:
            row = self._claim_one()
            if not row:
                time.sleep(self.POLL_INTERVAL_S)
                continue
            try:
                result = self._dispatch(row)
                self._project_result(row, result)
            except Exception as exc:
                self._handle_unexpected(row, exc)

    def _claim_one(self) -> dict | None:
        # Transaction 1: claim
        with db.transaction() as tx:
            row = tx.execute("""
                SELECT * FROM outbound_queue
                WHERE state = 'PENDING' AND available_at <= NOW()
                  AND workspace_id = $1
                ORDER BY priority_score DESC, enqueued_at ASC
                LIMIT 1 FOR UPDATE SKIP LOCKED
            """, self.current_workspace).fetchone()
            if not row:
                return None
            tx.execute("""
                UPDATE outbound_queue SET state='CLAIMED',
                  claimed_at=NOW(), claimed_by_worker=$1,
                  claim_expires_at=NOW() + interval '10 minutes'
                WHERE id=$2
            """, self.worker_id, row.id)
            attempt = tx.execute("""
                INSERT INTO send_attempts (draft_id, outbound_queue_id, workspace_id,
                  attempt_number, state, policy_snapshot_id, context_packet_id)
                VALUES ($1, $2, $3, $4, 'CREATED', $5, $6)
                RETURNING id
            """, row.draft_id, row.id, row.workspace_id,
                 row.attempt_count + 1, row.policy_snapshot_id,
                 self._fresh_packet(row).packet_id).fetchone()
            tx.write_workflow_event('outreach_draft', row.draft_id,
                                     'draft_claimed', 'ENQUEUED', 'SENDING')
        return row

    def _dispatch(self, row):
        # Outside any transaction — provider call is here
        gates = run_gate_stack(self.db, context_packet=self._fresh_packet(row))
        if not gates.passed:
            return DispatchResult.assertion_failure(gates.failed_gate, gates.detail)
        msg = build_message(self.db, row.draft_id)
        try:
            r = ResendAdapter().send(msg, idempotency_key=str(row.draft_id))
            return DispatchResult.success(r.message_id, r.raw)
        except ProviderTransientError as exc:
            return DispatchResult.transient(str(exc))
        except ProviderPermanentError as exc:
            return DispatchResult.permanent(str(exc))

    def _project_result(self, row, result):
        # Transaction 2: project
        with db.transaction() as tx:
            if result.is_success:
                tx.execute("UPDATE send_attempts SET state='DISPATCHED', "
                           "dispatched_at=NOW(), provider_message_id=$1, "
                           "provider_response=$2 WHERE outbound_queue_id=$3",
                           result.message_id, result.raw, row.id)
                tx.execute("UPDATE outbound_queue SET state='SENT', "
                           "completed_at=NOW() WHERE id=$1", row.id)
                tx.execute("UPDATE outreach_drafts SET sent_at=NOW(), "
                           "resend_message_id=$1, lifecycle_state='SENDING' "
                           "WHERE id=$2", result.message_id, row.draft_id)
                tx.execute("INSERT INTO interactions "
                           "(contact_id, company_id, type, source) "
                           "SELECT contact_id, company_id, 'email_sent', "
                           "'send_attempt:' || $1 FROM outreach_drafts WHERE id=$2",
                           result.send_attempt_id, row.draft_id)
                # sequence_step_state advance, contacts.lifecycle_state advance,
                # campaign_threads upsert — all in this transaction
                tx.write_workflow_event('send_attempt', result.send_attempt_id,
                                         'dispatch_succeeded', 'CREATED', 'DISPATCHED')
            elif result.is_transient_failure:
                # back off, retry
                self._backoff_retry(tx, row, result)
            elif result.is_permanent_failure:
                self._move_to_dlq(tx, row, 'PROVIDER_PERMANENT_4XX', result.detail)
            elif result.is_assertion_failure:
                self._move_to_dlq(tx, row, 'ASSERTION_FAILURE', result.detail)
```

### J.4 Failure branches

| Failure | Outbox state | send_attempts state | Action |
|---|---|---|---|
| Transient (5xx, timeout, 429) | PENDING again with `next_attempt_at = NOW() + 5min × 2^attempt` | DISPATCH_FAILED_RETRYABLE | Backoff retry |
| Transient + max_attempts reached | DEAD_LETTER | DISPATCH_FAILED_RETRYABLE then final DISPATCH_FAILED_TERMINAL | DLQ + operator alert |
| Permanent (4xx, invalid email) | DEAD_LETTER | DISPATCH_FAILED_TERMINAL | DLQ + draft regeneration recommended |
| Assertion failure (suppression appeared post-approval) | DEAD_LETTER | ASSERT_FAILED | DLQ; draft cancelled |
| Worker crash post-Resend pre-commit | CLAIMED (zombie) | CREATED (zombie) | Reconciliation: look up by idempotency_key in Resend; if delivered, mark DISPATCHED + outbox SENT; else reset to PENDING |
| DB commit fail post-Resend | Same | Same | Same recovery |

### J.5 Reconciliation Job (orphan claim sweeper + drift detect)

```python
@with_advisory_lock("reconcile_pipeline_state")
def reconcile_pipeline_state():
    # 1. Orphaned claims (worker crashed)
    orphans = db.fetchall("""
      SELECT id, draft_id, claimed_by_worker FROM outbound_queue
      WHERE state = 'CLAIMED' AND claim_expires_at < NOW()
    """)
    for o in orphans:
        with db.transaction() as tx:
            # Check if Resend actually delivered (idempotency_key lookup)
            actual = ResendAdapter().lookup_by_idempotency_key(str(o.draft_id))
            if actual and actual.delivered:
                # The send happened; just need to project
                tx.execute("UPDATE send_attempts SET state='DISPATCHED', "
                           "provider_message_id=$1 WHERE outbound_queue_id=$2",
                           actual.message_id, o.id)
                tx.execute("UPDATE outbound_queue SET state='SENT' WHERE id=$1", o.id)
            else:
                tx.execute("UPDATE outbound_queue SET state='PENDING', "
                           "claimed_at=NULL, claimed_by_worker=NULL, "
                           "claim_expires_at=NULL, attempt_count=attempt_count+1, "
                           "last_error='worker_crash_orphan' WHERE id=$1", o.id)
                tx.execute("UPDATE send_attempts SET state='ASSERT_FAILED', "
                           "terminal_at=NOW(), failure_reason='worker_crash' "
                           "WHERE outbound_queue_id=$1 AND state IN ('CREATED','ASSERTING')",
                           o.id)
            tx.write_workflow_event('outbox', o.id, 'orphan_reset',
                                     'CLAIMED', tx.fetchval(...))
    # 2. Detect-only drifts (the Stage 2 F-series queries)
    # ... write workflow_events with transition='state_drift_detected'
```

### J.6 Job Inventory (KEEP / REDESIGN / REMOVE)

| Job ID | Decision | Concurrency safety |
|---|---|---|
| `health_snapshot` (15m) | KEEP | Idempotent read-only |
| `pipeline_qc` (15m) | KEEP_WITH_GUARD | Advisory lock |
| `send_approved` (cron 8–11) | REDESIGN as `send_outbox_poll` (10s interval) | DB-level FOR UPDATE SKIP LOCKED |
| `process_due` (1h) | KEEP_WITH_GUARD | Advisory lock; reads sequence_step_state |
| `poll_instantly` (6h) | KEEP_WITH_GUARD | Advisory lock |
| `hitl_snoozed` (15m) | KEEP | Idempotent UPDATE |
| `hitl_auto_archive` (1h) | KEEP_WITH_GUARD | Advisory lock |
| `personalization_refresh` (24h) | KEEP_WITH_GUARD | Advisory lock (cost) |
| `jit_pregenerate` (24h) | KEEP_WITH_GUARD | Advisory lock; reads sequence_step_state.due_at |
| `gmail_intake` (15m) | KEEP_WITH_GUARD | Per-mailbox advisory lock |
| `qualification` (15m) | KEEP_WITH_GUARD | Advisory lock |
| `draft_generation` (5m) | KEEP_WITH_GUARD | Advisory lock; calls unified DraftGenerator |
| `weekly_post_send_audit` (Sun 7am) | KEEP | Idempotent |
| `weekly_approval_audit` (Fri 9am) | KEEP | Idempotent |
| `weekly_contact_backup` (Sat 5am) | **REMOVE** | Path doesn't exist on Railway |
| `weekly_signal_scrapers` (Sat 6am) | KEEP_WITH_GUARD | Advisory lock |
| `signal_monitor` (Sun 6am) | KEEP_WITH_GUARD | Advisory lock |
| `reengagement` (Sun 8am) | KEEP_WITH_GUARD | Advisory lock |
| `weekly_cost_summary` (Mon 8am) | KEEP | Idempotent |
| `daily_report` (Mon–Fri 6am) | KEEP | Idempotent |
| `intent_refresh` (5am daily) | KEEP_WITH_GUARD | Advisory lock |
| `bounce_hygiene` (3am daily) | REDESIGN — replaced by suppression event handlers + reconciliation | — |
| NEW: `reconcile_pipeline_state` (4h) | NEW | Advisory lock |
| NEW: `send_outbox_poll` (10s) | NEW | DB FOR UPDATE SKIP LOCKED |
| NEW: `provider_events_processor` (30s) | NEW | Advisory lock |
| NEW: `orphan_claim_sweeper` (5m) | NEW | Advisory lock |

---

## SECTION K — Provider Integration Architecture

### K.1 OutboundProvider interface

```python
from typing import Protocol

class OutboundProvider(Protocol):
    name: str

    def send(self, message: NormalizedMessage, *,
             idempotency_key: str) -> ProviderDispatchResult: ...

    def parse_webhook(self, raw_payload: bytes,
                      headers: dict) -> NormalizedWebhookEvent | None: ...

    def is_healthy(self) -> ProviderHealth: ...

PROVIDERS = {
    'resend': ResendAdapter(),
    'instantly': InstantlyAdapter(),   # warmup only
    'gmail': GmailAdapter(),
}
```

### K.2 Per-provider specs

**Resend (outbound + inbound webhooks):**
- Autonomous: send, parse webhooks for delivered/bounced/complained/opened/clicked, mark provider_events processed
- Forbidden: domain config changes, sender pool edits, API key rotation
- Idempotency key: `outreach_drafts.id` (UUID)
- Webhook dedup: `(provider='resend', external_event_id=data.id)` UNIQUE
- Failure: 5xx → ProviderTransientError → outbox retry; 4xx → ProviderPermanentError → DLQ
- Rate limit: respect Resend headers; on 429 → transient with `available_at = now + Retry-After`

**Instantly (warmup-only per project memory):**
- Autonomous: poll campaign analytics for warmup metrics
- Forbidden: send via Instantly (project memory: Resend = sends, Instantly = warmup only)
- Idempotency: webhook UNIQUE on `(provider='instantly', external_event_id)`
- Single canonical webhook path; the duplicate `webhooks/instantly.py` (or its alias in `routes/webhooks.py`) is unmounted after verifying which URL is configured in Instantly's dashboard

**Gmail (IMAP + Gmail API for reply intake):**
- Autonomous: fetch new unread; mark read after thread_messages INSERT succeeds
- Forbidden: send mail; modify mailbox settings
- Idempotency: per-mailbox-and-message_id UNIQUE on `provider_events`
- Failure: missing credentials → `is_healthy()` returns False; the gmail_intake job logs a structured `mailbox_unreachable` event in workflow_events rather than silently skipping; Slack alert fires after 2 consecutive unhealthy checks
- Rate limit: IMAP serial per account; one mailbox at a time

**Apollo (enrichment):**
- Autonomous: enrich a contact when stale > 30 days; respect per-day quota
- Forbidden: bulk searches via API (operator-initiated via cockpit only)
- Idempotency: `contacts.apollo_id` UNIQUE; per-process `TTLCache(maxsize=5000, ttl=86400)` replaces the unbounded class-level cache
- Webhook dedup: not applicable (Apollo is pull-only for ProspectIQ)
- Failure: 429 → ProviderRateLimited (back off); 5xx → ProviderTransientError; quota exhaustion → ProviderQuotaExhausted with `provider_state.healthy=false`
- Rate limit: `time.sleep(3.5)` between requests preserved; quota tracker in `provider_state`

**ZeroBounce (email verification):**
- Autonomous: verify newly-imported emails; re-verify after 180 days
- Forbidden: bulk verifications without operator initiation
- Idempotency: `email_verifications` table keyed on `(contact_id, provider)`
- Webhook dedup: N/A (synchronous)
- Failure: 429 → ProviderRateLimited; error response → `email_status='error'` + workflow_event
- Rate limit: single sync requests; per-day caps tracked in `provider_state`

---

## SECTION L — Operator Cockpit and Explainability

The operator-facing control plane. Read-side projections over `workflow_events`, `autonomy_decisions`, and live state columns; writes flow through `OrchestrationService`.

**Required views:**

1. **Engine State Dashboard** — what the engine plans to do next:
   - Reads: `outbound_queue WHERE state='PENDING'` ordered by priority; `sequence_step_state WHERE state='PENDING' AND due_at <= NOW() + 24h`; recent `autonomy_decisions WHERE decision IN ('HOLD','BLOCK','ESCALATE')`
   - Actions: open draft detail; manually approve a held draft; lift workspace freeze
2. **Risk Queue** — drafts requiring review, sorted by risk score:
   - Reads: `outreach_drafts WHERE lifecycle_state IN ('DRAFT_READY','UNDER_REVIEW','DUAL_REVIEW_PENDING')` JOIN `latest_risk_scores`
   - Actions: open detail; approve; reject; request override
3. **Traction Monitor** — companies with active engagement:
   - Reads: `companies WHERE lifecycle_state IN ('OUTREACH_ACTIVE','ACTIVE_CONVERSATION')` JOIN active sibling reply history
   - Actions: pause sequence; mark converted; set company hold
4. **Suppression Log** — recent suppression events:
   - Reads: `suppression_events ORDER BY created_at DESC LIMIT 200`
   - Actions: review classifier confidence; manual revoke (operator override)
5. **Sequence Health** — paused/stalled sequences:
   - Reads: `engagement_sequences WHERE lifecycle_state IN ('PAUSED','PAUSED_HUMAN_REPLY','STALLED')`
   - Actions: resume; abandon; jump to step
6. **Provider Health** — webhook intake, delivery rates, errors:
   - Reads: `provider_events` rate by provider + state; `send_attempts` state distribution last 7d; provider `is_healthy()` checks
   - Actions: trigger reconciliation; disable provider
7. **Autonomy Decisions** — log of every autonomous action:
   - Reads: `autonomy_decisions` filterable by workflow + decision + bucket
   - Actions: drill to `context_packet_id` for full explanation
8. **Audit Trail** — operator overrides, force approvals, policy changes:
   - Reads: `workflow_events WHERE actor_type IN ('user','operator_cli')`; `operator_overrides`; `policy_snapshots` history
   - Actions: read-only (full audit)
9. **Dry-Run Mode** — planned actions without executing:
   - Reads: `autonomy_decisions WHERE decision LIKE 'DRY_RUN_%'` from a dry-run worker pass; `outbound_queue` projections
   - Actions: trigger a dry-run pass over the next 24h of queued sends; review the projected actions before flipping live
10. **Quarantine Queue** — drafts held for content review:
    - Reads: `outreach_drafts WHERE lifecycle_state='DRAFT_READY' AND quarantine_flags IS NOT NULL`
    - Actions: register new claim from this draft's body; reject with categorized reason; force-approve with override

Each view loads under 1s by querying the read-side projections, not the event log. The event log is reachable from each view as a "show full history" panel.

---

## SECTION M — Migration Strategy

13 phases. Each phase has a strangler pattern with cutover criteria.

### Phase 0 — Stabilize (in progress)

| Field | Value |
|---|---|
| Objective | Make next send safe without architectural change |
| Schema changes | None |
| Application changes | SEND_ENABLED=false; snapshots; secret verification; replica=1; scripts disabled; quarantine queries |
| Compatibility | System paused; no compatibility surface |
| Data backfill | None |
| Cutover criteria | Stage 3 Section 12.12 hard stop cleared |
| Rollback | Stage 3 Section 12 |
| Complexity | S |
| Dependency | None |

### Phase 1 — Schema Hardening

| Field | Value |
|---|---|
| Objective | Add CHECK, FK, UNIQUE, triggers, the workflow_events/provider_events tables |
| Schema changes | Additive: `outreach_drafts.lifecycle_state` + CHECK; UNIQUE partial index on `(workspace_id, contact_id, sequence_name, sequence_step)` non-terminal; immutability trigger extension on body/subject when sent; `workflow_events`, `provider_events`, `policy_snapshots` tables; first policy_snapshots row capturing current YAML |
| Application changes | Begin dual-writing to `workflow_events` from current code paths (additive). All webhook routes prepended with `provider_events` INSERT-IF-NOT-EXISTS |
| Compatibility | Every existing path works; new writes are best-effort try/except |
| Data backfill | No backfill of workflow_events; `policy_snapshots v1` snapshot |
| Cutover criteria | 0 UNIQUE violations / 7d; 0 illegal UPDATE attempts; `workflow_events` count grows |
| Rollback | DROP constraints, tables; existing code is unaffected |
| Complexity | M |
| Dependency | Phase 0 |

### Phase 2 — Context Packet Creation

| Field | Value |
|---|---|
| Objective | Build ContextPacketBuilder; wire packet into draft generation |
| Schema changes | Additive: `context_packets` table; `outreach_drafts.generation_context_packet_id` FK |
| Application changes | Implement `ContextPacketBuilder.build()`; `DraftGenerator` reads from packet; legacy ad-hoc queries continue as fallback during shadow |
| Compatibility | Packet built in shadow mode for 14 days; comparison alerts logged when shadow recommendations diverge from actual draft outcome |
| Data backfill | None — packet is per-action |
| Cutover criteria | 100% of new drafts have a `generation_context_packet_id`; shadow divergence rate < 5% |
| Rollback | Disable packet wiring; ad-hoc queries remain |
| Complexity | L |
| Dependency | Phase 1 |

### Phase 3 — Provider Events and Workflow Events

| Field | Value |
|---|---|
| Objective | Every webhook hits `provider_events` UNIQUE; every state transition writes `workflow_events` |
| Schema changes | Already added in Phase 1; this phase activates them |
| Application changes | All 5 webhook routes prepended with INSERT-IF-NOT-EXISTS; legacy `process_webhook_event` gated; the duplicate Instantly router unmounted after Instantly URL confirmation |
| Compatibility | Old handlers still run; new dedup layer protects them |
| Data backfill | None |
| Cutover criteria | 0 duplicate `interactions` rows / 7d; legacy `process_webhook_event` unreachable for 7d |
| Rollback | Re-enable legacy handler |
| Complexity | M |
| Dependency | Phase 1 |

### Phase 4 — Outbound Queue and Send Attempts

| Field | Value |
|---|---|
| Objective | Decouple `sent_at` from claim and delivery; introduce transactional outbox |
| Schema changes | `outbound_queue`, `send_attempts`, `dead_letter_queue` tables; `outreach_drafts.body_version_id` FK; `draft_versions` table |
| Application changes | `EngagementAgent._send_approved_drafts` dual-writes legacy `sent_at` AND new tables. Webhook handlers update `send_attempts` AND legacy columns. Reconciliation job detects drift |
| Compatibility | Dual-write; dashboard reads from `sent_at`; analytics begin reading `send_attempts` |
| Data backfill | One `send_attempts` row per existing `outreach_drafts.sent_at IS NOT NULL` with state=DELIVERED; one `draft_versions` row per existing draft |
| Cutover criteria | 14d dual-write, 0 drift; `send_attempts.state='DELIVERED' COUNT` matches legacy daily for 14d |
| Rollback | Drop new write paths; old paths function unchanged |
| Complexity | XL |
| Dependency | Phase 1, 3 |

### Phase 5 — ApprovalService Consolidation

| Field | Value |
|---|---|
| Objective | Single writer to `approval_status='approved'`; 8 legacy paths retired; risk scoring in shadow |
| Schema changes | `approval_attestations`, `risk_scores` tables; `outreach_drafts.approval_attestation_id` FK; CHECK linking lifecycle state to attestation; Postgres role grants |
| Application changes | `ApprovalService` implemented; `POST /api/approvals/{id}/approve` rerouted; `?force=true` returns 410; override two-step endpoints added; `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` rewritten as JWT clients; `review_manifest.approve_manifest` calls `ApprovalService.approve` per draft; `threads.py::approve_and_send` reroutes; risk scorer runs in shadow on every approval |
| Compatibility | 7-day dual-acceptance window with monitoring |
| Data backfill | Backfill `approval_attestations` from existing approvals; placeholders with `is_override=true` for unauthenticated historical |
| Cutover criteria | 100% of new approvals have an attestation row; 0 writes to `approval_status='approved'` from non-svc roles for 14d; risk_scores populated for every approved draft |
| Rollback | Revert role grants; restore old endpoint behavior; attestation rows preserved |
| Complexity | L |
| Dependency | Phase 1, 4 |

### Phase 6 — Worker Process Migration

| Field | Value |
|---|---|
| Objective | APScheduler runs in `worker:` Procfile process; advisory lock; API loses scheduler |
| Schema changes | None |
| Application changes | `backend/app/worker/main.py` added; Procfile updated; `main.py` lifespan loses scheduler startup; Railway config deploys two processes |
| Compatibility | Cut during no-send window (Saturday); brief no-scheduler gap acceptable for non-send jobs |
| Data backfill | None |
| Cutover criteria | `worker:` runs 7d without crash; no "scheduler started" log lines in `web:`; send rate matches prior week |
| Rollback | Revert Procfile |
| Complexity | M |
| Dependency | None (independent of 1–5, run any quiet moment after Phase 4) |

### Phase 7 — Context Intelligence Layer

| Field | Value |
|---|---|
| Objective | ContextPacketBuilder live everywhere; all draft generation, approval evaluation, send-time gates consume packets |
| Schema changes | Already added in Phase 2 |
| Application changes | `ApprovalService` rebuilds packet at approval time; `SendWorker` rebuilds packet at claim time; risk scoring reads from packet |
| Compatibility | Packet is now the only input to messaging + decisions; shadow mode dropped |
| Data backfill | None |
| Cutover criteria | 100% of drafts, approvals, sends reference a `context_packet_id`; ad-hoc query paths removed from code |
| Rollback | Re-enable ad-hoc queries; packet writers retained |
| Complexity | L |
| Dependency | Phase 2, 5 |

### Phase 8 — Messaging Intelligence Layer

| Field | Value |
|---|---|
| Objective | Single `DraftGenerator`; `DraftStrategy` object; step-aware generation; evidence-grounded claims; continuity checks |
| Schema changes | `evidence_registry`, `claim_validation_results`, `draft_quality_results` tables (or activate from Phase 1 additive) |
| Application changes | Delete `backend/app/agents/outreach_agent.py`; `POST /api/outreach/generate*` rerouted; 4-pass validator inline; validator shadow mode 14d before enforcing |
| Compatibility | HTTP path and scheduler path share generator |
| Data backfill | Seed `evidence_registry` from `offer_context.yaml::product_facts`, `outreach_guidelines.yaml::never_include` (anti-patterns), validated case studies |
| Cutover criteria | 100% new drafts have `claim_ids_referenced`; 0% HARD_REJECT pattern in approved; < 5% QUARANTINE rate |
| Rollback | Disable validator (env flag); revert prompt to old form |
| Complexity | XL |
| Dependency | Phase 5, 7 |

### Phase 9 — Orchestration Layer

| Field | Value |
|---|---|
| Objective | `OrchestrationService` live; `DecisionEngine`, `SequenceCoordinator`, `ReplyCoordinator`, `SuppressionCoordinator` |
| Schema changes | `sequence_step_state`, `suppression_events`, `company_holds`, `contact_holds`, `operator_overrides` tables (suppression_events backfilled from suppression_log; 30d dual-write) |
| Application changes | APScheduler ticks become thin callers of orchestrator methods; webhook handlers route through ReplyCoordinator; `webhooks._handle_email_bounced` delegated to SuppressionCoordinator |
| Compatibility | Old handlers wired in dual-mode for 30 days; legacy `companies.status='bounced'` write deleted |
| Data backfill | `suppression_events` from `suppression_log`; `sequence_step_state` from `outreach_drafts` history |
| Cutover criteria | 0 legacy `companies.status='bounced'` writes / 7d; `sequence_step_state` count consistent with `outreach_drafts` sent_at history |
| Rollback | Re-enable legacy handlers; coordinators stay as no-ops |
| Complexity | XL |
| Dependency | Phases 3, 4, 5, 7 |

### Phase 10 — Evidence Registry and Claim Governance

| Field | Value |
|---|---|
| Objective | Generation grounded; validator integrated; auto-quarantine for unregistered claims |
| Schema changes | Activate `evidence_registry` writes; `claim_validation_results` |
| Application changes | Generator prompt construction injects only registered claims; validator runs pass 3 (claim grounding) in enforcing mode; cockpit "Evidence Library" view |
| Compatibility | Validator runs in shadow for 14d after Phase 8 cutover, then enforcing |
| Data backfill | Validate seeded registry against last 30 days of approved drafts; flag drafts that wouldn't pass for retroactive review |
| Cutover criteria | 100% of new drafts cite valid claim_ids OR have no claims; HARD_REJECT pattern coverage = 100% of body content; reviewer feedback rate < 10% rejection |
| Rollback | Disable pass 3 enforcement (env flag); registry persists |
| Complexity | L |
| Dependency | Phase 8 |

### Phase 11 — Operator Cockpit

| Field | Value |
|---|---|
| Objective | All 10 dashboard views live; dry-run mode; audit viewer; quarantine queue |
| Schema changes | None (read-side over existing tables) |
| Application changes | Frontend dashboard views; backend API endpoints for each view; dry-run worker mode (env `DRY_RUN=true`) |
| Compatibility | Cockpit additive; doesn't change engine behavior |
| Data backfill | None |
| Cutover criteria | All 10 views loaded under 1s; operators using cockpit for approvals 100% (no direct DB access) |
| Rollback | Hide views; engine unaffected |
| Complexity | L |
| Dependency | Phase 9 |

### Phase 12 — Risk-Based Autonomy

| Field | Value |
|---|---|
| Objective | LOW bucket auto-approve; MEDIUM to queue; HIGH to dual review; risk scoring validated on 30d shadow |
| Schema changes | None (risk_scores already in place from Phase 5) |
| Application changes | `ApprovalService.intake(draft_id)` runs scorer + validator; routes by bucket; LOW drafts get `actor_type='system'` attestation |
| Compatibility | 30-day shadow validation before any auto-approval; comparison against human decisions tracked in `autonomy_decisions` |
| Data backfill | None |
| Cutover criteria | Shadow-actual concordance > 95% for LOW bucket; reviewer queue depth halves; 0 LOW auto-approved drafts cause downstream issues |
| Rollback | Disable auto-approval (env flag); all drafts route to human |
| Complexity | M |
| Dependency | Phases 5, 8, 10 |

### Phase 13 — Full Governed Autonomy

| Field | Value |
|---|---|
| Objective | All guardrails in place; most workflows autonomous; HITL only for high-risk, positive replies, and overrides |
| Schema changes | Final triggers in enforcing mode (Phase 1 triggers were shadow until now) |
| Application changes | Triggers enforce all state-transition guards; ad-hoc queries removed |
| Compatibility | Strangler complete |
| Data backfill | Final reconciliation pass: any rows that would violate enforcing triggers flagged for operator review before activation |
| Cutover criteria | 14d enforcing mode with 0 trigger violations; HITL queue depth steady-state matches design assumption (positive replies + overrides only) |
| Rollback | Triggers to advisory mode; per-component disable possible |
| Complexity | XL |
| Dependency | Phases 1–12 |

---

## SECTION N — Current Capability Gap Assessment

| Capability | Exists? | Fragmented? | Missing? | Current Asset | Gap | Recommendation |
|---|---|---|---|---|---|---|
| Company research intelligence | YES | NO | — | `research_intelligence`, Perplexity agent | Stale refresh policy informal | Promote to scheduled `research_refresh` reading from policy snapshot |
| Contact enrichment | YES | NO | — | `enrichment.py`, Apollo adapter | Unbounded cache | TTLCache fix in adapter |
| Signal monitoring | PARTIAL | YES | — | `signal_monitor.py`, `signal_scrapers/` | No unified `learning_signals` table | Surface signals into Context Intelligence via `learning_signals` |
| Prior message awareness | NO | YES | YES | Reconstructed ad hoc per caller | No unified accessor | `ContextPacket.prior_messages` |
| Suppression management | YES | YES | — | `suppression_log`, 3 writers | Single-writer needed | `SuppressionCoordinator` + `suppression_events` |
| Sequence orchestration | YES | YES | — | `engagement_sequences`, implicit step state | No explicit step state | `sequence_step_state` + `SequenceCoordinator` |
| Reply classification | YES | NO | — | `reply_classifier.py` | Auto-action wiring partial | Wire through `ReplyCoordinator` with disposition table |
| Draft approval workflow | YES | YES | — | `approvals.py::approve_draft` | 8 writers; no attestation enforcement | `ApprovalService` (Phase 5) |
| Content validation | PARTIAL | NO | YES | Integrity regex + `validate_draft` heuristics | No claim grounding | 4-pass validator + `evidence_registry` (Phase 8, 10) |
| Context intelligence (context packet) | NO | NO | YES | None | Foundational gap | `ContextPacketBuilder` (Phase 2, 7) |
| Messaging intelligence (draft strategy) | PARTIAL | YES | YES | 2 `OutreachAgent` classes | No DraftStrategy object; HTTP path bypasses gates | Single `DraftGenerator` + `DraftStrategy` (Phase 8) |
| Orchestration authority | NO | YES | YES | Logic scattered across agents | No single decision authority | `OrchestrationService` (Phase 9) |
| Provider abstraction layer | NO | YES | YES | Direct SDK calls in 3 places | No adapter | `OutboundProvider` (Phase 4) |
| Lifecycle event log | PARTIAL | YES | — | `interactions` (non-transactional) | Not authoritative | `workflow_events` (Phase 1) |
| Dry-run / simulation mode | NO | NO | YES | None | No simulation surface | `DRY_RUN=true` mode + `autonomy_decisions` SHADOW prefix |
| Operator cockpit | PARTIAL | YES | — | `/api/approvals/*`, dashboards | No unified explanation view | Cockpit redesign (Phase 11) |
| Evidence registry | NO | NO | YES | `offer_context.yaml`, `never_include` list | No DB-backed registry | `evidence_registry` (Phase 10) |
| Risk scoring | NO | NO | YES | None | No score, no buckets | `RiskScoringService` (Phase 5) |
| Learning loop | PARTIAL | YES | — | `outreach_edit_feedback` | No surfacing back to generator | `learning_signals` table + Context Intelligence integration |

---

## SECTION O — Build vs Defer

| Item | Tier | Rationale |
|---|---|---|
| `workflow_events` table + dual-write | MUST_BUILD_NOW | Foundation for every other phase's audit; cheap; reversible |
| `provider_events` idempotent webhook intake | MUST_BUILD_NOW | Already double-counting opens/clicks; corrupts analytics |
| UNIQUE on `outreach_drafts(workspace_id, contact_id, sequence_name, sequence_step)` non-terminal | MUST_BUILD_NOW | Closes duplicate-draft race; single SQL line |
| Body/subject immutability trigger post-send | MUST_BUILD_NOW | Closes audit hole exploited by operator scripts |
| `ApprovalService` single writer | MUST_BUILD_NOW | Governance bypass surface is too large |
| Worker Procfile + advisory lock | MUST_BUILD_NOW | Multi-replica deploys are unsafe; small change |
| `send_attempts` + `outbound_queue` | MUST_BUILD_NOW | Decouples claim from delivery; eliminates orphan-on-rollback |
| `ContextPacketBuilder` | MUST_BUILD_NOW | The substrate for everything that follows |
| Single `DraftGenerator` (delete second OutreachAgent) | MUST_BUILD_NOW | HTTP path bypassing gates is a live exposure |
| `RiskScoringService` (shadow first) | BUILD_SOON | Required for risk-based autonomy; can run in shadow without affecting current behavior |
| `evidence_registry` + claim grounding | BUILD_SOON | Eliminates fabricated claims; brand risk reduction |
| `OrchestrationService` centralization | BUILD_SOON | Cleans up scattered state mutations |
| `SuppressionCoordinator` single writer | BUILD_SOON | Closes 3-writer drift |
| Operator cockpit redesign | BUILD_SOON | Operator productivity; cuts approval queue noise |
| Dry-run mode | BUILD_SOON | De-risks every later cutover |
| Multi-tenant DB-per-tenant | LATER | Current RLS adequate; would multiply ops surface |
| Celery + Redis | LATER | Procfile + advisory lock sufficient at scale; revisit at 10k sends/day |
| Real-time analytics dashboard | LATER | Daily reports adequate; streaming layer unnecessary |
| Customer-facing API (B2B) | LATER | No paying external developer dependencies yet |
| Self-service workspace onboarding | LATER | One workspace today |
| Kafka or any stream platform | NOT_YET | < 1k events/day; outbox pattern is sufficient |
| Microservices split | NOT_YET | Module + role boundaries enforce isolation; network split adds operational surface with no governance gain |
| Temporal | NOT_YET | Workflows are short and DB-durable; outbox covers retries |
| Event-sourced CQRS rewrite | NEVER_AT_THIS_SCALE | `workflow_events` is event LOG, not source; projection rebuild is multi-month for marginal benefit |
| Custom workflow DSL / rules engine | NEVER_AT_THIS_SCALE | YAML + policy snapshot suffices; adding DSL costs debuggability |
| ML-based reply classifier beyond Claude | NEVER_AT_THIS_SCALE | Existing Claude classifier works; no training data to beat it |
| Multi-region deployment | NEVER_AT_THIS_SCALE | Latency bottleneck is providers, not multi-region |

---

## SECTION P — Final Recommendation

**1. What is the right core architecture?**
A monolithic Python application on Postgres with two processes: `web:` (FastAPI) and `worker:` (advisory-locked APScheduler). Eight logical layers in code: Data Foundation, Context Intelligence, Messaging Intelligence, Governance and Policy, Orchestration, Execution, Feedback and Learning, Operator Control. Every action is preceded by a fresh `ContextPacket` and a fresh `PolicyDecision`; every state transition is single-writer through `OrchestrationService` and writes to `workflow_events`. Module boundaries enforced by Postgres roles, not by network. No microservices, no Kafka, no Temporal.

**2. What are the highest-risk current gaps?**
(1) `sent_at` overloaded as claim and delivery indicator with no transactional boundary — orphan drafts on rollback, silent projection failures. (2) Eight independent writers to `approval_status='approved'` with no schema enforcement of attestation — governance bypass is one query parameter away. (3) APScheduler in-process across replicas with no singleton guard — every concurrency safety depends on operational discipline alone.

**3. What should be built first?**
Phase 1 (Schema Hardening) and Phase 2 (Context Packet) in parallel — they unblock every later phase. Within Phase 1: UNIQUE on draft step, body immutability trigger, `workflow_events` and `provider_events` tables, `policy_snapshots v1`. Within Phase 2: `ContextPacketBuilder` writes to `context_packets`; shadow-compare against current behavior. Total: ~3 weeks of focused work.

**4. What can be preserved?**
The entire data substrate: `companies`, `contacts`, `research_intelligence`, `engagement_sequences`, `campaign_threads`, `thread_messages`, `outreach_drafts` row IDs, `suppression_log` (until 30-day migration to `suppression_events`), `send_assertions`, `outbound_eligible_contacts`, Apollo enrichment cache, ZeroBounce verifications, sender pool reputation, in-flight conversations, all sequence definitions, all outreach guidelines, all customer traction history. Nothing client-facing changes.

**5. What should be retired?**
The second `OutreachAgent` in `backend/app/agents/outreach_agent.py` (delete file). `EngagementAgent.process_webhook_event` static method. `pace_limiter.CAMPAIGN_DEFAULTS`. `workspaces.settings.daily_send_limit` JSONB key. `limits.yaml::outreach.daily_send_limit`. The `?force=true` parameter. Module-level `COMPANY_COOLDOWN_DAYS=14` legacy alias. One of the two Instantly webhook routers. `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` rewritten as JWT clients (the substantive logic survives in `ApprovalService`).

**6. How do we maximize autonomy safely?**
By inverting the current model: most actions autonomous by default, gated by enforceable invariants and Context Packets; HITL where structurally required. The mechanism: `RiskScoringService` computes a 16-dimension score from the packet; LOW bucket auto-approves with `actor_type='system'` attestation; MEDIUM routes to a fast human queue; HIGH requires dual review; BLOCKED requires override. Safety comes from the schema (CHECK + FK + trigger + role grants), not from human gating volume.

**7. How do we prevent disjointed outreach?**
Every action consumes a `ContextPacket` whose `prior_messages`, `sibling_contact_history`, `reply_history`, `prohibited_claims`, and `active_conversation` fields are computed fresh. Step-2 drafts receive step-1's `primary_angle` as a prohibition. Sibling positive replies force the draft to `HOLD_FOR_HUMAN_REVIEW`. Validator pass 4 catches trigram repetition. The packet is pinned at generation, approval, and send — drift between the three is itself a signal.

**8. How do we make the engine explainable?**
Three linked tables answer every "why did this happen" question: `context_packets` (what the system knew), `autonomy_decisions` (what the engine concluded and why, per gate), `workflow_events` (what actually transitioned). The operator cockpit's Audit Trail view shows any sent email's full chain in one query. Risk scores carry `triggered_dimensions` so the operator sees "this draft scored MEDIUM because traction_signal=WARM (12 pts) + sequence_step=3 (8 pts) + ...". Force approvals require categorized reasons stored in `operator_overrides`.

**9. Minimum architecture for 50 sends/day?**
Phases 0–6: stabilize + schema hardening + context packets + workflow_events + outbound_queue + send_attempts + ApprovalService + worker process. The rest (evidence registry, full orchestration, cockpit redesign, risk-based autonomy, state-machine enforcement) can ride along but the system is safe to scale to 50/day after Phase 6. Estimated 6–8 weeks of focused engineering.

**10. Architecture for 500 sends/day?**
All 13 phases. The increments that matter past 50/day: (a) the validator must be enforcing (Phase 10) — manual review of 500/day's worth of unregistered-claim drafts is intractable; (b) risk-based autonomy live (Phase 12) — LOW bucket auto-approval keeps reviewer load constant; (c) operator cockpit (Phase 11) — drift, queue depth, and provider health visibility become operationally mandatory; (d) orphan-claim sweeper + DLQ alerts (Phases 4, 9) — at 500/day, one orphan per week is one missed reply per week. Estimated 16–22 weeks total from today; the marginal cost from 50 to 500 is ~10–14 weeks of additional work on Phases 7–13.

