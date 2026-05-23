# ProspectIQ VNext — Canonical Architecture Doctrine

**Version 1.0 | 2026-05-14**
**Author: Avanish Mehrotra & Digitillis Architecture Team**
**Status: Architectural Reference | Not an Implementation Plan**

---

## Preamble

This document defines the canonical architecture for ProspectIQ as a governed engagement workflow engine. It is the architectural reference point for all future engineering decisions. It is not a sprint plan, not a backlog, and not a feature list.

Everything in this document should be read as a set of durable architectural commitments — decisions about what the system fundamentally is, how it should be structured, and what principles should govern every future engineering choice.

Where the current system departs from this architecture, that departure represents known technical debt to be resolved in a controlled, phased manner. It does not represent a contradiction.

---

## Part I — Core Architectural Philosophy

### What ProspectIQ Fundamentally Is

ProspectIQ is a **governed engagement workflow engine**.

This is not a marketing statement. It is an architectural statement. Every word matters.

**Governed**: Every consequential action in the system — sending a message, advancing a workflow step, generating a draft, suppressing a contact — occurs within an explicit governance envelope. Policies evaluate before actions execute. Decisions are explainable. Audit trails are structural, not afterthoughts.

**Engagement**: The system's domain is the *relationship* between a workspace and its prospect universe, not the mechanics of email delivery. The email is a side effect. The relationship is the subject.

**Workflow**: The durable unit of work is not a message. It is a **workflow** — a governed sequence of steps that advance a prospect from first contact toward a business outcome, across time, across channels, and subject to real-world signals. A draft is a step in a workflow. An approval is a checkpoint in a workflow. A bounce is a signal that alters a workflow.

**Engine**: The system should *run* these workflows, not merely *support* humans running them. Autonomous advancement, policy evaluation, signal processing, and context assembly happen without human intervention. Human judgment is invoked at defined checkpoints, not as the primary operational mechanism.

This framing changes everything downstream. The question is never "did we send this email?" The question is always: "is this workflow advancing correctly, with appropriate governance, toward a good outcome?"

### What the System Optimizes For

ProspectIQ optimizes for four things, in order:

1. **Signal quality per send.** One well-timed, well-contextualized, well-governed message that reflects genuine understanding of the recipient is worth more than ten generic sends. The architecture must make high-quality context assembly easier than low-quality shortcutting.

2. **Governance integrity.** Every send must be traceable to a policy disposition, a human attestation (where required), and a context packet. The system must be able to answer "why was this sent?" from DB records alone, without consulting logs or human memory.

3. **Operational transparency.** A small team should be able to understand the full state of the system at any moment. No black boxes, no hidden state, no decisions that cannot be explained. This is a competitive advantage at this scale, not a constraint.

4. **Resilience over throughput.** At 50–500 sends/day, the cost of a partially failed state that corrupts data or produces phantom sends is far higher than the cost of a slower, more conservative execution model. Correctness before performance.

### What the Architectural Center of Gravity Must Be

The architectural center of gravity is **PostgreSQL-as-workflow-substrate**.

All workflow state, all governance decisions, all context packets, all policy evaluations, all send attempts, all engagement signals, and all audit events are persisted in PostgreSQL. No workflow state lives in process memory, in Redis, or anywhere else that cannot be queried, introspected, and recovered from.

This is not a constraint imposed by the current infrastructure. It is an architectural principle. PostgreSQL's transactional guarantees — the ability to advance workflow state and enqueue a send in the same transaction, atomically — are the foundation of the durable execution model. These guarantees cannot be replicated across systems without introducing distributed coordination problems that are entirely inappropriate at this scale.

The corollary: **if you cannot express a workflow invariant as a PostgreSQL constraint or query, it is not an invariant yet.**

### What Must Explicitly NOT Become Part of the Architecture

The following should be treated as active architectural risks, not potential enhancements:

**Distributed message brokers** (Kafka, RabbitMQ, SQS as primary workflow bus). At 50–500 sends/day, the operational overhead of a message broker exceeds any benefit. PostgreSQL's `SELECT FOR UPDATE SKIP LOCKED` is a sufficient and far more observable queue mechanism.

**Workflow orchestration engines** (Temporal, Airflow, Prefect). The workflow state machine in ProspectIQ is not complex enough to justify an external orchestration dependency. A Temporal cluster requires dedicated operational expertise, introduces new failure modes, and obscures the system state behind a proprietary model. Build the orchestration in PostgreSQL.

**Microservice decomposition**. The system is operated by a team that cannot afford the operational surface area of distributed services, network partitions, and service meshes. The monolith is a virtue. Decompose only when a module's operational requirements (SLA, scaling, team boundary) genuinely require it.

**ML training pipelines in the execution path**. The system uses LLMs for draft generation, not ML inference. Treating draft generation as a prediction problem requiring training pipelines leads to premature ML infrastructure investment that delivers no practical benefit at this scale.

**Event sourcing maximalism**. Full CQRS with event-sourced projections for every entity requires significant rebuild complexity and operational discipline that is not justified here. A hybrid model — mutable current-state tables for frequently-queried state, append-only event records for significant decisions — is architecturally sufficient and far more accessible.

---

## Part II — Canonical Runtime Architecture

The ProspectIQ runtime is organized into seven layers. These layers are not microservices. They are logical separation within a single deployed monolith. Each layer has a defined responsibility, a defined interface with adjacent layers, and a defined relationship to the DB schema.

```
+--------------------------------------------------------------------+
|                         SIGNAL LAYER                               |
|  Ingest, normalize, and record real-world events                   |
+--------------------------------------------------------------------+
|                      INTELLIGENCE LAYER                            |
|  Assemble context; understand what is known about prospects        |
+--------------------------------------------------------------------+
|                      GOVERNANCE LAYER                              |
|  Evaluate policy; produce dispositions; manage attestation         |
+--------------------------------------------------------------------+
|                     ORCHESTRATION LAYER                            |
|  Advance workflows; manage draft lifecycle; schedule actions       |
+--------------------------------------------------------------------+
|                      EXECUTION LAYER                               |
|  Durable outbox; send attempts; retry; reconciliation              |
+--------------------------------------------------------------------+
|                       DELIVERY LAYER                               |
|  Channel adapters; provider abstraction; outcome normalization     |
+--------------------------------------------------------------------+
|                        MEMORY LAYER                   (horizontal) |
|  Operational memory; context persistence; traction state           |
+--------------------------------------------------------------------+
```

The **Memory Layer** is horizontal — it underpins all other layers and is read from and written to by every layer. It is not a service; it is a set of DB tables and the conventions governing how they are accessed.

### Layer 1: Signal Layer

**Responsibility**: Receive raw events from the outside world, normalize them into canonical internal event records, and trigger downstream processing.

**Inputs**: Resend webhooks (delivered, opened, clicked, bounced, complained), IMAP replies, provider-specific status callbacks, manual administrative events.

**Output**: `provider_events` records (immutable, raw), and derivative `workflow_events` records (normalized, canonical).

**Key behaviors**:
- Idempotent ingestion. Every provider event carries a provider-assigned ID. Duplicate delivery is expected and handled gracefully via unique constraint on the provider event ID.
- Normalization decouples signal semantics from provider semantics. The rest of the system never interprets a Resend-specific payload. It interprets a normalized `EMAIL_OPENED` event.
- Signals immediately update engagement state in the Memory Layer. This is the only point where engagement state is written.

**What this layer does NOT do**: make decisions, evaluate policies, or advance workflow state. It records and normalizes, nothing more.

### Layer 2: Intelligence Layer

**Responsibility**: Assemble Context Packets for contacts. Maintain operational memory per contact and company. Provide grounded, evidence-linked intelligence to the Orchestration and Governance layers.

**The canonical unit of this layer is the Context Packet.** A Context Packet is a point-in-time, purpose-specific snapshot of everything the system knows about a contact and their company that is relevant to a specific outreach action. It is not a streaming feed, a vector embedding, or a model input blob. It is a structured record with explicit provenance for every field.

**Inputs**: Memory Layer (contact profile, company profile, prior interactions, engagement state, traction state, policy context, workspace profile).

**Output**: `context_packets` records in the DB (persisted, TTL-governed, linked to workspace + contact + draft).

**Key behaviors**:
- Every field in a Context Packet traces to a source record. There are no hallucinated enrichment claims.
- Context Packets are assembled in shadow mode first (no production path dependency) and promoted to the production path only when the intelligence layer has demonstrated stability.
- Context Packets have TTLs. Stale intelligence is not surfaced as current.
- The layer produces warnings (never silent failures) for missing enrichment, low-confidence signals, or policy-gated fields.

**What this layer does NOT do**: evaluate whether a send should happen, generate draft content, or manage workflow state.

### Layer 3: Governance Layer

**Responsibility**: Evaluate policies against a proposed action and produce an explicit **disposition**. Manage the approval lifecycle. Capture attestations.

**The canonical output of this layer is a Disposition**: a structured record that says — for a given (workspace, contact, draft, action, timestamp) — whether the action is `ALLOW_AUTONOMOUS`, `REQUIRE_APPROVAL`, `BLOCK_TEMPORARY` (with reason and suggested `retry_after`), or `BLOCK_PERMANENT` (with reason).

**Policy evaluation is a decision chain**, not a flat rule list. The chain evaluates in order:
1. Hard suppression (permanent; always wins; short-circuits everything)
2. Temporary suppression (time-bounded; evaluated against current timestamp)
3. Company traction gate (does a sibling signal require pausing this contact?)
4. Send window (workspace-defined timing preferences)
5. Contact frequency guard (is this contact being contacted too often?)
6. Workspace quota guard (daily/weekly send budget)
7. Approval requirement evaluation (does this sequence/workspace require HITL?)

The chain terminates at the first blocking disposition. The first `ALLOW_AUTONOMOUS` that reaches step 7 without a block produces an autonomous send authorization.

**Policy snapshots are immutable at decision time.** When a governance decision is recorded, the policy state that governed it is captured as a `policy_snapshot` linked to the decision. Retroactive policy changes do not alter historical decisions. This is not optional behavior — it is the foundation of the audit architecture.

**Attestation** is the structured capture of a human approval decision. When a reviewer approves a draft, they attest to four things: content accuracy, recipient appropriateness, timing appropriateness, and policy compliance. This attestation is a DB record, linked to the draft, the reviewer, and the policy snapshot under which it was issued. It is immutable.

**What this layer does NOT do**: generate content, assemble context, or advance workflow state.

### Layer 4: Orchestration Layer

**Responsibility**: The state machine for engagement workflows. Determines what step should execute next. Evaluates gates (policy, signal, timing, sibling traction). Manages the draft lifecycle from generation through approval.

**The workflow** is the canonical unit of work. A workflow is scoped to a (workspace, contact, sequence). It has an explicit current state, a history of past states (event log), and a defined set of transitions.

**Workflow advancement** is triggered by:
- Time (the scheduler evaluates workflows ready to advance based on timing rules)
- Signal (an inbound engagement event — reply, open, bounce — triggers re-evaluation of affected workflows)
- Human action (approval, rejection, manual pause) — transitions the workflow immediately

**The scheduler is the heartbeat of the orchestration layer.** It runs as a set of idempotent jobs that evaluate the current DB state and advance anything that is ready. Jobs are safe to run twice. There is no persistent process that holds workflow state between scheduler ticks.

**Sibling traction** is a first-class orchestration concept. When one contact at a company reaches a high-engagement state (clicked, replied), the orchestration layer can pause or modify the workflows of other contacts at the same company. This avoids spamming a warm account. The mechanic: a company traction signal updates the `company_traction_state` projection, which the governance layer reads during policy evaluation for affected contacts.

**The draft lifecycle** is managed entirely within this layer. Generation is requested here. Context Packets are assembled and linked here. The approval gate is structured here. Approval/rejection transitions are processed here.

**What this layer does NOT do**: make delivery calls, interact with providers, process raw webhooks.

### Layer 5: Execution Layer

**Responsibility**: Ensure every authorized send attempt is durably recorded, executed, retried on failure, and reconciled against provider state.

**The core pattern is the transactional outbox.** When a draft is approved and authorized for sending:
1. An `outbound_queue` row is inserted **in the same transaction** as the approval event.
2. The scheduler picks up queue rows using `SELECT FOR UPDATE SKIP LOCKED`.
3. A `send_attempt` record is created with status `DISPATCHED`.
4. The delivery call is made.
5. On success: the send attempt is marked `DELIVERED`, the draft `sent_at` is set, the queue row is removed.
6. On transient failure: the send attempt is marked `FAILED`, a retry is scheduled with exponential backoff.
7. On permanent failure: the send attempt is marked `PERMANENTLY_FAILED`, the draft is marked accordingly, no retry.

**The send attempt is the authoritative record of every delivery action.** It is append-only. The most recent send attempt record for a draft is the ground truth for current delivery status.

**Reconciliation** runs as a separate scheduled job. It identifies send attempts that have been in `DISPATCHED` state beyond a defined timeout and queries the provider API to determine actual status. This handles the case where the in-process delivery call succeeded but the response was lost.

**Idempotency keys** are generated before the delivery call and stored on the send attempt. If a retry occurs, the same idempotency key is used. Provider-level deduplication (where supported) prevents double-sends.

**Dead-letter handling**: send attempts that exhaust all retry budget are moved to `dead_letter_queue`. A daily reconciliation report surfaces dead-letter items for manual review. No automatic requeue.

**What this layer does NOT do**: evaluate governance, assemble context, or interact with the orchestration state machine.

### Layer 6: Delivery Layer

**Responsibility**: The channel adapter interface. Translates a canonical "send this content to this contact via this channel" instruction into provider-specific mechanics, and normalizes the outcome back into canonical form.

**The key design principle**: the Orchestration and Execution layers never know which channel they are operating on. They issue canonical delivery instructions. The Delivery Layer resolves those instructions to the appropriate channel adapter.

**A Channel Adapter** is a module that:
- Accepts a canonical delivery instruction (contact profile + content + channel hint + metadata)
- Executes the provider-specific send mechanics
- Returns a canonical outcome (dispatched, failed, rate-limited, etc.)
- Is registered in a **Channel Manifest** that declares its capabilities and constraints (rate limits, content format requirements, auth requirements, consent requirements)

The Channel Manifest is the metadata that lets the Orchestration Layer reason about channel selection and sequencing without embedding channel-specific logic.

**Currently**: one adapter (Resend/email).
**Future**: LinkedIn, SMS, voice — each as a self-contained adapter, not a fork of the orchestration logic.

### Layer 7 (Horizontal): Memory Layer

**Responsibility**: The persistent substrate of accumulated intelligence. Maintains operational memory for contacts, companies, and workspaces. Serves as the read layer for all Intelligence and Orchestration operations.

**The Memory Layer is not a service.** It is a set of DB tables with clear ownership semantics:

- `contact_operational_memory` — what has been said to this contact, what they engaged with, what generated drafts have said, prior interaction history
- `company_traction_state` — a projection of all engagement signals across all contacts at a company, rolled up into a traction level and supporting metadata
- `workspace_profile` — accumulated understanding of the workspace's preferences, style patterns, and effective outreach signals
- `context_packet_cache` — persisted Context Packets (TTL-governed, used for draft generation and audit)

**Operational memory evolves over time.** Each signal event updates the relevant memory entries. Each draft generation writes a summary of what was said into the contact memory. Each approval or rejection is annotated into memory as a signal of quality.

**Operational memory is not training data.** It is retrieved at query time, not used to update model weights. The LLM receives operational memory as structured context in the prompt. The system does not train its own models.

---

## Part III — Canonical State Model

### Draft Lifecycle

The draft is the primary artifact in the system. Its lifecycle defines the state machine most visible to users.

```
PENDING
  |
  +--[edit]--------------------> PENDING      (idempotent loop)
  |
  +--[reject]------------------> REJECTED     (terminal; slot freed for re-draft)
  |
  +--[approve]-----------------> APPROVED
                                    |
                                    +--[enqueued in outbox]--> QUEUED
                                                                  |
                                                        [dispatch by scheduler]
                                                                  |
                                                                  +--> DISPATCHED
                                                                  |        |
                                                           [provider success]
                                                                  |        |
                                                                  +--> SENT    (content immutable)
                                                                             |
                                                                   [engagement signals]
                                                                             |
                                                                      SENT + metadata

                                                  [provider failure]
                                                          |
                                                    SEND_FAILED
                                               (retry or dead-letter)
```

**Immutability rule**: `body` and `subject` are frozen the moment `sent_at` is set. All subsequent updates to a SENT draft are limited to delivery metadata (resend_message_id, resend_status) and engagement metadata (opened_at, clicked_at, etc.). This is enforced at the DB trigger layer (already live).

**Authoritative state owner**: `outreach_drafts` table.

**Recoverability**: If a draft is QUEUED and the process crashes before dispatch, the queue row remains and will be picked up on next scheduler tick. If a draft is DISPATCHED and the process crashes before confirmation, the reconciliation job will determine actual status and reconcile.

### Contact Engagement Lifecycle

Contact engagement is a **projection**, not a state machine with explicit transitions. It is derived from the ordered sequence of `workflow_events` for a contact. There is no `engagement_status` column that is managed as a state field; there is a `contact_engagement_summary` projection table that is derived from events and refreshed on signal ingestion.

Engagement levels (a bounded set, workspace-configurable):
- `NONE` — no outreach yet
- `OUTREACH_INITIATED` — first draft sent
- `WARM` — opened or clicked
- `HOT` — replied or meeting link clicked
- `UNRESPONSIVE` — sent, no engagement beyond defined lookback window
- `SUPPRESSED` — bounce, complaint, or unsubscribe (terminal unless overridden)

**Recoverability**: the engagement summary can be fully rebuilt from `workflow_events` at any time. It is a projection, not a source of truth.

### Company Traction Lifecycle

Company traction is also a **projection**, derived from all engagement events across all contacts at a company. It is the aggregate signal that influences orchestration decisions for all contacts at that company.

Traction levels:
- `COLD` — no engagement from any contact
- `ACTIVE` — at least one contact has been sent to
- `WARM` — at least one contact has opened or clicked
- `HOT` — at least one contact has replied or booked
- `CHAMPION_IDENTIFIED` — a specific contact designated as the highest-traction signal (informational, not derived automatically)

**The traction level is read by the Governance Layer during policy evaluation.** A company at `HOT` traction may trigger a hold on new drafts for other contacts at the same company, pending human review of how to coordinate the account.

### Suppression Lifecycle

Suppression is **append-only** from a record-creation perspective, but has mutable effective state:

```
ACTIVE (blocks all sends; evaluated first in policy chain)
  |
  +--[TTL expiry]--------------> EXPIRED    (system marks expired; slot re-opens)
  |
  +--[manual override]---------> OVERRIDDEN (requires audit trail + justification)
  |
  +--[never expires]-----------> PERMANENT  (bounce/unsubscribe/complaint)
```

`PERMANENT` suppressions are never automatically lifted. An override requires explicit human action with justification captured in the audit record. This is a governance invariant.

### Policy Evaluation Lifecycle

Policy evaluation is **per-action** (not per-contact or per-workflow). For every proposed send:

1. Evaluation is triggered by the Orchestration Layer
2. The Governance Layer runs the decision chain
3. A `governance_decision` record is written (append-only)
4. The linked `policy_snapshot_id` captures the policy state at decision time
5. The disposition is returned to the Orchestration Layer

Governance decisions are immutable. They cannot be retroactively modified. If a policy changes after a decision is made, the historical decision reflects the policy at the time it was made.

---

## Part IV — Orchestration Model

### How Workflows Advance

Workflow advancement is **event-driven at the trigger, deterministic at the evaluation**. The orchestration layer does not run a continuous process that holds workflow state. Instead:

- A trigger event arrives (time-based via scheduler, signal-based via webhook, or human-action-based via API)
- The orchestration layer evaluates the **current state** of all affected workflows from DB
- For each workflow that is ready to advance, it evaluates the advancement conditions
- If conditions are met, it writes the new workflow state atomically with any side effects (e.g., requesting a new draft)

**This means the orchestration model is stateless at the process level.** The DB is the workflow state machine. Any scheduler tick that evaluates a workflow produces the same result as any other scheduler tick, given the same DB state. This is the property that enables safe restarts, crash recovery, and replay.

### How Pauses Occur

Workflows pause when a **gate condition** is not yet met. A paused workflow is not a special state — it is simply a workflow whose current step has an unsatisfied precondition. The scheduler evaluates it on each tick and does nothing until the precondition is met.

Gate conditions that pause workflows:
- Approval pending (HITL gate): waiting for human reviewer
- Company traction hold: a sibling contact is HOT, orchestration waiting for human coordination decision
- Timing window: workspace sends only between defined hours; gate satisfied when clock enters window
- Frequency guard: contact was sent to recently; gate satisfied when lookback window expires
- Suppression: temporary suppression in effect; gate satisfied when TTL expires

Paused workflows do not consume resources. They are DB rows. The scheduler queries for workflows with satisfied preconditions; paused workflows are not returned.

### How Retries Occur

**Two distinct retry domains:**

1. **Send delivery retries** (Execution Layer): transient provider failures, rate limits, timeout. These retry within the outbox model, with exponential backoff, up to a configurable maximum (default: 3 attempts). Governed by `send_attempt` records. Not visible to the Orchestration Layer until the attempt is PERMANENTLY_FAILED.

2. **Workflow step retries** (Orchestration Layer): if a draft generation step fails (LLM error, context assembly failure, etc.), the workflow marks the step as failed and schedules a retry via the scheduler. This is a higher-level retry — the entire step (context assembly + generation + approval request) is retried, not just the delivery.

The two retry domains are explicitly separated. A delivery failure does not re-trigger draft generation. A generation failure does not trigger a re-send.

### How Sibling Traction Affects Orchestration

When a contact at a company reaches `HOT` engagement (reply or meeting link click), the system evaluates all other contacts at the same company who are in flight:

- Contacts with drafts in `PENDING` status have their workflows paused (company traction gate applied)
- Contacts with drafts in `APPROVED / QUEUED` status are flagged for human review before dispatching
- No automatic suppression — this is a coordination signal, not a block
- A workspace-configurable policy governs the behavior (hold all, hold new, notify only)

This mechanic is implemented via the `company_traction_state` projection. The Governance Layer reads it during policy evaluation. The signal is always observable.

### How Policy Gates Are Evaluated

Policy gates are evaluated **synchronously before any action** and **lazily during scheduler evaluation**.

Synchronous evaluation occurs when:
- A draft approval is submitted via API (the system re-evaluates policy before accepting the approval)
- A send is requested manually

Lazy evaluation occurs when:
- The scheduler evaluates a paused workflow to determine if it should advance
- A traction signal arrives and the system re-evaluates affected workflows

In all cases, the evaluation produces a disposition record. There is no "implied" or "remembered" authorization. Each potential send requires a current disposition.

### How Autonomous Execution Coexists with HITL

The governing principle is: **HITL is the default. Autonomous execution is granted by policy.**

A workspace begins with a policy that requires approval for all drafts. The workspace can configure policies that grant autonomous execution for specific conditions (e.g., auto-approve step-1 drafts that pass a quality threshold, or auto-approve sends during a defined campaign window).

When autonomous execution is authorized by policy, the workflow transitions through the approval state without requiring a human reviewer. An `autonomous_approval` event is written, referencing the policy that authorized it. The attestation record is still created — it is attributed to the policy, not to a human. This is explicit, not implicit: the audit trail records that this send was authorized autonomously under a specific policy.

The critical architectural invariant: **there is no code path that sends without a recorded disposition and a recorded approval event, whether human or autonomous.** The approval record is structural, not optional.

---

## Part V — Context Intelligence Architecture

### What a Context Packet Truly Is

A Context Packet is not a blob of text assembled for an LLM prompt. It is a **structured, grounded, purpose-scoped snapshot of the system's current understanding of a contact and their company**, at a specific point in time, for a specific outreach purpose.

Every field in a Context Packet traces to a source record. Every claim is evidence-linked. The Context Packet is the intelligence substrate of the system — the structured answer to the question: "what do we know about this person right now, that is relevant to engaging them well?"

A Context Packet has five structural components:

**1. Contact Profile** — role, seniority, domain, company, LinkedIn profile data, enrichment signals. Source: `contacts` table + enrichment records. Provenance: explicit.

**2. Engagement History** — what has been sent to this contact before, what they engaged with, what they ignored, whether they replied, how long ago. Source: `workflow_events` + `outreach_drafts`. Provenance: explicit.

**3. Company Intelligence** — company profile, industry, size, observed pain indicators, relevant news signals (if present). Source: company records + signal intelligence. Provenance: explicit.

**4. Traction Context** — company traction level, other contacts engaged, champion/blocker patterns, warm account signals. Source: `company_traction_state` projection. Provenance: derived (flagged as such).

**5. Policy and Suppression Context** — current governance posture, active suppressions, workspace preferences, prohibited claim categories. Source: current policy snapshot + suppression rules. Provenance: explicit.

### Grounding and Evidence Requirements

Every substantive claim in a Context Packet must satisfy one of:

- **Direct observation**: the claim is based on a DB record with a timestamp and source identifier
- **Derived inference**: the claim is explicitly marked as derived (e.g., "traction level HOT — inferred from 2 engagement events"), with source events cited
- **External enrichment**: the claim comes from an enrichment API and is explicitly marked with provider + timestamp

Claims that do not satisfy one of these conditions are **prohibited**. The Intelligence Layer enforces this at assembly time. A Context Packet with an ungrounded claim is invalid and is not surfaced to the generation path.

**Prohibited claims** are a first-class concept. Certain claim categories are workspace-configurable as prohibited — topics the workspace has decided should never appear in outreach (competitor comparisons, unverified financial claims, specific product capability claims, etc.). These are evaluated at context assembly time, not at generation time. The generation model should never receive a prohibited claim as context.

### Conversation Continuity

Conversation continuity is the mechanism by which prior interactions inform future message generation. It is not a feature — it is an architectural requirement for the Memory Layer.

When a context packet is assembled for a contact who has prior interactions, the packet includes:

- A summary of what has been said (from `contact_operational_memory`)
- The engagement outcome of each prior draft (opened, ignored, replied, etc.)
- An explicit instruction derived from prior outcomes: "prior subject lines with question format were opened; prior body text referencing their press release was clicked; prior send without specific signal grounding was ignored"

This structured history is provided to the generation model as structured data, not as a free-text narrative. The model can reference it; it cannot hallucinate an alternative version of it.

**No conversation continuity without a grounded prior record.** If the memory layer has no prior interaction data, the context packet explicitly represents this as "first contact." The generation model is informed that this is a cold outreach with no prior engagement signal.

### Operational Memory Architecture

Operational memory is a **structured cache with decay semantics**. It is the accumulated intelligence substrate for each contact and company, maintained in the Memory Layer.

For each contact:
- All prior drafts and their content summaries (permanent)
- All engagement events and their timestamps (permanent)
- The assembled context packets used for each draft (stored; linked to draft; TTL for retrieval optimization but never deleted)
- Reviewer feedback on drafts (annotation, approval notes, rejection reasons) — highly valuable signal

For each company:
- All contacts in flight, their current workflow state, their engagement levels
- Company traction state and history
- Champion/blocker annotations from reviewers

Operational memory does not expire. It decays in relevance (older signals are weighted less by the Intelligence Layer) but the records are permanent. The system must be able to reconstruct the reasoning behind any draft from first principles.

---

## Part VI — Durable Execution Model

### Queue Semantics

The outbound queue is a **PostgreSQL table** (`outbound_queue`), not an external message broker. Rows are inserted atomically with the approval event (transactional outbox pattern). The scheduler picks up rows using `SELECT FOR UPDATE SKIP LOCKED`, which provides:

- Concurrent-safe access without application-level locking
- No row is processed twice concurrently (the FOR UPDATE lock prevents it)
- SKIP LOCKED means competing workers skip rows already being processed
- Compatible with PgBouncer in transaction mode (the lock is held only for the duration of the transaction, not the session)

Queue rows are deleted (not marked processed) once the send attempt is dispatched. The send attempt table is the durable record of what happened. The queue is ephemeral state for work in progress.

### Outbox Semantics

The transactional outbox pattern guarantees that a send attempt is enqueued if and only if the corresponding approval event is committed. This is the core durability guarantee:

- No approval without a queue entry (the INSERT is in the same transaction)
- No queue entry without a corresponding approval event (FK relationship)
- A crashed process between queue pickup and delivery leaves the row locked; on connection timeout the lock is released and the row is reprocessed

The outbox is the boundary between the Orchestration Layer and the Execution Layer. Nothing crosses this boundary without passing through the queue.

### Send Attempt Semantics

Every delivery action produces a `send_attempt` record at the moment of dispatch. The send attempt record is **append-only**. It records:

- The draft it corresponds to
- The idempotency key (generated before the provider call)
- The attempt number (1 for first attempt, incremented on retry)
- The status at creation (`DISPATCHED`)
- The provider response when received (success or failure details)
- The reconciliation timestamp if status was determined via reconciliation job

The sequence of send attempt records for a draft is the complete history of all delivery actions taken. The most recent record's status is the current delivery status.

### Exactly-Once vs At-Least-Once

ProspectIQ uses **at-least-once delivery with application-level idempotency**. Exactly-once delivery is not achievable with external email providers and is not a reasonable goal.

The implication: duplicate sends are possible in failure scenarios. The design must minimize the window:

- Idempotency keys on send attempts allow provider-level deduplication (Resend supports idempotency keys)
- The reconciliation job detects duplicate dispatches from DB state before re-dispatching
- The `sent_at IS NOT NULL` immutability invariant prevents re-sending a draft that has already been confirmed sent

The failure scenario that produces a duplicate send: process crashes after provider call succeeds but before the send_attempt record is updated. On reconciliation, the system detects a `DISPATCHED` record, queries the provider, finds it was already delivered, and marks it as `DELIVERED` without re-sending. The idempotency key is the mechanism for this reconciliation.

### Provider Webhook Reconciliation

Provider webhooks are supplementary confirmation, not the primary delivery record. The design:

1. Send attempt record is created at dispatch time (system-initiated, synchronous)
2. Provider webhook arrives and updates the send attempt record (provider-initiated, asynchronous)
3. Reconciliation job periodically checks for DISPATCHED records older than a defined threshold and queries the provider API for current status (system-initiated, background)

Any one of these three mechanisms can produce the authoritative delivery status. The system does not depend on webhooks alone. Webhooks are processed idempotently — receiving the same webhook twice produces the same DB state.

---

## Part VII — Governance Architecture

### Policy Evaluation Model

Governance in ProspectIQ is not a checkbox. It is a **structured decision chain that produces an explicit, recorded disposition for every potential send action**.

The policy evaluation chain is ordered (described fully in Part IV). Each step in the chain is a **policy evaluator** — a pure function that takes (contact, company, draft, workspace_policy_snapshot, timestamp) and returns a disposition. Each evaluator is independently testable and independently configurable.

Workspace policy configuration governs the behavior of each evaluator: suppression TTLs, send windows, frequency limits, approval requirements. This configuration is stored as a `policy_snapshot` at the time of evaluation and is immutable thereafter.

**Policy snapshots are the audit foundation.** Every governance decision record references the policy snapshot under which it was evaluated. If a policy is changed after a decision is made, the historical decision is unaffected. The system can reconstruct "what policy was in effect when this draft was sent" from DB records alone.

### Approval Semantics

Approval is a **governance checkpoint**, not a UI convenience. Structurally:

1. A draft in `PENDING` state has a corresponding open review gate
2. The Governance Layer evaluates whether HITL is required (per policy)
3. If required: the review gate is opened, a notification event is written, the workflow pauses
4. A reviewer submits an approval action via the API
5. The approval event is written with reviewer identity, timestamp, and attestation fields
6. The draft transitions to `APPROVED`
7. The workflow advances to the queue step

**The reviewer interface is not just an approve/reject button.** It surfaces the Context Packet used for this draft, the policy disposition, the suppression status, and the company traction context. This is not optional UX polish — it is the mechanism by which the reviewer can make an informed attestation.

Rejections are equally structured. A rejection records a reason category (content quality, wrong timing, wrong recipient, policy concern, other) and optionally a free-text note. This annotation is written to the contact's operational memory and influences future draft generation.

### Risk Scoring

The architecture supports a **draft risk score** — a composite signal of how risky a given send is, surfaced to reviewers and used as an optional escalation signal.

Risk factors include:
- Contact has been sent to before and did not engage (diminishing returns signal)
- Company traction is COLD (no engagement signal from any contact)
- Context Packet completeness is low (missing enrichment fields)
- Draft age is high (draft was generated more than N days ago; context may be stale)
- Suppression was recently lifted (caution on re-engagement)

The risk score is advisory, not blocking. It does not produce a disposition. It informs the reviewer and the escalation logic.

**Escalation**: drafts above a configurable risk threshold require a second review (surfaced as a `PENDING_SECOND_REVIEW` approval status, already in the schema). This is the mechanism for managing high-risk sends without blocking the entire pipeline.

### Audit Architecture

The audit record is complete and permanent. The system must be able to answer any of the following questions from DB records alone:

- Why was this draft sent?
- What policy was in effect when it was sent?
- Who approved it and when?
- What context was available at the time of generation?
- What engagement did it produce?
- Was this contact suppressed at the time of the send?
- What other drafts were sent to contacts at this company around the same time?

These answers must not require log files, memory, or human recollection. They must be answerable from structured DB queries.

The tables that comprise the audit record: `workflow_events`, `governance_decisions`, `policy_snapshots`, `approval_events`, `send_attempts`, `provider_events`, `context_packets`.

---

## Part VIII — Operational Model

### Scheduler Philosophy

The scheduler is an **idempotent evaluation engine**, not a command dispatcher. It does not issue instructions to other services or maintain in-memory state between ticks. Each scheduler tick evaluates the current DB state and advances anything that is ready.

Three job categories:

**Advancement jobs** (high frequency, lightweight):
- Evaluate workflows ready to advance based on timing conditions
- Process workflows unblocked by recently resolved gate conditions
- Trigger context assembly for drafts ready for generation
- Request provider status for DISPATCHED attempts near timeout

**Reconciliation jobs** (medium frequency, corrective):
- Find DISPATCHED send attempts beyond timeout threshold and reconcile via provider API
- Find dead-letter queue items and generate operational alerts
- Find context packets approaching TTL and re-evaluate whether they should be refreshed

**Housekeeping jobs** (low frequency, maintenance):
- Expire temporary suppressions past their TTL
- Archive old workflow events beyond retention window
- Compute company traction state projection updates

**Singleton guarantee**: the scheduler is a single instance. DB-row-based locking (not session-level advisory locks — incompatible with PgBouncer) ensures that if multiple processes start, only one holds the scheduler lock. The lock is a heartbeat row: a process that holds it must update the heartbeat timestamp within a defined interval, or the lock is considered stale and eligible for takeover.

### Observability Requirements

The system must expose the following operational questions with no more than a DB query:

- **Pipeline health**: how many drafts are in each state (pending, approved, queued, sent, failed)?
- **Queue depth**: how many sends are in the outbound queue right now?
- **Suppression state**: how many contacts are suppressed, at what level, expiring when?
- **Governance disposition distribution**: of the last N policy evaluations, what fraction were ALLOW, REQUIRE_APPROVAL, BLOCK?
- **Send success rate**: of the last N send attempts, what fraction were DELIVERED vs FAILED vs PERMANENTLY_FAILED?
- **Workflow velocity**: how many workflows advanced in the last 24 hours? Last 7 days?
- **Review queue age**: what is the oldest open review gate in the system?
- **Context packet coverage**: what fraction of drafts in the last 7 days had a linked context packet?

These metrics are derived from the same tables that comprise the audit record. No separate metrics store is needed at this scale. A materialized view or a daily summary table suffices.

### Manual Intervention Boundaries

The system must define the exact set of manual intervention operations and the guardrails around each:

- **send_enabled toggle**: single-column write to `outreach_send_config`; requires explicit human action; never automated; always logged
- **Suppression override**: removes a suppression with mandatory justification capture; creates an override event in the audit log
- **Dead-letter requeue**: manually requeues a dead-letter item for retry; creates a requeue event; limited to authorized operators
- **Workflow force-advance**: manually advances a paused workflow; creates a force-advance event; requires justification
- **Policy modification**: updates workspace policy; creates a new policy_snapshot; does not affect historical decisions

**The principle**: every manual intervention creates an immutable record of itself. The system distinguishes between "this happened autonomously under a policy" and "this happened because a human directly intervened." These are fundamentally different categories of event and must be auditable separately.

### Dead-Letter Handling

A send attempt is dead-lettered when:
- It has exhausted all retry budget (max attempts exceeded)
- It has received a permanent failure response from the provider (hard bounce, authentication failure)

Dead-lettered items are NOT automatically deleted or re-attempted. They require human review. The operational question for each dead-lettered item is one of:
- The contact is unreachable (bad email): trigger suppression
- The provider rejected the send (policy violation): investigate and remediate
- The system configuration was wrong: fix and manually requeue
- The draft content was malformed: fix and re-generate

Dead-letter is not a queue. It is a holding area for items that require human diagnosis. The system alerts on new dead-letter items and presents them in the review interface.

---

## Part IX — Data Architecture

### Entity Classification

All entities in the ProspectIQ data model fall into one of four categories. The category determines the DB design pattern, the mutation semantics, and the recovery model.

**Category A: Append-Only Event Records** (immutable, permanent, never updated or deleted)
- `workflow_events` — every state transition for every workflow
- `send_attempts` — every delivery action ever taken
- `provider_events` — raw webhook payloads from external providers
- `governance_decisions` — every policy evaluation and its disposition
- `approval_events` — every human (or autonomous) approval or rejection action
- `policy_snapshots` — workspace policy at a specific point in time
- `context_packets` — assembled context at a specific point in time for a specific draft

The append-only invariant is enforced at the DB level (trigger + no-update rule), not just by convention. These tables are the source of truth for the audit record.

**Category B: Mutable Current-State Tables** (authoritative present state; updatable within defined rules)
- `outreach_drafts` — current draft state (content frozen post-send; engagement metadata freely updatable)
- `contacts` — contact profile (updatable as enrichment arrives)
- `companies` — company profile (updatable)
- `suppression_rules` — current suppression entries (lifecycle-managed)
- `workspace_config` / `outreach_send_config` — workspace settings
- `outbound_queue` — pending dispatch work (entries are deleted on completion)

Mutable state tables have defined mutation rules. Not every column is freely updatable. The draft immutability trigger is the prototype of this pattern.

**Category C: Projection Tables** (derived from event records; rebuildable; do not need to be perfectly consistent in real-time)
- `contact_engagement_summary` — rolled-up engagement level per contact
- `company_traction_state` — aggregate traction level per company
- `contact_operational_memory` — assembled context and interaction history per contact
- `sequence_progress` — current step and status per (contact, sequence) workflow

Projection tables can be stale by design. They are updated on event ingestion. They can be fully rebuilt from the append-only event records. If a projection table is corrupted or needs to be extended, it can be dropped and rebuilt without data loss.

**Category D: Operational Control Tables** (system-level; not domain records)
- `scheduler_lock` — heartbeat-based singleton guarantee
- `dead_letter_queue` — send attempts requiring manual intervention

### Event Log Philosophy

The event log is the spine of the audit architecture. Every significant state transition in the system is represented by an event record. The event log answers "what happened?" The current-state tables answer "what is the current state?"

Event log entries are never deleted. They are never updated. They may be archived to cold storage after a retention period, but they are never destroyed.

The event log is not used as the primary query target for operational dashboards. Current-state tables and projections serve that purpose. The event log is consulted for audit queries, reconstruction, and debugging.

### Historical Reconstruction

The system must be capable of reconstructing the full state of any contact, company, or workflow at any point in historical time from the event log alone. This is the test of whether the event log design is sufficient.

Specifically:
- "What was the state of contact X's engagement at time T?" must be answerable from `workflow_events`
- "What policy was in effect when draft Y was sent?" must be answerable from `governance_decisions` + `policy_snapshots`
- "What context did the system have when draft Y was generated?" must be answerable from `context_packets`

Historical reconstruction is an audit capability, not an operational performance requirement. It should be possible; it need not be fast.

---

## Part X — Multi-Channel Future

### The Core Principle

When a second channel (LinkedIn, SMS, voice) is added to ProspectIQ, **the orchestration model must not fork**. There must not be a "LinkedIn workflow engine" that runs separately from the "email workflow engine." There must be one orchestration model that operates on **workflow steps**, and channel adapters that implement those steps on specific channels.

This is the anti-pattern to prevent: building LinkedIn as a separate system that shares the DB but has its own orchestration loop, its own approval queue, and its own policy evaluators. That path leads to duplicated governance logic, divergent state models, and an operational complexity that doubles with every new channel.

### Channel Adapter Architecture

A channel adapter is a registered module that satisfies the **Channel Adapter Interface**:

```
interface ChannelAdapter:
    channel_type: ChannelType
    manifest: ChannelManifest

    can_send(contact: Contact) -> CanSendResult
    send(instruction: DeliveryInstruction) -> DeliveryOutcome
    normalize_event(raw_event: ProviderEvent) -> WorkflowEvent
    get_delivery_status(idempotency_key: str) -> DeliveryStatus
```

The **Channel Manifest** is metadata that the orchestration layer uses to reason about channel selection:
- Supported content formats (plain text, HTML, markdown, etc.)
- Rate limits and send windows
- Consent requirements
- Contact data requirements (email address, LinkedIn URL, phone number, etc.)
- Typical engagement signal latency (email opens arrive in seconds; LinkedIn read receipts may not arrive at all)

The orchestration layer does not contain channel-specific conditional logic. It asks "does this contact have a qualified LinkedIn profile?" by querying the manifest's contact data requirements, not by checking a `linkedin_url IS NOT NULL` condition inline.

### Multi-Touch Orchestration

When the system can send across multiple channels to the same contact, the orchestration model must manage **cross-channel coordination**:

- A contact should not receive an email and a LinkedIn message within 24 hours of each other (configurable)
- An engagement signal on one channel (LinkedIn reply) should pause the workflow on other channels for the same contact
- The traction model is channel-independent: a LinkedIn click by a contact at Company X is a company traction signal for Company X, regardless of whether the outreach to other contacts at Company X is by email

These behaviors are governed by policies at the workspace level, not hard-coded in the orchestration model. The orchestration model reads cross-channel context from the Memory Layer (company traction state is channel-independent; contact engagement summary is per-channel but company traction is aggregate).

### Channel Addition Checklist

Adding a new channel to the system should require exactly:
1. A new Channel Adapter module implementing the Channel Adapter Interface
2. A new Channel Manifest entry for the new channel type
3. Any new contact data fields required (e.g., `linkedin_url`)
4. Provider event normalization rules for the new channel's webhook format

It should NOT require:
- New workflow state machine logic
- New policy evaluator code
- New approval flow code
- New audit schema

If adding a new channel requires touching the orchestration or governance layer, that is a signal that channel-specific logic has leaked into those layers.

---

## Part XI — Relationship to Digitillis Architectural Concepts

### What Applies Directly

**Context Packet as first-class concept**: ProspectIQ's Intelligence Layer design mirrors the Digitillis FirstLook context assembly pattern — structured, grounded, evidence-linked, purpose-scoped snapshots of what is known. The concept is the same; the domain is different.

**Policy snapshot immutability**: The Digitillis approach of capturing an immutable policy snapshot at decision time applies directly. The governance audit foundation is identical in structure.

**Append-only event log for significant decisions**: The event sourcing philosophy (not maximalist CQRS, but selective append-only records for significant decisions) is the same architecture in both systems.

**Capability manifest pattern**: The Channel Adapter manifest in ProspectIQ is conceptually parallel to the Digitillis capability registry — registered, declarative capability metadata that lets the orchestration layer reason about what is possible without embedding capability-specific logic.

**Circuit breaker for external providers**: The provider adapter layer should implement provider-specific circuit breakers, exactly as Digitillis does for external ML services and integrations.

### What Does NOT Apply

**L1-L5 industrial connectivity layers**: ProspectIQ has no OPC-UA, MQTT, Modbus, or CMMS integrations. The Signal Layer ingests webhooks and IMAP, not industrial telemetry.

**CognitiveMesh and graph-based ML**: ProspectIQ's intelligence requirements at the current scale are relational, not graph-based. Neo4j and vector similarity search are premature. Structured DB queries against well-indexed tables are sufficient.

**106-agent manifest system**: ProspectIQ has a small number of workflow types (sequence steps, one-offs) and a small number of job types (advancement, reconciliation, housekeeping). An agent manifest system with circuit breakers per agent is architectural overhead that serves no purpose here.

**TimescaleDB for time-series optimization**: At 50-500 sends/day, time-series query optimization is not a real problem. Standard PostgreSQL indexes on timestamp columns are sufficient for a decade of growth at this scale.

**Event-sourced CQRS with Kafka**: The operational sophistication required to run Kafka, maintain consumer groups, and manage projection rebuilds from a Kafka log is not justified here. PostgreSQL as the event substrate is sufficient.

### Where ProspectIQ Should Be Intentionally Simpler

Digitillis is a multi-tenant, multi-industry platform with 100+ intelligence runners, ML pipeline infrastructure, and industrial connectivity. ProspectIQ is a focused outbound engagement engine for a single vertical motion.

ProspectIQ should be intentionally simpler in:
- **Infrastructure**: one DB, one backend service, one scheduler, one delivery adapter for now
- **Intelligence**: structured queries over relational data, not ML inference or graph traversal
- **Orchestration**: a handful of workflow types with explicit state transitions, not a 106-agent manifest system
- **Multi-tenancy**: workspace-scoped isolation via DB row-level filtering, not full tenant-isolated schema separation

The temptation to "adopt the Digitillis architecture" wholesale should be resisted. Take the concepts and vocabulary. Do not import the complexity.

### Shared Vocabulary That Helps

Using consistent vocabulary across both systems aids thinking and communication:

| Digitillis Term | ProspectIQ Equivalent | Notes |
|---|---|---|
| Context Packet | Context Packet | Same concept, same structure |
| Policy snapshot | Policy snapshot | Identical |
| Governance gate | Governance disposition / HITL gate | Same concept |
| Capability manifest | Channel manifest | Parallel pattern |
| Signal integration | Signal Layer | Same layer purpose |
| Operational memory | Contact/company operational memory | Narrower scope |
| Disposition | Disposition | Identical concept |

---

## Part XII — Explicit Anti-Patterns

### The Scheduler God Object

A single scheduled job that fetches all pending drafts, evaluates all policies, and sends everything in a loop. This seems simple but becomes:
- Unobservable (one job doing everything is not introspectable)
- Brittle (one internal error stops all processing)
- Opaque to reasoning (interleaved policy evaluation and delivery)
- Impossible to test incrementally

The scheduler should be a set of narrowly scoped, independently observable jobs. Each job has one responsibility. Jobs are additive, not monolithic.

### State in Code, Not in Data

Workflow state scattered across Python service methods, class attributes, or API route logic. If the process restarts, the state is lost. If two requests arrive concurrently, the state is corrupt. All workflow state must be in PostgreSQL, with transitions enforced by DB constraints.

### Policy Strings in Conditionals

Governance logic as nested `if` statements in Python code: `if workspace.requires_approval and not draft.was_pre_approved and not is_autonomous_window():`. This is:
- Not auditable (conditions are evaluated at runtime, not recorded)
- Not configurable without deployment
- Not independently testable
- A maintenance nightmare as conditions accumulate

Governance logic is data: a set of evaluators that read from policy snapshot records and produce recorded dispositions.

### The AI Black Box

Treating the LLM generation call as an oracle that produces a good draft if given enough instructions. No grounding, no evidence linking, no prohibited claim checking, no Context Packet validation, no post-generation quality gate. This produces:
- Hallucinated claims about contacts or companies
- Policy violations that are not caught until a human reviewer notices
- Inconsistent quality with no observable root cause
- No mechanism to learn from reviewer feedback

Every draft generation invocation is grounded by a validated Context Packet. Every prohibited claim category is filtered at context assembly, not at generation. Every reviewer rejection includes a structured reason that feeds back into the memory layer.

### Eventual Consistency Theater

Marking send attempts as "dispatched" and relying on provider webhooks alone to confirm delivery. Provider webhooks:
- Are not guaranteed to arrive
- Can arrive out of order
- Can be delivered multiple times
- Can be delayed by hours

A system that relies solely on webhooks for delivery confirmation has unknown state for any send where the webhook was lost or delayed. The reconciliation job is not optional.

### HITL as Optional Plugin

Treating human review as an optional feature that can be enabled or disabled via a flag. This is architecturally dangerous because:
- The approval record is the foundation of the audit trail
- Skipping approval means no attestation record exists
- The governance model assumes approvals happen; code that bypasses it is invisible to governance reporting

Human review is a structural property of the architecture. Autonomous approval (policy-authorized) is a distinct concept from bypassed approval. These must be explicitly differentiated in the event log.

### Channel-Specific Orchestration Forks

Building a separate orchestration loop, approval queue, and scheduler logic for LinkedIn or any future channel. This doubles the maintenance burden for each new channel, creates divergent governance models, and makes cross-channel coordination nearly impossible.

The delivery of a message is channel-specific. The workflow that governs when and whether to send it is not.

### Over-Normalized Event Sourcing

Decomposing every column-level change into an event (e.g., DraftBodyUpdatedEvent, DraftSubjectUpdatedEvent, DraftApprovalStatusChangedEvent). This requires complex projection logic, slows all reads, and makes the event log unreadable without tooling. At ProspectIQ's scale, it produces operational overhead with no practical benefit.

The right granularity for event sourcing: significant state transitions (workflow advanced, draft approved, send dispatched, engagement received, suppression applied). Not column-level changes.

### Feature Flag Proliferation

Using `send_enabled` boolean columns, env var gates, and ad-hoc feature flags to control fundamental architectural behaviors. This creates:
- Untested code paths (the disabled path is never tested in production)
- Invisible state (the system behaves differently depending on a flag nobody documented)
- Maintenance debt (flags accumulate and are never removed)

System-level controls like `send_enabled` are appropriate during the transition phase. They should be treated as temporary operational controls, not permanent architectural features. The long-term architecture has a well-defined governance model that makes a single `send_enabled` flag unnecessary.

### Provider Lock-In via Direct Coupling

Writing the send path to be directly coupled to Resend's API surface (specific endpoint paths, Resend-specific headers, Resend-specific response parsing) scattered throughout the codebase. When Resend changes its API, or when LinkedIn requires a different pattern, or when a backup provider is needed, every callsite must be found and changed.

All provider coupling is localized to the Delivery Layer adapters. The rest of the system communicates with the Delivery Layer via canonical interfaces.

---

## Part XIII — Phased Roadmap

### Current State

ProspectIQ is a manually-operated outbound automation tool with recently hardened DB invariants, foundational governance primitives, and a Context Intelligence layer in shadow mode. Sends are manually authorized. The system has no durable execution model, no workflow state machine, and no canonical orchestration layer.

The foundation is now trustworthy. The evolution can begin.

---

### Phase 1: Stabilization (Complete)

**Goal**: trust the data.

PRs A through E and D have established:
- Immutable governance primitives (`workflow_events`, `provider_events`)
- Sent-draft content immutability (DB trigger)
- Duplicate draft prevention (unique partial index)
- Context Intelligence infrastructure (shadow mode)
- Webhook deduplication

The DB invariants are enforced at the lowest level. The system can no longer silently corrupt state. This is the prerequisite for everything that follows.

**Exit criterion**: the system's DB state is trustworthy and every significant governance decision is recorded.

---

### Phase 2: Durable Execution

**Goal**: every send is durably tracked, idempotent, and recoverable.

This phase introduces:
- `outbound_queue` table (transactional outbox)
- `send_attempts` table (append-only delivery record)
- Retry model with exponential backoff
- Provider reconciliation job
- Dead-letter queue and operational alerting

The send path transitions from "call Resend and hope" to "insert queue row, dispatch atomically, reconcile asynchronously." The system can now answer "what is the current delivery status of every send?" from DB records alone.

**Exit criterion**: every authorized send has a `send_attempt` record. The system can be restarted mid-send without double-sending or losing a send.

---

### Phase 3: Orchestration Runtime

**Goal**: the system advances workflows; humans review and approve.

This phase introduces:
- Explicit workflow state per (contact, sequence) in `sequence_progress`
- Policy evaluation chain producing recorded dispositions
- Governance disposition decision records linked to policy snapshots
- Scheduler jobs for workflow advancement and gate evaluation
- Sibling traction hold mechanics
- Autonomous approval model (policy-authorized)

The system transitions from "humans manually trigger sends" to "the system proposes and schedules; humans approve at defined gates; the system executes."

**Exit criterion**: a contact can enter a sequence, receive a context-informed draft, be reviewed and approved by a human, be sent to, and have their engagement recorded — all via defined DB state transitions, with no manual database manipulation required.

---

### Phase 4: Contextual Intelligence

**Goal**: every draft is grounded in what is known about this person.

This phase graduates the Context Intelligence Layer from shadow mode to the production generation path:
- Context Packets are assembled and linked to draft generation requests
- Prior interaction history is surfaced to the generation model
- Rejected draft annotations feed back into operational memory
- Company traction context is included in every generation request
- Prohibited claim checking is enforced at context assembly

**Exit criterion**: every generated draft has a linked Context Packet. The review interface surfaces the context packet alongside the draft. Reviewer rejections generate structured annotations that persist in operational memory.

---

### Phase 5: Governance Maturity

**Goal**: governance is observable, configurable, and self-enforcing.

This phase matures the Governance Layer:
- Risk scoring for drafts surfaced to reviewers
- Escalation rules for high-risk drafts (`PENDING_SECOND_REVIEW`)
- Governance dashboard: disposition distribution, approval latency, suppression state
- Policy configuration UI (workspace-level policy management, not hardcoded values)
- Audit query interface: "why was this sent?" answerable in the UI

**Exit criterion**: a non-technical operator can understand the governance posture of the system from the UI without consulting an engineer.

---

### Phase 6: Multi-Channel Intelligence

**Goal**: LinkedIn and multi-touch orchestration without forking the orchestration model.

This phase introduces:
- Channel Adapter Interface and Channel Manifest
- LinkedIn adapter (first alternative channel)
- Cross-channel traction signals in the company traction state projection
- Cross-channel coordination policies (hold email if LinkedIn is hot)
- Unified review queue across channels

**Exit criterion**: a contact can receive outreach via email or LinkedIn, governed by the same policy evaluation chain, tracked in the same audit record, with cross-channel coordination enforced by the Memory Layer.

---

### Phase 7: Self-Improving Intelligence

**Goal**: the system gets better over time without retraining models.

This phase introduces:
- Outcome signal feedback into operational memory (what subject lines were clicked, what body patterns were replied to)
- Workspace-level effectiveness patterns surfaced for policy configuration
- Champion identification patterns from company traction history
- Sequence effectiveness scoring (which sequences produce engagement, which don't)

**Exit criterion**: the system can surface a workspace-level report showing "these outreach patterns produce engagement; these don't" based on recorded signals, requiring no data export or external analysis.

---

## Part XIV — Architectural Doctrine

The following ten principles govern all future ProspectIQ engineering decisions. These are not recommendations. They are the constraints within which the system is built.

---

**Principle 1: State in PostgreSQL, not in processes.**
All workflow state, governance decisions, context, and audit records are persisted in PostgreSQL. A process restart must be lossless. A process that holds no DB-persisted state cannot corrupt the system when it crashes. If a workflow state cannot be expressed as a DB row, it is not a workflow state yet.

---

**Principle 2: Every consequential decision is explainable.**
The system must be able to answer "why was this draft sent?" from DB records alone. No logs, no human memory, no process state. Governance decisions, policy snapshots, context packets, approval events, and send attempts together constitute a complete, auditable record of every consequential action.

---

**Principle 3: Policy is data, not code.**
Governance rules are stored, versioned, and evaluated as structured records with explicit dispositions. Governance logic is not embedded as conditional code in API routes or scheduler jobs. Policy snapshots are immutable at evaluation time. Historical decisions reflect the policy that governed them.

---

**Principle 4: HITL is architecture, not feature.**
Human review is a structural property of the governance model. Every send either has a human attestation record or an autonomous approval event referencing the policy that authorized it. There is no code path that sends without a recorded authorization. Bypassing the approval model is not a performance optimization — it is an audit violation.

---

**Principle 5: Immutability for committed content.**
Once a draft is sent, its content is permanent. The body and subject of a sent draft cannot be changed. Engagement metadata evolves; content does not. This invariant is enforced at the DB level, not by convention.

---

**Principle 6: Context is grounded or it is not surfaced.**
Every claim in a Context Packet traces to a source record. There are no hallucinated enrichment fields. Derived claims are explicitly marked as derived with their source events cited. Prohibited claim categories are filtered at context assembly, before reaching the generation model.

---

**Principle 7: Channel adapters, not channel forks.**
Adding a new outreach channel means writing a new Channel Adapter that satisfies the Channel Adapter Interface. It does not mean forking the orchestration logic, the governance model, or the approval flow. The orchestration layer is channel-agnostic. The delivery layer is channel-specific. These boundaries are enforced by design.

---

**Principle 8: Operational simplicity over architectural purity.**
A single PostgreSQL database, a single deployed monolith, and a scheduler-driven orchestration model are virtues at this scale. Introducing a message broker, a workflow engine, or a separate microservice must justify itself against the team's operational capacity. The complexity budget is finite. Spend it on domain problems, not infrastructure.

---

**Principle 9: At-least-once with idempotency.**
ProspectIQ accepts that external providers cannot guarantee exactly-once delivery. Every delivery operation is designed to be safe when retried: idempotency keys on send attempts, provider-level deduplication where available, and reconciliation logic that detects duplicate states before re-executing. Exactly-once is not a design goal; idempotent at-least-once is.

---

**Principle 10: Governance is the happy path.**
Approval gates, policy evaluations, and audit record creation are not friction added to an otherwise fast system. They are the system. The architecture optimizes for governance integrity first. Throughput and latency are secondary concerns at 50-500 sends/day. A governance shortcut that makes the system faster but less auditable is the wrong tradeoff at every phase of this roadmap.

---

*End of canonical architecture doctrine.*

---

**Document status**: This document is the reference point for all PR scoping, design reviews, and architecture discussions going forward. When a proposed change conflicts with this doctrine, the conflict should be discussed explicitly — either the change should be revised, or the doctrine should be updated with a written rationale.
