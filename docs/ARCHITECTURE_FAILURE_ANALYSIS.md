# ProspectIQ Architectural Discovery and Failure Analysis

## A. Executive Summary

ProspectIQ is a multi-tenant, AI-driven cold-outreach automation platform sitting on top of Supabase/Postgres. The data flow is: Apollo enriches contacts → research/qualification populates `companies` and `research_intelligence` → an SQL gate (`outbound_eligible_contacts`) restricts who can be drafted → an LLM agent (`OutreachAgent` in `backend/app/agents/outreach.py`) generates drafts into `outreach_drafts` with `approval_status='pending'` → a human approves via `POST /api/approvals/{id}/approve` → APScheduler tick `_run_send_approved` (Mon–Fri 8–11 AM Chicago at :00/:30) calls `EngagementAgent._send_approved_drafts` which atomically claims `sent_at`, runs send-path assertions, then dispatches via Resend → inbound replies arrive via Gmail IMAP/API or webhook handlers (`/api/webhooks/resend`, `/api/webhooks/instantly`) → replies are classified and routed to a HITL queue. Sequences (`engagement_sequences`) drive multi-step follow-ups, with `_run_jit_pregenerate` creating step-N drafts 3 days ahead.

The architecture is layered correctly in intent (gate → draft → approve → send → webhook → suppress), but in practice it is held together by many implicit invariants that are enforced in code rather than in the schema. Concretely: `outreach_drafts` has no DB-level uniqueness on (company_id, contact_id, sequence_step), no CHECK constraints linking `approval_status` to who approved it, and only one DB-side trigger (`prevent_sent_draft_deletion`). All other gates — quality, attestation, daily caps, tier-1 dual review, cooldown, step gap, bounce rate — are enforced in Python and only at certain code paths. Three independent code paths can drive `approval_status='approved'`: the approval HTTP endpoint, the `review_manifest.py` batch approval, and operational scripts (`pending_draft_reconciliation.py`, `rejected_draft_reassessment.py`) that write directly to Supabase using the service-role key.

The most critical architectural risks observed: (1) **multiple writers to `approval_status` that bypass the approval endpoint's quality gate, attestation, and per-reviewer cap**, (2) **two different `OutreachAgent` classes** living in `agents/outreach.py` and `agents/outreach_agent.py` with different gate logic, (3) **`sent_at` is set before assertions run** — failures rely on a non-transactional Python rollback that can orphan drafts, (4) **multi-source send limits with documented mismatches** (`outreach_send_config.daily_limit` vs `workspaces.settings.daily_send_limit` vs `config/limits.yaml::outreach.daily_send_limit` vs `pace_limiter.CAMPAIGN_DEFAULTS`), and (5) **reviewer column gate falls open**: when the migration adding `approved_by`/`reviewed_at` is missing, the strict send filter logs a warning and silently sends with `approval_status='approved'` only — so an unattested draft can still be sent.

The system is also event-sourced only in name. `interactions` is the closest thing to an event log but is written non-transactionally as a side effect of many actions, so reconstructing state from it is unsafe. Real state lives in mutable columns on `contacts`, `companies`, `outreach_drafts`, `campaign_threads`, and `engagement_sequences`.

## B. System Component Inventory

### API routes (all under `backend/app/api/routes/`)
The router is mounted in `backend/app/api/main.py` (lines ~2257–2296).

| File | Notable routes (prefix shown) |
|------|---------|
| `approvals.py` | `GET /api/approvals/`, `GET /sent`, `GET /approved-queue`, `GET /alerts`, `POST /{id}/approve`, `PATCH /{id}/edit`, `POST /{id}/reject`, `POST /{id}/test-send`, `GET /{id}/thread`, `GET /{id}/research` |
| `sequences.py` | `GET/POST/PATCH/DELETE /api/sequences/...`, `POST /api/sequences/launch`, `POST /api/sequences/send-approved`, `GET /api/sequences/send-status`, V2 builder routes |
| `outreach_agent.py` | `POST /api/outreach/generate`, `POST /api/outreach/generate-batch`, `GET /api/outreach/intelligence/{contact_id}`, `POST /api/outreach/score-draft/{draft_id}` |
| `hitl.py` | `GET /api/hitl/queue`, `GET /api/hitl/queue/{id}`, `PATCH /api/hitl/queue/{id}/action`, `GET /api/hitl/stats`, `POST /api/hitl/queue/{id}/suggest-response` |
| `webhooks.py` | `POST /api/webhooks/unipile`, `POST /api/webhooks/instantly`, `POST /api/webhooks/resend`, `POST /api/webhooks/trigify`, `POST /api/webhooks/meeting-transcript`, `POST /api/webhooks/apollo/phone` |
| `pipeline.py` | Pipeline status, status counts |
| `contacts.py`, `companies.py` | CRUD + listings |
| `action_queue.py` | `POST /request`, `GET ""`, `POST /{id}/complete`, `POST /{id}/skip`, `DELETE /{id}`, targets, summary |
| `actions.py` | `GET /linkedin-tasks`, `POST /linkedin-tasks/{id}/complete`, `GET /hot-replies` |
| `composer.py` | `POST /plan`, `POST /variants`, `POST /confirm`, `GET /rate-limits` |
| `ghostwriting.py` | LinkedIn post drafting + posts CRUD |
| `today.py` | "Today" page rollups |
| `threads.py`, `multi_thread.py` | Thread inspection |
| `monitoring.py` | Health snapshots, admin |
| `auth.py`, `signup.py`, `invite.py`, `onboarding.py`, `workspaces.py`, `settings.py`, `billing.py` | Tenant management |
| `analytics.py`, `quality_dashboard.py` | Dashboards |
| `meetings.py`, `deals.py`, `crm.py` | Post-meeting / CRM integration |
| `intelligence.py`, `intent_signals.py`, `lookalike.py`, `targeting.py`, `personalization.py`, `llm_qualify.py`, `voice_of_prospect.py`, `memory.py`, `content.py`, `events.py` | Intelligence/data routes |

### Background agents (`backend/app/agents/`)

| File | Class | Purpose |
|------|-------|---------|
| `base.py` | `BaseAgent`, `AgentResult` | Lifecycle, cost tracking |
| `outreach.py` | `OutreachAgent` | Draft generation (scheduler path) — 1524 lines |
| `outreach_agent.py` | `OutreachAgent` (different) | Draft generation (HTTP `/api/outreach/generate` path) |
| `engagement.py` | `EngagementAgent` | Send, sequence advance, JIT pregenerate, webhook fan-out, Instantly poll |
| `enrichment.py` | `EnrichmentAgent` | Apollo enrichment |
| `discovery.py` | discovery agents | Top-of-funnel discovery (paused) |
| `research.py` | `ResearchAgent` | Perplexity/Claude research (paused) |
| `qualification.py` | `QualificationAgent` | PQS scoring |
| `llm_qualification.py` | `LLMQualificationAgent` | LLM-based qualification |
| `reply.py` | `ReplyAgent` | Inbound reply classification + drafting response |
| `reply_classifier.py` | `ReplyClassifier` | Claude classification of inbound emails |
| `signal_monitor.py` | `SignalMonitorAgent` | Re-research for buying signals weekly |
| `signal_scrapers/` | FDA, OSHA, MEP scrapers | Weekly external signal pulls |
| `post_send_audit.py` | `PostSendAuditAgent` | Weekly + benchmark audit |
| `learning.py` | learning loop | Outcome analysis |
| `reengagement.py` | `ReengagementAgent` | Re-queue stale prospects (90d cooldown) |
| `thread.py` | thread mgmt | Cross-thread state |
| `linkedin.py`, `linkedin_sender.py` | LinkedIn ops | LinkedIn connection / DM (largely manual) |
| `bounce_hygiene.py` | `BounceHygieneAgent` | Wraps `bounce_suppressor.run_bounce_suppression` |
| `content.py` | `ContentAgent` | Content/ghostwriting generation |
| `daily_report.py` | daily report | 6am Mon–Fri summary email |
| `post_meeting.py` | post-meeting | Sync after meeting |
| `contact_backup.py` | contact backup | Weekly disk export |
| `monitoring.py` | `HealthSnapshotAgent`, `PipelineMonitor` | Per-15min health + per-run lifecycle |

### Scheduler (APScheduler — `backend/app/api/main.py` lines 2030–2218)
All triggered in-process by APScheduler `BackgroundScheduler(timezone="America/Chicago")` started in the FastAPI lifespan.

| Job ID | Trigger | Function |
|--------|---------|----------|
| `health_snapshot` | interval 15m | `_run_health_snapshot` |
| `pipeline_qc` | interval 15m | `_run_pipeline_qc` (executes `scripts/pipeline_qc.py`) |
| `send_approved` | cron Mon–Fri 8–11 :00/:30 Chicago | `_run_send_approved` → `EngagementAgent.run("send_approved")` per workspace |
| `process_due` | interval 1h | `_run_process_due_sequences` → `EngagementAgent.run("process_due")` |
| `poll_instantly` | interval 6h | `_run_poll_instantly` |
| `hitl_snoozed` | interval 15m | `_run_process_hitl_snoozed` |
| `hitl_auto_archive` | interval 1h | `_run_auto_action_low_priority` |
| `personalization_refresh` | interval 24h | `_run_personalization_refresh` |
| `jit_pregenerate` | interval 24h | `_run_jit_pregenerate` |
| `gmail_intake` | interval 15m | `_run_gmail_intake` |
| `qualification` | interval 15m | `_run_qualification` |
| `draft_generation` | interval 5m | `_run_draft_generation` |
| `weekly_post_send_audit` | cron Sun 7am | `_run_weekly_post_send_audit` |
| `weekly_approval_audit` | cron Fri 9am | `_run_weekly_approval_audit` |
| `weekly_contact_backup` | cron Sat 5am | `_run_weekly_contact_backup` |
| `weekly_signal_scrapers` | cron Sat 6am | `_run_weekly_signal_scrapers` |
| `signal_monitor` | cron Sun 6am | `_run_signal_monitor` |
| `reengagement` | cron Sun 8am | `_run_reengagement` |
| `weekly_cost_summary` | cron Mon 8am | `_run_weekly_cost_summary` |
| `daily_report` | cron Mon–Fri 6am | `_run_daily_report` |
| `intent_refresh` | cron 5am daily | `_run_intent_refresh` |
| `bounce_hygiene` | cron 3am daily | `_run_bounce_hygiene` |
| (commented out) | — | `research`, `enrichment`, `pipeline_monitor`, `auto_approve`, `pipeline_advance_heartbeat`, `fb_discovery`, `mfg_discovery` — explicitly disabled 2026-05-07/08 |

Reactive jobs added at runtime (one-shot): `_schedule_post_send_intent_refresh` adds a one-shot 24h date job after a successful send batch.

### Operational scripts

| File | Purpose |
|------|---------|
| `weekend_run.py` | Continuous pipeline loop (research/qualify/enrich/draft), buffer/spend gated |
| `run_pipeline_loop.sh` | Shell parallel-shards orchestrator for research+qualification+enrichment |
| `scripts/pipeline_qc.py` | Health checks, auto-fixes OEC staleness, alert email |
| `scripts/dry_run_send.py` | Read-only preview of the send queue |
| `scripts/pending_draft_reconciliation.py` | **Direct DB writes** to `approval_status='approved'` for pending drafts that pass content checks |
| `scripts/rejected_draft_reassessment.py` | **Direct DB writes** to `approval_status='approved'` for previously rejected drafts |
| `scripts/reconcile_resend_csv.py` | Reconcile Resend CSV exports against drafts |
| `scripts/remediate_company_bounce_status.py` | One-off fix for tiered-suppression migration |
| `scripts/import_instantly_leadfinder.py`, `scripts/seed_fb_named_companies.py`, `scripts/dedup_companies.py`, `scripts/backfill_*` | Imports/backfills |
| `scripts/zb_verify_targeted.py` | ZeroBounce verification CLI |
| `backend/scripts/run_outreach.py`, `run_qualification.py`, `run_research.py`, `run_enrichment.py`, `run_discovery.py`, `run_full_pipeline.py`, `run_daily_actions.py`, `run_poll_instantly.py` | CLI wrappers over agents |
| `backend/scripts/send_queue.py` | CLI dump of priority queue (read-only) |
| `backend/scripts/push_to_sequences.py`, `manage_thread.py`, `daily_outreach.py` | Operational tools |
| `governance_enforcement_trace.py`, `send_path_self_test.py`, `synthetic_reply_end_to_end_test.py` | Diagnostic tools (root of repo) |

### Configuration files (`config/`)

| File | Governs |
|------|---------|
| `limits.yaml` | Spend caps, QC thresholds, pipeline guards, batch sizes, sleep, daily send limit, reviewer cap, send_config defaults/ramp, notification routing, queue priority |
| `sequences.yaml` | All sequence definitions (linkedin_relationship, email_value_first, …), global anti-patterns, channel orchestration rules, linkedin_automation flags, reply strategies |
| `outreach_guidelines.yaml` | Sender identity, voice, signatures, must/never lists, banned phrases, banned characters, subject/opening rules, sender_pool |
| `offer_context.yaml` | Product positioning facts |
| `icp.yaml` | ICP definitions, NAICS allowlist |
| `signal_weights.yaml` | Buying signal weights → PQS |
| `scoring.yaml` | PQS scoring rules |
| `content_guidelines.yaml`, `linkedin_messages_guidelines.yaml` | Per-channel guidelines |
| `competitors.yaml` | Competitor names (used in suppression) |
| `manufacturing_ontology.yaml` | Tier→sub-sector mapping, value messaging |

### Database migrations (`supabase_migrations/migrations/` plus root `migrations/`)
Schema is defined by `001_initial_schema.sql` (companies, contacts, research_intelligence, outreach_drafts, interactions, engagement_sequences, api_costs, learning_outcomes; enums `company_status`, `approval_status`, `channel_type`, `interaction_type`) + 47 incremental migrations through `049_review_manifests.sql`. The root `migrations/` directory contains a parallel/older series (`001_campaign_threads.sql`…`008_memory_rpc_functions.sql`); both sets target the same DB. Most important schema deltas relevant to outreach lifecycle:

- `003_protect_sent_emails.sql` — trigger `protect_sent_drafts_from_deletion` blocks deleting a row when `sent_at IS NOT NULL`. Updates are NOT blocked.
- `010_contact_state_machine.sql` — `contacts.outreach_state`, `outreach_state_updated_at`, `last_touch_*`, `open_count`/`click_count`, `intent_score`; `companies.outreach_active`, `primary_contact_id`, `outreach_started_at`, `outreach_last_touch_at`; `outreach_state_log` audit table.
- `029_outreach_send_config.sql` — `outreach_send_config (workspace_id, daily_limit, batch_size, min_gap_minutes, send_enabled)`; adds `outreach_drafts.resend_message_id`, `resend_status`.
- `031_contact_outreach_eligibility.sql` — `contacts.is_outreach_eligible`, `contact_tier`, `email_name_verified`.
- `032_contact_email_status.sql` — `contacts.email_status` ('verified', 'catch_all', 'invalid', 'bounce', 'unverified', 'unknown').
- `033_outbound_eligible_contacts.sql` — hard SQL gate table + trigger `trg_contact_eligibility` + RPC `refresh_outbound_eligible`.
- `034_send_assertions_and_outcomes.sql` — `send_assertions` (every assertion result), `outreach_outcomes` (one row per send + downstream conversion), `icp_definitions`, `icp_exclusions`.
- `035_reply_classifications_signals_threading.sql`, `043_draft_model_tracking.sql`, `044_edit_feedback.sql` — `outreach_drafts.model`, `outreach_edit_feedback`.
- `047_send_assertions_context.sql` — adds `assertion_context` column to `send_assertions`.
- `048_tiered_suppression.sql` — `suppression_log` table, escalation logic, `contacts.suppression_reason`, `companies.suppression_reason`. Backfills bounced contacts into suppression_log.
- `049_review_manifests.sql` — `review_manifests` table for hash-bound batch approval.

A migration that adds `outreach_drafts.approved_by` (UUID FK), `outreach_drafts.reviewed_at`, `outreach_drafts.attestation` is **referenced as a TODO** in `approvals.py` lines 37 and `engagement.py` lines 432–437 and 471–485 — code falls back gracefully when these columns are missing. There is no migration file for them in either migrations directory.

## C. Draft Lifecycle Code Path Inventory

```
Operation: CREATE (scheduler path)
File: backend/app/agents/outreach.py
Function: OutreachAgent.run → insert_outreach_draft
Trigger: Scheduler job `draft_generation` (every 5 min) → _run_draft_generation → for_each_workspace → OutreachAgent.run
Tables Read: companies, contacts, outbound_eligible_contacts, research_intelligence, outreach_drafts (prior_messages, prior_rejections, edit feedback, sibling email dedup), company_signals, outreach_edit_feedback, icp_definitions, suppression_log (via is_suppressed), engagement_sequences, interactions (recent activity), company_outreach_state
Tables Written: outreach_drafts (insert), outreach_outcomes (insert with static context), send_assertions (one row per assertion result), company_outreach_state (via ThreadingCoordinator), companies.status='outreach_pending' (post-loop), interactions (rejection flag note when threshold)
Fields Mutated: outreach_drafts.{approval_status,subject,body,sequence_name,sequence_step,channel,model,top_signal_id,top_signal_type,personalization_notes,rejection_reason}; companies.status; company_outreach_state.state
External APIs Called: Anthropic Messages API (system prompt from outreach_guidelines.yaml + offer_context.yaml; user prompt with research+hooks+history)
Transactional: No — multi-step Python loop, each Supabase write is its own HTTP call. No transaction across draft insert, outcome insert, threading update, A/B record, company status update.
Idempotency Protection: Partial — Database.insert_outreach_draft has a dedup guard on (company_id, contact_id, sequence_step) when approval_status in {pending,approved,edited,rejected}; cross-company email dedup for step 1 (returns {} silently).
Bypasses Approval/Governance: No — output is always approval_status='pending' (or 'rejected' for integrity/url violations) and never sent directly.
Notes: Inserts `outreach_outcomes` BEFORE the draft has been approved or sent. send_id points to a draft that may never actually send. The model integrity regex (_INTEGRITY_RULES) is the only ML-output gate; if it false-negatives, fabricated content flows to the approval queue.
```

```
Operation: CREATE (HTTP path — different agent)
File: backend/app/agents/outreach_agent.py
Function: OutreachAgent.generate_draft / generate_batch
Trigger: POST /api/outreach/generate, POST /api/outreach/generate-batch
Tables Read: companies, contacts, outreach_drafts (existing-draft check on sequence_name='initial_outreach' only)
Tables Written: outreach_drafts (via Database.insert_outreach_draft), api_costs
Fields Mutated: outreach_drafts.{subject,body,personalization_notes,sequence_name='initial_outreach',sequence_step,approval_status,rejection_reason if url-violation}
External APIs Called: Anthropic Messages API (different PERSONA_PROMPTS + CLUSTER_CONTEXT system; model resolved by model_router.get_model("outreach_step1" vs "outreach_step2plus"))
Transactional: No
Idempotency Protection: Partial — only skips if a non-rejected draft exists for that exact (company_id, contact_id, sequence_name='initial_outreach'). Does not check sequence_step. Does not deduplicate against scheduler-generated drafts that use sequence_name='email_value_first' etc.
Bypasses Approval/Governance: No (creates pending) — but ALSO bypasses every gate the scheduler OutreachAgent runs: suppression, ICP exclusion, threading coordinator, channel coordinator, has_recent_activity, run_pre_send_assertions, is_outreach_eligible check.
Notes: This is a second OutreachAgent in a separate file. The HTTP path skips the integrity regex and the rejection-rate flag. It uses a different sequence_name namespace which means scheduler's dedup will not see drafts from this path.
```

```
Operation: MODIFY / EDIT (in-place draft body change)
File: backend/app/api/routes/approvals.py
Function: edit_draft (PATCH /api/approvals/{draft_id}/edit), and approve_draft writes edited_body when body.edited_body provided
Trigger: HTTP PATCH from dashboard
Tables Read: outreach_drafts (via Database.update_outreach_draft)
Tables Written: outreach_drafts.edited_body, outreach_edit_feedback (only on approve+edit path)
Fields Mutated: outreach_drafts.edited_body (approval_status untouched on /edit; on /approve it transitions pending → edited)
External APIs Called: None
Transactional: No
Idempotency Protection: None (last write wins)
Bypasses Approval/Governance: No
Notes: edit_draft does not re-run the quality gate or integrity check. A reviewer can paste in fabricated content that the original draft generator would have rejected, and then approve it through /approve where the gate runs against edited_body — but only the error-severity issues; warnings pass.
```

```
Operation: APPROVE (primary path)
File: backend/app/api/routes/approvals.py
Function: approve_draft (POST /api/approvals/{draft_id}/approve)
Trigger: HTTP POST from dashboard
Tables Read: outreach_drafts (with companies join), outreach_drafts count by approved_by in past 24h (for cap), companies.tier (for dual-review), users via get_current_user
Tables Written: outreach_drafts.{approval_status='approved'|'edited'|'pending_second_review', approved_at, approved_by, reviewed_at, attestation, edited_body if provided}; outreach_edit_feedback (best-effort, non-blocking); audit_log via log_audit_event_from_ctx
Fields Mutated: outreach_drafts.{approval_status, approved_at, approved_by, reviewed_at, attestation, edited_body}
External APIs Called: None
Transactional: No
Idempotency Protection: None — re-clicking approve on an already-approved draft updates approved_at again
Bypasses Approval/Governance: No — gates: quality_gate via validate_draft (only error-severity), tier-1 dual review, daily reviewer cap, attestation recording. All optional via ?force=true.
Notes: Attestation is "recorded for audit purposes but not enforced as a hard gate" (line 397–399). Pydantic AttestationModel requires all five booleans, but the body.attestation is optional and only inspected to record JSON. Reviewer-column write retries silently strip the columns if the migration is missing — so a draft can be "approved" with no approved_by recorded and the engagement scheduler then falls back to sending it under the legacy filter.
```

```
Operation: APPROVE (batch manifest path)
File: backend/app/core/review_manifest.py
Function: ReviewManifest.approve_manifest (lines 270–352)
Trigger: Programmatic / API caller passes a manifest_id + list of draft_ids
Tables Read: outreach_drafts, review_manifests
Tables Written: outreach_drafts.{approval_status='approved', approved_at, approved_by}; review_manifests.{approved_at, approved_by, approval_decisions, status}
Fields Mutated: outreach_drafts.{approval_status, approved_at, approved_by}
External APIs Called: None
Transactional: No (per-draft try/except, partial success returns errors[] + approved[])
Idempotency Protection: Hash gate — current body sha256 must equal manifest's stored hash; skipped if mismatch
Bypasses Approval/Governance: YES — skips: quality gate (validate_draft), attestation, tier-1 dual review, per-reviewer daily cap. Reviewer column writes are unconditional (the function assumes the columns exist).
Notes: This is a distinct approval surface that operates on a separate trust model (hash-pinned bulk approval). The hash binding protects against body change after manifest issue but not against the absence of every other gate. Manifest expiry default is 24h.
```

```
Operation: APPROVE (script path — pending)
File: scripts/pending_draft_reconciliation.py
Function: main (writes update at line 472)
Trigger: Manual CLI invocation by operator (no auth)
Tables Read: outreach_drafts joined with companies+contacts (lines ~335)
Tables Written: outreach_drafts.{approval_status='approved', approved_at, approved_by='avanish' (hardcoded string, not a user UUID), body, edited_body}
Fields Mutated: outreach_drafts.{approval_status, approved_at, approved_by, body, edited_body}
External APIs Called: None
Transactional: No
Idempotency Protection: None
Bypasses Approval/Governance: YES — bypasses every endpoint gate: quality gate, attestation, tier-1 dual review, per-reviewer cap, audit_log emission, edit-feedback capture.
Notes: APPROVED_BY = "avanish" (str). outreach_drafts.approved_by may be a UUID column — writing a string can cast-error silently if the column is text or fail loudly if it is UUID. The script also rewrites `body` (the original, supposedly stable draft body) plus edited_body when fixes_applied, which means it modifies the immutable record of what the model originally produced.
```

```
Operation: APPROVE (script path — rejected)
File: scripts/rejected_draft_reassessment.py
Function: main (writes update at line 557)
Trigger: Manual CLI invocation
Tables Read: outreach_drafts, companies, contacts
Tables Written: outreach_drafts.{approval_status='approved', approved_at, approved_by='avanish', rejection_reason=NULL, body, edited_body}
Fields Mutated: Same as above, plus rejection_reason cleared
Notes: Re-approves previously REJECTED drafts. Once rejection_reason is wiped, the audit trail of why the draft was rejected in the first place is lost. The reassessment script's classification logic is decoupled from the live integrity regex in outreach.py — they can drift apart.
```

```
Operation: REJECT
File: backend/app/api/routes/approvals.py
Function: reject_draft (POST /api/approvals/{draft_id}/reject)
Trigger: HTTP POST
Tables Read: outreach_drafts
Tables Written: outreach_drafts.{approval_status='rejected', rejection_reason}
Fields Mutated: outreach_drafts.{approval_status, rejection_reason}
External APIs Called: None
Transactional: No
Idempotency Protection: None
Bypasses Approval/Governance: N/A
Notes: log_audit_event_from_ctx is called.
```

```
Operation: REJECT (auto, draft generation)
File: backend/app/agents/outreach.py
Function: OutreachAgent.run (integrity regex block at lines 966–984, URL-violation block at 988–999)
Trigger: Inline after model output parsed, before save
Tables Written: outreach_drafts with approval_status='rejected', rejection_reason='auto_rejected|<tags>' or 'url_in_step_1'; interactions (rejection flag note when threshold)
Bypasses Approval/Governance: Inverts it — it never enters approval queue.
```

```
Operation: CLAIM (atomic sent_at)
File: backend/app/agents/engagement.py
Function: EngagementAgent._send_approved_drafts (lines 554–569)
Trigger: Scheduler job `send_approved` (Mon–Fri 8–11 Chicago, :00 and :30), or POST /api/sequences/send-approved
Tables Read: outreach_drafts (approved + unsent + non-empty subject + channel=email; with approved_by+reviewed_at filter when migration present), outreach_send_config, companies, contacts (fresh state pre-assertion), suppression_log (via is_suppressed)
Tables Written: outreach_drafts.sent_at = now() (compare-and-swap: WHERE sent_at IS NULL); then conditional ROLLBACK to sent_at=NULL on assertion failure
Fields Mutated: outreach_drafts.sent_at
Transactional: No DB transaction. The "atomic claim" is a single UPDATE … WHERE sent_at IS NULL. The rollback (line 175–207) is a follow-up UPDATE. If the rollback fails, a CRITICAL log fires and the draft is orphaned.
Idempotency Protection: Yes — the WHERE sent_at IS NULL clause is the only mechanism preventing two scheduler instances from double-sending.
Bypasses Approval/Governance: No
Notes: When called with explicit draft_ids from /api/sequences/send-approved, the strict reviewer column filter is intentionally skipped (lines 451–457) with comment "explicit draft_ids selection IS the human attestation."
```

```
Operation: SEND (Resend dispatch)
File: backend/app/agents/engagement.py
Function: EngagementAgent._send_approved_drafts (lines 730–740)
Trigger: After claim + assertions pass
Tables Read: outreach_send_config (sender_pool, reply_to), outreach_guidelines.yaml (sender_pool fallback), workspaces.settings
Tables Written: outreach_drafts.resend_message_id; interactions (type='email_sent'); companies.status='contacted'; companies.outreach_active/outreach_last_touch_at (via set_company_outreach_active); campaign_threads (insert or update last_sent_at, current_step); thread_messages (outbound record); engagement_sequences (insert via insert_engagement_sequence); contacts.outreach_state via update_contact_state (with extra_updates last_touch_*); outreach_state_log
Fields Mutated: A large fan-out. Each side effect is in its own try/except — "non-fatal so a DB hiccup doesn't orphan a sent draft."
External APIs Called: Resend Emails.send with idempotency_key=draft["id"]
Transactional: No. The send happens, then 6+ follow-on writes happen. Each may fail independently.
Idempotency Protection: Resend idempotency_key=draft.id (provider-side dedup); DB compare-and-swap on sent_at (caller-side). Both must be intact for true exactly-once.
Bypasses Approval/Governance: Send-path assertions run BEFORE Resend, so a fail rolls back. But the bounce_rate_ok gate (system-wide) is checked once per loop entry in run_pre_send_assertions — if the first contact passes, subsequent ones in the same batch are not re-checked against rolling bounce rate.
Notes: The order is claim → fetch fresh contact → run assertions → on fail rollback. Between the claim and the rollback, the row carries sent_at != NULL — any reader (UI listing "sent" emails, post-send audit, bounce rate calc) sees the row as "sent" for the duration. If multiple concurrent batches hit different drafts, this is fine; if the rollback fails, the row is forever inconsistent.
```

```
Operation: SEND (manual single-draft re-send)
File: backend/app/api/routes/approvals.py
Function: test_send_draft (POST /api/approvals/{draft_id}/test-send)
Trigger: HTTP POST with operator's own email as recipient
Tables Read: outreach_drafts joined with companies+contacts
Tables Written: interactions (type='note', subject='Test email sent to …')
Fields Mutated: None on outreach_drafts (does NOT set sent_at)
External APIs Called: Resend Emails.send to test_email (the operator's address)
Transactional: No
Idempotency Protection: None — repeated calls send repeated test emails
Bypasses Approval/Governance: YES by design — this is for operator preview. But it uses the live Resend API key and sender_pool, so it consumes sender reputation if abused.
Notes: Does not check approval_status. Could be invoked on a rejected or pending draft.
```

```
Operation: FREEZE / SUPPRESS (system-wide bounce-rate gate)
File: backend/app/core/pre_send_assertions.py
Function: assert_bounce_rate_ok
Trigger: First contact of every send_path tick
Tables Read: outreach_drafts (count where sent_at >= 7d cutoff, count where resend_status='bounced' in same window)
Tables Written: send_assertions
External APIs Called: None
Transactional: No
Notes: This is the only system-wide kill switch in the send path. It does NOT halt the whole tick; it raises AssertionFailure on the first contact, which causes that contact's sent_at to roll back. The next iteration of the for-loop calls run_pre_send_assertions again and the gate re-fires. Net effect: the batch effectively pauses, but it's per-contact, not atomic.
```

```
Operation: FREEZE (kill switch — flag-based)
File: config/limits.yaml (agents.discovery.enabled, agents.enrichment.enabled) + backend/app/api/main.py scheduler add_job comments
Function: agents check L.discovery_enabled / L.enrichment_enabled in their run() early-exit; main.py has commented-out scheduler add_job lines
Trigger: Editing limits.yaml or commenting/uncommenting code in main.py
Notes: send_enabled is in config/limits.yaml at the operator level (outreach_send_config.send_enabled), settings.send_enabled at env-var level, and AUTH_DEMO_MODE / send_window_end at deploy level. Mixing levels of freeze is high-risk.
```

```
Operation: SUPPRESS (record_suppression / maybe_escalate_to_company)
File: backend/app/core/suppression.py
Function: record_suppression, maybe_escalate_to_company
Trigger: webhooks._handle_email_bounced (Instantly), webhooks.resend_webhook (email.bounced, email.complained), bounce_suppressor sweep
Tables Read: suppression_log (existing entries)
Tables Written: suppression_log (insert)
Fields Mutated: None directly (callers update contacts.{status,outreach_state}, companies.{status} separately)
```

```
Operation: SUPPRESS (bounce hygiene sweep)
File: backend/app/core/bounce_suppressor.py
Function: run_bounce_suppression
Trigger: Scheduler job `bounce_hygiene` (3am Chicago daily) → BounceHygieneAgent.run
Tables Read: outreach_drafts joined with contacts (bounced_at IS NOT NULL), do_not_contact
Tables Written: contacts.{status='bounced', is_outreach_eligible=false}; do_not_contact (insert at email + domain when ≥3 distinct contacts in domain bounced)
Bypasses Approval/Governance: N/A
Notes: Runs WITHOUT going through suppression_log — directly updates contacts.status and inserts into do_not_contact. So tiered_suppression (migration 048) and this older sweep can disagree.
```

```
Operation: RETRY (assertion failure rollback)
File: backend/app/agents/engagement.py
Function: _rollback_sent_at (lines 156–207)
Trigger: AssertionFailure / contact_fetch_failed / assertion_exception inside _send_approved_drafts
Tables Written: outreach_drafts.sent_at = NULL
Idempotency Protection: Best-effort — if the rollback raises, a CRITICAL log fires and the draft is orphaned
Notes: There is no automated retry of the orphaned draft. The next scheduler tick will see sent_at IS NOT NULL and skip it forever.
```

```
Operation: DELETE
File: backend/app/api/routes/sequences.py and other paths
Function: Various delete endpoints
Trigger: HTTP DELETE
Notes: Migration 003 trigger `protect_sent_drafts_from_deletion` blocks deletion of any outreach_drafts row with sent_at IS NOT NULL. Pending/approved/rejected/edited rows are deletable.
```

## D. Contact and Company State Mutation Inventory

```
Operation: contacts.status / outreach_state / email_status / is_outreach_eligible
File: backend/app/agents/engagement.py
Function: process_webhook_event (line 1697), _send_approved_drafts (update_contact_state call line 870)
Trigger: Webhook (engagement.process_webhook_event) or successful send
Tables Written: contacts.{status, outreach_state, last_touch_channel, last_touch_at}; outreach_state_log
Bypasses Approval/Governance: N/A
```

```
Operation: contacts.status='bounced' / outreach_state='bounced'
Multiple paths (highest risk of divergence):
  1. backend/app/api/routes/webhooks.py _handle_email_bounced — Instantly webhook path: db.update_contact(contact_id, {"outreach_state":"bounced", "status":"bounced"})
  2. webhooks.resend_webhook (email.bounced) — db.update_contact + record_suppression(scope='contact') + maybe_escalate_to_company
  3. backend/app/core/bounce_suppressor.run_bounce_suppression — daily 3am sweep: contacts.{status='bounced', is_outreach_eligible=false} + do_not_contact insert
  4. engagement.process_webhook_event (legacy Instantly fallback) — companies.status='bounced', contacts.status='bounced', cancel sequences
Tables Written: Each path writes a different subset.
Transactional: No across the multi-write set
Idempotency Protection: None — repeated webhooks re-update
Bypasses Approval/Governance: N/A
Notes: All four paths can fire for the same bounce event in sequence. The legacy engagement.process_webhook_event sets companies.status='bounced' which is the very status the new tiered_suppression doc says NOT to use ("'bounced' is intentionally excluded — bounce suppression now lives in suppression_log at contact scope"). New webhook handler path correctly uses tiered suppression but old code is still wired up.
```

```
Operation: contacts.outreach_state=touch_N_sent
File: backend/app/agents/engagement.py
Function: update_contact_state via Database.update_contact_state inside _send_approved_drafts after a send succeeds
Tables Written: contacts.{outreach_state, outreach_state_updated_at, last_touch_channel, last_touch_at}; outreach_state_log (audit)
Transactional: No — wrapped in try/except marked "non-fatal"
```

```
Operation: contacts.outreach_state='unsubscribed'
File: backend/app/api/routes/webhooks.py _handle_email_reply (auto-handle classification=='unsubscribe'), _handle_email_unsubscribed; backend/app/api/routes/hitl.py (unsubscribe action)
Tables Written: contacts.outreach_state='unsubscribed'; campaign_threads.status='unsubscribed'; do_not_contact (insert); engagement_sequences.status=… (varies)
Notes: do_not_contact and suppression_log are written by different paths inconsistently — webhook unsubscribed writes do_not_contact only; resend bounce writes suppression_log + do_not_contact.
```

```
Operation: contacts.reply_sentiment / linkedin_status
File: backend/app/agents/reply.py, channel_coordinator.py (read-only), webhooks.py (sets via thread updates)
Trigger: Reply classification
Tables Written: contacts.reply_sentiment indirectly via various agents
Notes: Set via separate code paths; channel_coordinator reads it as a traction signal.
```

```
Operation: contacts.is_outreach_eligible (true/false)
Setters:
  - scripts/icp_prefilter.py — bulk false-set based on title classifier
  - backend/app/core/title_classifier.py (called during import)
  - backend/app/agents/discovery.py / enrichment.py during ingest
  - backend/app/core/bounce_suppressor.py daily sweep (false)
  - migrations 031, 042, etc. at create time
Trigger Effect: Trigger trg_contact_eligibility on contacts UPDATE keeps outbound_eligible_contacts in sync — IF the trigger remains attached and the Python service hasn't dropped it.
```

```
Operation: companies.status
Setters (non-exhaustive):
  - outreach.py: companies.status='outreach_pending' after generating drafts for a company
  - engagement.py: 'contacted' on send, 'engaged' on open/click, 'bounced' on bounce (legacy fallback)
  - webhooks.py: 'engaged' on email.opened/clicked, 'bounced' on email.bounced (legacy), 'not_interested' on spam complaint, 'converted' on hitl mark_converted, 'qualified' on reengagement re-queue
  - reply.py: 'engaged' on positive reply
  - hitl.py: 'converted' on mark_converted
  - bounce_suppressor + suppression_log: do NOT touch companies.status (modern tiered architecture intentionally avoids this)
Fields Mutated: companies.status (enum company_status; trigger update_status_changed_at fires)
Transactional: No across multi-event sequences
Notes: The same company can ratchet through status in multiple paths simultaneously. update_company in database.py has an `allow_downgrade` kwarg referenced in webhooks (resend complaint path) but the default Database.update_company method does not honor it — it just writes whatever you pass. Code at webhooks.py:989 calls `db.update_company(company_id, {"status": "not_interested"}, allow_downgrade=False)` but update_company does not accept that kwarg in the version in database.py — this call would TypeError at runtime if reached.
```

```
Operation: companies.outreach_active / primary_contact_id / outreach_started_at / outreach_last_touch_at
File: backend/app/core/database.py set_company_outreach_active
Trigger: Inside engagement._send_approved_drafts after a successful send
Tables Written: companies.{outreach_active, primary_contact_id, outreach_started_at, outreach_last_touch_at}
Notes: Best-effort try/except — non-fatal if it fails. Result: companies.outreach_active can be FALSE for a company that actually has sends in flight, if the post-send write transiently failed.
```

```
Operation: companies.status='bounced' (legacy)
Files writing: backend/app/agents/engagement.py:1793, webhooks.py legacy Instantly handler
Notes: This propagates a single bounce up to company scope, which the tiered_suppression doc explicitly says to avoid. Conflict between legacy code path and migration 048 intent.
```

```
Operation: companies.suppression_reason
File: Modern path (suppression_log + companies.suppression_reason column from migration 048).
Setters: bounce_suppressor (domain-level), webhooks._handle_email_bounced / resend (spam complaint escalation)
Notes: The column exists but no central writer keeps it in sync with the suppression_log — most code reads suppression_log directly via is_suppressed().
```

## E. Scheduler and Worker Inventory

| Worker | File / Class | Trigger | Frequency | Reads | Writes | Concurrency | Parallel-self? |
|--------|--------------|---------|-----------|-------|--------|-------------|----------------|
| send_approved | `_run_send_approved` → `EngagementAgent._send_approved_drafts` | APScheduler cron | Mon–Fri 8–11 :00/:30 Chicago | outreach_drafts, outreach_send_config, contacts, companies, suppression_log | outreach_drafts.sent_at, interactions, campaign_threads, thread_messages, engagement_sequences, contacts.outreach_state, companies.{status, outreach_active}, send_assertions, outreach_state_log | Atomic claim via WHERE sent_at IS NULL; no other concurrency primitive | In theory yes (multiple Railway instances) — protected only by the compare-and-swap |
| process_due | `EngagementAgent._process_due_sequences` | interval | 1h | engagement_sequences, outreach_drafts, campaign_threads, thread_messages, contacts, companies, campaign_sequence_definitions_v2 | outreach_drafts (via OutreachAgent.run call), engagement_sequences, interactions (linkedin task records) | None | Yes if scheduler restarted overlapping; no DB lock |
| jit_pregenerate | `_jit_pregenerate_upcoming` | interval | 24h | engagement_sequences (next_action_at within 3d), outreach_drafts | outreach_drafts (via OutreachAgent.run) | Dedup via existing-pending check | Yes — two ticks could race and the existing-pending check is not race-safe |
| draft_generation | `_run_draft_generation` → OutreachAgent.run per workspace | interval | 5m | companies, outbound_eligible_contacts, contacts, research_intelligence | outreach_drafts, outreach_outcomes, send_assertions, company_outreach_state, companies.status | Database.insert_outreach_draft dedup | Yes — overlapping 5m ticks rely on dedup |
| poll_instantly | `_poll_instantly_events` | interval | 6h | outreach_drafts, contacts, interactions | interactions (via process_webhook_event), companies, engagement_sequences | None | Yes |
| gmail_intake | `_gmail_intake_workspace` | interval | 15m | Gmail IMAP/API, campaign_threads, contacts | thread_messages, hitl_queue, campaign_threads, interactions | None — IMAP STORE \Seen flag is the only dedup | Two ticks could double-process if marking-as-read fails |
| pipeline_qc | `_run_pipeline_qc` (executes scripts/pipeline_qc.py) | interval | 15m | many | outbound_eligible_contacts via refresh_outbound_eligible; sends alert emails | None | Yes |
| health_snapshot | `HealthSnapshotAgent.capture` | interval | 15m | many | health_snapshots table | None | Yes |
| hitl_snoozed | inline in main.py | interval | 15m | hitl_queue | hitl_queue.{status='pending', snoozed_until=null} | None | Two ticks could compete; idempotent because filter is `eq('status','snoozed')` |
| hitl_auto_archive | `_run_auto_action_low_priority` | interval | 1h | hitl_queue | hitl_queue.status='archived' (presumably) | None | — |
| qualification | `_run_qualification` → QualificationAgent | interval | 15m | companies (status='researched'), research_intelligence | companies.{pqs_*, status='qualified'/'disqualified'} | None | Yes |
| personalization_refresh | `PersonalizationBatch.run_batch` | interval | 24h | top 100 companies | companies.{personalization_hooks, pain_signals}, api_costs | None | — |
| daily_report | `_run_daily_report` | cron 6am Mon–Fri | daily | many | sends email via Resend | — | — |
| intent_refresh | `_run_intent_refresh` | cron 5am | daily | companies, intent_signals via Apollo | companies.pqs_timing, intent_signals | — | — |
| bounce_hygiene | `BounceHygieneAgent.run` | cron 3am | daily | outreach_drafts (bounced_at), contacts | contacts.{status='bounced', is_outreach_eligible=false}, do_not_contact | None | — |
| weekly_post_send_audit | `_run_weekly_post_send_audit` → PostSendAuditAgent | cron Sun 7am | weekly | recent sends | audit report | — | — |
| weekly_approval_audit | `_run_weekly_approval_audit` | cron Fri 9am | weekly | recent approvals | audit report (Slack/email) | — | — |
| weekly_contact_backup | `_run_weekly_contact_backup` | cron Sat 5am | weekly | contacts | local disk CSV at `/Volumes/Digitillis/Data/prospectiq_backups/` | — | — |
| weekly_signal_scrapers | `_run_weekly_signal_scrapers` | cron Sat 6am | weekly | FDA / OSHA / MEP public sources | company_signals | — | — |
| signal_monitor | `SignalMonitorAgent.run` | cron Sun 6am | weekly | tracked companies | research_intelligence, intent_signals, pqs_timing | — | — |
| reengagement | `ReengagementAgent.run` | cron Sun 8am | weekly | engagement_sequences (completed, past cooldown) | companies.status='qualified', interactions (note) | None | — |
| weekly_cost_summary | `_run_weekly_cost_summary` | cron Mon 8am | weekly | api_costs | email | — | — |

All workers run **in-process** inside the FastAPI web server via APScheduler. There is no external Celery/queue. Railway deployment of multiple web replicas would therefore run all schedulers in parallel, with only the compare-and-swap on `sent_at` as the per-row guard.

`weekend_run.py` is a separate long-running CLI process that bypasses the API server scheduler and drives research/qualify/enrich/draft in a loop. It uses raw `get_supabase_client()` with no workspace context wrapper for some operations.

## F. Integration Inventory

```
Provider: Apollo.io
File(s): backend/app/integrations/apollo.py
Operations: search_people (free), search_organizations, people_match (paid enrichment), organizations_enrich, organization_job_postings
Triggers: EnrichmentAgent (paused), DiscoveryAgent (paused), SignalMonitorAgent, intent_refresh scheduler, scripts/run_enrichment.py, scripts/run_discovery.py
Tables Written: companies (insert/update), contacts (insert/update), enrichment_attempts (audit log), api_costs (cost track)
Retry: 429 single retry with 60s sleep; no retry on 5xx
Rate Limiting: time.sleep(3.5) between requests; class-level _enrich_cache prevents duplicate calls in same process
Idempotency: Cache prevents reentry within a process; no DB-level "I already paid for this contact" guard beyond contacts.apollo_id UNIQUE
Failure Consistency: An Apollo response that succeeds at the HTTP layer but returns garbage data writes garbage to contacts. The class-level cache persists garbage across the agent run.
```

```
Provider: Resend (cold-outreach email)
File(s): backend/app/agents/engagement.py (calls resend.Emails.send directly), backend/app/integrations/resend_client.py (transactional path — separate)
Operations: send (cold outreach + transactional both via raw `resend` SDK), receive via webhook /api/webhooks/resend
Triggers: EngagementAgent._send_approved_drafts (scheduler), POST /api/sequences/send-approved (manual), POST /api/approvals/{id}/test-send (operator test), various ad-hoc alert sends in weekend_run.py
Tables Written: outreach_drafts.resend_message_id, .resend_status, .delivered/opened/clicked/bounced/complained_at; interactions; campaign_threads; thread_messages; contacts; companies; do_not_contact; suppression_log; engagement_sequences
Retry: None at SDK call site
Rate Limiting: stagger_seconds sleep between sends (configured per workspace)
Idempotency: idempotency_key=draft["id"] passed to Resend SDK (provider-side dedup) PLUS DB compare-and-swap on sent_at
Failure Consistency: If resend.Emails.send raises after writing sent_at, the outer except catches and logs but doesn't roll back — the draft is in "sent_at set, but no message_id, no interaction" state.
Notes: resend_client.py docstring says "transactional ONLY, NOT cold outreach" but engagement.py uses the same SDK key directly for cold outreach.
```

```
Provider: Instantly.ai
File(s): backend/app/integrations/instantly.py, backend/app/agents/engagement.py (_poll_instantly_events), backend/app/api/routes/webhooks.py (instantly_webhook), backend/app/webhooks/instantly.py
Operations: list_campaigns, create_campaign, get_campaign_analytics, pause/resume_campaign, add_leads_to_campaign, get_lead_status (used for polling)
Triggers: Webhooks (inbound), poll_instantly scheduler 6h
Tables Written: Same as engagement.process_webhook_event — interactions, companies, contacts, engagement_sequences, hitl_queue, thread_messages, campaign_threads
Retry: None
Rate Limiting: RATE_LIMIT_DELAY = 1.0 sec sleep before each call; poll iterates one contact at a time with 0.5s sleep
Idempotency: Polling path checks existing interactions before insert (stored_types set); webhook path has no dedup at the event level (a replayed webhook will write a duplicate interaction)
Failure Consistency: Webhook handlers are best-effort; failures return 200 with status=ignored
Notes: Used as "warmup only" per project memory (not sends) but the API client still has full send capability.
```

```
Provider: Gmail (IMAP + Gmail API)
File(s): backend/app/integrations/gmail_imap.py, backend/app/integrations/gmail_api_client.py
Operations: fetch_unseen_replies (IMAP), fetch_recent_replies (Gmail API), mark_as_read
Triggers: gmail_intake scheduler 15m
Tables Written: thread_messages, hitl_queue, campaign_threads, interactions (type='email_replied' indirectly)
Retry: None at fetch; reading is non-destructive
Rate Limiting: IMAP serial per account; SDK rate limit not enforced explicitly
Idempotency: IMAP path marks messages \Seen after processing; Gmail API path uses lookback window — no Seen flag, relies on idempotent inserts (which are not idempotent — same message_id could insert twice if the in_reply_to check fails)
Failure Consistency: If mark_as_read fails, next tick re-processes the same reply → potential duplicate thread_messages rows and duplicate HITL queue entries
```

```
Provider: ZeroBounce
File(s): backend/app/integrations/zerobounce.py
Operations: find_email (guessformat)
Triggers: scripts/zb_verify_targeted.py, contact_filter / enrichment fallback when Apollo returned no email
Tables Written: contacts.{email, email_status}
Retry: None
Rate Limiting: None — single sync requests
Idempotency: Caller-side; no inherent dedup
Failure Consistency: On request error returns {"email": None, "status": "error"} silently. Caller must check status.
```

```
Provider: HubSpot, Salesforce
File(s): backend/app/integrations/hubspot.py, salesforce.py
Notes: Stubbed integrations for CRM sync. Not currently active in the outreach hot path.
```

```
Provider: Trigify
File(s): /api/webhooks/trigify in webhooks.py
Operations: Inbound competitor-engagement signal webhook
Tables Written: intent_signals
```

```
Provider: Unipile (LinkedIn automation)
File(s): /api/webhooks/unipile, backend/app/agents/linkedin_sender.py
Notes: LinkedIn send guarded behind linkedin_automation.auto_send_enabled=false in sequences.yaml; effectively manual/HITL.
```

```
Provider: Anthropic (Claude)
File(s): Direct anthropic.Anthropic SDK use in many places: agents/outreach.py, agents/outreach_agent.py, agents/reply.py, agents/research.py, agents/qualification.py, agents/llm_qualification.py, core/reply_classifier.py, core/draft_quality.py (no — uses heuristics), core/voice_of_prospect.py, etc.
Operations: Messages.create with various models (Sonnet, Haiku, etc.)
Triggers: Any draft generation, reply classification, content generation
Tables Written: api_costs (cost tracking)
Retry: None at SDK call site
Rate Limiting: Single SDK calls; no global rate limiter
Idempotency: None — re-running generates a fresh (different) draft
Failure Consistency: A retried call after a write-but-no-response generates two LLM calls and two drafts unless the caller's dedup catches it.
```

## G. Configuration and Governance Source Inventory

```
Source: config/limits.yaml (loaded by backend/app/core/limits.py via @lru_cache)
Surfaces:
  - spend.* (lines 12–18) — monthly cap $200, hard $270, research $93/$135, workspace defaults
  - qc_alerts.* (23–30) — open_rate_min_pct, stuck_threshold_days, outreach_pnd_max
  - pipeline.* (35–39) — draft_buffer_target 600, enrichment_cap 3000, apollo_min_buffer 2000, max_error_cycles 5
  - agents.discovery.enabled / required_naics_match / agents.enrichment.enabled (51–58) — kill switches
  - batch_sizes (65–68), sleep_seconds (74–75)
  - outreach.daily_send_limit 125 (81), outreach.max_approvals_per_reviewer_per_day 500 (84)
  - send_limits.* (92–97) — company_cooldown_days 14, step_gap_days_step_2 3, step_gap_days_step_3_plus 2, max_bounce_rate 0.02, company_lock_business_days 5
  - send_config.* (104–110) — onboarding_daily_limit 125, fallback_daily_limit 125, ramp_daily_limit 150
  - notifications.workspace_owner_email, reply_sla_hours, notify_on_positive, notify_on_question
  - queue.priority_score_batch 500
Runtime read: via L = _Limits() property accessors; @lru_cache on _load means edits require either reload_limits() or process restart.
Overridable by env var: COMPANY_COOLDOWN_DAYS, MIN_STEP_GAP_DAYS, MAX_BOUNCE_RATE, COMPANY_LOCK_BUSINESS_DAYS, MAX_APPROVALS_PER_DAY, STEP_GAP_DAYS_STEP_2/3_PLUS. Env var wins.
```

```
Source: outreach_send_config table (DB, per-workspace, migration 029)
Columns: daily_limit, batch_size, min_gap_minutes, min_gap_seconds, send_enabled, sender_pool, reply_to
Runtime read: EngagementAgent._load_send_config (engagement.py:252)
Note: This is the AUTHORITATIVE runtime cap — the comment at main.py:189–194 explicitly says workspace_daily_sends_ok (reads workspaces.settings.daily_send_limit) is "intentionally not called here" and was causing earlier outages.
```

```
Source: workspaces.settings JSONB column
Keys: daily_send_limit, monthly_api_budget_usd, research_monthly_budget_usd, sender_pool, enrichment_companies_processed, fb_simultaneous_outreach
Runtime read: workspace_scheduler.workspace_daily_sends_ok (default 125), workspace_budget_ok, get_total_daily_capacity
Conflict: workspaces.settings.daily_send_limit (default 125) ≠ outreach_send_config.daily_limit (default 30 in migration, 500 in some workspaces per main.py comment) ≠ config/limits.yaml outreach.daily_send_limit 125 ≠ pace_limiter.CAMPAIGN_DEFAULTS 30.
Documented conflict: main.py:190–194 explicitly notes the mismatch caused "Railway ticks to be gated out after ~125 sends/day."
```

```
Source: settings (env vars loaded via pydantic-settings in backend/app/core/config.py)
Keys: SEND_ENABLED, send_window_start, send_window_end, RESEND_API_KEY, APOLLO_API_KEY, INSTANTLY_API_KEY, ANTHROPIC_API_KEY, ZEROBOUNCE_API_KEY, RESEND_WEBHOOK_SECRET, default_workspace_id, daily_send_limit (default 125), etc.
Runtime read: get_settings() (cached). Env vars override .env file.
```

```
Source: config/sequences.yaml + database campaign_sequence_definitions_v2 table
File path: config/sequences.yaml
Surfaces:
  - sequences.* — per-sequence steps with delay_days, channel, instructions, anti_patterns
  - global_principles.anti_patterns (lines 476–489) — banned phrases (used as anti_patterns in prompt)
  - channel_orchestration.rules (504–526) — which sequence based on contact attrs
  - linkedin_automation.{auto_send_enabled, daily_connection_request_limit, daily_dm_limit, stale_invite_withdraw_days, scheduler_interval_minutes}
  - reply_strategies (575–end) — per-classification response instructions
Runtime read: get_sequences_config() in backend/app/core/config.py (loaded on demand)
DB equivalent: campaign_sequence_definitions_v2 (V2 sequences override YAML). Engagement._process_due_sequences checks V2 first, falls back to YAML.
Conflict: A V2 sequence with the same id-name as a YAML key shadows YAML.
```

```
Source: config/outreach_guidelines.yaml
Surfaces: sender.{name, email, signature, step_1_signature}, voice_and_tone, email_structure, must_include, never_include, banned_phrases, banned_characters, product_facts, subject_line_rules, opening_line_rules, first_email_rules, cta_rules, integrity_rules, sender_pool
Runtime read: get_outreach_guidelines() — re-read every prompt build so dashboard edits are picked up live (per outreach.py:201–202)
Conflict: sender.email AND workspaces.outreach_send_config.sender_pool AND config/outreach_guidelines.yaml::sender_pool — priority is DB > YAML > fallback ("avi@digitillis.io").
```

```
Source: config/offer_context.yaml — product positioning
Source: config/icp.yaml — ICP definitions, NAICS allowlist; also referenced by icp_definitions DB table (migration 034)
Conflict: icp.yaml vs icp_definitions row marked is_active=true. Some code reads the YAML, some reads the table.
Source: config/signal_weights.yaml, scoring.yaml — PQS scoring
Source: config/competitors.yaml — read by suppression.is_suppressed competitor check
Source: config/manufacturing_ontology.yaml — tier → value messaging
Source: backend/app/core/suppression.py (module constants):
  - SEQUENCE_COOLDOWN_DAYS = 90
  - COMPANY_ESCALATION_BOUNCE_COUNT = 2
  - _COMPANY_BLOCK_STATUSES = {"not_interested", "disqualified", "converted"}
Hardcoded, no env override. Distinct from limits.yaml send_limits.company_cooldown_days (14).
Source: backend/app/core/threading_coordinator.py (module constants):
  - MIN_DAYS_BETWEEN_CONTACTS = 5
  - PQS_THREADING_THRESHOLD = 65
  - SMALL_COMPANY_EMPLOYEE_LIMIT = 500
Hardcoded; no env override.
Source: backend/app/core/channel_coordinator.py:
  - LINKEDIN_TO_EMAIL_COOLDOWN_DAYS = 0
  - DM_COMPLETE_TO_EMAIL_COOLDOWN_DAYS = 14
  - ACTIVITY_COOLDOWN_HOURS = 48
  - _company_lock_business_days() reads limits.yaml send_limits.company_lock_business_days (5) but is shadowed by module-level COMPANY_LOCK_BUSINESS_DAYS = 5 constant — both exist.
Source: backend/app/core/pre_send_assertions.py:
  - SENDABLE_EMAIL_STATUSES = {"verified", "catch_all"} (hardcoded frozenset)
  - module-level COMPANY_COOLDOWN_DAYS=14, MAX_BOUNCE_RATE=0.02, MIN_STEP_GAP_DAYS=3 (legacy aliases)
Source: backend/app/core/bounce_suppressor.py:
  - DOMAIN_BOUNCE_THRESHOLD = 3 (module constant — distinct from suppression.py COMPANY_ESCALATION_BOUNCE_COUNT = 2)
Source: backend/app/api/routes/approvals.py:
  - TIER_1_REQUIRES_DUAL_REVIEW: bool = True (line 32 — hardcoded; comment says "toggleable via config" but no config wire-up)
  - _REQUIRED_ATTESTATION_KEYS tuple — informational only (attestation not enforced)
Source: backend/app/core/pace_limiter.py:
  - CAMPAIGN_DEFAULTS = {"tier0-mfg-pdm-roi": 30, "tier0-fb-fsma": 30, "default": 30}
  - This is a SECOND independent daily send cap mechanism — separate from outreach_send_config and limits.yaml
```

```
Effective send-time governance precedence (observed):
  1. settings.send_enabled (env) — global kill
  2. outreach_send_config.send_enabled (DB) — workspace kill
  3. send_window_start/end (env) — time-of-day gate
  4. outreach_send_config.daily_limit (DB) — primary cap
  5. _count_sent_today vs daily_limit — pre-fetch check
  6. send_assertions (per-contact) — assert_bounce_rate_ok (system), assert_email_deliverable, assert_email_status_verified, assert_email_name_consistent, assert_outreach_eligible, assert_persona_target, assert_no_recent_company_send (workspace cooldown), assert_sender_under_daily_cap (uses daily_limit param passed in), assert_prior_step_sent, assert_minimum_step_gap
  7. is_suppressed (suppression_log + contact.status + company.status + competitor + sequence cooldown + duplicate_draft + email dedup)
  8. is_company_locked (channel_coordinator)
  9. workspace_daily_sends_ok (NOT called by _send_approved_workspace — explicitly commented out)
  10. PaceLimiter (used by some scripts/agents but NOT by the scheduler send path)
```

## H. Risk Observations

**DATA INTEGRITY RISK** — *Three writer paths to `approval_status='approved'`:*
- `backend/app/api/routes/approvals.py::approve_draft` (full gate)
- `backend/app/core/review_manifest.py::approve_manifest` (hash-gate only, skips quality/attestation/cap)
- `scripts/pending_draft_reconciliation.py` line 462 and `scripts/rejected_draft_reassessment.py` line 547 (direct service-key writes, hardcoded `approved_by="avanish"` string, skips every endpoint gate)
The dashboard's "approved" status no longer guarantees a human approval flow was followed.

**DATA INTEGRITY RISK** — `outreach_drafts.body` is mutated by `pending_draft_reconciliation.py` (line 469) and `rejected_draft_reassessment.py` (line 554). The schema has no constraint preventing this; once `body` is rewritten the audit trail of what the model originally produced is gone. Only `sent_at IS NOT NULL` rows are protected against deletion (migration 003), and they remain mutable.

**DATA INTEGRITY RISK** — Two `OutreachAgent` classes (`backend/app/agents/outreach.py` and `backend/app/agents/outreach_agent.py`) write to the same `outreach_drafts` table with different sequence names ("email_value_first" vs "initial_outreach"), different gate suites, different model routers, and different dedup logic. `Database.insert_outreach_draft` dedups on (company_id, contact_id, sequence_step) regardless of sequence_name, so an HTTP-triggered "initial_outreach" step 1 will collide with a scheduler "email_value_first" step 1 — but only by chance of identical step numbers; semantics diverge.

**DATA INTEGRITY RISK** — `outreach_outcomes` row is inserted during draft generation (`outreach.py` lines 1031–1043), before the draft is approved or sent. `send_id` points to a draft that may be rejected or never sent. Code reading `outreach_outcomes` as "history of sends" will count drafts as sends.

**CONCURRENCY RISK** — In-process APScheduler runs alongside the FastAPI app. If Railway runs more than one web replica, every scheduler runs in every replica. The only safety net is `outreach_drafts UPDATE … WHERE sent_at IS NULL` for the send path. All other workers (jit_pregenerate, draft_generation, process_due, gmail_intake, qualification, intent_refresh, bounce_hygiene) have no concurrency primitives at all.

**CONCURRENCY RISK** — `EngagementAgent._send_approved_drafts` sets `sent_at` before assertions run (engagement.py:557–569). On assertion failure, `_rollback_sent_at` issues a non-transactional UPDATE setting `sent_at=NULL`. During the window between claim and rollback (typically < 1s, but unbounded under DB latency), any concurrent reader sees the row as "sent." If the rollback itself fails (a network blip), the draft is orphaned forever — a CRITICAL log fires but no retry mechanism exists.

**CONCURRENCY RISK** — `Database.insert_outreach_draft`'s dedup guard (database.py:443–467) is read-then-write. Two scheduler instances or two ticks racing can both pass the existence check and insert duplicate drafts. There is no UNIQUE index on (workspace_id, company_id, contact_id, sequence_step) in any migration.

**GOVERNANCE BYPASS RISK** — `engagement.py` lines 432–485 document a missing migration that adds `approved_by` and `reviewed_at` to `outreach_drafts`. When those columns don't exist, the strict send filter logs a single warning and falls back to `approval_status='approved'` only. Combined with the script-based approval path that doesn't set `approved_by` properly, the system can send drafts that have no reviewer attestation, no quality gate result, no audit trail — and the operator sees nothing wrong because warnings are logged once.

**GOVERNANCE BYPASS RISK** — `POST /api/sequences/send-approved` with `draft_ids` parameter (engagement.py:451–457) explicitly skips the `approved_by IS NOT NULL` strict filter "because explicit draft_ids selection IS the human attestation." This means a script or admin who knows draft UUIDs can bypass attestation entirely. The `test_send_draft` endpoint similarly bypasses approval status checks (it just reads the draft and sends to an operator-supplied email).

**GOVERNANCE BYPASS RISK** — Attestation (`AttestationModel` in approvals.py) is required-by-Pydantic when present but optional in the `ApproveRequest` body. Line 397–399 explicitly states: "Attestation is recorded for audit purposes but not enforced as a hard gate." The `_REQUIRED_ATTESTATION_KEYS` tuple is unused.

**GOVERNANCE BYPASS RISK** — `?force=true` on `POST /api/approvals/{id}/approve` (line 376) bypasses both the quality gate and the per-reviewer daily cap (lines 410 and 438). The check is `if not force:`. There is no audit of who used `?force=true` beyond the standard `log_audit_event_from_ctx`.

**GOVERNANCE BYPASS RISK** — The HTTP path `OutreachAgent.generate_draft` (`backend/app/agents/outreach_agent.py`) bypasses every gate the scheduler `OutreachAgent.run` runs: ICP exclusion, suppression, threading coordinator, channel coordinator, has_recent_activity, run_pre_send_assertions, integrity regex check. It only checks for an existing non-rejected draft on the same `sequence_name='initial_outreach'`. A draft made via the API can therefore be created for a suppressed contact or one in cooldown.

**SILENT FAILURE RISK** — `_send_approved_drafts` post-send writes (lines 776–887) are all wrapped in try/except marked "non-fatal." So a sent email can leave: `companies.status` unchanged from `outreach_pending`, `set_company_outreach_active` not called, `campaign_threads` not created, `engagement_sequences` not inserted, `update_contact_state` not called. The downstream sequence-advance logic in `_process_due_sequences` requires both `engagement_sequences` and `outreach_drafts.sent_at` set; if the former failed, the next step never schedules and the contact is silently dropped from the sequence.

**SILENT FAILURE RISK** — `Database.insert_outreach_draft` cross-company email dedup (lines 469–508) returns `{}` (empty dict) silently when a step-1 draft is skipped because a sibling contact already received an email. Callers (outreach.py line 1001 `inserted_draft = self.db.insert_outreach_draft(draft_data)`) then use `(inserted_draft or {}).get("id")` and silently continue — but `result.processed += 1` was already incremented (the call happens after).

**SILENT FAILURE RISK** — `webhooks.py` event handlers return `{"status": "ignored"}` or `{"status": "error"}` with HTTP 200 on any failure. A bounced webhook that fails to write suppression_log is invisible to the operator — Resend sees a 200 and never retries.

**SILENT FAILURE RISK** — `_handle_email_reply` in webhooks.py line 387–395 falls back to a hardcoded `ReplyClassification(intent="other", auto_actionable=False)` if the classifier throws. The reply is queued for HITL but never re-classified. If the underlying classifier is broken across the board, every reply ends up in HITL with no signal.

**SILENT FAILURE RISK** — `gmail_imap.fetch_unseen_replies` is the only intake for replies sent to addresses outside the IMAP poll list. If a Gmail account is added to `sender_pool` but its app password is not stored in CredentialStore under the key `gmail_{safe_email}`, the loop skips it without error (main.py:373). Replies to that mailbox vanish.

**CONFIGURATION CONFLICT RISK** — Four independent daily-send-cap sources documented in section G. The comment at main.py:189–194 confirms operators have already been bitten by this: workspaces.settings.daily_send_limit gating sends out at 125 while outreach_send_config.daily_limit was set to 500.

**CONFIGURATION CONFLICT RISK** — `COMPANY_COOLDOWN_DAYS = 14` is a module-level constant in `pre_send_assertions.py` (line 83) duplicated in `_company_cooldown_days()` function and in `config/limits.yaml::send_limits.company_cooldown_days`. The function reads YAML; module constant is a stale legacy alias. Imports of the constant (engagement.py:640 `COMPANY_COOLDOWN_DAYS as _COOLDOWN_DAYS`) capture the legacy value at import time, never picking up YAML edits.

**CONFIGURATION CONFLICT RISK** — `SEQUENCE_COOLDOWN_DAYS = 90` (suppression.py:34) vs `COMPANY_ESCALATION_BOUNCE_COUNT = 2` (suppression.py:35) vs `DOMAIN_BOUNCE_THRESHOLD = 3` (bounce_suppressor.py:36) — two separate bounce-escalation thresholds in two modules with no shared source.

**CONFIGURATION CONFLICT RISK** — Tier-1 dual-review and per-reviewer-cap behaviors come from a mix of hardcoded constants (TIER_1_REQUIRES_DUAL_REVIEW = True in approvals.py:32), env var (MAX_APPROVALS_PER_DAY), and YAML (`outreach.max_approvals_per_reviewer_per_day: 500`). Default 30 in `_max_approvals_per_reviewer_per_day` (line 67) does not match the YAML default 500 — the env-var-not-set fallback path is different from the YAML-present path.

**CONFIGURATION CONFLICT RISK** — `sequences.yaml::linkedin_automation.scheduler_interval_minutes: 0` ("disable scheduled runs") is documentation only — the APScheduler in main.py does not consult this key to add or omit a LinkedIn sender job.

**IDEMPOTENCY RISK** — Webhook handlers in webhooks.py do not check `external_id` / `event_id` before inserting interactions. Resend supports webhook retries with the same payload; a replayed `email.opened` event will increment `contacts.open_count` again, double-counting opens.

**IDEMPOTENCY RISK** — `_poll_instantly_events` (engagement.py:1565) does check for existing interaction types per contact before writing — but only checks the *type*, not the specific event. So a contact who has been opened once and then opened again will have only one row recorded, undercounting opens.

**IDEMPOTENCY RISK** — `_run_jit_pregenerate` runs every 24 hours but generates drafts for sequences due "within 3 days." Three consecutive 24h ticks can each try to pre-generate the same draft. The race is mostly caught by `Database.insert_outreach_draft`'s dedup guard, but not transactionally.

**OTHER RISK (TENANT LEAK)** — `engagement.process_webhook_event` (engagement.py:1697) takes an `email` from the webhook payload and queries `contacts` with no workspace filter (`_lookup_db = Database()` — line 1714). If the same email exists under two workspaces (rare but possible after imports), the webhook writes to the first match. The subsequent `db = Database(workspace_id=contact.get("workspace_id"))` re-scopes future operations correctly but the contact lookup itself is cross-tenant.

**OTHER RISK (RUNTIME ERROR)** — `webhooks.py:989` calls `db.update_company(company_id, {"status": "not_interested"}, allow_downgrade=False)`. The `Database.update_company` method in `database.py:285` does not accept a kwarg named `allow_downgrade`. This will TypeError at runtime when a spam complaint webhook lands on a company already in a "downstream" status. Wrapped in a try/except that catches it.

**OTHER RISK (DEAD CODE)** — `OutreachAgent.run` in `agents/outreach_agent.py` line 185 returns an empty AgentResult unconditionally — but the class is still listed as an agent and could be hit by anything that loads agents by name.

**OTHER RISK (UNBOUNDED CACHE)** — `ApolloClient._enrich_cache` is a class-level dict (`apollo.py:40`). Across a long-running process (the FastAPI server lives for the lifetime of a deploy), this never evicts. Long-lived processes accumulate enrichment results in RAM.

**OTHER RISK (LRU SCOPE)** — `backend/app/core/database.py::get_supabase_client` is `@lru_cache()` with no arguments — singleton client. `backend/app/core/limits.py::_load` is `@lru_cache(maxsize=1)` — config is read once per process. Editing `config/limits.yaml` requires a server restart or an explicit `reload_limits()` call. The dashboard "edit limits" UX is undefined; there is no obvious code path that calls `reload_limits()`.

**OTHER RISK (UNAUDITABLE OPERATOR ACTIONS)** — `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` write `approved_by="avanish"` as a literal string. If `outreach_drafts.approved_by` is a UUID column, this fails; if TEXT, it silently writes a non-user-identifying string. Audit reports that group by approved_by will conflate these with legitimate approvals.

**OTHER RISK (LEGACY HANDLER)** — `engagement.process_webhook_event` (the static method) sets `db.update_company(company_id, {"status": "bounced"})` on email_bounced — directly contradicting tiered_suppression (migration 048) which says bounce is contact-scope only. This handler is still wired into the legacy Instantly webhook path.

## I. Open Questions

1. **How many Railway replicas run concurrently?** The "atomic claim" pattern is the only concurrency primitive in the send path. If only one replica runs, most of the concurrency risks become latent; if more than one runs, the system relies entirely on `WHERE sent_at IS NULL` semantics. Cannot determine from source alone.

2. **Is the migration adding `outreach_drafts.approved_by`, `reviewed_at`, `attestation` actually applied in production?** Code in both `approvals.py` and `engagement.py` falls back gracefully when the columns are missing. The fallback explicitly accepts unsigned approvals. No migration file for these columns exists in either migrations directory. Production behavior depends entirely on which path is live.

3. **What is the actual production value of `outreach_send_config.daily_limit` per workspace?** The migration default is 30; the YAML onboarding default is 125; the ramp value is 150; the documented mismatch in main.py:189–194 hints at 500. Cannot determine without DB inspection.

4. **Does any production code currently call `reload_limits()` or rely on a watcher to pick up YAML changes?** The lru_cache means edits without restart are no-ops; the dashboard UX implies live edits work.

5. **Are `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` run regularly in production, or are they one-shot operator scripts?** The audit trail consequences differ dramatically — regular use means a large fraction of approvals never went through the endpoint.

6. **Is the legacy `engagement.process_webhook_event` static method still wired to the Instantly webhook**, or has it been fully superseded by the per-event handlers in `webhooks.py`? `routes/webhooks.py instantly_webhook` and `webhooks/instantly.py` both exist; which is mounted as `/api/webhooks/instantly` cannot be determined without verifying router includes.

7. **What is the failure mode when the trigger `trg_contact_eligibility` (migration 033) is disabled or absent?** The fallback function `refresh_outbound_eligible` is called by `pipeline_qc.py`, but on a 15-minute lag. Sends in the gap could target ineligible contacts that the SQL gate would have removed.

8. **What happens if Resend's `idempotency_key` rejects a retried send because the original returned an error before the message_id was stored on `outreach_drafts.resend_message_id`?** The DB compare-and-swap protects against double-send within the same code path, but a manual retry via `POST /api/sequences/send-approved draft_ids=[…]` resets `sent_at` to NULL only if the previous send raised — but the engagement.py except-handler at line 898 does NOT roll back. A draft can be marked sent with no resend_message_id, blocking webhook correlation forever.

9. **What is the relationship between `engagement_sequences`, `campaign_threads`, and `outreach_outcomes`?** All three track active outreach state. The send path writes to all three with separate try/except. Reconciliation between them appears nowhere in source. Drift between the three would explain stuck pipelines but is invisible to the operator.

10. **How is the `pipeline_qc.py` script executed?** main.py:175–184 dynamically loads it via `importlib.util.spec_from_file_location`. This means the script runs inside the API server process, sharing the supabase singleton client and the @lru_cache config. Its auto-fixes therefore execute under the API server's identity. If the script is also run via cron from outside, the behavior would differ.
agentId: a2ad1fb78ffac0e74 (use SendMessage with to: 'a2ad1fb78ffac0e74' to continue this agent)
<usage>total_tokens: 303401
tool_uses: 80
duration_ms: 679330</usage>

---

# Stage 2: Runtime Truth Audit

## A. Production Schema Truth

### A.1 Reviewer column migration

The Stage 1 claim that "there is no migration file" for the reviewer columns is **incorrect**. Migration `supabase_migrations/migrations/045_gtm_rebuild.sql` adds all three columns. Full migration body (lines 1–25):

```sql
-- GTM rebuild: approval gate + engagement tiers
-- Phase 1-4 support columns

-- outreach_drafts: reviewer tracking
ALTER TABLE outreach_drafts
  ADD COLUMN IF NOT EXISTS approved_by    TEXT,
  ADD COLUMN IF NOT EXISTS reviewed_at    TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS attestation    JSONB;

-- approval_status enum: tier-1 two-reviewer flow
ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'pending_second_review';

-- companies: engagement tier classification
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS engagement_tier TEXT;
```

**Findings:**

1. **`approved_by`** — `TEXT`, NULLABLE, no default. Defined at line 6.
2. **`reviewed_at`** — `TIMESTAMP WITH TIME ZONE`, NULLABLE, no default. Defined at line 7.
3. **`attestation`** — `JSONB`, NULLABLE, no default. Defined at line 8.
4. **`approval_status` enum gains `pending_second_review`** — line 11.

Critical implication: **`approved_by` is TEXT, not a UUID FK to users.** This means the operator scripts that write `APPROVED_BY = "avanish"` (string literal, no quotes-as-UUID) will **succeed silently** rather than fail loudly. There is no referential integrity check that this maps to a real user record. Audit queries grouping by `approved_by` will see the literal string `"avanish"` alongside real user UUIDs and treat them as peer reviewer identifiers.

Also critical: the columns are all nullable with no default, so a draft can carry `approval_status='approved'` while `approved_by IS NULL` and `reviewed_at IS NULL`. There is no DB-level CHECK constraint forcing those fields to be populated when `approval_status='approved'`.

### A.2 Code paths that check/fall back on these columns

**File: `backend/app/api/routes/approvals.py`**

Lines 30–46 (comment block):
```python
# Persisted columns added by future migrations (P1.3, P2.2, P2.3, P1.4).
# When the migration hasn't run yet, the code below logs a single warning and
# proceeds without writing those fields, so the API stays functional.
# TODO: run migration adding outreach_drafts.approved_by (UUID, FK to users)
```
The TODO claims the column should be UUID FK to users, but migration 045 actually delivered TEXT.

Lines 410–434 — daily reviewer cap query:
```python
if reviewer_id and not force:
    cap = _max_approvals_per_reviewer_per_day()
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        count_q = (
            db._filter_ws(
                db.client.table("outreach_drafts").select("id", count="exact")
            )
            .eq("approved_by", reviewer_id)
            .gte("reviewed_at", since)
        )
        existing_count = count_q.execute().count or 0
    except Exception as exc:
        # Reviewer columns missing → cannot enforce cap. Surface a single warning.
        logger.warning(
            "Daily approval cap not enforced — outreach_drafts.approved_by/reviewed_at "
            "columns unavailable (%s). Run reviewer-columns migration.",
            exc,
        )
        existing_count = 0
```
**Fallback behavior:** `existing_count = 0`, which means the cap check at line 430 (`if existing_count >= cap:`) is bypassed completely. A reviewer can approve unlimited drafts.

Lines 518–540 — write of the reviewer columns:
```python
if reviewer_id:
    update_data["approved_by"] = reviewer_id
update_data["reviewed_at"] = datetime.now(timezone.utc).isoformat()
if body and body.attestation is not None:
    update_data["attestation"] = body.attestation.model_dump()

try:
    draft = db.update_outreach_draft(draft_id, update_data)
except Exception as exc:
    # Likely an unknown-column error from a missing migration. Strip the
    # new fields and retry with the legacy columns only so reviewer flow
    # stays unblocked. Log a warning so the migration gap is visible.
    logger.warning(
        "Approval write hit unknown column (%s) — retrying without "
        "reviewer/attestation fields. Run the reviewer-columns migration.",
        exc,
    )
    legacy_only = {k: v for k, v in update_data.items()
                   if k not in {"approved_by", "reviewed_at", "attestation"}}
    draft = db.update_outreach_draft(draft_id, legacy_only)
```
**Fallback behavior:** the approval is committed with `approval_status='approved'` but **no `approved_by`, no `reviewed_at`, no `attestation`** recorded. The draft is fully approved and eligible for send under the legacy filter (Stage 1 H — "GOVERNANCE BYPASS RISK").

**File: `backend/app/agents/engagement.py`**

Lines 431–485 — send query with strict-vs-fallback logic:
```python
# P1.3: send query MUST require both `approved_by IS NOT NULL` and
# `reviewed_at IS NOT NULL`. The reviewer columns are added by a
# migration noted as a TODO; until that migration runs, fall back to
# `approval_status='approved'` only and emit a single warning so the
# gap is visible in logs.
# TODO: run migration adding outreach_drafts.approved_by (UUID FK to users)
# TODO: run migration adding outreach_drafts.reviewed_at (TIMESTAMPTZ)
_draft_query = (
    self.db.client.table("outreach_drafts")
    .select(...)
    .eq("approval_status", "approved")
    .is_("sent_at", "null")
    .eq("channel", "email")
    .not_.is_("subject", "null")
    .neq("subject", "")
)
if draft_ids:
    _draft_query = _draft_query.in_("id", draft_ids)

try:
    if draft_ids:
        # Explicit draft_ids selection IS the human attestation — the caller
        # has reviewed and nominated these specific drafts by ID. Skip the
        # approved_by/reviewed_at gate so unpopulated reviewer columns don't
        # silently block manually-targeted sends.
        drafts = _draft_query.order("created_at").limit(fetch_limit).execute().data
        logger.info("Send query using explicit draft_ids (%d) — skipping reviewer column gate", len(draft_ids))
    else:
        # Scheduler path: require explicit human attestation
        _strict_query = (
            _draft_query.not_.is_("approved_by", "null").not_.is_("reviewed_at", "null")
            .order("created_at")
            .limit(fetch_limit)
        )
        drafts = _strict_query.execute().data
        ...
except Exception as exc:
    # Migration not yet applied — column doesn't exist. Log once and
    # fall back to approval_status='approved' only (still a hard gate;
    # no auto-approve job runs anymore).
    ...
    drafts = (
        _draft_query.order("created_at").limit(fetch_limit).execute().data
    )
```

**Fallback behavior:** the strict query throws (column missing) → outer except catches → resends the unfiltered `approval_status='approved'` query. Any draft that anybody marked approved goes out, including approvals via scripts that never set `approved_by`/`reviewed_at`. Because migration 045 has the columns as `IF NOT EXISTS` and they are nullable with no default, **production may have applied 045 yet still have rows where the columns are NULL** — those drafts will be EXCLUDED by the strict path and INCLUDED by the fallback path. Whether the system is currently in strict or fallback mode cannot be determined from source — it depends on whether the strict `.not_.is_("approved_by", "null")` query raises or not. With migration 045 applied, the query will not raise; it will simply return zero rows where the columns are NULL. So drafts approved via the script path (`approved_by="avanish"`) WILL satisfy `approved_by IS NOT NULL` and proceed; drafts approved via the endpoint when its retry-without-reviewer-columns path fired will NOT satisfy the strict filter and will sit forever.

### A.3 What the fallback path allows that strict would not

Under the fallback path (`except Exception` branch in engagement.py:471):
- A draft with `approval_status='approved'`, `approved_by=NULL`, `reviewed_at=NULL`, `attestation=NULL` will be **sent**. The strict path would skip it.
- Drafts approved via the `review_manifest.approve_manifest` path (which DOES write `approved_by` unconditionally — see review_manifest.py:320–324) work in both paths.
- Drafts approved via `pending_draft_reconciliation.py` / `rejected_draft_reassessment.py` (which write `approved_by="avanish"`) satisfy the strict filter (column non-null) so they are sent in both paths — **but `reviewed_at` is NOT set by these scripts**, so under the strict filter they will be skipped, under the fallback filter they will be sent.

### A.4 Complete `outreach_drafts` schema across all migrations

Aggregated from `001_initial_schema.sql`, `016_workspaces_multitenant.sql`, `017_workspace_id_remaining_tables.sql`, `029_outreach_send_config.sql`, `039_sender_tracking.sql`, `043_draft_model_tracking.sql`, `044_edit_feedback.sql`, `045_gtm_rebuild.sql`, `046_signal_attribution.sql`:

| Column | Type | Nullable | Default | Added by |
|--------|------|----------|---------|----------|
| `id` | UUID | NO | `uuid_generate_v4()` | 001 |
| `company_id` | UUID FK companies | YES | — | 001 |
| `contact_id` | UUID FK contacts | YES | — | 001 |
| `channel` | `channel_type` | NO | `'email'` | 001 |
| `sequence_name` | TEXT | YES | — | 001 |
| `sequence_step` | INTEGER | YES | `1` | 001 |
| `subject` | TEXT | YES | — | 001 |
| `body` | TEXT | YES | — | 001 |
| `personalization_notes` | TEXT | YES | — | 001 |
| `approval_status` | `approval_status` enum | YES | `'pending'` | 001 (extended by 045) |
| `edited_body` | TEXT | YES | — | 001 |
| `rejection_reason` | TEXT | YES | — | 001 |
| `approved_at` | TIMESTAMPTZ | YES | — | 001 |
| `sent_at` | TIMESTAMPTZ | YES | — | 001 |
| `instantly_lead_id` | TEXT | YES | — | 001 |
| `instantly_campaign_id` | TEXT | YES | — | 001 |
| `created_at` | TIMESTAMPTZ | YES | `NOW()` | 001 |
| `updated_at` | TIMESTAMPTZ | YES | `NOW()` | 001 |
| `workspace_id` | UUID | **NO** (after 017) | — | 016/017 |
| `resend_message_id` | TEXT | YES | — | 029 |
| `resend_status` | TEXT | YES | — | 029 |
| `sender_email` | TEXT | YES | — | 039 |
| `opened_at` | TIMESTAMPTZ | YES | — | 039 |
| `clicked_at` | TIMESTAMPTZ | YES | — | 039 |
| `bounced_at` | TIMESTAMPTZ | YES | — | 039 |
| `complained_at` | TIMESTAMPTZ | YES | — | 039 |
| `model` | TEXT | YES | — | 043 |
| `approved_by` | TEXT | YES | — | 045 |
| `reviewed_at` | TIMESTAMPTZ | YES | — | 045 |
| `attestation` | JSONB | YES | — | 045 |
| `top_signal_id` | UUID | YES | — | 046 |
| `top_signal_type` | TEXT | YES | — | 046 |

**Indexes:**
- `idx_drafts_approval` on `(approval_status, created_at)` — 001
- `idx_drafts_company` on `(company_id)` — 001
- `idx_outreach_drafts_workspace` on `(workspace_id)` — 016
- `idx_outreach_drafts_sender_email` partial on `(sender_email)` WHERE NOT NULL — 039
- `idx_outreach_drafts_sender_bounced` partial on `(sender_email, bounced_at)` WHERE bounced_at IS NOT NULL — 039
- `idx_outreach_drafts_rejection_lookup` partial on `(contact_id, sequence_name, sequence_step, approval_status)` WHERE `approval_status = 'rejected'` — 043

**Constraints:**
- No UNIQUE constraint on `(workspace_id, company_id, contact_id, sequence_step)` or `(company_id, contact_id, sequence_name, sequence_step)` — duplicate drafts cannot be prevented at the schema level.
- No CHECK linking `approval_status='approved'` to `approved_by IS NOT NULL` or `reviewed_at IS NOT NULL`.
- No CHECK preventing `sent_at < approved_at` or `approved_at < created_at`.
- Migration 003 (`003_protect_sent_emails.sql`, in the OTHER migrations directory `/migrations/`) installs a BEFORE DELETE trigger `protect_sent_drafts_from_deletion` that raises if `OLD.sent_at IS NOT NULL`. UPDATE is not blocked.
- RLS policies from 007 and 027 — workspace-scoped access.

---

## B. Scheduler/Deployment Truth

### B.1 Deployment configuration files

- **`Procfile`** (only deployment config present at repo root):
  ```
  web: pip install -r backend/requirements.txt && uvicorn backend.app.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
  ```
- **No `railway.json`, `railway.toml`, `.railway/`, `Dockerfile`, `docker-compose.yml`, or `nixpacks.toml`** exists in the repo (verified via `find -maxdepth 3`).
- **`netlify.toml`** exists — for the dashboard front-end, not the backend.
- **`runtime.txt`** exists at repo root — Python version pin only.

The Procfile declares a single `web` process. Railway, by default, runs **one replica of each Procfile process type** unless explicitly scaled. There is no replica-count config in any file; replica count is set in the Railway dashboard, not in source. **From source alone, the production replica count cannot be determined.** Runtime evidence required: Railway dashboard service settings.

### B.2 APScheduler startup — singleton check

`backend/app/api/main.py` lines 2029–2227 contain the `lifespan` context manager that starts APScheduler. Reading the full block:

- Line 2032: `_validate_scheduler_signatures()` — startup sanity check on kwargs, raises if signatures wrong.
- Line 2038: `global _scheduler` — module-level singleton reference.
- Line 2039–2041: `BackgroundScheduler(timezone="America/Chicago")` created and assigned.
- Line 2042 onward: `scheduler.add_job(...)` calls for every job.
- Line 2204: `scheduler.start()`.

**There is NO singleton check before starting the scheduler.** No environment variable like `SCHEDULER_ENABLED`, no Redis lock, no file lock, no DB advisory lock, no process-rank check. Every running instance of the FastAPI app starts a full BackgroundScheduler with all jobs. The only conditional gating is `try/except ImportError` around the entire startup block — which exists only to allow the app to run when APScheduler is not installed (development environments).

`SCHEDULER_ENABLED` does not appear anywhere in the codebase (verified by grep — no matches).

### B.3 Job inventory and concurrency-safety classification

Jobs registered in `lifespan` (with concurrency safety classification):

| Job ID | Trigger | Function | Concurrency-safe? |
|--------|---------|----------|-------------------|
| `health_snapshot` | interval 15m | `_run_health_snapshot` | **SAFE** — read-only metrics dump |
| `pipeline_qc` | interval 15m | `_run_pipeline_qc` | **UNSAFE** — auto-fixes via `refresh_outbound_eligible` RPC, sends alert emails. Two instances could send duplicate alerts and double-call the RPC. |
| `send_approved` | cron Mon–Fri 8–11 :00/:30 Chicago | `_run_send_approved` | **MOSTLY SAFE** — relies entirely on `UPDATE … WHERE sent_at IS NULL` compare-and-swap in engagement.py:558–564. If both replicas claim before the other's UPDATE commits the row is sent once; if they interleave with the rollback path, the row could be sent then orphaned. |
| `process_due` | interval 1h | `_run_process_due_sequences` | **UNSAFE** — two ticks can both insert a step-N draft for the same contact (insert_outreach_draft dedup is read-then-write, race-prone). |
| `poll_instantly` | interval 6h | `_run_poll_instantly` | **UNSAFE** — increments interaction counts; replays will double-count opens. |
| `hitl_snoozed` | interval 15m | `_run_process_hitl_snoozed` | **MOSTLY SAFE** — `eq("status","snoozed").update({"status":"pending"})` is idempotent in effect, but two ticks could both fire downstream notifications. |
| `hitl_auto_archive` | interval 1h | `_run_auto_action_low_priority` | **UNSAFE** — bulk status updates without lock. |
| `personalization_refresh` | interval 24h | `_run_personalization_refresh` | **UNSAFE** — burns Anthropic spend twice on each company. |
| `jit_pregenerate` | interval 24h | `_run_jit_pregenerate` | **UNSAFE** — duplicate drafts for same `(contact, step)`. |
| `gmail_intake` | interval 15m | `_run_gmail_intake` | **UNSAFE** — two instances can both fetch the same UNSEEN UID, both mark `\Seen`, both insert HITL queue rows. |
| `qualification` | interval 15m | `_run_qualification` | **UNSAFE** — duplicate Anthropic calls for same company. |
| `draft_generation` | interval 5m | `_run_draft_generation` | **UNSAFE** — same drafting race as jit_pregenerate, more frequent. |
| `weekly_post_send_audit` | cron Sun 7am | `_run_weekly_post_send_audit` | **UNSAFE** — duplicate audit emails. |
| `weekly_approval_audit` | cron Fri 9am | `_run_weekly_approval_audit` | **UNSAFE** — same. |
| `weekly_contact_backup` | cron Sat 5am | `_run_weekly_contact_backup` | **UNSAFE** — concurrent disk writes to `/Volumes/Digitillis/Data/prospectiq_backups/` (and the path requires a mounted volume that does not exist on Railway, so this likely fails silently). |
| `weekly_signal_scrapers` | cron Sat 6am | `_run_weekly_signal_scrapers` | **UNSAFE** — duplicate FDA/OSHA scraping API calls. |
| `signal_monitor` | cron Sun 6am | `_run_signal_monitor` | **UNSAFE** — duplicate Perplexity/Apollo calls. |
| `reengagement` | cron Sun 8am | `_run_reengagement` | **UNSAFE** — duplicate re-queue of companies. |
| `weekly_cost_summary` | cron Mon 8am | `_run_weekly_cost_summary` | **UNSAFE** — duplicate emails. |
| `daily_report` | cron Mon–Fri 6am | `_run_daily_report` | **UNSAFE** — duplicate emails. |
| `intent_refresh` | cron 5am daily | `_run_intent_refresh` | **UNSAFE** — duplicate Apollo job-posting fetches. |
| `bounce_hygiene` | cron 3am daily | `_run_bounce_hygiene` | **UNSAFE** — bulk DNC inserts, contact status updates. Concurrent runs can race on the contact update. |

Reactive (one-shot date jobs added at runtime):
- `intent_post_send_{workspace_id}_{ts}` — scheduled after a successful send batch. The job id is deterministic per-workspace per-timestamp, so within a single replica the `replace_existing=True` flag dedupes. But two replicas calculating different `int(run_at.timestamp())` (clock drift) would each register a separate job. ID collision logic does not cross replicas.

### B.4 Distributed lock search

Searched for `advisory_lock`, `pg_advisory`, `redis.*lock`, `FileLock`, `fcntl.flock`, `distributed.*lock` across `backend/` and `scripts/`. **Zero matches.** No distributed primitive exists anywhere in the codebase.

The only concurrency primitives in the entire codebase are:
1. `WHERE sent_at IS NULL` compare-and-swap in `engagement.py:558–564` (single row per draft).
2. `ApolloClient._enrich_cache` — class-level dict, in-process only.
3. `@lru_cache` decorators on `get_supabase_client`, `get_settings`, `_load` — process-local.

There is **no protection against multi-replica concurrent runs** of any scheduler job other than `send_approved`.

---

## C. Approval Path Truth

Comprehensive table of all code paths that write `approval_status='approved'`:

| File + function | Trigger | Auth required | Quality gate | Attestation | Per-reviewer cap | `approved_by` set | `reviewed_at` set | Audit log | `?force=true` bypass | Gates skipped vs. full endpoint |
|---|---|---|---|---|---|---|---|---|---|---|
| `backend/app/api/routes/approvals.py::approve_draft` (POST `/api/approvals/{id}/approve`) | HTTP | `require_role("member")` — JWT | YES (`validate_draft`, errors-only) | RECORDED only (line 397–399 says "not enforced as hard gate") | YES (24h count vs `MAX_APPROVALS_PER_DAY`) | YES — `reviewer_id` from `get_current_user` | YES — `now()` | YES — `log_audit_event_from_ctx` | YES — `?force=true` (quality + cap) | **(baseline)** |
| `backend/app/core/review_manifest.py::approve_manifest` | Programmatic (called from elsewhere; no current HTTP wrapper found via grep) | Caller-supplied — depends on caller | NO | NO | NO | YES — `approved_by` param (no validation that it's a real user) | NO — only `approved_at` (line 322) | NO — no `log_audit_event_from_ctx` call | N/A | Quality gate, attestation, per-reviewer cap, `reviewed_at` write, audit event. Only the body-hash check is enforced. |
| `scripts/pending_draft_reconciliation.py::reconcile_pending` (line 462) | Manual CLI invocation; uses `SUPABASE_SERVICE_KEY` env var | **NONE — service-role key bypasses RLS** | Custom in-script regex (`_check_body_quality`) — different from `validate_draft` | NO | NO | YES — hardcoded `"avanish"` string | NO | NO | N/A | All endpoint gates. Also mutates `body` and `edited_body` (lines 469–470). |
| `scripts/rejected_draft_reassessment.py::reassess_rejected` (line 548) | Manual CLI; service-role key | **NONE — service-role key bypasses RLS** | Custom regex | NO | NO | YES — hardcoded `"avanish"` string | NO | NO | N/A | All endpoint gates. Mutates `body`, `edited_body`, and **clears `rejection_reason` to NULL** (line 551). |
| `backend/app/api/routes/threads.py::approve_and_send` (≈line 373) | HTTP — thread approval endpoint | JWT (inherits from router) | NO | NO | NO | NO | NO | NO | N/A | All endpoint gates. Then calls `EngagementAgent.run("send_approved")` immediately. |
| `backend/scripts/manage_thread.py` (line 619–621, inside `send` subcommand) | Manual CLI; raw `Database()` | NONE | NO | NO | NO | NO | NO | NO | N/A | All endpoint gates. Sets `approved` then pushes lead to Instantly via API. |
| `backend/app/agents/linkedin_sender.py::_register_send` (line 297) | Internal agent | N/A (agent runs in scheduler) | NO | NO | NO | NO | NO | NO | N/A | Linked-in path — not email. Sets `approval_status='approved'` after LinkedIn send completes. |
| `backend/app/api/routes/content.py` (line 628, 770) | HTTP — content (ghostwriting) routes, separate from outreach drafts | JWT | NO | NO | NO | NO | NO | NO | N/A | Different table semantics — appears to mark LinkedIn posts as "posted" by reusing `approval_status='approved'`. |

**Narrative findings:**

1. **At least eight write paths exist to `approval_status='approved'`**, of which only the HTTP `/api/approvals/{id}/approve` endpoint runs the full gate suite. The other seven each skip a different mix of governance.

2. **`approve_manifest` writes `approved_at` (line 322) but does NOT write `reviewed_at` (line 320–324)** — so manifests-approved drafts pass the strict scheduler filter only if `reviewed_at` was set somehow else, otherwise they fall through to the legacy filter.

3. **`manage_thread.py`'s `send` subcommand sets `approval_status='approved'` AFTER calling Instantly's send API** (line 619 comes after line 614's `instantly.add_lead_to_campaign`). This means a draft can be sent, the script crashes before line 619, and the row stays `pending`. A subsequent automated send via the scheduler will not find it (filtered to `approved`) but a re-run of the script will re-send via Instantly.

4. **`threads.py::approve_and_send`** is a single HTTP endpoint that approves and immediately calls `EngagementAgent.run("send_approved")` in-process. Since it sets `approval_status='approved'` without setting `approved_by`/`reviewed_at`, the immediate-send call hits the strict filter and finds nothing — the draft only sends in a future tick if the column-fallback path fires.

5. **`force=true` is the only documented bypass** on the endpoint path. Lines 410 and 438 in approvals.py both check `if not force:`. No audit metadata distinguishes a force-approval from a normal one beyond the standard log_audit_event_from_ctx call.

---

## D. Send-Config Truth

### D.1 `_load_send_config` — engagement.py:252–272

Full function:
```python
def _load_send_config(self) -> dict:
    defaults = {"daily_limit": 30, "batch_size": 10, "min_gap_minutes": 4,
                "min_gap_seconds": 0, "send_enabled": True}
    try:
        row = (
            self.db.client.table("outreach_send_config")
            .select("daily_limit, batch_size, min_gap_minutes, min_gap_seconds, send_enabled")
            .eq("workspace_id", self.db.workspace_id)
            .limit(1)
            .execute()
            .data
        )
        if row:
            return {**defaults, **row[0]}
    except Exception:
        pass
    return defaults
```
**What it reads:** `outreach_send_config` table, filtered by `workspace_id`. **Order:** defaults first, then DB row overlay (DB wins for any non-null key). **Winner:** DB row keys override defaults; defaults fill in missing keys.

Defaults: `daily_limit=30`, `batch_size=10`, `min_gap_minutes=4`.

### D.2 `workspace_daily_sends_ok` — workspace_scheduler.py:117–155

Reads `workspace.settings.daily_send_limit` (default 125, see line 127). Counts drafts with `sent_at >= today_start UTC` for this workspace. Returns False if `today_count >= daily_limit`. **Fails open on exception (line 155).**

### D.3 `main.py` lines 189–194 — the documented mismatch

Full text:
```python
def _send_approved_workspace(ws: dict) -> None:
    # Note: workspace_daily_sends_ok is intentionally not called here.
    # It reads workspaces.settings.daily_send_limit (default 125) which is a
    # different config source from outreach_send_config.daily_limit (500).
    # That mismatch caused Railway ticks to be gated out after ~125 sends/day.
    # EngagementAgent._load_send_config + _count_sent_today enforce the correct limit.
```

So `workspace_daily_sends_ok` is **explicitly skipped** in the scheduler send path because it disagrees with `outreach_send_config.daily_limit`. The intended authoritative source is `outreach_send_config.daily_limit`.

### D.4 `config/limits.yaml`

```yaml
outreach:
  daily_send_limit: 125             # Default per-workspace daily send cap
  max_approvals_per_reviewer_per_day: 500
...
send_config:
  onboarding_daily_limit: 125
  onboarding_batch_size: 25
  fallback_daily_limit: 125
  fallback_batch_size: 25
  fallback_min_gap_minutes: 4
  ramp_daily_limit: 150
  ramp_batch_size: 25
```
`outreach.daily_send_limit = 125`. Note `send_config.fallback_daily_limit = 125` but `_load_send_config`'s hardcoded fallback is `30` — they disagree.

### D.5 `pace_limiter.py` — CAMPAIGN_DEFAULTS

```python
CAMPAIGN_DEFAULTS: dict[str, int] = {
    "tier0-mfg-pdm-roi": 30,
    "tier0-fb-fsma": 30,
    "default": 30,
}
```
**Where called:** Only by `backend/scripts/dashboard.py:24` (CLI dashboard) and `check_all_campaigns()` from `pace_limiter.py` itself. **Not called by the scheduler send path** (verified by grep showing only the import in dashboard.py).

### D.6 Send-cap source table

| Source | Value (per migration/code) | Read by (runtime) | Used by scheduler send tick? |
|--------|----------------------------|--------------------|------------------------------|
| `config/limits.yaml::outreach.daily_send_limit` | 125 | `limits.py::_load()` (lru_cached) — read by approvals reviewer cap fallback (`_max_approvals_per_reviewer_per_day` line 65) but NOT by the send path | **NO** |
| `config/limits.yaml::send_config.fallback_daily_limit` | 125 | Nowhere — declarative only, not consumed in code | **NO** |
| `outreach_send_config.daily_limit` (DB) | per-workspace; migration default 30; main.py comment notes 500; YAML onboarding 125; ramp 150 | `EngagementAgent._load_send_config` (engagement.py:252) | **YES — authoritative** |
| `_load_send_config` hardcoded fallback | 30 | engagement.py:258 when DB row missing | YES — only if DB row absent |
| `workspaces.settings.daily_send_limit` (JSONB) | per-workspace; default 125 | `workspace_scheduler.workspace_daily_sends_ok` | **NO** — explicitly skipped by main.py:189–194 |
| `pace_limiter.CAMPAIGN_DEFAULTS` | 30 | `PaceLimiter.__init__`, only used by `backend/scripts/dashboard.py` | **NO** |
| Env var `daily_send_limit` (settings) | 125 default | `get_settings()` — read by tests, not the send path | **NO** |
| `pre_send_assertions.assert_sender_under_daily_cap` | `daily_cap` parameter passed in | Called from `run_pre_send_assertions` with `daily_cap=daily_limit` from `_load_send_config` | YES — per-sender |

### D.7 Definitive answer

**The single value that gates production sends per scheduler tick is `outreach_send_config.daily_limit` for the active workspace, read by `EngagementAgent._load_send_config()` (engagement.py:252).** If that DB row is missing, the hardcoded fallback `30` applies. The value cannot be determined from source — it requires a SELECT on `outreach_send_config` per workspace.

Secondary, per-tick batch cap: `outreach_send_config.batch_size` (same source). Default in code: 10.

Per-sender per-day cap: enforced inside `assert_sender_under_daily_cap` using the same `daily_limit` value passed in from `_load_send_config` — so it is bounded by the same number, not a separate column.

---

## E. Webhook Truth

### E.1 Routers mounted on the FastAPI app

From `backend/app/api/main.py`:
- Line 53: `from backend.app.api.routes import ... webhooks ...`
- Line 55: `from backend.app.webhooks import instantly as instantly_webhooks`
- Line 2258: `app.include_router(approvals.router)` (not relevant to webhooks, listed for orientation)
- Line 2261: `app.include_router(webhooks.router)` — prefix `/api/webhooks` (from webhooks.py:26)
- Line 2269: `app.include_router(instantly_webhooks.router)` — prefix `/webhooks` (from instantly.py:119)

**TWO Instantly webhook handlers are mounted simultaneously at different prefixes:**
- `POST /api/webhooks/instantly` → `backend/app/api/routes/webhooks.py::instantly_webhook` (lines 648–744)
- `POST /webhooks/instantly` → `backend/app/webhooks/instantly.py::instantly_webhook` (lines 447–599)

Which URL Instantly is actually configured to hit cannot be determined from source. Both endpoints will respond if hit. They have different verification methods, different DB write patterns, and different return shapes.

### E.2 Routes in `backend/app/api/routes/webhooks.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/webhooks/unipile` | `unipile_webhook` — LinkedIn connection accepted / message received |
| POST | `/api/webhooks/instantly` | `instantly_webhook` — Instantly event router. Dispatches to `_handle_email_reply`, `_handle_email_bounced`, `_handle_email_unsubscribed`, `_handle_email_opened`, `_handle_email_clicked`, or falls through to `EngagementAgent.process_webhook_event` (line 716) for unknown event types. |
| POST | `/api/webhooks/resend` | `resend_webhook` — Resend event handler for delivered/opened/clicked/bounced/complained |
| POST | `/api/webhooks/trigify` | `trigify_webhook` — competitor engagement signal |
| POST | `/api/webhooks/meeting-transcript` | `meeting_transcript_webhook` |
| POST | `/api/webhooks/apollo/phone` | `apollo_phone_webhook` |

### E.3 `backend/app/webhooks/instantly.py`

Single route: `POST /webhooks/instantly` (note: no `/api/` prefix). Has HMAC signature verification via `INSTANTLY_WEBHOOK_SECRET` env var and `X-Instantly-Signature` header (lines 181–204). Falls open if `INSTANTLY_WEBHOOK_SECRET` is unset (line 188–194 returns True with a warning). Dispatches to handlers `_handle_email_sent`, `_handle_email_opened`, `_handle_email_clicked`, `_handle_email_replied`, `_handle_email_bounced`, `_handle_email_unsubscribed` (line 432–440).

There is also `backend/app/webhooks/webhooks.py` (a file inside the webhooks package) — not inspected here but its existence suggests a third webhook surface. Not currently mounted as a router based on the main.py imports above.

### E.4 Resend webhook — duplicate event detection and secret check

From `routes/webhooks.py::resend_webhook` (lines 751–1030):

**Duplicate event_id check:** **NONE.** The handler does not check for `data.id` or `event_id` before writing. A replayed Resend webhook will insert a duplicate `interactions` row (line 903–916), re-increment `open_count`/`click_count` (line 877–883), and re-stamp `opened_at`/`clicked_at` on the draft (line 862–874). The bounce path inserts duplicate `suppression_log` rows (line 959–974) and duplicate `do_not_contact` entries (line 999).

**Secret check:** Line 783:
```python
if settings.resend_webhook_secret and secret != settings.resend_webhook_secret:
    raise HTTPException(status_code=401, detail="Invalid webhook secret")
```
The secret is passed as a URL query parameter (`?secret=...`). If `RESEND_WEBHOOK_SECRET` is **unset in env**, the check is skipped — **anyone can POST to this endpoint without authentication.** If set, a mismatch returns HTTP 401 (Resend then retries on its schedule).

**Failure mode under bad secret:** HTTPException 401 propagates, so the handler does not silently succeed. But there is no logging of failed signature attempts.

### E.5 Instantly webhook secret verification

The two paths differ:
- `routes/webhooks.py::instantly_webhook` (line 669): `if settings.webhook_secret and secret != settings.webhook_secret:` — same pattern as Resend. Query-param based. **Falls open if `webhook_secret` env unset.**
- `webhooks/instantly.py::instantly_webhook` (line 462–465): HMAC-SHA256 verification of body using `INSTANTLY_WEBHOOK_SECRET`. Falls open if env unset, returns `{"status": "rejected", "reason": "invalid_signature"}` with HTTP 200 (not 401) on mismatch — so Instantly does NOT retry on bad signature; the event is silently dropped.

### E.6 Is `EngagementAgent.process_webhook_event` still called?

Yes. `routes/webhooks.py:716` calls it as a fallback for unknown event types:
```python
else:
    # Unknown event — pass through to EngagementAgent for legacy handling
    try:
        from backend.app.agents.engagement import EngagementAgent
        result = EngagementAgent.process_webhook_event(event_type, payload)
    except Exception:
        result = {"status": "ignored", "reason": f"unknown event_type: {event_type}"}
```

And `engagement.py:1680` calls it from `_poll_instantly_events`:
```python
self.process_webhook_event(instantly_event, event_data)
```

Within `process_webhook_event` (engagement.py:1697–1820), the bounce path still writes `companies.status='bounced'` (line 1793) — directly contradicting the tiered-suppression intent of migration 048. The reply path writes `companies.status='engaged'` (line 1808). It is fully wired up and active.

### E.7 Gmail IMAP — missing credentials behavior

`gmail_imap.py::fetch_unseen_replies` (line 164) requires `self._conn` to be set. The connection is established in `__init__` via `connect()` which calls `imaplib.IMAP4_SSL.login(user, app_password)`. **If the app password is wrong, `login()` raises `imaplib.IMAP4.error`.**

`main.py::_gmail_intake_workspace` (lines 339–377) iterates over `sender_pool` and looks up each account's password by key `gmail_{safe_email}`:
```python
acct_password = creds.get(f"gmail_{safe_key}", "app_password")
if acct_password:
    accounts_to_poll.append((acct_email, acct_password))
```
**If no password is stored for that account, the email is silently skipped (line 372–373).** No log, no warning. If `accounts_to_poll` is empty after the loop, line 376 returns immediately.

This means: a Gmail account added to a workspace's `sender_pool` without its app password being stored in CredentialStore will receive replies that are **never fetched**. Outreach can still go out via that sender (if it has SMTP/Resend creds), but inbound replies vanish until the operator notices missing HITL entries.

### E.8 Can a single event be double-written?

**Resend `email.opened`/`email.clicked`:** YES. Resend retries on non-2xx. Even with successful 2xx responses, no `event_id` dedup means a replay of the exact same payload (e.g., due to network glitch on Resend's side) creates a second `interactions` row and increments `open_count`/`click_count` twice. Confirmed by reading lines 877–917 of webhooks.py — no precondition check on `id`.

**Resend `email.bounced`:** YES. Each replay inserts a new `suppression_log` row (line 959), inserts again into `do_not_contact` (line 999 — depends on whether `add_to_dnc` is idempotent), and cancels already-cancelled sequences (line 1009–1013). The latter is harmless; the former two are not.

**Instantly via `routes/webhooks.py` `email.reply`:** YES. The handler creates a new `thread_messages` row (line 414) per call. If Instantly replays a reply, a second thread message is inserted with `direction='inbound'` even though it's the same physical email. No `external_id` or `message_id` precondition.

**Instantly via `webhooks/instantly.py`:** YES. The handler calls `db.update_contact_state(...)` for every event. The `update_contact_state` function is best-effort — does not check whether the same `instantly_event` has already been recorded for the same contact at the same timestamp.

**Gmail IMAP:** Conditional. The IMAP path marks UID as `\Seen` after processing (line 446 in main.py: `gmail.mark_as_read(reply["uid"])`). If `mark_as_read` fails, next tick re-processes the same reply. The Gmail-API path (`fetch_recent_replies` when env-OAuth set, line 394) does NOT mark as read — relies on dedup via `metadata.raw_message_id` lookup (lines 454–466). If the lookup fails for any reason (DB error swallowed in `existing` try block; the code I saw at lines 454–466 is wrapped in the dedup check itself), a duplicate `thread_messages` row could be inserted.

**Concurrent webhook + IMAP for the same reply:** YES, distinctly. If a prospect replies and Instantly fires a webhook AND the same email lands in the Gmail mailbox we poll, both paths fire independently — both write a `thread_messages` inbound row and both create HITL queue entries. Stage 1 enumerated these multiple writers; Stage 2 confirms there is no shared dedup key bridging them.

---

## F. Data Consistency SQL Queries

The following queries are read-only SELECTs intended to be run against the production Supabase Postgres database to identify inconsistencies. Each is annotated with what it detects.

```sql
-- F.1: Drafts marked sent but with an approval_status that wasn't a recognized send state.
-- Detects: drafts where the send-path claim happened but approval_status was never written
-- to 'approved' or 'edited' (the two states the strict filter accepts).
-- Note: 'sent' is NOT a valid approval_status enum value — the 'sent' state lives in sent_at IS NOT NULL.
SELECT id, workspace_id, company_id, contact_id, sequence_name, sequence_step,
       approval_status, approved_at, approved_by, sent_at, resend_message_id
  FROM outreach_drafts
 WHERE sent_at IS NOT NULL
   AND approval_status NOT IN ('approved', 'edited')
 ORDER BY sent_at DESC;
```

```sql
-- F.2: Drafts approved but with no reviewer recorded.
-- Detects approvals via script paths that never set approved_by, or endpoint fallbacks
-- where the column-write retry stripped reviewer fields.
SELECT id, workspace_id, company_id, contact_id, sequence_name, sequence_step,
       approval_status, approved_at, approved_by, reviewed_at, sent_at
  FROM outreach_drafts
 WHERE approval_status IN ('approved', 'edited', 'pending_second_review')
   AND (approved_by IS NULL OR approved_by = '')
 ORDER BY approved_at DESC NULLS LAST;
```

```sql
-- F.3: Drafts approved but reviewed_at is null.
-- Detects approvals via review_manifest, threads.py, and operator scripts that wrote
-- approved_at without reviewed_at. These rows are excluded by the scheduler strict filter
-- and included by the fallback filter — explains drafts that "should send but never do",
-- or drafts that "approved months ago and just went out today".
SELECT id, workspace_id, company_id, contact_id, sequence_name, sequence_step,
       approval_status, approved_at, approved_by, reviewed_at, sent_at
  FROM outreach_drafts
 WHERE approval_status IN ('approved', 'edited', 'pending_second_review')
   AND reviewed_at IS NULL
 ORDER BY approved_at DESC NULLS LAST;
```

```sql
-- F.4: Resend status recorded but sent_at is null.
-- Detects: webhook ran before sent_at was committed (race), or claim was rolled back
-- but resend_status was already updated by an earlier event.
SELECT id, workspace_id, company_id, contact_id, approval_status,
       sent_at, resend_message_id, resend_status, opened_at, clicked_at,
       bounced_at, complained_at
  FROM outreach_drafts
 WHERE resend_status IS NOT NULL
   AND sent_at IS NULL
 ORDER BY updated_at DESC;
```

```sql
-- F.5: Sent drafts without a Resend message id.
-- Detects: Resend SDK call raised before message_id was captured, or the post-send
-- update at engagement.py:746–750 failed silently. These rows block webhook correlation.
SELECT id, workspace_id, company_id, contact_id, sequence_name, sequence_step,
       sent_at, resend_message_id, resend_status, sender_email
  FROM outreach_drafts
 WHERE sent_at IS NOT NULL
   AND resend_message_id IS NULL
 ORDER BY sent_at DESC;
```

```sql
-- F.6: Sent drafts with no matching engagement_sequences row.
-- Detects: post-send sequence insert (engagement.py:855–865) failed silently.
-- These contacts are dropped from the sequence — no next step ever fires.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       od.sequence_name, od.sequence_step, od.sent_at
  FROM outreach_drafts od
  LEFT JOIN engagement_sequences es
    ON es.contact_id = od.contact_id
   AND es.sequence_name = od.sequence_name
   AND es.current_step >= od.sequence_step
 WHERE od.sent_at IS NOT NULL
   AND od.channel = 'email'
   AND es.id IS NULL
 ORDER BY od.sent_at DESC;
```

```sql
-- F.7: Sent drafts with no email_sent interaction within +/- 1 minute of sent_at.
-- Detects: interactions insert (engagement.py:758–772) failed, OR was inserted but the
-- interaction.created_at clock differs from sent_at by more than 1 min (suggesting
-- a clock-skew or a delayed retry).
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       od.sent_at, od.resend_message_id, od.sender_email
  FROM outreach_drafts od
  LEFT JOIN interactions i
    ON i.contact_id = od.contact_id
   AND i.type = 'email_sent'
   AND i.created_at BETWEEN (od.sent_at - INTERVAL '1 minute')
                        AND (od.sent_at + INTERVAL '1 minute')
 WHERE od.sent_at IS NOT NULL
   AND od.channel = 'email'
   AND i.id IS NULL
 ORDER BY od.sent_at DESC;
```

```sql
-- F.8: Pending or approved drafts for contacts that are suppressed or marked ineligible.
-- Detects: drafts that should not exist because the contact gate excluded them.
-- The presence of these rows means draft generation bypassed the gate or contact
-- state changed after generation but the queue was never cleaned.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       od.approval_status, od.created_at,
       c.email, c.is_outreach_eligible, c.suppression_reason, c.email_status
  FROM outreach_drafts od
  JOIN contacts c ON c.id = od.contact_id
 WHERE od.approval_status IN ('pending', 'approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (c.suppression_reason IS NOT NULL OR c.is_outreach_eligible = FALSE)
 ORDER BY od.created_at DESC;
```

```sql
-- F.9: Pending or approved drafts for contacts with terminal email status.
-- Detects: drafts targeting bounced/invalid/DNC contacts. These will fail at the
-- send-path assertion gate but consume queue slots and create reviewer noise.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       od.approval_status, od.created_at,
       c.email, c.email_status, c.status AS contact_status
  FROM outreach_drafts od
  JOIN contacts c ON c.id = od.contact_id
 WHERE od.approval_status IN ('pending', 'approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (c.email_status IN ('bounced', 'invalid', 'do_not_contact')
        OR c.status IN ('bounced', 'do_not_contact', 'unsubscribed'))
 ORDER BY od.created_at DESC;
```

```sql
-- F.10: Companies with positive engagement on one contact while other contacts have
-- pending/approved drafts. Detects: company traction signal is not propagating to
-- siblings — outreach continues at a company that has already engaged via someone else.
SELECT od.id AS draft_id, od.workspace_id, od.company_id,
       od.contact_id AS pending_contact_id,
       od.approval_status,
       engaged.contact_id AS engaged_contact_id,
       engaged.reply_sentiment,
       engaged.status AS engaged_contact_status
  FROM outreach_drafts od
  JOIN contacts engaged
    ON engaged.company_id = od.company_id
   AND engaged.id <> od.contact_id
   AND engaged.reply_sentiment IS NOT NULL
   AND engaged.reply_sentiment NOT IN ('bounced', 'unsubscribed', 'auto_reply')
 WHERE od.approval_status IN ('pending', 'approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
 ORDER BY od.company_id, od.created_at DESC;
```

```sql
-- F.11: Duplicate draft detection. Two or more non-terminal rows for the same
-- (workspace, company, contact, step) combination. Stage 1 noted no UNIQUE index
-- protects this; query confirms current population.
SELECT workspace_id, company_id, contact_id, sequence_step,
       COUNT(*) AS dup_count,
       ARRAY_AGG(id ORDER BY created_at) AS draft_ids,
       ARRAY_AGG(approval_status ORDER BY created_at) AS statuses,
       ARRAY_AGG(sequence_name ORDER BY created_at) AS seq_names
  FROM outreach_drafts
 WHERE approval_status NOT IN ('rejected')  -- 'deleted' is not in enum; rejected is the disposal state
 GROUP BY workspace_id, company_id, contact_id, sequence_step
HAVING COUNT(*) > 1
 ORDER BY dup_count DESC, workspace_id;
```

```sql
-- F.12: Contact outreach_state suggests a touch was sent, but no matching draft
-- has sent_at set for that step. Detects: state machine drift — contact thinks
-- they've been touched but the draft record disagrees.
-- Step number is extracted from the touch_N_sent / touch_N_opened / touch_N_clicked pattern.
SELECT c.id AS contact_id, c.workspace_id, c.company_id,
       c.outreach_state,
       (REGEXP_MATCH(c.outreach_state, 'touch_([1-5])_sent'))[1]::int AS state_step,
       c.outreach_state_updated_at,
       od.id AS matching_draft_id,
       od.sequence_step AS draft_step,
       od.sent_at
  FROM contacts c
  LEFT JOIN outreach_drafts od
    ON od.contact_id = c.id
   AND od.sequence_step = (REGEXP_MATCH(c.outreach_state, 'touch_([1-5])_sent'))[1]::int
   AND od.sent_at IS NOT NULL
 WHERE c.outreach_state ~ '^touch_[1-5]_sent$'
   AND od.id IS NULL
 ORDER BY c.outreach_state_updated_at DESC;
```

---

## G. Operator Script Truth

### G.1 `scripts/pending_draft_reconciliation.py`

1. **Supabase key used:** `SUPABASE_SERVICE_KEY` (line 42) — **service-role key**, bypasses RLS. Loaded via `dotenv` from `.env` at repo root (line 31).
2. **Columns written to `outreach_drafts`** (single `.update({...})` call at line 472):
   - `approval_status = 'approved'`
   - `approved_at = now_iso` (UTC timestamp)
   - `approved_by = 'avanish'` (literal string, line 465)
   - `body = body_after` (only when fixes applied — line 469)
   - `edited_body = body_after` (only when fixes applied — line 470)
3. **Does it preserve `body`?** **NO when fixes are applied.** Lines 468–470 overwrite `body` with the fixed version. The script's `_fix_body` does regex substitutions for em-dash, en-dash, double dash, spaced-hyphen, meeting-ask patterns, diagnostic offer wording, no-commitment/no-cost language. The original model output is gone after this write.
4. **Does it write to audit tables?** **NO.** No `outreach_edit_feedback` insert. No `audit_events`/`audit_log` insert. No `log_audit_event_from_ctx` call.
5. **`approved_by` value:** Hardcoded string `"avanish"` (line 41 `APPROVED_BY = "avanish"`). Since the column is TEXT (migration 045), this succeeds silently.
6. **Quality gates before writing:** Script-internal regex-based `_check_body_quality` (lines 65–154) checks for em-dash, en-dash, double-dash, spaced-hyphen, dropped-I-subject, missing brand descriptor, meeting ask, diagnostic offer, no-commitment language, no-cost language. **This is a separate code path from `backend/app/core/draft_quality.validate_draft`** and they can drift. Also runs `_check_contact_governance` (lines 268–277): checks `email_status` in `{verified, catch_all}`, `is_outreach_eligible == True`, `contact_tier != 'excluded'`. Also `_check_suppression` (lines 280–293) and `_check_step_gap` (lines 296–318) — but **a `CHECK_ERROR` or `PARSE_ERROR` from step-gap check is treated as OK** (line 427: `step_gap_ok = step_gap_status in ("OK", "PARSE_ERROR", "CHECK_ERROR")`). So a step-1 draft that has not actually been sent could pass if the check raises.
7. **Recently run?** File mtime: `May 13 18:01` (1 day before today, 2026-05-14). Recent. Stage 1 mentioned a docs file `docs/reports/REVIEW_QUEUE_RECONCILIATION_AND_DRAFT_STATE_RECOVERY.md` references this script. No cron entry, no Makefile target. Invoked manually.
8. **Blast radius on full pending queue:** Currently capped at `BATCH_SIZE = 64` (line 47), with sort key `(company_name, last_name)`. Within those 64, any draft passing both content checks and governance gets `approval_status='approved'` and (if content was fixed) its `body`/`edited_body` rewritten. Under fallback-filter mode in the scheduler, all approved drafts are immediately eligible for the next send tick. **A run touches up to 64 drafts; if MIN_STEP_GAP_DAYS check is lenient (treats errors as OK), some of those 64 could send without a step-1 having actually been sent.**

### G.2 `scripts/rejected_draft_reassessment.py`

1. **Supabase key:** Same — `SUPABASE_SERVICE_KEY`, service-role.
2. **Columns written** (single `.update({...})` call at line 557):
   - `approval_status = 'approved'`
   - `approved_at = now_iso`
   - `approved_by = 'avanish'` (line 550)
   - `rejection_reason = None` (line 551) — **clears the prior rejection reason**
   - `body = body_after` (when fixes applied, line 554)
   - `edited_body = body_after` (when fixes applied, line 555)
3. **Preserves `body`?** **NO when fixes applied.** Same surgical rewrites as pending_draft_reconciliation.
4. **Audit table writes?** **NO.** Same as pending script.
5. **`approved_by` value:** Hardcoded `"avanish"`.
6. **Quality gate:** Same body-quality regex check. Additionally classifies rejection_reason into categories (REGENERATE / PERMANENT_REJECT / SAFE_TO_APPROVE / CONTENT_FIX_THEN_APPROVE / QUARANTINE).
7. **Recently run?** File mtime: `May 13 18:01`. Same window.
8. **Blast radius:** Reads from rejected-status drafts. Each row that classifies as SAFE_TO_APPROVE or CONTENT_FIXED_APPROVED gets `rejection_reason` cleared AND `approval_status='approved'` AND (potentially) `body` rewritten. **Once `rejection_reason` is NULL, the original reason for rejection is unrecoverable.** Drafts that the model previously rejected for integrity violations (e.g., URL in step 1, banned phrases) could be re-approved by the regex check missing what the model caught.

### G.3 `backend/scripts/manage_thread.py`

1. **Supabase key:** Uses `Database()` (line ≈593), which goes through `get_supabase_client()` — the singleton client. Production environment determines which key (likely service-role, since this is a CLI tool).
2. **Approval-status writes:** Single `.update({"approval_status": "approved"}).eq("id", draft_id)` at line 619–621. **Only writes that single field — no `approved_by`, no `reviewed_at`, no `approved_at`.**
3. **`body` preservation:** Does NOT mutate body. Reads from existing draft.
4. **Audit writes:** Calls `tm.add_outbound_message(...)` to record in `thread_messages` (line 624–630). Does NOT call `log_audit_event_from_ctx`.
5. **`approved_by`:** Never set.
6. **Quality gate:** **NONE.** Goes straight from `draft.get("body")` to push-to-Instantly to `approval_status='approved'`.
7. **Recently run?** Cannot determine; file is part of historical "send via Instantly" tooling. The script's `send` subcommand is registered at line 719.
8. **Blast radius:** Per-invocation, processes one draft id passed as argv. If invoked in a loop by a wrapper, the blast radius scales with the wrapper.

### G.4 Operational hooks

Searched Makefile, `run_pipeline_loop.sh`, all README files for references to `pending_draft_reconciliation` or `rejected_draft_reassessment`. **Zero hits in Makefile** (which only contains `install`, `api`, `dashboard`, `dev` targets). The scripts are documented in `docs/reports/REVIEW_QUEUE_RECONCILIATION_AND_DRAFT_STATE_RECOVERY.md` (per Stage 1 grep) but not wired into any automated runner. They are invoked manually.

---

## Stage 2 Summary

### Confirmed Runtime Facts

1. **Migration 045 was authored and exists in `supabase_migrations/migrations/`.** It adds `outreach_drafts.approved_by` (TEXT, nullable, no default), `outreach_drafts.reviewed_at` (TIMESTAMPTZ, nullable, no default), `outreach_drafts.attestation` (JSONB, nullable, no default), and extends the `approval_status` enum with `pending_second_review`. Whether the migration is actually applied in production cannot be determined from source — but the column types are now known.

2. **`approved_by` is TEXT, not a UUID FK.** Operator scripts writing literal `"avanish"` to it succeed without error. Audit grouping by `approved_by` mixes real user IDs with this literal.

3. **There is no DB-level CHECK constraint** linking `approval_status='approved'` to `approved_by IS NOT NULL` or `reviewed_at IS NOT NULL`. All three columns can be NULL while the row reads as approved.

4. **No UNIQUE index** exists on `outreach_drafts(workspace_id, company_id, contact_id, sequence_step)` or any subset suitable for duplicate-draft prevention.

5. **The send-path strict filter is conditional in two distinct ways**, both in `engagement.py`:
   - `if draft_ids:` skips it (line 451–457) — explicit draft_ids are treated as attestation.
   - `except Exception` branch (line 471–485) falls back to `approval_status='approved'` only when the strict query raises. With migration 045 applied, the query no longer raises — it simply returns zero rows, which the operator may misread as "scheduler is broken."

6. **APScheduler starts unconditionally** in every running FastAPI process. No singleton check, no environment gate, no distributed lock anywhere in the codebase.

7. **The Procfile declares one `web` process.** Replica count is set in Railway dashboard, not in source.

8. **Of 23 active scheduler jobs, only `send_approved` has any per-row concurrency protection** (the compare-and-swap on `sent_at`). Every other job is unsafe under multi-replica execution.

9. **There are eight distinct write paths to `approval_status='approved'`** — the HTTP `/api/approvals/{id}/approve` endpoint, `review_manifest.approve_manifest`, `pending_draft_reconciliation.py`, `rejected_draft_reassessment.py`, `threads.py::approve_and_send`, `manage_thread.py::send`, `linkedin_sender._register_send`, and `content.py` (LinkedIn post path). Only the first runs the full gate suite.

10. **Two Instantly webhook routers are simultaneously mounted at different prefixes** (`/api/webhooks/instantly` and `/webhooks/instantly`), with different verification methods (query-param secret vs HMAC), different DB write patterns, and different handler implementations.

11. **No webhook handler in the system performs duplicate-event detection by `event_id`/`external_id`.** Resend, Instantly (both paths), Trigify all blindly write on replay.

12. **The single value that gates production sends per tick is `outreach_send_config.daily_limit` for the active workspace.** Defaults are 30 in code, 125 in YAML, 500 per the main.py comment — three different "defaults" in three sources. The actual value per workspace requires a DB read.

13. **`workspace_daily_sends_ok` is deliberately disabled** in the send path (main.py:189–194 comment).

14. **`pace_limiter.PaceLimiter` is dead code in the send path** — its only consumer is `backend/scripts/dashboard.py`. The CAMPAIGN_DEFAULTS=30 documented in Stage 1 has no effect on production sends.

15. **Operator scripts `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` were last modified May 13, 2026 (one day before today).** They are recent and actively maintained. Both bypass every endpoint gate, mutate `body` in-place, write `approved_by="avanish"` literal, and do not write `reviewed_at` or audit events.

16. **`process_webhook_event` (engagement.py:1697) is still live and called from two paths:** `routes/webhooks.py:716` (unknown-event-type fallback) and `engagement.py:1680` (`_poll_instantly_events` reconciliation). It writes `companies.status='bounced'` on email_bounced — contradicting tiered-suppression intent.

17. **`db.update_company(..., allow_downgrade=False)` at `webhooks.py:989` would TypeError at runtime** — `Database.update_company` (database.py:285) takes only `(self, company_id, data)`. The call is reachable only on the spam-complaint path. Wrapped in a try/except so the failure is silently swallowed, but the intended downgrade-block is not applied — the company status DOES move to `not_interested` because the kwarg never makes it to the underlying call. Actually wait: the kwarg makes the call itself raise before the SQL is issued, so the company status update does NOT happen and the exception is logged then swallowed. Net effect: spam-complaint never updates the company status, contrary to the comment.

### Unknowns Requiring Live DB or Log Access

1. **Has migration 045 actually been applied in production?** Source confirms the file exists; only a `\d outreach_drafts` against the production DB will tell.

2. **What is the current per-workspace value of `outreach_send_config.daily_limit`?** Cannot be determined from source.

3. **How many Railway replicas are running?** Set in Railway dashboard.

4. **How often are `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` actually invoked?** Shell history, terminal logs, or audit JSON files in `docs/reports/` would tell.

5. **Which Instantly webhook URL is configured in the Instantly dashboard** — `/api/webhooks/instantly` or `/webhooks/instantly`? Live Instantly settings.

6. **Are `RESEND_WEBHOOK_SECRET`, `INSTANTLY_WEBHOOK_SECRET`, `webhook_secret` actually set in the production Railway env?** If unset, those endpoints accept unsigned traffic.

7. **Has the production database accumulated drafts where `approval_status='approved'` but `approved_by IS NULL` or `reviewed_at IS NULL`?** F.2 and F.3 SQL queries answer this directly.

8. **How many production rows have `sent_at IS NOT NULL` but `resend_message_id IS NULL` or no matching `email_sent` interaction?** F.5, F.7 queries.

9. **Does the `/Volumes/Digitillis/Data/prospectiq_backups/` path exist on the Railway container?** Likely no — Railway containers are ephemeral. The `weekly_contact_backup` job is silently failing.

10. **Is the Gmail OAuth path (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`) set in production?** Determines whether IMAP or Gmail API is in use. Different dedup semantics each path.

### Immediate Kill-Switch Recommendations (No Rearchitecture Required)

1. **Set `SEND_ENABLED=false` in Railway env** until the strict-vs-fallback ambiguity is resolved (see #5 below).

2. **Disable both operator scripts** (rename to `.disabled` or move out of `scripts/`) until they are rewritten to call the endpoint instead of writing directly. They are the single largest current source of approval-bypass.

3. **Run F.2, F.3 immediately** to enumerate drafts approved without reviewer attribution. Hold them in a quarantine status (`approval_status='pending'` rollback) until manually re-approved through the endpoint.

4. **Run F.4, F.5, F.7** to identify orphaned `sent_at` rows. Decide per-row whether to clear `sent_at` (to retry) or to backfill `resend_message_id` from Resend's logs.

5. **Unmount one of the two Instantly webhook routers.** Pick whichever path is actually configured in Instantly (preferably the HMAC-verified `/webhooks/instantly`) and `app.include_router(...)` the other should be commented out. Currently both are live and behavior depends on which URL Instantly is hitting.

6. **Set `RESEND_WEBHOOK_SECRET` and `INSTANTLY_WEBHOOK_SECRET` in Railway env if not already set.** The endpoints fail-open today.

7. **Set `force=true` audit:** Add a Railway log alert / grep on log lines matching the `?force=true` parameter being used. There is no audit metadata distinguishing force-approvals from normal ones today; the only signal is the log line generated by `log_audit_event_from_ctx`.

8. **Add a manual reviewer-cap check** at the top of `approve_manifest` (review_manifest.py:270) — currently it bypasses the cap entirely.

9. **Comment out the `weekly_contact_backup` job** until either the volume is mounted or the path is changed to S3/Supabase storage. Silently-failing backups are worse than no backups.

10. **Block deployment of more than one Railway replica** until distributed-lock work lands. Set Railway service to 1 replica. Document this as a HARD constraint.

11. **Stop the `process_webhook_event` static method from being called by `_poll_instantly_events`** — the legacy path writes `companies.status='bounced'`, which contradicts tiered-suppression. Either delete the function or have the polling path call the new handlers in `webhooks.py`.

12. **Fix the `allow_downgrade=False` TypeError on the spam-complaint path** by either accepting `**kwargs` in `update_company` or removing the kwarg from the caller. Currently spam complaints do NOT downgrade company status because the exception is swallowed.

### Risks Requiring Rearchitecture

1. **Eight independent writers to `approval_status='approved'`** cannot be safely reconciled by patching each call site. The schema needs a CHECK constraint linking `approval_status` to `(approved_by IS NOT NULL AND reviewed_at IS NOT NULL AND attestation IS NOT NULL)`, AND a database-level trigger that forces `approved_at = now()` on transition, AND the application code paths need to consolidate around a single approval procedure (e.g., a stored procedure or one Python module).

2. **`outreach_drafts.body` is mutable forever.** Migration 003 only protects against DELETE of `sent_at IS NOT NULL` rows. The body is still writable. Either add a trigger that blocks `UPDATE` of `(body, subject, sequence_name, sequence_step)` once `sent_at IS NOT NULL`, or split into an immutable `outreach_draft_versions` table.

3. **The compare-and-swap on `sent_at` is the only guard against concurrent sends.** Stage 1 noted this. In the multi-replica future, this should be supplemented by a postgres advisory lock taken on `(workspace_id, contact_id)` for the duration of the send-path assertion + Resend call + post-send writes, so the whole sequence is atomic. Today it is decidedly not.

4. **`sent_at` is set before assertions run, then rolled back if assertions fail.** A failed rollback orphans the draft forever. Rearchitect to (a) take an advisory lock, (b) run assertions, (c) call Resend, (d) write `sent_at` and follow-ons in a single transaction, (e) release lock. This is the single highest-priority structural change.

5. **No transactional boundary around the post-send writes** (interactions, campaign_threads, thread_messages, engagement_sequences, contact state update, company status update, set_company_outreach_active). Any of these failing silently leaves the system in an inconsistent state. Wrap them in a single transaction or use the Outbox pattern (write an event to an outbox table, then a separate consumer fans out).

6. **Two `OutreachAgent` classes** (Stage 1 H risk #3) writing to the same table with different gate suites. Either delete `agents/outreach_agent.py` or consolidate.

7. **The four-source send-cap mismatch** (limits.yaml / outreach_send_config / workspaces.settings / pace_limiter CAMPAIGN_DEFAULTS) cannot be patched away. Designate a single source — likely `outreach_send_config` — and either delete the others (pace_limiter) or treat them as documentation only.

8. **In-process APScheduler under FastAPI** is unsuitable for any multi-replica deployment. Move to Celery + Redis, or to a single-instance worker container (Procfile `worker:` process with concurrency=1 and explicit "only on this process" gating).

9. **Webhook idempotency** requires a `webhook_events` table keyed on `(provider, event_id)` with INSERT-IF-NOT-EXISTS semantics. Every handler should call `if not webhook_events.insert(...): return {"status": "duplicate"}` as its first line.

10. **The two Instantly webhook handlers** are an architectural split, not a code-organization issue. Remove `backend/app/webhooks/instantly.py` (or `backend/app/api/routes/webhooks.py::instantly_webhook`) entirely and pick one canonical path.

11. **Reviewer column type mismatch:** `approved_by` is TEXT in migration 045 but the TODO comment in approvals.py:37 specifies "UUID, FK to users." Either change the column type (data migration required to map existing values) or accept the looser TEXT semantics in code (and stop expecting UUID-shaped reviewer ids).




---
# Stage 3: Preservation-First Stabilization Plan

- **Date:** 2026-05-14
- **Status:** ACTIVE — read before next send run
- **Owner:** Avanish Mehrotra
- **Scope window:** before the next Mon–Fri 8:00–11:00 AM Chicago send tick
- **Operating posture:** preserve every draft, contact, company, suppression signal, sequence, and reply thread. Quarantine, never delete. Reverse every action with a single SQL/env change.

---

## Section 1: Immediate Pre-Send Safety Actions (Ordered by Priority)

These are sequenced so each step's rollback is independent of the next.

### Action 1.1 — Snapshot every at-risk table to CSV (Supabase)
- **What to do:** run every COPY/SELECT in Section 2 against the production Supabase Postgres before any other action. Save the outputs to `/Users/avanish/prospectIQ/backups/2026-05-14/` and to Supabase Storage `prospectiq-stabilization-2026-05-14/`.
- **Why:** every subsequent action — quarantine, env flips, router unmounts — assumes a recoverable snapshot exists. Stage 2 confirmed there is no transactional boundary around approval or send writes (engagement.py:557–569 claim, lines 776–887 post-send writes, all best-effort), so an in-flight failure is only undoable from a snapshot.
- **Duration:** 10–15 minutes (Supabase SQL editor + manual download).
- **Deployment required:** No. Read-only SELECTs.
- **Rollback:** N/A — read-only.
- **SEND-BLOCKER:** **Yes.** Do not proceed past this step without the snapshot stored.

### Action 1.2 — Set `SEND_ENABLED=false` in Railway env, force-redeploy
- **What to do:** in the Railway dashboard for the ProspectIQ API service, set env var `SEND_ENABLED=false` and trigger a redeploy. Confirm by hitting `GET /api/admin/send-config` (main.py:2313) — `send_enabled` should report false. The engagement path at engagement.py:310–315 hard-exits before any draft is fetched when this is false.
- **Why:** Stage 2 H risk #1 — eight write paths to `approval_status='approved'` are live; the fallback-vs-strict reviewer filter at engagement.py:471–485 is undecidable from source. Until we have confirmed in section 5 which approved drafts are safe, no scheduler tick should be permitted to fire.
- **Duration:** ~3 minutes to set, ~5 minutes for Railway redeploy.
- **Deployment required:** Yes — Railway env var change forces a redeploy.
- **Rollback:** unset `SEND_ENABLED` or set to `true` in Railway dashboard; redeploy. The `_send_approved_drafts` function will resume on the next tick.
- **SEND-BLOCKER:** **Yes.** This is the single global kill switch confirmed in Stage 2 G section.

### Action 1.3 — Set `outreach_send_config.send_enabled = false` for every workspace (DB-level kill)
- **What to do:** run the following SQL in Supabase SQL Editor:
  ```sql
  -- Save current values first so we can roll back exactly per workspace.
  CREATE TABLE IF NOT EXISTS _stabilization_send_config_2026_05_14 AS
    SELECT workspace_id, send_enabled, daily_limit, batch_size, min_gap_minutes,
           NOW() AS captured_at
      FROM outreach_send_config;

  -- Apply the kill switch.
  UPDATE outreach_send_config SET send_enabled = false WHERE send_enabled = true;
  ```
- **Why:** Section G of the analysis lists send-time governance precedence — `outreach_send_config.send_enabled` (DB) is precedence #2 and Stage 2 D.7 confirms it is the per-workspace authoritative kill. Defense in depth on top of Action 1.2: if `SEND_ENABLED` is re-enabled prematurely, the DB toggle still blocks at engagement.py:333–335.
- **Duration:** 1 minute.
- **Deployment required:** No.
- **Rollback:**
  ```sql
  UPDATE outreach_send_config oc
     SET send_enabled = s.send_enabled
    FROM _stabilization_send_config_2026_05_14 s
   WHERE oc.workspace_id = s.workspace_id;
  ```
  Then verify with `SELECT workspace_id, send_enabled FROM outreach_send_config;`.
- **SEND-BLOCKER:** **Yes** (paired with 1.2 for defense in depth).

### Action 1.4 — Confirm Railway scheduler replica count = 1
- **What to do:** follow Section 8 below. If replica count > 1, scale to 1 and redeploy.
- **Why:** Stage 2 B.2 confirmed there is NO singleton check, NO advisory lock, NO Redis lock anywhere in the scheduler. Multi-replica execution doubles every cron tick. Of 23 jobs only `send_approved` has compare-and-swap protection. Even with `SEND_ENABLED=false`, other unsafe jobs (`bounce_hygiene`, `process_due`, `draft_generation`, `jit_pregenerate`) will write concurrently if replicas > 1.
- **Duration:** 5 minutes.
- **Deployment required:** Yes if scaling.
- **Rollback:** scale back to prior replica count. The system tolerated this before; no data corrective action needed unless duplicate writes appeared in section 5 query (e).
- **SEND-BLOCKER:** **Yes** — if replicas > 1 are running concurrent draft_generation/jit_pregenerate ticks, the approved queue may already contain duplicates that the send tick would dispatch in parallel.

### Action 1.5 — Verify migration 045 columns are present in production
- **What to do:** run in Supabase SQL Editor:
  ```sql
  SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
   WHERE table_name = 'outreach_drafts'
     AND column_name IN ('approved_by', 'reviewed_at', 'attestation')
   ORDER BY column_name;
  ```
  Expected: three rows with types `text`, `timestamp with time zone`, `jsonb`. If any row is missing, migration 045 has NOT been applied in production.
- **Why:** Stage 2 A.1 confirms migration 045 authored these columns but applied state is unknown. The fallback path in engagement.py:471–485 fires only if the strict query raises (column missing); if 045 is applied, the strict path returns rows where `approved_by IS NOT NULL AND reviewed_at IS NOT NULL`. Knowing this resolves the largest ambiguity for the next send.
- **Duration:** 1 minute.
- **Deployment required:** No.
- **Rollback:** N/A — read-only.
- **SEND-BLOCKER:** **Yes.** Cannot make a safe decision about which drafts will go out without this answer.

### Action 1.6 — Verify production `outreach_send_config.daily_limit` per workspace
- **What to do:**
  ```sql
  SELECT workspace_id, daily_limit, batch_size, min_gap_minutes, send_enabled, sender_pool
    FROM outreach_send_config
   ORDER BY workspace_id;
  ```
- **Why:** Stage 2 D.7 — this is the single authoritative cap. Defaults are 30 (code) / 125 (YAML) / 500 (per main.py comment). Operator should write down the value before re-enabling sends so the post-send count can be verified against intent.
- **Duration:** 1 minute.
- **Deployment required:** No.
- **Rollback:** N/A — read-only.
- **SEND-BLOCKER:** No, but strongly recommended.

### Action 1.7 — Pause the two operator scripts via filename
- **What to do:** see Section 7 — rename to `.disabled.py`. Do not delete.
- **Why:** Stage 2 G.1 + G.2 confirm both scripts use service-role key, write `approved_by="avanish"` literal, mutate `body` in place, do not write `reviewed_at`, and were last touched May 13 (yesterday). Until quarantine queries in Section 5 are run, no further script approval writes should be permitted.
- **Duration:** 30 seconds.
- **Deployment required:** No (the scripts are CLI tools — they live on Avanish's workstation, not Railway).
- **Rollback:** rename back to `.py`.
- **SEND-BLOCKER:** No, because the scripts are manually invoked. But should be done before Section 5 runs to prevent a race.

### Action 1.8 — Verify `RESEND_WEBHOOK_SECRET` and `INSTANTLY_WEBHOOK_SECRET` are set in Railway env
- **What to do:** check Railway dashboard env. If either is unset, set it now (generate a 32-byte hex random value, store in 1Password, and update the corresponding webhook provider config in Resend / Instantly).
- **Why:** Stage 2 E.4 + E.5 confirm both endpoints fail open when the secret is unset. An unsigned webhook can mutate `companies.status`, `contacts.status`, `outreach_drafts.resend_status`, `suppression_log`, `do_not_contact`. With sends paused, this is the second-largest write vector.
- **Duration:** 5 minutes.
- **Deployment required:** Yes (env var change).
- **Rollback:** revert to prior value (or unset).
- **SEND-BLOCKER:** No. But unsigned webhooks during the paused window could corrupt state we will need to inspect.

---

## Section 2: Data Backup and Snapshot Checklist

Run all queries below in the Supabase SQL Editor, then export each result to CSV using the editor's download button. Store at `/Users/avanish/prospectIQ/backups/2026-05-14/`. For very large tables, use the `COPY (...) TO STDOUT` form from a `psql` connection (Supabase → Database → Connection string).

Note: Supabase web SQL editor exports as CSV; for canonical JSON snapshots use `pg_dump --data-only --table=<name> --format=plain` against the connection string.

### 2.1 outreach_drafts — full table (every status)
```sql
SELECT id, workspace_id, company_id, contact_id, channel, sequence_name, sequence_step,
       subject, body, edited_body, personalization_notes,
       approval_status, rejection_reason,
       approved_at, approved_by, reviewed_at, attestation,
       sent_at, instantly_lead_id, instantly_campaign_id,
       resend_message_id, resend_status, sender_email,
       opened_at, clicked_at, bounced_at, complained_at,
       model, top_signal_id, top_signal_type,
       created_at, updated_at
  FROM outreach_drafts
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_outreach_drafts_full.csv`

### 2.2 contacts — full table
```sql
SELECT *
  FROM contacts
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_contacts_full.csv`. For pg_dump:
```bash
pg_dump --no-owner --data-only --table=contacts \
  --format=plain --file=2026-05-14_contacts_full.sql "$SUPABASE_CONN"
```

### 2.3 companies — full table
```sql
SELECT *
  FROM companies
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_companies_full.csv`. Also export `research_summary`, `pain_signals`, `personalization_hooks` separately if they were stored as `jsonb` — Supabase CSV truncates large JSONB cells in the UI; use pg_dump for fidelity:
```bash
pg_dump --no-owner --data-only --table=companies \
  --format=plain --file=2026-05-14_companies_full.sql "$SUPABASE_CONN"
```

### 2.4 engagement_sequences — full table
```sql
SELECT *
  FROM engagement_sequences
 ORDER BY started_at DESC NULLS LAST, created_at DESC;
```
Filename: `2026-05-14_engagement_sequences_full.csv`.

### 2.5 interactions — full table
```sql
-- Filter to the last 180 days if the row count is huge; otherwise export all.
SELECT *
  FROM interactions
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_interactions_full.csv`. Use pg_dump for canonical:
```bash
pg_dump --no-owner --data-only --table=interactions \
  --format=plain --file=2026-05-14_interactions_full.sql "$SUPABASE_CONN"
```

### 2.6 suppression_log — full table
```sql
SELECT *
  FROM suppression_log
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_suppression_log_full.csv`.

### 2.7 campaign_threads — full table
```sql
SELECT *
  FROM campaign_threads
 ORDER BY updated_at DESC NULLS LAST, created_at DESC;
```
Filename: `2026-05-14_campaign_threads_full.csv`.

### 2.8 outreach_send_config — every workspace
```sql
SELECT *
  FROM outreach_send_config
 ORDER BY workspace_id;
```
Filename: `2026-05-14_outreach_send_config_full.csv`.

### 2.9 workspaces.settings — JSONB column specifically
```sql
SELECT id AS workspace_id, name, settings, created_at, updated_at
  FROM workspaces
 ORDER BY id;
```
Filename: `2026-05-14_workspaces_settings.csv`. The `settings.daily_send_limit`, `settings.sender_pool`, `settings.monthly_api_budget_usd` keys live here (Stage 1 G).

### 2.10 thread_messages — preserve outbound/inbound history
```sql
SELECT id, thread_id, direction, subject, body,
       sent_at, received_at, outreach_draft_id, source,
       created_at, updated_at, workspace_id
  FROM thread_messages
 ORDER BY COALESCE(sent_at, received_at, created_at) DESC;
```
Filename: `2026-05-14_thread_messages_full.csv`. Critical for reply correlation (Section 9).

### 2.11 do_not_contact — preserve hard blocks
```sql
SELECT *
  FROM do_not_contact
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_do_not_contact_full.csv`.

### 2.12 send_assertions — last 60 days of pre-send gate evidence
```sql
SELECT *
  FROM send_assertions
 WHERE evaluated_at >= NOW() - INTERVAL '60 days'
 ORDER BY evaluated_at DESC;
```
Filename: `2026-05-14_send_assertions_recent.csv`.

### 2.13 workspace_audit_log — last 60 days of approval events
```sql
SELECT *
  FROM workspace_audit_log
 WHERE created_at >= NOW() - INTERVAL '60 days'
 ORDER BY created_at DESC;
```
Filename: `2026-05-14_workspace_audit_log_recent.csv`. Stage 1 G — this is where `log_audit_event_from_ctx` lands.

### 2.14 Verification — count every row exported
After download, verify counts match:
```sql
SELECT
  (SELECT COUNT(*) FROM outreach_drafts) AS outreach_drafts,
  (SELECT COUNT(*) FROM contacts) AS contacts,
  (SELECT COUNT(*) FROM companies) AS companies,
  (SELECT COUNT(*) FROM engagement_sequences) AS engagement_sequences,
  (SELECT COUNT(*) FROM interactions) AS interactions,
  (SELECT COUNT(*) FROM suppression_log) AS suppression_log,
  (SELECT COUNT(*) FROM campaign_threads) AS campaign_threads,
  (SELECT COUNT(*) FROM outreach_send_config) AS outreach_send_config,
  (SELECT COUNT(*) FROM thread_messages) AS thread_messages,
  (SELECT COUNT(*) FROM do_not_contact) AS do_not_contact;
```
Save the output in `2026-05-14_row_counts.txt`.

---

## Section 3: Tables and Fields That Must Never Be Modified During Stabilization

Read-only window: from now until the next clean send tick completes. The following are preservation-critical: any UPDATE / DELETE on them during this window destroys traction history, suppression signals, or reply routing.

### 3.1 outreach_drafts — partial read-only

| Column | Read-only? | Reason |
|---|---|---|
| `id` | YES | Stable identifier referenced by `interactions.metadata`, `thread_messages.outreach_draft_id`, Resend `idempotency_key`. |
| `body`, `subject` | YES | Audit trail of original model output. Stage 2 G.1 confirms operator scripts mutate this — must stop. |
| `sent_at` | YES | Migration 003 DELETE trigger covers DELETE; UPDATE is the risk. Setting to NULL on a row with `resend_message_id` would cause duplicate Resend dispatch on the next tick. |
| `resend_message_id` | YES | Sole webhook correlation key. |
| `rejection_reason` | YES | Stage 2 G.2 — `rejected_draft_reassessment.py` line 551 clears this. Once NULL the prior model judgement is gone. |
| `approved_at`, `approved_by`, `reviewed_at`, `attestation` | YES | Reviewer attestation evidence. |
| `created_at`, `updated_at` | YES | Auditability. |
| `approval_status` | Quarantine-write OK (Section 6) — otherwise read-only | The only intentional column write during stabilization is the quarantine flip described in Section 6. |
| `edited_body` | Quarantine/reviewer-only | Section 6 backfill or future endpoint approval. |

### 3.2 contacts — preserve all enrichment + state

| Column | Read-only? | Reason |
|---|---|---|
| `email`, `first_name`, `last_name`, `full_name`, `title` | YES | Apollo/ZeroBounce-enriched. Rebuilding costs $$. |
| `email_status` | YES | Sole input to `assert_email_status_verified` and bounce hygiene. |
| `is_outreach_eligible`, `contact_tier`, `outreach_state`, `outreach_state_updated_at` | YES | State machine — touching it without coordinated draft updates causes drift (Stage 2 F.12). |
| `last_touch_at`, `last_touch_channel`, `open_count`, `click_count`, `intent_score` | YES | Traction signals. |
| `reply_sentiment` | YES | Drives channel_coordinator traction read. |
| `linkedin_url`, `linkedin_status`, `apollo_id`, `apollo_person_id` | YES | Enrichment identifiers. |
| `suppression_reason` | YES | Tiered-suppression signal. |
| `status` | YES | bounced / unsubscribed / do_not_contact are sticky. |

### 3.3 companies — research intelligence is irreplaceable

| Column | Read-only? | Reason |
|---|---|---|
| `research_summary`, `pain_signals`, `personalization_hooks` | YES | Anthropic/Perplexity-generated; cost ~$0.10–$0.40 per company. |
| `naics`, `naics_prefix`, `sub_industry`, `tier`, `campaign_cluster` | YES | Targeting taxonomy. |
| `outreach_active`, `primary_contact_id`, `outreach_started_at`, `outreach_last_touch_at` | YES | Sequence anchor. |
| `pqs_*` (all PQS score columns), `intent_score`, `intent_signals` | YES | Scoring history. |
| `engagement_tier` (if present from migration 045) | YES | Tier-state machine. |
| `status` | YES | Modern + legacy code both write here; under stabilization treat read-only to prevent ratchet from `contacted` back to `outreach_pending`. |
| `suppression_reason` | YES | |

### 3.4 engagement_sequences — sequence orchestration anchor

All columns read-only. The send path inserts here at engagement.py:855–865 to schedule next steps. Modifying `next_action_at` or `status` mid-stabilization would either drop contacts from the sequence or trigger an unscheduled re-send.

### 3.5 campaign_threads + thread_messages — reply routing identity

| Column | Read-only? | Reason |
|---|---|---|
| `campaign_threads.id` | YES | Foreign key target for every inbound reply. |
| `campaign_threads.contact_id`, `company_id`, `sequence_name` | YES | Reply correlation. |
| `campaign_threads.status` | YES | Lifecycle (`active`, `paused`, `unsubscribed`). |
| `campaign_threads.current_step`, `last_sent_at` | YES | Sequence position. |
| `thread_messages.*` | YES | Reply history — never mutate. |

### 3.6 interactions — non-transactional event log

All columns read-only. Stage 1 A — `interactions` is the closest thing to an event log and is the only history for opens, clicks, replies, sends, bounces. Re-counting or backfilling it during stabilization breaks every downstream metric (open rate, bounce rate gate, engagement-tier classifier).

### 3.7 suppression_log + do_not_contact — bounce intelligence

All columns read-only. Migration 048 tiered suppression sources every send-time `is_suppressed` decision from here. Removing rows re-opens contacts that we already know are bad.

### 3.8 outreach_send_config — only the `send_enabled` flip allowed (Section 1.3)

Every other column (`daily_limit`, `batch_size`, `min_gap_minutes`, `sender_pool`, `reply_to`) must NOT be modified during the stabilization window. The cohort table `_stabilization_send_config_2026_05_14` from Action 1.3 is the canonical pre-change snapshot.

### 3.9 workspaces.settings — JSONB blob

Read-only. `daily_send_limit`, `sender_pool`, budget settings are read by multiple agents. A surgical edit risks invalidating the entire JSONB structure.

### 3.10 send_assertions — historical gate evidence

Read-only. Used by audit + post-send audit (`PostSendAuditAgent`) to confirm decisions.

### 3.11 workspace_audit_log — compliance trail

Read-only. The only audit evidence that distinguishes legitimate approvals from script writes.

---

## Section 4: Risky Code Paths to Temporarily Disable (Without Breaking Continuity)

Each item below is hot-configurable (env var, DB row, or file rename) unless explicitly marked otherwise.

### 4.1 Operator scripts `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py`
- **Path:** `/Users/avanish/prospectIQ/scripts/pending_draft_reconciliation.py`, `/Users/avanish/prospectIQ/scripts/rejected_draft_reassessment.py`
- **Risk:** Stage 2 G.1, G.2. Bypass every endpoint gate. Mutate `body`. Write `approved_by="avanish"` literal. Do not write `reviewed_at` (so under strict filter they sit; under fallback they go out). Last modified 2026-05-13.
- **Disable method:** rename the files.
  ```bash
  cd /Users/avanish/prospectIQ/scripts
  mv pending_draft_reconciliation.py pending_draft_reconciliation.py.disabled
  mv rejected_draft_reassessment.py  rejected_draft_reassessment.py.disabled
  ```
- **Functionality lost:** none — operator can still review drafts via the dashboard (`POST /api/approvals/{id}/approve`). The scripts were not on any scheduler or cron.
- **Deployment required:** No. These are local CLI tools.
- **Re-enable:** `mv pending_draft_reconciliation.py.disabled pending_draft_reconciliation.py` — but only after the scripts are rewritten to call the endpoint instead of writing directly (Stage 2 "Rearchitecture" #1).

### 4.2 `?force=true` approval bypass — approvals.py
- **Path:** `backend/app/api/routes/approvals.py:376` (`force: bool = False` param), lines 410, 438 (`if not force:` gates).
- **Risk:** Stage 1 H — bypasses both the quality gate (line 438) and the daily reviewer cap (line 410). No audit metadata distinguishes a force-approval beyond the standard log line.
- **Disable method:** there is no env-var gate; the cleanest interim is to instrument logging. Open a follow-up to require an explicit env var (`ALLOW_FORCE_APPROVAL=false` default). For now, add a log-based watcher on the workspace_audit_log:
  ```sql
  -- Run before every send window to detect force-approvals in the last 24h.
  SELECT id, user_email, action, resource_type, resource_id, metadata, created_at
    FROM workspace_audit_log
   WHERE created_at >= NOW() - INTERVAL '24 hours'
     AND metadata::text ILIKE '%force%true%'
   ORDER BY created_at DESC;
  ```
- **Functionality lost while watched:** none — `?force=true` still works. Only the visibility changes.
- **Deployment required:** No.
- **Re-enable cleanly:** N/A (watcher is non-invasive). Section 10.3 contains the minimal patch to gate `?force=true` behind an env var.

### 4.3 HTTP `OutreachAgent.generate_draft` — bypasses every gate
- **Path:** `backend/app/agents/outreach_agent.py::OutreachAgent.generate_draft` (mounted via `backend/app/api/routes/outreach_agent.py` at `POST /api/outreach/generate` and `POST /api/outreach/generate-batch`).
- **Risk:** Stage 1 H Governance Bypass — does not run ICP exclusion, suppression check, threading coordinator, channel coordinator, has_recent_activity, run_pre_send_assertions, integrity regex. Creates `pending` drafts that downstream approval treats as legitimate. Stage 1 D — second `OutreachAgent` class colliding with the scheduler agent.
- **Disable method:** comment out the two router includes by overriding at app-include time. Cleanest hot-disable without a code change is dashboard-side — confirm with frontend that no UI currently calls these endpoints. If safe, leave alone for the stabilization window. If a frontend caller exists, gate it server-side via:
  ```python
  # In outreach_agent.py route file, add before the route handler:
  import os
  if os.environ.get("ENABLE_HTTP_DRAFT_GEN", "false").lower() != "true":
      raise HTTPException(status_code=503, detail="HTTP draft generation temporarily disabled — use scheduler path.")
  ```
- **Functionality lost:** ability to generate drafts via the API. The scheduler path at `_run_draft_generation` (every 5 min) continues producing drafts.
- **Deployment required:** Yes if patch applied (Section 10.4).
- **Re-enable cleanly:** set `ENABLE_HTTP_DRAFT_GEN=true` in Railway env, or remove the gate after consolidating the two OutreachAgent classes.

### 4.4 `approve_manifest` — bypasses quality gate + cap
- **Path:** `backend/app/core/review_manifest.py::approve_manifest` (lines 270–352).
- **Risk:** Stage 1 H — skips validate_draft, attestation, dual-review, and per-reviewer cap. The hash-binding does not protect against missing-quality-gate, only against post-hash body edits.
- **Disable method:** search the codebase for callers; if no live HTTP wrapper exists (Stage 2 C confirmed grep found none), the function is dormant. Re-verify:
  ```bash
  cd /Users/avanish/prospectIQ
  grep -rn "approve_manifest" backend/ scripts/ --include='*.py' | grep -v 'def approve_manifest'
  ```
  If any caller is found, document who calls it and gate that caller (not the function) behind an env var.
- **Functionality lost:** none if dormant. If a caller exists, bulk hash-approval is disabled.
- **Deployment required:** depends on caller.
- **Re-enable cleanly:** remove the gate at the caller site.

### 4.5 Legacy Instantly webhook handler in `engagement.process_webhook_event`
- **Path:** `backend/app/agents/engagement.py::process_webhook_event` (line 1697). Called from `routes/webhooks.py:716` (unknown-event-type fallback) and `engagement.py:1680` (`_poll_instantly_events`).
- **Risk:** Stage 2 E.6 — writes `companies.status='bounced'` (line 1793) directly contradicting tiered-suppression intent of migration 048. Also writes `companies.status='engaged'` on reply (line 1808).
- **Disable method:** comment out the fallback call at `routes/webhooks.py:716`. Section 10.5 contains the minimal patch — wrap the call in `if False:` so the diff is one line and reversible.
- **Functionality lost:** unknown-event-type Instantly events return `{"status":"ignored","reason":"unknown event_type"}` instead of being processed by the legacy handler. Known events (reply, bounced, opened, clicked, unsubscribed) are handled by the modern `_handle_*` functions and are unaffected.
- **Deployment required:** Yes — backend redeploy.
- **Re-enable cleanly:** remove the `if False:` wrap, redeploy.

### 4.6 `POST /api/sequences/send-approved` with explicit `draft_ids` — bypasses strict reviewer filter
- **Path:** `backend/app/api/routes/sequences.py` (send-approved route) → `EngagementAgent._send_approved_drafts(draft_ids=...)` at engagement.py:451–457.
- **Risk:** Stage 1 H — comment says "explicit draft_ids selection IS the human attestation." A script knowing draft UUIDs can bypass attestation.
- **Disable method:** add an env gate in `sequences.py` before forwarding `draft_ids`:
  ```python
  if draft_ids and os.environ.get("ALLOW_EXPLICIT_DRAFT_IDS","false").lower() != "true":
      raise HTTPException(status_code=503, detail="Explicit draft_ids selection paused for stabilization.")
  ```
- **Functionality lost:** `draft_ids` mode of the endpoint. The "send all approved" mode still works.
- **Deployment required:** Yes (Section 10.6).
- **Re-enable:** set `ALLOW_EXPLICIT_DRAFT_IDS=true` in Railway env or remove the gate.

### 4.7 `POST /api/approvals/{id}/test-send` — bypasses approval status
- **Path:** `backend/app/api/routes/approvals.py::test_send_draft`.
- **Risk:** Stage 1 H — sends via live Resend to operator-supplied address. No `approval_status` check. Consumes sender reputation if abused.
- **Disable method:** for the stabilization window, do not invoke. No code change required if discipline holds. If extra safety wanted, add an env gate (Section 10.7).
- **Functionality lost:** operator preview emails.
- **Deployment required:** No if discipline; yes if patched.
- **Re-enable:** N/A or remove gate.

### 4.8 Two simultaneously mounted Instantly webhook routers
- **Path:** `backend/app/api/routes/webhooks.py::instantly_webhook` (prefix `/api/webhooks/instantly`) AND `backend/app/webhooks/instantly.py::instantly_webhook` (prefix `/webhooks/instantly`).
- **Risk:** Stage 2 E.1 — duplicate handlers with different verification, different DB writes. Whichever URL Instantly hits wins; the other is dead but reachable.
- **Disable method:** Section 9 below describes how to confirm which URL is active, then unmount the other. The unmount is one-line in `main.py`:
  ```python
  # Comment out exactly one of these in main.py (line 2261 or 2269):
  # app.include_router(webhooks.router)         # leave this if /api/webhooks/instantly is active
  # app.include_router(instantly_webhooks.router)  # leave this if /webhooks/instantly is active
  ```
  Do NOT do this until Section 9 confirms which URL Instantly is configured against.
- **Functionality lost:** none — only the unused handler is removed.
- **Deployment required:** Yes (backend redeploy).
- **Re-enable:** uncomment the line, redeploy.

### 4.9 Resend webhook with optional secret
- **Path:** `backend/app/api/routes/webhooks.py::resend_webhook` (line 783).
- **Risk:** Stage 2 E.4 — falls open if `RESEND_WEBHOOK_SECRET` env unset. Stabilization-critical because unsigned webhook can write to `outreach_drafts.resend_status`, `bounced_at`, `complained_at`, plus suppression rows.
- **Disable method:** Action 1.8 already covers this — ensure the env var is set in Railway. There is no code change needed.

### 4.10 `weekly_contact_backup` scheduler job
- **Path:** `main.py:2120–2125`, target `/Volumes/Digitillis/Data/prospectiq_backups/`.
- **Risk:** Stage 2 (unknowns) — Railway containers do not have this volume mount. The job silently fails every Saturday 5am. Not a stabilization risk per se, but the implication is that we have no automatic backup of `contacts` — only the manual snapshot from Section 2 protects us.
- **Disable method:** none required this window — already silently no-op.
- **Re-enable cleanly:** rewrite to write to Supabase Storage; out of scope for this window.

---

## Section 5: SQL Queries to Identify Unsafe Approved Drafts

Run these in order. Save each result to CSV. The action column at the bottom of each query says what to do with the rows.

### 5.a — Approved drafts with NULL `approved_by`
```sql
-- 5.a APPROVED but no reviewer recorded (script paths or endpoint fallback retry).
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email AS contact_email, co.name AS company_name,
       od.sequence_name, od.sequence_step,
       od.approval_status, od.approved_at, od.approved_by, od.reviewed_at,
       od.created_at, od.updated_at,
       LEFT(od.body, 200) AS body_preview
  FROM outreach_drafts od
  LEFT JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN companies co ON co.id = od.company_id
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (od.approved_by IS NULL OR TRIM(od.approved_by) = '')
 ORDER BY od.approved_at DESC NULLS LAST;
```
**Action on results:** quarantine via Section 6. These are the highest-risk drafts — either the endpoint fallback fired (column-write retry stripped reviewer) or `manage_thread.py`/`threads.py::approve_and_send`/legacy paths wrote them. Hold until re-approved through the endpoint.

### 5.b — Approved drafts with NULL `reviewed_at`
```sql
-- 5.b APPROVED but no review timestamp (covers approve_manifest, threads.py,
-- operator scripts that set approved_at but not reviewed_at).
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email AS contact_email, co.name AS company_name,
       od.approval_status, od.approved_at, od.approved_by, od.reviewed_at,
       od.attestation,
       od.created_at, od.updated_at
  FROM outreach_drafts od
  LEFT JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN companies co ON co.id = od.company_id
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND od.reviewed_at IS NULL
 ORDER BY od.approved_at DESC NULLS LAST;
```
**Action on results:** review manually. If the only issue is missing `reviewed_at` but `approved_by` looks legitimate (a real user UUID, not the literal `"avanish"`), backfill `reviewed_at = approved_at`. If `approved_by="avanish"` literal, quarantine and require endpoint re-approval. Backfill SQL:
```sql
-- Use only for rows whose approved_by IS a real user (manually verified), not "avanish".
UPDATE outreach_drafts
   SET reviewed_at = approved_at
 WHERE id = ANY(ARRAY['<draft_id_1>', '<draft_id_2>']::uuid[])
   AND approved_by IS NOT NULL
   AND reviewed_at IS NULL
   AND sent_at IS NULL;
```

### 5.c — Approved drafts with fabricated-claim patterns in body
```sql
-- 5.c APPROVED drafts whose body matches known fabrication patterns from the
-- integrity regex (outreach.py _INTEGRITY_RULES) and historical rejections.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email AS contact_email, co.name AS company_name,
       od.sequence_name, od.sequence_step, od.approval_status,
       od.approved_at, od.approved_by,
       LEFT(COALESCE(od.edited_body, od.body), 400) AS body_preview,
       CASE
         WHEN COALESCE(od.edited_body, od.body) ~* '\m(40\s*[-–—]?\s*65|40\s*to\s*65)\s*%' THEN '40-65% claim'
         WHEN COALESCE(od.edited_body, od.body) ~* '\mSMRP\M' THEN 'SMRP reference'
         WHEN COALESCE(od.edited_body, od.body) ~* '\mwe typically\M' THEN 'we typically'
         WHEN COALESCE(od.edited_body, od.body) ~* '\mwe.?ve worked with\M' THEN "we've worked with"
         WHEN COALESCE(od.edited_body, od.body) ~* '\mone plant found\M' THEN 'one plant found'
         WHEN COALESCE(od.edited_body, od.body) ~* '\mone .* (operation|facility|customer) found\M' THEN 'one X found'
         WHEN COALESCE(od.edited_body, od.body) ~* '\m\d{2,3}\s*%\s*(reduction|improvement|increase|decrease|savings|uptime|downtime)\M' THEN 'specific percentage stat'
         ELSE 'other'
       END AS pattern_matched
  FROM outreach_drafts od
  LEFT JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN companies co ON co.id = od.company_id
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (
        COALESCE(od.edited_body, od.body) ~* '\m(40\s*[-–—]?\s*65|40\s*to\s*65)\s*%'
     OR COALESCE(od.edited_body, od.body) ~* '\mSMRP\M'
     OR COALESCE(od.edited_body, od.body) ~* '\mwe typically\M'
     OR COALESCE(od.edited_body, od.body) ~* '\mwe.?ve worked with\M'
     OR COALESCE(od.edited_body, od.body) ~* '\mone plant found\M'
     OR COALESCE(od.edited_body, od.body) ~* '\mone .* (operation|facility|customer) found\M'
     OR COALESCE(od.edited_body, od.body) ~* '\m\d{2,3}\s*%\s*(reduction|improvement|increase|decrease|savings|uptime|downtime)\M'
   )
 ORDER BY od.approved_at DESC NULLS LAST;
```
**Action on results:** quarantine all matches via Section 6. These match the fabrication patterns the integrity regex catches; if they passed the gate, they were either approved with `?force=true` or via a path that skipped quality (Section 4.2, 4.4, scripts).

### 5.d — Approved drafts for suppressed contacts
```sql
-- 5.d APPROVED drafts for contacts that are currently suppressed.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email AS contact_email,
       c.suppression_reason, c.status AS contact_status,
       c.outreach_state, c.is_outreach_eligible,
       od.approval_status, od.approved_at, od.approved_by,
       sl.reason AS suppression_log_reason,
       sl.created_at AS suppressed_at
  FROM outreach_drafts od
  JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN LATERAL (
        SELECT reason, created_at
          FROM suppression_log
         WHERE contact_id = c.id
         ORDER BY created_at DESC
         LIMIT 1
       ) sl ON TRUE
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (
        c.suppression_reason IS NOT NULL
     OR c.status IN ('bounced','unsubscribed','do_not_contact')
     OR c.outreach_state IN ('bounced','unsubscribed','do_not_contact')
     OR c.is_outreach_eligible = FALSE
   )
 ORDER BY od.approved_at DESC NULLS LAST;
```
**Action on results:** quarantine all. The send path will skip them at `is_suppressed`, but they should not sit in the queue masquerading as ready.

### 5.e — Approved drafts for bounced/invalid email contacts
```sql
-- 5.e APPROVED drafts whose contact email is bounced/invalid/unverified.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email, c.email_status, c.email_name_verified,
       c.status AS contact_status,
       od.approval_status, od.approved_at, od.approved_by, od.sequence_step
  FROM outreach_drafts od
  JOIN contacts c ON c.id = od.contact_id
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND (
        c.email_status IS NULL
     OR c.email_status NOT IN ('verified','catch_all')
     OR c.email IS NULL
     OR c.email = ''
   )
 ORDER BY od.approved_at DESC NULLS LAST;
```
**Action on results:** quarantine. `assert_email_status_verified` would block these at send time anyway, but they should not occupy the queue.

### 5.f — Duplicate approved drafts (same contact+step)
```sql
-- 5.f Multiple non-rejected rows for the same (workspace, company, contact, step).
WITH dup AS (
  SELECT workspace_id, company_id, contact_id, sequence_step,
         COUNT(*) AS dup_count,
         ARRAY_AGG(id ORDER BY created_at) AS draft_ids,
         ARRAY_AGG(approval_status ORDER BY created_at) AS statuses,
         ARRAY_AGG(sequence_name ORDER BY created_at) AS seq_names,
         ARRAY_AGG(created_at ORDER BY created_at) AS created_ats
    FROM outreach_drafts
   WHERE approval_status NOT IN ('rejected')
     AND sent_at IS NULL
   GROUP BY workspace_id, company_id, contact_id, sequence_step
  HAVING COUNT(*) > 1
)
SELECT d.*, c.email, co.name AS company_name
  FROM dup d
  LEFT JOIN contacts c ON c.id = d.contact_id
  LEFT JOIN companies co ON co.id = d.company_id
 ORDER BY dup_count DESC, workspace_id;
```
**Action on results:** for each group, keep the most recent `approved`/`edited` draft, quarantine the others. Manual review — do not auto-resolve, because the older draft may contain content the operator preferred.

### 5.g — Approved step-2+ drafts where step-1 was never sent
```sql
-- 5.g APPROVED step-N drafts (N>=2) where no prior step was actually sent.
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email, co.name AS company_name,
       od.sequence_name, od.sequence_step, od.approval_status,
       od.approved_at, od.approved_by,
       (SELECT MAX(prev.sequence_step)
          FROM outreach_drafts prev
         WHERE prev.contact_id = od.contact_id
           AND prev.sequence_name = od.sequence_name
           AND prev.sent_at IS NOT NULL
       ) AS max_sent_step
  FROM outreach_drafts od
  LEFT JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN companies co ON co.id = od.company_id
 WHERE od.approval_status IN ('approved', 'edited', 'pending_second_review')
   AND od.sent_at IS NULL
   AND od.sequence_step >= 2
   AND NOT EXISTS (
       SELECT 1 FROM outreach_drafts prev
        WHERE prev.contact_id = od.contact_id
          AND prev.sequence_name = od.sequence_name
          AND prev.sequence_step = od.sequence_step - 1
          AND prev.sent_at IS NOT NULL
   )
 ORDER BY od.sequence_step DESC, od.approved_at DESC NULLS LAST;
```
**Action on results:** quarantine. `assert_prior_step_sent` would block these at send time; pre-empting prevents queue noise and reviewer confusion. Note: pending_draft_reconciliation.py treats CHECK_ERROR as OK (Stage 2 G.1) so this may catch script-approved drafts.

---

## Section 6: Safe Quarantine Strategy for Questionable Drafts

### 6.1 Approach
Constraints:
1. The `approval_status` enum (`001_initial_schema.sql:29` + `045_gtm_rebuild.sql:11`) supports: `pending`, `approved`, `rejected`, `edited`, `pending_second_review`. **There is no `on_hold` value.**
2. Adding an enum value requires a migration (`ALTER TYPE approval_status ADD VALUE 'on_hold'`). Per the operating constraints, no schema changes during stabilization unless strictly necessary.
3. Quarantine must be reversible in one UPDATE.
4. Quarantined rows must be visible distinctly in the approval queue UI.

**Recommended approach:** flip `approval_status` from `approved`/`edited`/`pending_second_review` back to `pending` and stamp the row with a quarantine marker in `rejection_reason` so the UI and queries can distinguish quarantined-pending from organically-pending rows. This:
- preserves the draft `body`, `edited_body`, `approved_at`, `approved_by`, `reviewed_at`, `attestation` exactly as they were (so re-approval is trivial)
- removes the draft from the send query (engagement.py:441 requires `approval_status='approved'`)
- restores it to the approval queue under the existing `pending` status which the dashboard already filters for
- is fully reversible with one UPDATE
- requires no migration

A second column-stamp into a JSONB or a marker prefix in `rejection_reason` makes the quarantine cohort searchable.

### 6.2 Quarantine a specific draft (reversible)
```sql
-- Stash the pre-quarantine state for clean rollback (single row per draft_id).
CREATE TABLE IF NOT EXISTS _stabilization_quarantine_2026_05_14 (
  draft_id          UUID PRIMARY KEY,
  prev_status       TEXT NOT NULL,
  prev_rejection    TEXT,
  prev_approved_at  TIMESTAMPTZ,
  prev_approved_by  TEXT,
  prev_reviewed_at  TIMESTAMPTZ,
  quarantined_at    TIMESTAMPTZ DEFAULT NOW(),
  quarantine_reason TEXT
);

-- Quarantine the draft. Replace :draft_id and :reason as needed.
WITH original AS (
  SELECT id, approval_status, rejection_reason, approved_at, approved_by, reviewed_at
    FROM outreach_drafts
   WHERE id = :draft_id
)
INSERT INTO _stabilization_quarantine_2026_05_14
       (draft_id, prev_status, prev_rejection, prev_approved_at, prev_approved_by, prev_reviewed_at, quarantine_reason)
SELECT id, approval_status, rejection_reason, approved_at, approved_by, reviewed_at, :reason
  FROM original
ON CONFLICT (draft_id) DO NOTHING;

UPDATE outreach_drafts
   SET approval_status = 'pending',
       rejection_reason = '[QUARANTINE 2026-05-14] ' || :reason
 WHERE id = :draft_id
   AND sent_at IS NULL
   AND approval_status IN ('approved', 'edited', 'pending_second_review');
```

### 6.3 Bulk quarantine — feed the IDs from Section 5
Replace the IN-list with the draft_ids surfaced by 5.a/5.c/5.d/5.e/5.f/5.g. Example for 5.c (fabricated claims):
```sql
WITH targets AS (
  SELECT od.id, od.approval_status, od.rejection_reason,
         od.approved_at, od.approved_by, od.reviewed_at
    FROM outreach_drafts od
   WHERE od.id = ANY(ARRAY[
     -- paste UUIDs from 5.c CSV here
     '00000000-0000-0000-0000-000000000000'::uuid
   ])
     AND od.sent_at IS NULL
     AND od.approval_status IN ('approved', 'edited', 'pending_second_review')
)
INSERT INTO _stabilization_quarantine_2026_05_14
       (draft_id, prev_status, prev_rejection, prev_approved_at, prev_approved_by,
        prev_reviewed_at, quarantine_reason)
SELECT id, approval_status, rejection_reason, approved_at, approved_by,
       reviewed_at, '5.c fabricated-claim pattern'
  FROM targets
ON CONFLICT (draft_id) DO NOTHING;

UPDATE outreach_drafts od
   SET approval_status = 'pending',
       rejection_reason = '[QUARANTINE 2026-05-14] 5.c fabricated-claim pattern'
  FROM targets t
 WHERE od.id = t.id;
```

### 6.4 Lift quarantine (rollback)
```sql
-- Lift quarantine for a single draft. The original status, rejection_reason, and
-- reviewer fields are restored exactly.
UPDATE outreach_drafts od
   SET approval_status = q.prev_status::approval_status,
       rejection_reason = q.prev_rejection,
       approved_at      = q.prev_approved_at,
       approved_by      = q.prev_approved_by,
       reviewed_at      = q.prev_reviewed_at
  FROM _stabilization_quarantine_2026_05_14 q
 WHERE od.id = q.draft_id
   AND od.id = :draft_id;

-- Optionally remove the snapshot row once lifted:
DELETE FROM _stabilization_quarantine_2026_05_14 WHERE draft_id = :draft_id;
```
Bulk lift (every quarantined row):
```sql
UPDATE outreach_drafts od
   SET approval_status = q.prev_status::approval_status,
       rejection_reason = q.prev_rejection,
       approved_at      = q.prev_approved_at,
       approved_by      = q.prev_approved_by,
       reviewed_at      = q.prev_reviewed_at
  FROM _stabilization_quarantine_2026_05_14 q
 WHERE od.id = q.draft_id
   AND od.sent_at IS NULL;
```

### 6.5 View all currently quarantined drafts
```sql
SELECT od.id AS draft_id, od.workspace_id, od.company_id, od.contact_id,
       c.email, co.name AS company_name,
       od.sequence_name, od.sequence_step,
       od.approval_status AS current_status,
       od.rejection_reason,
       q.prev_status, q.quarantine_reason, q.quarantined_at,
       q.prev_approved_by, q.prev_reviewed_at
  FROM _stabilization_quarantine_2026_05_14 q
  JOIN outreach_drafts od ON od.id = q.draft_id
  LEFT JOIN contacts c ON c.id = od.contact_id
  LEFT JOIN companies co ON co.id = od.company_id
 WHERE od.approval_status = 'pending'
   AND od.rejection_reason LIKE '[QUARANTINE 2026-05-14]%'
 ORDER BY q.quarantined_at DESC;
```

### 6.6 UI distinctness
The existing approval queue dashboard reads `approval_status='pending'` and displays `rejection_reason` when present. Quarantined drafts will show as **pending with a leading `[QUARANTINE 2026-05-14]` label in `rejection_reason`** — distinct on inspection from organic-pending drafts which have `rejection_reason IS NULL`. No UI code change required.

### 6.7 Sequence continuity
The quarantine path preserves `sequence_name` and `sequence_step` unchanged. The next-step generation logic in `_run_jit_pregenerate` looks for prior sent steps (engagement.py paths) — a quarantined step-N still being `pending` means a future step-N+1 will not be generated yet (it waits on step-N to be sent). When quarantine is lifted, the chain resumes naturally.

---

## Section 7: Safe Way to Pause Operator Scripts

### 7.1 Pause without deleting
Rename only — preserves git history and lets reversal be a 5-second `mv`:
```bash
cd /Users/avanish/prospectIQ/scripts
mv pending_draft_reconciliation.py  pending_draft_reconciliation.py.disabled
mv rejected_draft_reassessment.py   rejected_draft_reassessment.py.disabled
```
This is preferred over chmod-ing them non-executable because:
- the scripts have no shebang permission gating (they are invoked as `python scripts/<name>.py`)
- renaming makes any wrapper / shell history attempt fail with a clear error (`python: can't open file …`)
- git status will show the rename, so the reversal step is documented

### 7.2 Verify they have not been run since the last known timestamp
**File modification time check** — Stage 2 G.1 confirmed `May 13 18:01` as the last touch:
```bash
ls -la /Users/avanish/prospectIQ/scripts/pending_draft_reconciliation.py* \
       /Users/avanish/prospectIQ/scripts/rejected_draft_reassessment.py*
```
This only shows last *edit*, not last *run*. For run-history, check shell history:
```bash
grep -E "(pending_draft_reconciliation|rejected_draft_reassessment)" ~/.zsh_history ~/.bash_history 2>/dev/null | tail -20
```

### 7.3 Database-side run detection — last `approved_by="avanish"` write
```sql
-- Most recent write of approved_by="avanish" — strong signal a script ran.
-- Endpoint approvals write UUIDs to approved_by, not the literal string.
SELECT id, workspace_id, company_id, contact_id,
       approval_status, approved_at, approved_by, reviewed_at, sequence_step,
       rejection_reason
  FROM outreach_drafts
 WHERE approved_by = 'avanish'
 ORDER BY approved_at DESC NULLS LAST
 LIMIT 50;
```
The `MAX(approved_at)` for `approved_by='avanish'` is the last time either script wrote. Pair with workspace_audit_log to confirm the absence of a corresponding endpoint event:
```sql
-- For each "avanish" approval, was there a matching endpoint audit event in the
-- same ~60-second window? Lack of match = script (not endpoint).
SELECT od.id AS draft_id, od.approved_at, od.approved_by,
       wal.id AS audit_event_id, wal.action, wal.user_email, wal.created_at AS audit_at
  FROM outreach_drafts od
  LEFT JOIN workspace_audit_log wal
    ON wal.resource_type = 'outreach_draft'
   AND wal.resource_id = od.id::text
   AND wal.created_at BETWEEN od.approved_at - INTERVAL '90 seconds'
                          AND od.approved_at + INTERVAL '90 seconds'
 WHERE od.approved_by = 'avanish'
 ORDER BY od.approved_at DESC NULLS LAST;
```
Rows where `audit_event_id IS NULL` are conclusively script-written (no audit entry was emitted because the scripts do not call `log_audit_event_from_ctx`).

### 7.4 Last endpoint approval (for comparison)
```sql
SELECT MAX(approved_at) AS last_endpoint_approval, COUNT(*) AS endpoint_count
  FROM outreach_drafts
 WHERE approved_by IS NOT NULL
   AND approved_by <> 'avanish'
   AND approved_at >= NOW() - INTERVAL '30 days';
```

---

## Section 8: Confirming Railway Scheduler Singleton Behavior

### 8.1 Check replica count in the Railway dashboard
1. Open https://railway.app/ and select the ProspectIQ project.
2. Click the API service (the one whose Procfile is `web: ... uvicorn backend.app.api.main:app ...`).
3. Click **Settings** in the left rail.
4. Scroll to **Deploy** → **Replicas**. The value here is the live replica count.
5. The **safe maximum for the current codebase is `1`**. Stage 2 B.4 confirmed there is no distributed lock anywhere — `advisory_lock`, `pg_advisory`, `redis.*lock`, `FileLock`, `fcntl.flock` all return zero matches.
6. If the value is > 1: change to 1, click **Save**, and let Railway redeploy. Confirm only one container is running under **Deployments** → active deployment.

### 8.2 Verify scheduler has started exactly once (from logs)
1. In Railway, open the API service → **Deployments** → click the active deployment → **View logs**.
2. Filter logs for the string `APScheduler started`. This corresponds to `main.py:2205` log line.
3. **Expected:** exactly one occurrence per deployment lifecycle. The lifespan log emits when the process starts. If you see two `APScheduler started` lines within the same deployment window, it means either:
   - two replicas are running (verify against 8.1)
   - the lifespan ran twice (uvicorn worker recycle — would not normally happen at PORT=$PORT single-worker default)
4. Also search for `pipeline_advance every 4h` (part of the same multi-line log) as a corroborating signal.

### 8.3 What to do if multiple scheduler starts are observed
- If replicas > 1: scale to 1 (step 8.1).
- If replicas = 1 but two `APScheduler started` lines appear close in time: confirm uvicorn is running with a single worker. The Procfile does not pass `--workers`, so the default is 1. Verify by checking the active process command in Railway logs at startup.

### 8.4 Safe maximum replica count
**1 replica.** Until the distributed-lock work in Stage 2 "Rearchitecture #3" lands (postgres advisory lock around the entire send-path), more than one replica risks:
- duplicate `interactions` rows on every webhook poll
- duplicate Anthropic spend on every personalization refresh / qualification tick
- duplicate `outreach_drafts` rows on every `draft_generation` and `jit_pregenerate` tick
- duplicate emails only on send (the `sent_at` CAS protects this single path)

---

## Section 9: Confirming Active Instantly Webhook URL

### 9.1 Find the configured URL in Instantly
1. Sign in to https://app.instantly.ai/.
2. Open the workspace whose campaigns are integrated with ProspectIQ.
3. Click **Settings** → **Integrations** → **Webhooks** (Instantly's menu path; if labels have moved, search for "webhook" in workspace settings).
4. Record the full URL configured for the active event subscription. It will end either in `/api/webhooks/instantly` or `/webhooks/instantly`.

### 9.2 Map the URL to the active router
- `/api/webhooks/instantly` → **`backend/app/api/routes/webhooks.py::instantly_webhook`** (lines 648–744). Verification: query-param `?secret=`. Dispatches to `_handle_email_reply`, `_handle_email_bounced`, `_handle_email_unsubscribed`, `_handle_email_opened`, `_handle_email_clicked`, plus legacy fallback at line 716 to `EngagementAgent.process_webhook_event`.
- `/webhooks/instantly` → **`backend/app/webhooks/instantly.py::instantly_webhook`** (line 447). Verification: HMAC-SHA256 of body via `X-Instantly-Signature` header. Different handler suite (`_handle_email_sent`, `_handle_email_opened`, `_handle_email_clicked`, `_handle_email_replied`, `_handle_email_bounced`, `_handle_email_unsubscribed`).

### 9.3 Verify via Railway logs which path is actually receiving events
Open Railway logs and search for either path:
```
GET /api/webhooks/instantly
POST /api/webhooks/instantly
POST /webhooks/instantly
```
You should see POST entries on whichever path Instantly is configured to hit. If you see traffic on both, **both paths are wired up in Instantly** — choose the HMAC path (`/webhooks/instantly`) as canonical and remove the other from Instantly first.

### 9.4 What to do after confirming the active URL
Two changes — neither during the stabilization window itself, but the verification must happen first:
1. **Preferred long-term path:** `/webhooks/instantly` (HMAC-verified). If Instantly is currently configured to the query-param path, update Instantly to the HMAC path AFTER confirming `INSTANTLY_WEBHOOK_SECRET` is set in Railway (Action 1.8) and matches what Instantly will sign with.
2. **Unmount the inactive router** in `main.py`. If `/webhooks/instantly` is active, comment out line 2261 NO — wait, line 2261 mounts `webhooks.router` which contains many other webhooks (resend, unipile, trigify, meeting-transcript, apollo phone). You cannot unmount the whole router — instead remove only the `instantly_webhook` route handler inside `webhooks.py` by changing its decorator (Section 10.8). If `/api/webhooks/instantly` is active, comment out `app.include_router(instantly_webhooks.router)` at main.py:2269.

### 9.5 Logging verification after unmount
After the unmount, hit each URL with curl and confirm 404 from the unmounted one:
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://<railway-prod-host>/api/webhooks/instantly -X POST -d '{}'
curl -s -o /dev/null -w "%{http_code}\n" \
  https://<railway-prod-host>/webhooks/instantly -X POST -d '{}'
```
One should return `404`; the other a 4xx that's NOT 404 (likely 401 if secret is wrong, or 400 if event_type missing).

---

## Section 10: Minimal Safe Code Patches Allowed Before Next Send

Each patch is < 20 lines, reversible by a one-line revert, addresses an active risk, and does not touch the happy path.

### 10.1 Gate `?force=true` behind an env var (optional)
- **File:** `backend/app/api/routes/approvals.py`, around line 376–410.
- **Patch:** at the top of `approve_draft`, before the cap check, add:
  ```python
  if force and os.environ.get("ALLOW_FORCE_APPROVAL", "false").lower() != "true":
      raise HTTPException(
          status_code=403,
          detail={"error": "force_approval_disabled",
                  "message": "Set ALLOW_FORCE_APPROVAL=true to use ?force=true."},
      )
  ```
- **Why safe:** new env var defaults to false; existing default behavior is preserved by setting `ALLOW_FORCE_APPROVAL=true` in Railway. We can ship it in disabled mode first and flip the env when needed.
- **Protects against:** silent quality-gate + reviewer-cap bypass via `?force=true` (Stage 1 H).

### 10.2 Add audit logging for the column-write fallback in `approve_draft`
- **File:** `backend/app/api/routes/approvals.py`, line 533–540 (the `except Exception` retry).
- **Patch:** add an audit event so the fallback is visible in `workspace_audit_log`:
  ```python
  try:
      log_audit_event_from_ctx(
          request,
          action="approval_reviewer_column_fallback",
          resource_type="outreach_draft",
          resource_id=draft_id,
          metadata={"error": str(exc), "stripped_fields":
                    ["approved_by", "reviewed_at", "attestation"]},
      )
  except Exception:
      pass
  ```
- **Why safe:** purely additive logging.
- **Protects against:** Stage 2 A.2 — when the retry strips reviewer fields the row becomes invisibly unsigned. This makes it visible.

### 10.3 Gate the legacy `EngagementAgent.process_webhook_event` fallback
- **File:** `backend/app/api/routes/webhooks.py` around line 716 (the unknown-event-type fallback).
- **Patch:** change:
  ```python
  else:
      # Unknown event — pass through to EngagementAgent for legacy handling
      try:
          from backend.app.agents.engagement import EngagementAgent
          result = EngagementAgent.process_webhook_event(event_type, payload)
      except Exception:
          result = {"status": "ignored", "reason": f"unknown event_type: {event_type}"}
  ```
  to:
  ```python
  else:
      # Stabilization 2026-05-14: legacy handler disabled — was writing
      # companies.status='bounced' contradicting tiered suppression.
      logger.warning("instantly_webhook unknown event_type=%s ignored (legacy handler disabled)", event_type)
      result = {"status": "ignored", "reason": f"unknown event_type: {event_type}"}
  ```
- **Why safe:** the modern `_handle_*` functions handle every event Instantly actually sends. The fallback was reserved for unknown event types, and the only thing it did was write `companies.status='bounced'` and similar legacy mutations.
- **Protects against:** Stage 2 E.6 — tiered-suppression contradiction.

### 10.4 Add an env gate to the HTTP draft generation endpoints
- **File:** `backend/app/api/routes/outreach_agent.py` at the top of the `generate_one` / `generate_batch` handlers.
- **Patch:**
  ```python
  if os.environ.get("ENABLE_HTTP_DRAFT_GEN", "false").lower() != "true":
      raise HTTPException(
          status_code=503,
          detail={"error": "http_draft_gen_disabled",
                  "message": "Use scheduler path; HTTP draft gen paused for stabilization."},
      )
  ```
- **Why safe:** if no UI calls these endpoints (verify), this is a no-op. If a UI does, it gets a clean 503 the operator can spot.
- **Protects against:** Stage 1 H — HTTP path bypasses every gate.

### 10.5 Audit-log `?force=true` use (alternative to 10.1 if you do not want to gate)
- **File:** `backend/app/api/routes/approvals.py`, after line 410 (cap check) or inside the function early.
- **Patch:**
  ```python
  if force:
      try:
          log_audit_event_from_ctx(
              request,
              action="approval_force_used",
              resource_type="outreach_draft",
              resource_id=draft_id,
              metadata={"reviewer_id": reviewer_id},
          )
      except Exception:
          pass
  ```
- **Why safe:** additive logging only.
- **Protects against:** invisibility of `?force=true` use (Stage 1 H).

### 10.6 Gate explicit `draft_ids` send path
- **File:** `backend/app/api/routes/sequences.py` in the `send-approved` handler before forwarding `draft_ids` to `EngagementAgent.run`.
- **Patch:**
  ```python
  if draft_ids and os.environ.get("ALLOW_EXPLICIT_DRAFT_IDS", "false").lower() != "true":
      raise HTTPException(
          status_code=503,
          detail={"error": "explicit_draft_ids_disabled",
                  "message": "Explicit draft_ids selection paused for stabilization."},
      )
  ```
- **Why safe:** the "send all approved" mode of the endpoint is unaffected.
- **Protects against:** Stage 1 H — `draft_ids` mode skips the reviewer column strict filter (engagement.py:451–457).

### 10.7 Capture rollback failure to a DB row (in-memory observability)
- **File:** `backend/app/agents/engagement.py::_rollback_sent_at` (line 156–207).
- **Patch:** inside the `except Exception as rollback_exc:` block, after the `logger.critical`, append a best-effort DB write to a small audit table (or a JSON column on `interactions`):
  ```python
  try:
      db.client.table("interactions").insert({
          "company_id": company_id,
          "contact_id": contact_id,
          "type": "note",
          "channel": "system",
          "subject": "ORPHANED_DRAFT_ROLLBACK_FAILURE",
          "metadata": {
              "draft_id": draft_id,
              "assertion": assertion,
              "rollback_error": str(rollback_exc),
              "original_error": str(original_exc),
          },
      }).execute()
  except Exception:
      pass
  ```
- **Why safe:** purely additive, wrapped in try/except. Does not change rollback control flow.
- **Protects against:** Stage 1 H — orphaned-draft invisibility. Today only a log line fires; after this patch an `interactions` row with type `note` carries the same payload, queryable forever.

### 10.8 (Optional) Disable the duplicate Instantly webhook route after Section 9 confirms which is active
- **File:** `backend/app/api/main.py` line 2269 OR `backend/app/api/routes/webhooks.py` line 648.
- **Patch (if HMAC `/webhooks/instantly` is active):** in `webhooks.py` change the `@router.post("/instantly")` decorator (the one inside the routes file) to `@router.post("/instantly-DISABLED-2026-05-14")` so the function is unreachable but still importable. Reversible by changing the path back.
- **Why safe:** only one route disappears. The function stays in the file.
- **Protects against:** Stage 2 E.1 — dual-mount confusion.

Note: do NOT apply both 10.1 and 10.5 — 10.1 supersedes 10.5.

---

## Section 11: Changes That Must Be Deferred to Rearchitecture

The Stage 2 "Risks Requiring Rearchitecture" list (Stage 2 final summary) contains 11 items. The following cannot be safely patched before the next send. For each, the residual risk during deferral plus a monitoring/manual partial mitigation.

### 11.1 Consolidating the eight writers to `approval_status='approved'`
- **Why not patchable now:** consolidation requires either (a) changing every caller to invoke a single Python function with the full gate suite, or (b) adding a DB-level CHECK + trigger that enforces invariants. (a) touches 8 files; (b) requires a migration plus careful data migration of existing NULL `approved_by`/`reviewed_at` rows. Either is medium+ risk before the send window.
- **Residual risk:** scripts can still bypass; `?force=true` can still bypass (unless 10.1 applied); `approve_manifest` can still skip quality.
- **Mitigation interim:**
  - Section 5 queries catch the resulting bad drafts before send
  - Section 10.5 audit-logs `?force=true` use
  - Section 4.1 disables the scripts
  - Section 4.4 confirms `approve_manifest` has no live caller

### 11.2 Making `outreach_drafts.body` immutable after send
- **Why not patchable now:** requires adding an UPDATE-blocking trigger that distinguishes legitimate UPDATEs (sent_at, status transitions, resend_message_id) from illegitimate ones (body changes when sent_at IS NOT NULL). Drafting that trigger correctly + testing it is medium-risk; mis-firing would block legitimate post-send writes.
- **Residual risk:** an attacker or a future operator script could rewrite a sent draft's body, breaking the audit trail.
- **Mitigation interim:** the Section 2.1 snapshot serves as the immutable ground truth for every body in flight. Re-snapshot before any future operator script run.

### 11.3 Adding postgres advisory lock around the send path
- **Why not patchable now:** requires refactoring `_send_approved_drafts` to acquire a lock on `(workspace_id, contact_id)` before assertions, hold it through Resend dispatch, release after post-send writes. Touches the hottest path in the system; should not be shipped under deadline pressure.
- **Residual risk:** if more than one replica is ever accidentally enabled, the CAS on `sent_at` is the only guard. Other ticks (process_due, jit_pregenerate, draft_generation) have no guard at all.
- **Mitigation interim:** Section 8 verifies and enforces 1-replica policy. Operator discipline must hold.

### 11.4 Wrapping `sent_at` + assertions + Resend call in a single transaction
- **Why not patchable now:** Resend is an external HTTP call; you cannot hold a DB transaction across it without risking lock starvation. The correct fix is the Outbox pattern: claim → write outbox entry → release → outbox consumer fires Resend → on confirm, mark draft sent. That is a several-day rebuild.
- **Residual risk:** if `_rollback_sent_at` fails, the draft is orphaned forever. The `interactions` row from patch 10.7 makes this discoverable, not preventable.
- **Mitigation interim:** patch 10.7 logs every orphan to `interactions`. Operator runs the following query daily during the stabilization window:
  ```sql
  SELECT * FROM interactions
   WHERE type = 'note' AND subject = 'ORPHANED_DRAFT_ROLLBACK_FAILURE'
     AND created_at >= NOW() - INTERVAL '24 hours'
   ORDER BY created_at DESC;
  ```

### 11.5 Transactional boundary around post-send writes
- **Why not patchable now:** same as 11.4 — requires Outbox or saga rearchitecture.
- **Residual risk:** silent failure of `engagement_sequences` insert means contacts drop from sequence; silent failure of `campaign_threads` insert breaks reply correlation.
- **Mitigation interim:** run Stage 2 F.6 and F.7 queries weekly to detect drift:
  ```sql
  -- F.6 sent drafts with no engagement_sequences row
  -- F.7 sent drafts with no email_sent interaction
  ```

### 11.6 Deleting/consolidating the duplicate `OutreachAgent` classes
- **Why not patchable now:** the HTTP path is referenced from a frontend route; deleting the class breaks the dashboard's draft-generation button (if used). Confirm absence of caller first.
- **Residual risk:** drafts created via the HTTP path bypass every gate the scheduler agent enforces.
- **Mitigation interim:** patch 10.4 gates the HTTP path behind `ENABLE_HTTP_DRAFT_GEN`.

### 11.7 Consolidating the four-source send-cap mismatch
- **Why not patchable now:** removing or merging `pace_limiter.CAMPAIGN_DEFAULTS`, `workspaces.settings.daily_send_limit`, `config/limits.yaml::outreach.daily_send_limit` requires either a deprecation cycle or a coordinated rip. Touching this before a send is high-risk.
- **Residual risk:** edits to one cap may not propagate if another is consulted.
- **Mitigation interim:** Action 1.6 documents the authoritative value per workspace. Stage 2 D.7 confirms `outreach_send_config.daily_limit` is the only one the send path reads. Operator inspects this single value before the send window.

### 11.8 Moving APScheduler out of the FastAPI process to a worker container
- **Why not patchable now:** requires either Celery+Redis or a separate Procfile `worker:` process with explicit gating. Procfile change forces full Railway re-config and worker container spin-up. Multi-day project.
- **Residual risk:** multi-replica scenarios remain unsafe.
- **Mitigation interim:** Section 8 holds replicas at 1.

### 11.9 Webhook idempotency via `webhook_events` table
- **Why not patchable now:** requires a new table + INSERT-IF-NOT-EXISTS pattern at every webhook handler entry. New migration + handler edits in 4+ files.
- **Residual risk:** Resend/Instantly retries double-count opens, clicks; duplicate `suppression_log` and `do_not_contact` rows on replayed bounces.
- **Mitigation interim:**
  - confirm webhook secrets are set (Action 1.8) so unauthenticated replays cannot enter at all
  - operator runs the following daily during stabilization:
    ```sql
    -- duplicate inbound thread_messages
    SELECT thread_id, direction, subject, received_at, COUNT(*) AS dups
      FROM thread_messages
     WHERE direction = 'inbound'
       AND received_at >= NOW() - INTERVAL '24 hours'
     GROUP BY thread_id, direction, subject, received_at
    HAVING COUNT(*) > 1;
    ```

### 11.10 Removing one of the two Instantly webhook handlers
- **Why not patchable now:** requires confirmation from Section 9 first (which URL Instantly is actually configured against). Then the patch 10.8 is small. So this is *not* deferred-to-rearchitecture — it is deferred-to-after-section-9.
- **Residual risk while pending:** dual-write of `companies.status` and `contacts.status` on the same physical event if Instantly is configured to BOTH URLs (rare but possible).
- **Mitigation interim:** patch 10.3 disables the legacy fallback in the `routes/webhooks.py` path, which is the worst of the two.

### 11.11 Migrating `approved_by` from TEXT to UUID FK
- **Why not patchable now:** existing rows contain the literal string `"avanish"` (Stage 2 G.1). Type-changing requires either (a) backfilling those rows to a real user UUID first, or (b) NULL-ing them and losing attribution. Both are data-mutating decisions that should not be made under deadline.
- **Residual risk:** audit queries grouping by `approved_by` will treat `"avanish"` as a peer reviewer of the real UUIDs.
- **Mitigation interim:** every audit query in this plan filters `approved_by = 'avanish'` separately (Section 7.3) so the script writes are surfaced distinctly.

---

## Section 12: Rollback Plan

For every Section 1 action and every Section 10 patch.

### 12.1 — Rollback for Action 1.1 (snapshots)
- **Failure condition:** snapshot files truncated, corrupted, or never written.
- **Rollback step:** re-run the queries in Section 2. SELECTs are idempotent.
- **Verification:** `wc -l` the CSV files vs the row counts from query 2.14.
- **Manual cleanup needed:** no.

### 12.2 — Rollback for Action 1.2 (`SEND_ENABLED=false`)
- **Failure condition:** sends need to resume immediately, or the env var change broke deployment.
- **Rollback step:** in Railway, set `SEND_ENABLED=true` (or remove the var) and redeploy.
- **Verification:** hit `GET /api/admin/send-config` — `send_enabled` should return true. Wait for next scheduler tick and confirm logs show the send loop entering.
- **Manual cleanup needed:** no. The scheduler picks up the env on next tick.

### 12.3 — Rollback for Action 1.3 (`outreach_send_config.send_enabled = false`)
- **Failure condition:** workspaces unintentionally globally paused; some workspaces need to resume while others stay paused.
- **Rollback step:**
  ```sql
  UPDATE outreach_send_config oc
     SET send_enabled = s.send_enabled
    FROM _stabilization_send_config_2026_05_14 s
   WHERE oc.workspace_id = s.workspace_id;
  ```
- **Verification:**
  ```sql
  SELECT oc.workspace_id, oc.send_enabled, s.send_enabled AS pre_change
    FROM outreach_send_config oc
    JOIN _stabilization_send_config_2026_05_14 s ON s.workspace_id = oc.workspace_id;
  ```
  Every row should show `oc.send_enabled = s.send_enabled`.
- **Manual cleanup needed:** no. Drop `_stabilization_send_config_2026_05_14` only after the window closes and you are sure no further rollbacks are needed.

### 12.4 — Rollback for Action 1.4 (replica scale-down to 1)
- **Failure condition:** other services on the same Railway project depended on a higher replica count (unlikely for a Procfile-only setup).
- **Rollback step:** Railway dashboard → Service Settings → Replicas → set back to prior value → save.
- **Verification:** check Deployments view shows the new replica count.
- **Manual cleanup needed:** check `interactions` for duplicate rows in the window after re-scale; if duplicates appear, the lock-contention items in Section 11 are immediately required.

### 12.5 — Rollback for Action 1.5 (column verification)
- **Failure condition:** none — read-only.
- **Rollback step:** N/A.

### 12.6 — Rollback for Action 1.6 (cap verification)
- **Failure condition:** none — read-only.
- **Rollback step:** N/A.

### 12.7 — Rollback for Action 1.7 (rename operator scripts)
- **Failure condition:** legitimate need to run the scripts before they are rewritten (should not happen, but if so).
- **Rollback step:**
  ```bash
  cd /Users/avanish/prospectIQ/scripts
  mv pending_draft_reconciliation.py.disabled pending_draft_reconciliation.py
  mv rejected_draft_reassessment.py.disabled  rejected_draft_reassessment.py
  ```
- **Verification:** `ls scripts/pending_draft_reconciliation.py scripts/rejected_draft_reassessment.py` returns both with normal extension.
- **Manual cleanup needed:** if the scripts are re-enabled and re-run, every Section 5 query must be re-run afterward to recapture the new approval cohort.

### 12.8 — Rollback for Action 1.8 (webhook secrets set)
- **Failure condition:** new secret mismatches what Resend/Instantly are signing with.
- **Rollback step:** Railway dashboard → unset `RESEND_WEBHOOK_SECRET` / `INSTANTLY_WEBHOOK_SECRET`, OR reset to the prior value if known. The endpoint falls back to fail-open behavior.
- **Verification:** Resend dashboard webhook delivery log should show 2xx responses; if it shows 401s, the secret in Resend's config does not match Railway.
- **Manual cleanup needed:** if missed events while the secret mismatched, manually replay them from Resend's dashboard.

### 12.9 — Rollback for Section 6 quarantine
- **Failure condition:** a draft was quarantined that should not have been.
- **Rollback step:** Section 6.4 (single) or bulk lift query.
- **Verification:** Section 6.5 query returns no rows (or only intended rows).
- **Manual cleanup needed:** confirm `engagement_sequences.next_action_at` for the lifted contact still makes sense; if a step-2 was quarantined and step-1 was never sent (5.g), lifting won't fix the gap — manual decision required.

### 12.10 — Rollback for Section 10 patches

#### 10.1 / 10.5 (`?force=true` gate or audit log)
- **Failure condition:** legitimate force-approval blocked; or audit emission caused approval write failures.
- **Rollback step:** git revert the commit. Or set `ALLOW_FORCE_APPROVAL=true` (for 10.1).
- **Verification:** re-run an approve request with `?force=true`; should succeed and log event.

#### 10.2 (column-fallback audit log)
- **Failure condition:** audit emit fails silently — wrapped in try/except, no impact.
- **Rollback step:** git revert. None needed otherwise.
- **Verification:** N/A.

#### 10.3 (legacy fallback in webhooks.py)
- **Failure condition:** an unknown event_type Instantly sends that we needed `process_webhook_event` for.
- **Rollback step:** git revert. Restart the API service.
- **Verification:** verify Instantly webhook delivery dashboard for 2xx responses on the event types in question.
- **Manual cleanup needed:** any rows that the legacy handler would have updated (companies.status, contacts.status) need manual reconciliation from Section 2 snapshots.

#### 10.4 (HTTP draft gen gate)
- **Failure condition:** UI needed the endpoint.
- **Rollback step:** set `ENABLE_HTTP_DRAFT_GEN=true` in Railway env, or git revert.
- **Verification:** UI button works; new pending draft appears.

#### 10.6 (explicit draft_ids gate)
- **Failure condition:** legitimate need to send a specific list of drafts.
- **Rollback step:** set `ALLOW_EXPLICIT_DRAFT_IDS=true` in Railway env, or git revert.
- **Verification:** `POST /api/sequences/send-approved` with `draft_ids` returns 200 and sends.

#### 10.7 (rollback-failure audit row)
- **Failure condition:** the `interactions` insert raises and was not properly wrapped. (Already wrapped — no rollback expected.)
- **Rollback step:** git revert.
- **Verification:** no `interactions` row spam appears in normal operation.

#### 10.8 (unmount duplicate Instantly route)
- **Failure condition:** Instantly was actually configured to BOTH URLs and one path's events are now dropped.
- **Rollback step:** revert the decorator change in `webhooks.py` (10.8 case) or uncomment the `app.include_router(instantly_webhooks.router)` line.
- **Verification:** Instantly's webhook delivery log shows 2xx; Railway logs show POST hits on the restored path.
- **Manual cleanup needed:** none if reverted promptly. If Instantly retried the dropped events while the route was down (Instantly's retry policy), confirm reconciliation.

### 12.11 — Rollback for the entire stabilization window
If at any point the operator decides to abort and return to the pre-stabilization state:
1. Lift every quarantine (Section 6.4 bulk).
2. Restore every `outreach_send_config.send_enabled` (Action 1.3 rollback).
3. Unset / reset `SEND_ENABLED` (Action 1.2 rollback).
4. Rename operator scripts back (Action 1.7 rollback).
5. Revert every Section 10 patch via `git revert`.
6. Drop the `_stabilization_*` snapshot tables ONLY after confirming the rollback held for at least 24 hours.
7. Re-run all Section 5 queries afterward — if anything was approved in the rollback window via the now-re-enabled scripts, Section 5.a/5.b/5.c will surface it.

### 12.12 — Soft-defer of the next send (one slot)
If at the next 8:00 AM Chicago slot any of the following are unresolved, defer the send by exactly one 30-minute slot (8:30, 9:00, …, 11:00 cap):
- Section 5.a, 5.c, 5.d, 5.e returned >0 rows that have not been quarantined
- Section 8 has not confirmed replica count = 1
- Section 9 has not identified the active Instantly URL
- `RESEND_WEBHOOK_SECRET` is still unset

To defer one slot:
- Leave `SEND_ENABLED=false` and `outreach_send_config.send_enabled=false` until the next slot
- The 30-minute cron interval will fire again automatically; just keep the flags off
- When ready, flip both back (Actions 1.2/1.3 rollback) at least 5 minutes before the next slot so the scheduler tick picks up the env

Hard stop: if 11:00 AM Chicago passes without all four cleared, skip Today's send entirely; the cron has no more slots today and will resume tomorrow morning.





---
# Stage 4: Target Architecture and Migration Design
- Date: 2026-05-14
- Status: DESIGN — not yet implemented
- Owner: Avanish Mehrotra

---

## SECTION A — Architectural Diagnosis

### A.1 The fundamental architectural anti-pattern

**ProspectIQ is a multi-writer, code-enforced state machine layered on a mutable CRUD schema.** Every important lifecycle invariant (approved-implies-attested, sent-implies-approved, suppression-blocks-send, immutability-after-send) is enforced in Python at one call site while many other call sites mutate the same row outside that enforcement; the schema accepts every transition the database engine permits.

The two structural consequences that produce nearly every Stage 1–3 finding:

1. **The lifecycle is implicit in column values rather than explicit in a state machine.** `approval_status='approved'` plus `sent_at IS NOT NULL` plus `resend_message_id IS NOT NULL` plus a row in `engagement_sequences` plus an `email_sent` row in `interactions` collectively mean "sent." Any subset can be true while the others are false; the system has no concept of "the row is invalid because it occupies an impossible state."

2. **There is no transactional boundary around any business action.** Approval writes one row across two retries. Send claims `sent_at`, then runs assertions, then calls Resend, then writes 6+ side-effect rows, each in its own HTTP request, each wrapped in `try/except` marked "non-fatal." Webhooks fan out further writes that the send path knows nothing about. The "atomic claim" on `sent_at` is the only true atomic operation in the entire outreach pipeline.

Every Stage 1/2/3 risk reduces to one of these two roots: a write that should have been impossible was permitted by the schema, or a sequence that should have been all-or-nothing was partial.

### A.2 Salvageable as-is or with minor hardening

| Component | State | Hardening required |
|---|---|---|
| `outbound_eligible_contacts` SQL gate (migration 033) + `trg_contact_eligibility` trigger | Sound — declarative SQL view of eligibility | Add monitoring that the trigger is attached on every deploy; replace the 15-minute lag fallback (`pipeline_qc.py refresh_outbound_eligible`) with a same-tick consistency check |
| `send_assertions` table + `assertion_context` column (migrations 034, 047) | Sound — every assertion result is captured | Add a CHECK that `assertion_context IN ('draft_gen','send_path','approval_gate')`; rely on it as the authoritative gate evidence going forward |
| `suppression_log` + tiered suppression (migration 048) | Modeled correctly at contact scope with escalation to company | Remove every legacy writer that touches `companies.status='bounced'` directly (engagement.py:1793 in `process_webhook_event`); make `suppression_log` the sole bounce writer |
| `outreach_send_config` table (migration 029) | Sound — per-workspace, DB-backed, hot-editable | Designate as **the sole** send-cap source; deprecate `workspaces.settings.daily_send_limit`, `limits.yaml::outreach.daily_send_limit`, `pace_limiter.CAMPAIGN_DEFAULTS` |
| `interactions` table | Useful as a non-transactional event log of opens/clicks/replies | Keep, but stop relying on it for state; promote it from sole event store to one of several read-side projections |
| `campaign_threads` + `thread_messages` | Sound — reply correlation works | Add UNIQUE on `(provider_message_id)` on `thread_messages` to dedupe replayed webhooks |
| `contacts.outreach_state` + `outreach_state_log` (migration 010) | Useful state machine column for contacts | Keep the column; make `outreach_state_log` the ONLY writer through a single update procedure; add CHECK on the state value |
| Apollo/ZeroBounce/Anthropic enrichment data on `contacts` and `companies` | Sound — irreplaceable, cost real money to rebuild | Read-only protection: add UPDATE triggers blocking enrichment-column mutations except by a designated enrichment service identity |
| `outreach_guidelines.yaml`, `offer_context.yaml`, `icp.yaml`, `signal_weights.yaml`, `scoring.yaml`, `manufacturing_ontology.yaml` | Sound as content config | Keep as-is; move to a `policy_snapshots` mechanism (Section D.4) so each approval/send records WHICH version was in force |
| Migration 003 DELETE-protect trigger on sent drafts | Sound directionally | Extend to block UPDATE of `(body, subject, sequence_name, sequence_step, sent_at)` once `sent_at IS NOT NULL` |
| Resend integration (the SDK call itself + `idempotency_key=draft.id`) | Sound at the call site | Wrap inside the outbox consumer (Section F.2); the Resend dispatch logic does not need to change |
| `review_manifests` table (migration 049) hash-binding concept | Sound concept | Salvage as the basis for the approval workflow's body-version pin (Section D.6); fix the bypass by routing manifest approval through the new `ApprovalService` |

### A.3 Deprecate and replace

| Component | Why deprecate | Replacement |
|---|---|---|
| `backend/app/agents/outreach_agent.py` (the second `OutreachAgent`) | Bypasses every scheduler-side gate; duplicates `agents/outreach.py` with a different model router and sequence namespace (Stage 1 D, Stage 2 C) | Delete the file; route `POST /api/outreach/generate*` to the same generation core used by the scheduler |
| `scripts/pending_draft_reconciliation.py`, `scripts/rejected_draft_reassessment.py` | Service-role key writes, no audit, mutates `body`, writes `approved_by="avanish"` literal (Stage 2 G.1, G.2) | Rewrite as thin CLI clients that call `POST /api/approvals/{id}/approve` with an operator JWT |
| `backend/app/webhooks/instantly.py` OR `backend/app/api/routes/webhooks.py::instantly_webhook` (whichever Instantly is NOT configured against) | Dual-mount with different verification, different DB writes (Stage 2 E.1) | Pick HMAC path as canonical; unmount the other |
| `EngagementAgent.process_webhook_event` static method (engagement.py:1697) | Writes `companies.status='bounced'` contradicting tiered suppression (Stage 2 E.6) | Delete; route inbound events through the new webhook idempotency layer + handler suite |
| `pace_limiter.CAMPAIGN_DEFAULTS` and `PaceLimiter` class | Dead code in the send path (Stage 2 D.5); a third "daily cap" source no one reads | Delete |
| `workspaces.settings.daily_send_limit` JSONB key | Already deliberately skipped by the send path (main.py:189–194) | Drop the key; remove `workspace_daily_sends_ok` |
| `limits.yaml::outreach.daily_send_limit` | Duplicate of `outreach_send_config.daily_limit` per workspace | Remove from YAML; YAML keeps reviewer cap only |
| In-process APScheduler in the FastAPI process | No singleton check, no distributed lock, 22 of 23 jobs unsafe under multi-replica (Stage 2 B.2, B.3) | Move to a separate Procfile `worker:` process with concurrency=1 and an explicit start-once advisory lock (Section F.1) |
| `weekly_contact_backup` writing to `/Volumes/Digitillis/Data/...` | Path doesn't exist on Railway containers; silent no-op (Stage 2 risk list) | Replace with Supabase Storage or S3 export; or delete |
| Two-class `OutreachAgent` architecture | Duplicated draft-generation logic | Single `DraftGenerator` module callable from scheduler and HTTP, with the HTTP path enforcing every scheduler gate |
| `outreach_outcomes` written at draft-generation time (outreach.py lines 1031–1043) | Conflates "draft created" with "send happened" (Stage 1 H data integrity risk) | Write `outreach_outcomes` only on confirmed send; the draft creation event lives in `workflow_events` (Section D.2) |
| `?force=true` parameter on the approval endpoint | Silent quality + cap bypass (Stage 1 H) | Replace with a separate `POST /api/approvals/{id}/override` endpoint that requires an explicit reason, dual approver, and writes a distinct event type to the audit trail |

### A.4 Fundamentally unfixable without lifecycle redesign

These cannot be patched in place; every patch moves the risk somewhere else.

1. **`sent_at` as both the "claim" and the "delivered" indicator.** Stage 1 H concurrency risk + Stage 3 11.3/11.4. As long as `sent_at` carries both meanings, every assertion failure between claim and Resend dispatch causes a window in which the row reads "sent" without an email having gone out, and every rollback failure orphans the draft forever. No CHECK constraint or trigger can repair this because the semantics are overloaded on one column. Fix: split into a separate `send_attempts` table where `claimed_at`, `dispatched_at`, `delivered_at` are different columns on different rows (Section D.1, D.9).

2. **Eight writers to `approval_status='approved'`.** Stage 2 C + Stage 3 11.1. A CHECK constraint can force `approved_by IS NOT NULL` but cannot validate that the write went through the full quality gate or that the reviewer was authorized. Every per-caller patch leaves the next caller free to bypass. Fix: schema-level "approval requires an `approval_attestations` row whose `approval_id = outreach_drafts.id`" (Section D.3 + E.2) — the draft cannot reach approved without the attestation row existing, and the attestation row can only be created via a single `ApprovalService` procedure.

3. **Mutable `outreach_drafts.body` and `subject`.** Stage 3 11.2. Migration 003 protects DELETE but not UPDATE. An UPDATE-blocking trigger that distinguishes "legitimate body edit pre-approval" from "illegitimate post-send rewrite" requires the body to live somewhere distinct from the draft row. Fix: `draft_content_versions` immutable history (Section D.6); `outreach_drafts.body` becomes a pointer to the current version.

4. **In-process scheduler tied to API process.** Stage 2 B.2 + Stage 3 11.8. Any singleton check inside the FastAPI process can be defeated by deploying more replicas. The scheduler must live in a different process whose lifecycle is independent of the API. Fix: separate `worker:` Procfile process; advisory-lock start-once guard (Section F.1).

5. **Webhook handlers without idempotency.** Stage 2 E.8 + Stage 3 11.9. Adding `if event_id in seen: return 200` to every handler creates a TOCTOU race; the seen-set has to be in the DB and the check has to be atomic with a write that creates the seen row. Fix: `webhook_event_log` with INSERT-IF-NOT-EXISTS (Section D.5 + G.1) as the first statement of every handler.

6. **Non-transactional post-send fan-out.** Stage 1 H silent failure risk + Stage 3 11.5. Six post-send writes each in its own HTTP request, each `try/except`. No amount of error handling at each site repairs the missing transaction. Fix: outbound_queue/outbox pattern (Section D.9 + F.2) — the post-send writes become events the worker projects to side tables.

7. **Implicit step-state derived from `engagement_sequences.current_step` + the existence of a `sent_at`-set draft for the prior step.** Stage 1 D + Stage 2 F.6. Whenever the side-effect write to `engagement_sequences` after a send fails silently, the contact drops from the sequence forever. The state is reconstructable only by joining four tables. Fix: explicit `sequence_step_state` row per `(contact_id, step_number)` with its own state machine (Section D.8).

### A.5 Strongest foundations for the next architecture

| Table or workflow | Why it is a strong foundation |
|---|---|
| `outreach_drafts` (the primary record) | Stable, referenced by every other table; survives the redesign as the canonical draft record (with `body`/`subject` becoming pointers to versions) |
| `outreach_send_config` per-workspace | Already the de facto single source for daily caps; promote to policy-registry-style versioning |
| `suppression_log` + tiered suppression (migration 048) | Modeled correctly; needed unchanged |
| `contacts.outreach_state` + `outreach_state_log` | Right concept — a state column with an audit log; pattern is reused for every state machine in Section C |
| `send_assertions` with `assertion_context` | Per-assertion evidence row is the right shape; will be referenced by `send_attempts` as the gate-evidence FK target |
| `campaign_threads` + `thread_messages` | Reply correlation works once webhooks become idempotent |
| `outbound_eligible_contacts` materialized gate | Declarative SQL eligibility is correct; will be paired with the new state machines as a generated read-side view |
| `review_manifests` (migration 049) hash-binding | The body-hash binding concept is correct; will become the foundation of `approval_attestations` (Section D.3) which pins not only the body but the full policy snapshot |
| `workspace_audit_log` | Already exists; will absorb the new `workflow_events` semantics (Section D.2) — every state transition lands here too |

The redesign keeps every operational asset (Apollo enrichment, research intelligence, suppression history, reply threads, sequence anchors) and replaces the implicit-state, multi-writer, non-transactional control plane.

---

## SECTION B — Target System Principles

Each principle has a one-sentence statement, a rationale tied to Stage 1/2/3, a current-violation citation, and an enforcement mechanism. The rule of thumb: every principle is enforced at the schema where possible, the service layer where not, and the API layer only as the last line of defense.

### B.1 Single Writer per State

- **Statement:** Each lifecycle state column has exactly one Python module authorized to transition it, and the database physically rejects writes from anywhere else.
- **Rationale:** Stage 2 C found eight writers to `approval_status='approved'`, each with a different governance subset. Stage 1 D found two `OutreachAgent` classes writing to `outreach_drafts`. Stage 1 H found three writers to `contacts.status='bounced'`. Multi-writer drift is the root of every governance bypass.
- **Current violation:** `backend/app/api/routes/approvals.py::approve_draft`, `backend/app/core/review_manifest.py::approve_manifest`, `scripts/pending_draft_reconciliation.py`, `scripts/rejected_draft_reassessment.py`, `backend/app/api/routes/threads.py::approve_and_send`, `backend/scripts/manage_thread.py::send`, `backend/app/agents/linkedin_sender.py::_register_send` all write `approval_status='approved'`.
- **Enforced in target by:** Postgres roles + RLS — a `prospectiq_writer_approval_svc` role is the only role that can `UPDATE outreach_drafts SET approval_status = ...`; everything else uses a `prospectiq_writer_reader` role that can read but not transition lifecycle columns; the `ApprovalService` runs as the `approval_svc` role; the new `approval_attestations` table has a FK from `outreach_drafts.approved_attestation_id` that is required for `approval_status='approved'` via a CHECK constraint. The schema therefore makes it impossible to set `approval_status='approved'` without going through `ApprovalService.approve()`.

### B.2 Canonical State Lives in the Database

- **Statement:** State machines have explicit `_state` columns with `CHECK (state IN (...))`; transitions are explicit; in-memory computation of state is forbidden.
- **Rationale:** Stage 2 F.12 — `contacts.outreach_state` and `outreach_drafts.sent_at` can drift; reconstruction requires regex parsing a state column. Stage 1 D — `outreach_outcomes` written at draft generation; readers can't tell whether the row reflects a sent email.
- **Current violation:** `_send_approved_drafts` derives "sent" from `(approval_status='approved' AND sent_at IS NOT NULL AND resend_message_id IS NOT NULL AND a matching engagement_sequences row AND an email_sent interaction)` — no single column says "sent."
- **Enforced in target by:** `outreach_drafts.lifecycle_state` column with `CHECK` (Section C.1); `send_attempts.state` column with `CHECK` (Section C.5); `contacts.lifecycle_state` column with `CHECK` (Section C.2); state-transition triggers reject illegal moves.

### B.3 Transactional Boundaries Match Business Outcomes

- **Statement:** Each business outcome (approve, claim-and-attest, dispatch, project-side-effects) is exactly one DB transaction; if any part fails, the whole outcome rolls back.
- **Rationale:** Stage 1 H concurrency + silent-failure risks. The send path issues 7+ separate writes across the same logical operation, each in its own HTTP request.
- **Current violation:** `engagement.py:557–887` — the send path has no transactional boundary; failures between claim and Resend orphan the draft, failures after Resend leave projections inconsistent (Stage 2 F.6, F.7).
- **Enforced in target by:** `ApprovalService.approve()` is one DB transaction (Section E.2); `SendWorker.dispatch()` consists of (a) a transaction that claims and writes the outbound queue row; (b) the Resend call outside the transaction; (c) a second transaction that consumes the outbox and projects side effects. Each transaction is small, idempotent, and crash-safe.

### B.4 Event Logging is not Event Sourcing

- **Statement:** Distinguish the `interactions` event log (a denormalized read-side projection for analytics) from `workflow_events` (the append-only authoritative transition record). Do not pretend the system is event-sourced when it is event-logged; do not store business-critical state in either.
- **Rationale:** Stage 1 A — "interactions is the closest thing to an event log but is written non-transactionally as a side effect of many actions, so reconstructing state from it is unsafe."
- **Current violation:** `interactions` is the only audit of opens/clicks/sends; the code at engagement.py:758–772 inserts it after the send in its own try/except. Failures invisible.
- **Enforced in target by:** Two-tier event model. Tier 1: `workflow_events` (new — Section D.2) is the authoritative state-transition record, written in the same transaction as the state column change. Tier 2: `interactions` is a side-effect projection useful for analytics but never trusted for control flow. Future state recovery uses `workflow_events`; analytics uses `interactions`.

### B.5 Governance is Schema-First, Service-Second, API-Last

- **Statement:** Lifecycle invariants are enforced first at the schema (CHECK, FK, UNIQUE, triggers), second at the `ApprovalService`/`SendWorker` layer, third at the API layer. A bypass at any layer must still hit the schema enforcement.
- **Rationale:** Stage 1 H — every governance bypass was a code path that wrote past the service layer directly to the table. The schema accepted it.
- **Current violation:** `approval_status='approved'` has no CHECK linking it to `approved_by IS NOT NULL` (Stage 2 A.4). The schema accepts an unsigned approval.
- **Enforced in target by:** New CHECK constraints (Section D), DB triggers for state transitions (Section C), and `prospectiq_writer_*` Postgres roles for column-level write control (Section B.1).

### B.6 Idempotency at Every External Boundary

- **Statement:** Every operation triggered by an external event (webhook, scheduler tick, manual API call) has a deterministic idempotency key; the key is enforced by a `UNIQUE` constraint that the operation checks before doing work.
- **Rationale:** Stage 2 E.8 — no webhook handler does duplicate-event detection; Resend retries double-count opens.
- **Current violation:** `webhooks.py::resend_webhook` writes `interactions` on every replay (line 903–916); `_poll_instantly_events` checks type but not event id.
- **Enforced in target by:** `webhook_event_log` (Section D.5) keyed on `(provider, event_id)` UNIQUE; INSERT first in every handler. `outbound_queue` (Section D.9) keyed on `(draft_id, attempt_number)` UNIQUE.

### B.7 Orchestration is Separate from the API Process

- **Statement:** Background work runs in a separate process with a known start-once guard; the API process serves requests only.
- **Rationale:** Stage 2 B.2 + B.3 — APScheduler in-process plus multi-replica defeats every concurrency-safety assumption.
- **Current violation:** `backend/app/api/main.py:2029–2227` starts APScheduler unconditionally in every replica of the FastAPI lifespan.
- **Enforced in target by:** Procfile `worker:` process running APScheduler (Section F.1); the API `web:` process does not start a scheduler; the worker process takes a postgres advisory lock on startup so only one worker runs.

### B.8 Integrations Are Adapters Behind a Stable Interface

- **Statement:** Every external service is accessed through a single adapter module exposing a stable interface; provider-specific quirks (rate limits, dedup keys, retry policy, failure shapes) are normalized inside the adapter.
- **Rationale:** Stage 1 F — three places call `resend.Emails.send` directly; two Instantly webhook handlers exist with different verification; Apollo has an unbounded class-level cache.
- **Current violation:** `engagement.py` calls `resend.Emails.send` directly; `resend_client.py` claims transactional-only but uses the same key; two Instantly routers mounted simultaneously.
- **Enforced in target by:** `OutboundProvider` interface (Section G.1); one `ResendAdapter`, one `InstantlyAdapter`, one `GmailAdapter`. Direct SDK calls from agents are forbidden.

### B.9 Observability Through Structured Events, Not Log Lines

- **Statement:** Every state transition emits a structured event row in `workflow_events`; logs are for debugging humans, not for reconstructing what happened.
- **Rationale:** Stage 1 H — `_rollback_sent_at` failure fires a CRITICAL log but creates no queryable record; orphaned drafts are not findable.
- **Current violation:** Logs are the only record of rollback failures and force-approvals.
- **Enforced in target by:** `workflow_events` table (Section D.2) is the structured event store; `_rollback_sent_at` writes a `rollback_failed` event row; `?force=true` writes a `force_approved` event row; the dashboard queries `workflow_events` directly.

### B.10 Audit is Immutable and Append-Only

- **Statement:** Every audit table has no DELETE/UPDATE privilege for any application role; the schema physically prevents mutation.
- **Rationale:** Stage 2 G.2 — `rejected_draft_reassessment.py` clears `rejection_reason` to NULL, destroying the model's prior judgment.
- **Current violation:** `outreach_drafts.rejection_reason`, `outreach_drafts.approved_at`, every `interactions` row are all UPDATE-able.
- **Enforced in target by:** `workflow_events`, `approval_attestations`, `send_attempts`, `webhook_event_log`, `policy_snapshots` are all `GRANT INSERT, SELECT` only — no UPDATE, no DELETE — for the application roles. Schema-level immutability.

### B.11 Approved Means Provably Approved

- **Statement:** A draft is "approved" only when an `approval_attestations` row exists referencing it, written by `ApprovalService` under an authenticated reviewer identity, with a policy_snapshot reference, a quality-gate result, an attestation payload, and a body content hash.
- **Rationale:** Stage 2 C — eight write paths to `approved`, of which seven omit at least one piece of governance.
- **Current violation:** Schema permits `approval_status='approved'` with `approved_by=NULL`, `reviewed_at=NULL`, `attestation=NULL`.
- **Enforced in target by:** CHECK `(approval_status NOT IN ('approved','edited') OR approval_attestation_id IS NOT NULL)`; FK `outreach_drafts.approval_attestation_id REFERENCES approval_attestations(id)` ON DELETE RESTRICT; `approval_attestations` itself is INSERT-only.

### B.12 Content Claims are Grounded in Evidence

- **Statement:** Every factual or performance claim used in a draft body is sourced from a `content_claims` registry row; generation cannot introduce a claim that isn't in the registry; validation rejects drafts whose body contains claim-shaped strings not in the registry.
- **Rationale:** Section 5.c of Stage 3 catalogs the fabrication patterns ("40-65% claim," "SMRP reference," "one plant found"). The integrity regex is a blacklist; the right approach is an allowlist of claims.
- **Current violation:** Drafts containing "we typically", "40 to 65%", "one plant found" survive the gate when generated via the HTTP path (Stage 1 H), or are approved via `pending_draft_reconciliation.py`.
- **Enforced in target by:** `content_claims` registry (Section D.7) is the only source of allowable performance claims; `DraftGenerator` constructs the prompt to reference registry entries; validator rejects drafts containing unauthorized claim shapes.

### B.13 Failure Isolation: Send Failures Stop Sends, Not Sequences

- **Statement:** A failure in one phase of the lifecycle pauses that phase only; unrelated phases continue. A send-path bounce-rate violation stops sends; it does not stop draft generation, qualification, or reply intake.
- **Rationale:** Stage 1 H — `assert_bounce_rate_ok` raises on the first contact of every batch, effectively pausing the batch but in a per-contact rather than per-pipeline way.
- **Current violation:** The global send halt is implemented as a per-contact assertion failure that re-fires; there is no first-class "send freeze" entity that stops sends cleanly while allowing other work to continue.
- **Enforced in target by:** `send_freezes` table (a row pauses sends globally or per-workspace); the send worker checks for an active freeze before claiming any outbox row; draft generation and reply intake do not consult `send_freezes`.

### B.14 Replayability of State Transitions

- **Statement:** Any contact, draft, or company state is reconstructible by replaying `workflow_events` rows in `(target_id, sequence_number)` order; the live state columns are a cached projection that can be rebuilt.
- **Rationale:** Stage 1 A "real state lives in mutable columns" — recovery from data corruption is impossible without replay.
- **Current violation:** `interactions` is non-transactional and incomplete; there is no event log that can rebuild `contacts.outreach_state` after a corruption.
- **Enforced in target by:** `workflow_events` (Section D.2) holds the canonical sequence of transitions; a `rebuild_contact_state(contact_id)` function reconstructs the projection from events.

### B.15 Human Approval Means a Real Human, in Policy Compliance

- **Statement:** Every approval requires a real authenticated user identity, attestation payload, policy snapshot reference, and quality-gate evidence; "force" approvals are a separate, more-audited workflow, not a query-string flag.
- **Rationale:** Stage 1 H — `?force=true` bypasses quality and cap with one query-string parameter and no special audit.
- **Current violation:** `backend/app/api/routes/approvals.py:376` accepts `force: bool = False`; lines 410, 438 `if not force:` short-circuit the cap and quality checks.
- **Enforced in target by:** `approve_draft` endpoint accepts no force parameter; `POST /api/approvals/{id}/override` is a separate endpoint requiring (a) explicit reason string, (b) a second approver, (c) writes `approval_attestations.is_override=true` with an `override_reason` field; the audit row is in a distinct event type.

---

## SECTION C — Canonical Lifecycle State Machines

For each entity, an explicit state machine. Conventions used in the diagrams:

- States are uppercase tokens.
- Transitions are labeled `[trigger / actor]`.
- An `*` after a state name means terminal.

### C.1 `outreach_draft` lifecycle

**Owner:** `DraftService` (creation), `ApprovalService` (approval/rejection), `SendWorker` (dispatch via send_attempts).

**States:**

| State | Description |
|---|---|
| `DRAFTING` | Generator is composing content; row may not yet exist |
| `QUEUED` | Row exists; pending review; passed integrity regex |
| `QUARANTINED` | Row failed integrity regex auto-check; needs human review or auto-discard |
| `UNDER_REVIEW` | A reviewer has opened the draft; soft lock (advisory) |
| `APPROVED` | `ApprovalService` wrote an `approval_attestations` row; eligible for outbox |
| `EDITED` | Approved with edits; the `edited_body_version_id` differs from the original body version |
| `PENDING_SECOND_REVIEW` | Tier-1 first-reviewer approved; awaiting second reviewer |
| `REJECTED` | A reviewer rejected with reason |
| `ENQUEUED` | A row in `outbound_queue` exists; ready for `SendWorker` to claim |
| `SENDING` | A `send_attempts` row in state `CLAIMED` or `DISPATCHED` exists |
| `SENT` * | At least one `send_attempts` row in state `DELIVERED` |
| `FAILED` * | All `send_attempts` rows terminal in `FAILED` / `BOUNCED` / `COMPLAINED` |
| `SUPPRESSED` * | Contact or company moved to a suppression state after draft creation; draft is no longer eligible |
| `ARCHIVED` * | Manually retired; preserved for audit |

**Valid transitions:**

```
DRAFTING       --[generator emit / DraftService]--> QUEUED
DRAFTING       --[integrity_regex_fail / DraftService]--> QUARANTINED
QUARANTINED    --[reviewer_release / ApprovalService]--> QUEUED
QUARANTINED    --[auto_discard / DraftService:auto]--> REJECTED
QUEUED         --[reviewer_open / ApprovalService:advisory]--> UNDER_REVIEW
UNDER_REVIEW   --[reviewer_close_no_action / ApprovalService:advisory]--> QUEUED
UNDER_REVIEW   --[approve(non-tier1) / ApprovalService]--> APPROVED
UNDER_REVIEW   --[approve(tier-1) / ApprovalService]--> PENDING_SECOND_REVIEW
PENDING_SECOND_REVIEW --[second_approve / ApprovalService]--> APPROVED
UNDER_REVIEW   --[approve_with_edit / ApprovalService]--> EDITED
UNDER_REVIEW   --[reject / ApprovalService]--> REJECTED
QUEUED         --[reject_directly / ApprovalService]--> REJECTED
APPROVED       --[outbox_enqueue / ApprovalService:same-tx]--> ENQUEUED
EDITED         --[outbox_enqueue / ApprovalService:same-tx]--> ENQUEUED
ENQUEUED       --[claim / SendWorker]--> SENDING
SENDING        --[delivery_confirmed / SendWorker]--> SENT *
SENDING        --[dispatch_failed_retryable / SendWorker]--> ENQUEUED
SENDING        --[dispatch_failed_terminal / SendWorker]--> FAILED *
SENDING        --[bounce / SendWorker]--> FAILED *
QUEUED         --[contact_suppressed / SuppressionService]--> SUPPRESSED *
APPROVED       --[contact_suppressed / SuppressionService]--> SUPPRESSED *
ENQUEUED       --[contact_suppressed / SuppressionService]--> SUPPRESSED *
REJECTED       --[archive_after_90d / Reconciliation:auto]--> ARCHIVED *
SENT           --[archive_after_180d / Reconciliation:auto]--> ARCHIVED *
```

**Explicitly illegal transitions:**

- `SENT` → any state except `ARCHIVED` (sent is terminal; no rewind).
- `REJECTED` → `APPROVED` (re-approval requires a NEW draft row; preserves the original rejection record).
- Any state → `DRAFTING` (no rewind to generation).
- `APPROVED`/`EDITED` → `QUEUED` (approval is committed; rollback requires the explicit `quarantine` path used during Stage 3 stabilization, which becomes a first-class operation: `unapprove(reason)` creates a new event and moves to `QUARANTINED`, never back to `QUEUED` without re-review).
- `SUPPRESSED` → any non-archived state (suppression is final at the draft level; a new draft can be created if the contact is later un-suppressed).
- `ENQUEUED` → `SENT` (without going through `SENDING`).

**Required invariants per state:**

| State | Invariant |
|---|---|
| `QUEUED`, `QUARANTINED`, `UNDER_REVIEW` | `approval_attestation_id IS NULL` |
| `APPROVED`, `EDITED`, `PENDING_SECOND_REVIEW`, `ENQUEUED`, `SENDING`, `SENT` | `approval_attestation_id IS NOT NULL` |
| `EDITED` | `edited_body_version_id IS NOT NULL` AND `edited_body_version_id <> original_body_version_id` |
| `ENQUEUED` | An `outbound_queue` row exists with `draft_id = this.id AND state IN ('PENDING','RETRYING')` |
| `SENDING` | A `send_attempts` row with `draft_id = this.id AND state IN ('CLAIMED','ASSERTING','DISPATCHED')` |
| `SENT` | At least one `send_attempts` row with `state = 'DELIVERED'` AND `delivery_confirmed_at IS NOT NULL` |
| `FAILED` | All `send_attempts` rows in terminal failure states; `last_failure_reason IS NOT NULL` |
| `SUPPRESSED` | `contacts.lifecycle_state IN ('SUPPRESSED_*')` or equivalent at company scope |

**Recommended DB constraints:**

```sql
ALTER TABLE outreach_drafts ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'QUEUED';
ALTER TABLE outreach_drafts ADD CONSTRAINT outreach_drafts_lifecycle_state_check
  CHECK (lifecycle_state IN (
    'DRAFTING','QUEUED','QUARANTINED','UNDER_REVIEW','APPROVED','EDITED',
    'PENDING_SECOND_REVIEW','REJECTED','ENQUEUED','SENDING','SENT','FAILED',
    'SUPPRESSED','ARCHIVED'));

-- Approval must be backed by an attestation row.
ALTER TABLE outreach_drafts ADD COLUMN approval_attestation_id UUID
  REFERENCES approval_attestations(id) ON DELETE RESTRICT;
ALTER TABLE outreach_drafts ADD CONSTRAINT outreach_drafts_approval_attestation_required
  CHECK (
    lifecycle_state NOT IN ('APPROVED','EDITED','PENDING_SECOND_REVIEW','ENQUEUED','SENDING','SENT')
    OR approval_attestation_id IS NOT NULL
  );

-- UNIQUE on (workspace, contact, sequence_name, sequence_step) for non-terminal states.
CREATE UNIQUE INDEX uniq_active_draft_per_step
  ON outreach_drafts (workspace_id, contact_id, sequence_name, sequence_step)
  WHERE lifecycle_state NOT IN ('REJECTED','FAILED','SUPPRESSED','ARCHIVED');

-- State-transition guard via trigger.
CREATE OR REPLACE FUNCTION outreach_drafts_state_transition_guard()
RETURNS TRIGGER AS $$ BEGIN
  IF OLD.lifecycle_state = 'SENT' AND NEW.lifecycle_state <> 'ARCHIVED' THEN
    RAISE EXCEPTION 'illegal_transition: SENT -> %', NEW.lifecycle_state;
  END IF;
  IF OLD.lifecycle_state = 'REJECTED' AND NEW.lifecycle_state = 'APPROVED' THEN
    RAISE EXCEPTION 'illegal_transition: REJECTED -> APPROVED (create a new draft)';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_outreach_drafts_state_transition_guard
  BEFORE UPDATE OF lifecycle_state ON outreach_drafts
  FOR EACH ROW EXECUTE FUNCTION outreach_drafts_state_transition_guard();

-- Block body/subject mutation once approved.
CREATE OR REPLACE FUNCTION outreach_drafts_content_immutability_guard()
RETURNS TRIGGER AS $$ BEGIN
  IF OLD.lifecycle_state IN ('APPROVED','EDITED','PENDING_SECOND_REVIEW','ENQUEUED','SENDING','SENT','FAILED','ARCHIVED')
     AND (OLD.body_version_id IS DISTINCT FROM NEW.body_version_id
       OR OLD.edited_body_version_id IS DISTINCT FROM NEW.edited_body_version_id) THEN
    RAISE EXCEPTION 'content_immutable: cannot change body_version after approval';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
```

**Events emitted on each transition** (all to `workflow_events`):
`draft_generated`, `draft_quarantined`, `draft_released_to_queue`, `draft_opened_for_review`, `draft_approved`, `draft_edited`, `draft_pending_second_review`, `draft_second_approved`, `draft_rejected`, `draft_enqueued`, `draft_claimed`, `draft_sent`, `draft_failed`, `draft_suppressed`, `draft_archived`.

**Ownership:** `outreach_drafts.lifecycle_state` writes are restricted via the `prospectiq_writer_approval_svc` and `prospectiq_writer_send_worker` Postgres roles. No other code path may UPDATE this column.

```
                       +-------------+
            generator->| DRAFTING    |
                       +------+------+
              ok|             |fail
                |             v
                |       +-------------+      reviewer        +-------------+
                |       | QUARANTINED |-------release------> |             |
                |       +-------------+                      |             |
                v                                            |   QUEUED    |
          +-------------+   reviewer_open    +-------------+ |             |<--+
          |   QUEUED    |------------------->|  UNDER_     | |             |   |
          +------+------+                    |   REVIEW    | +------+------+   |
                 |                           +---+-----+---+        |          |
                 |                               |     |            |close     |
                 |                          approve  approve_edit   |no-action |
                 |                               |     |            +----------+
                 |              +-------tier1?--+|     |
                 |              |              ||     |
                 v              v              |v     v
            +-------+   +----------------+    +--------+  +------+
            |REJECT*|<--| PENDING_2ND_   |    |EDITED  |  |APPROVE|
            +-------+   |  REVIEW        |    +---+----+  +---+--+
                        +-------+--------+        |           |
                              second_ok|          |           |
                                       v          +-->ENQUEUED|<-+
                                  +--------+           +---+--+   |
                                  |APPROVE |--enqueue->|         |
                                  +--------+           |  send   |
                                                       |  attempt|
                                                       v  loop   |
                                                  +---------+    |
                                                  | SENDING |    |
                                                  +----+----+    |
                                                       |         |
                                              +--------+---------+
                                              | ok        retry  fail
                                              v                  v
                                          +------+           +-------+
                                          | SENT*|           |FAILED*|
                                          +------+           +-------+

(Any state in {QUEUED, APPROVED, ENQUEUED} can also move to SUPPRESSED*
 when SuppressionService marks the contact suppressed.)
```

### C.2 `contact` lifecycle

**Owner:** `EnrichmentService` (enrichment states), `OutreachStateService` (outreach states), `SuppressionService` (suppression states), `ReplyService` (engaged state).

**States:**

| State | Description |
|---|---|
| `RAW` | Just imported from Apollo/CSV; not yet enriched |
| `ENRICHING` | Enrichment in progress |
| `ENRICHED` | Apollo + ZeroBounce passes recorded; eligible for qualification |
| `ENRICHMENT_FAILED` | Enrichment terminally failed; contact remains but is ineligible |
| `QUALIFIED` | Passed ICP/PQS qualification gate |
| `DISQUALIFIED` | Failed qualification permanently (industry, persona) |
| `ELIGIBLE` | In `outbound_eligible_contacts`; ready for drafting |
| `SEQUENCED` | At least one draft has been sent (touch-1 sent) |
| `WARMING` | At least one engagement signal (open or human click) in last 14d |
| `HOT` | At least one reply or 2+ human-class events in last 7d |
| `RESPONDED` | Engaged through reply with positive intent |
| `CONVERTED` | Meeting booked / pipeline opp created |
| `SUPPRESSED_BOUNCED` | Email bounced hard |
| `SUPPRESSED_UNSUBSCRIBED` | Opt-out received |
| `SUPPRESSED_COMPLAINED` | Spam complaint |
| `SUPPRESSED_DEPARTED` | Apollo / signal indicates contact left the company |
| `SUPPRESSED_NOT_INTERESTED` | Reply classified as soft no |
| `SUPPRESSED_DO_NOT_CONTACT` | Manual DNC or domain-level |

**Valid transitions:**

```
RAW                  --[enrich_start / EnrichmentService]--> ENRICHING
ENRICHING            --[enrich_complete / EnrichmentService]--> ENRICHED
ENRICHING            --[enrich_terminal_fail / EnrichmentService]--> ENRICHMENT_FAILED
ENRICHED             --[qualify_pass / QualificationService]--> QUALIFIED
ENRICHED             --[qualify_fail / QualificationService]--> DISQUALIFIED
QUALIFIED            --[eligibility_view_pass / DB:trigger]--> ELIGIBLE
ELIGIBLE             --[first_send / SendWorker]--> SEQUENCED
SEQUENCED            --[open_or_human_click / WebhookHandler]--> WARMING
SEQUENCED            --[reply / WebhookHandler]--> HOT
WARMING              --[reply / WebhookHandler]--> HOT
HOT                  --[positive_intent / ReplyService]--> RESPONDED
HOT                  --[meeting_booked / CRM]--> CONVERTED
WARMING              --[cooldown_14d_no_engagement / Reconciliation]--> SEQUENCED
* (any non-suppressed) --[bounce / WebhookHandler]--> SUPPRESSED_BOUNCED
* (any non-suppressed) --[unsubscribe / WebhookHandler]--> SUPPRESSED_UNSUBSCRIBED
* (any non-suppressed) --[complaint / WebhookHandler]--> SUPPRESSED_COMPLAINED
* (any non-suppressed) --[apollo_departure_signal / SignalMonitor]--> SUPPRESSED_DEPARTED
* (any non-suppressed) --[soft_no_reply / ReplyService]--> SUPPRESSED_NOT_INTERESTED
* (any non-suppressed) --[manual_dnc / Operator]--> SUPPRESSED_DO_NOT_CONTACT
```

**Illegal transitions:**

- `CONVERTED` → any non-converted state (conversions are sticky).
- Any `SUPPRESSED_*` → non-suppressed state (re-activation requires explicit operator action via a new transition `manual_resurrect` which creates a new logical contact row).
- `RAW` → anything except `ENRICHING`.
- `DISQUALIFIED` → `ELIGIBLE` without going through `QUALIFIED`.

**Required invariants:**

- `ELIGIBLE` → contact must be present in `outbound_eligible_contacts` (the materialized eligibility view).
- `SEQUENCED`, `WARMING`, `HOT`, `RESPONDED` → at least one `send_attempts` row in `DELIVERED` state.
- `SUPPRESSED_*` → matching row in `suppression_log` with the same reason.

**DB constraints:**

```sql
ALTER TABLE contacts ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'RAW';
ALTER TABLE contacts ADD CONSTRAINT contacts_lifecycle_state_check
  CHECK (lifecycle_state IN (
    'RAW','ENRICHING','ENRICHED','ENRICHMENT_FAILED','QUALIFIED','DISQUALIFIED',
    'ELIGIBLE','SEQUENCED','WARMING','HOT','RESPONDED','CONVERTED',
    'SUPPRESSED_BOUNCED','SUPPRESSED_UNSUBSCRIBED','SUPPRESSED_COMPLAINED',
    'SUPPRESSED_DEPARTED','SUPPRESSED_NOT_INTERESTED','SUPPRESSED_DO_NOT_CONTACT'));

-- A suppressed contact must have a matching suppression_log row.
CREATE OR REPLACE FUNCTION contacts_suppression_required()
RETURNS TRIGGER AS $$ BEGIN
  IF NEW.lifecycle_state LIKE 'SUPPRESSED_%'
     AND NOT EXISTS (SELECT 1 FROM suppression_log
                       WHERE contact_id = NEW.id
                         AND created_at >= NOW() - INTERVAL '1 minute') THEN
    RAISE EXCEPTION 'suppression_log_row_required for state %', NEW.lifecycle_state;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
```

**Events:** `contact_enriched`, `contact_qualified`, `contact_eligible`, `contact_sequenced`, `contact_warming`, `contact_hot`, `contact_responded`, `contact_converted`, `contact_suppressed`.

**Ownership:** Strict — only the named services may write `lifecycle_state`. Postgres role grants enforce this.

ASCII:
```
RAW --enrich--> ENRICHING --ok--> ENRICHED --qualify_pass--> QUALIFIED
                              \--fail--> ENRICHMENT_FAILED       |
                                                                 v
                                                            ELIGIBLE
                                                                 |
                                                          first_send
                                                                 v
                                                            SEQUENCED <--+
                                                          /     |     \  |
                                                         /open  reply  \-+
                                                        v        v
                                                  WARMING --> HOT --positive-> RESPONDED --booked--> CONVERTED*
                                                              |  --soft_no--> SUPPRESSED_NOT_INTERESTED*
   any of (ELIGIBLE,SEQUENCED,WARMING,HOT) --bounce--> SUPPRESSED_BOUNCED*
                                          --unsub--> SUPPRESSED_UNSUBSCRIBED*
                                          --spam--> SUPPRESSED_COMPLAINED*
                                          --departed--> SUPPRESSED_DEPARTED*
                                          --manual_dnc--> SUPPRESSED_DO_NOT_CONTACT*
```

### C.3 `company` lifecycle

**Owner:** `CompanyStateService` for primary transitions; `SuppressionService` for company-scope suppression; `ChannelCoordinator` writes lock-related state via a derived column.

**States:**

| State | Description |
|---|---|
| `DISCOVERED` | Created via Apollo/CSV/discovery; not yet researched |
| `RESEARCHING` | Research agent in progress |
| `RESEARCHED` | Has `research_intelligence` row; awaiting qualification |
| `QUALIFIED` | PQS passed |
| `DISQUALIFIED` | PQS failed terminally |
| `OUTREACH_READY` | At least one eligible contact, no active suppression |
| `OUTREACH_ACTIVE` | At least one contact in `SEQUENCED`/`WARMING`/`HOT` |
| `ACTIVE_CONVERSATION` | At least one contact in `RESPONDED` |
| `CONVERTED` | Pipeline opp created |
| `DISQUALIFIED_LATE` | Disqualified after outreach started (e.g., wrong fit revealed) |
| `SUPPRESSED_DOMAIN_DNC` | Domain-level DNC |
| `SUPPRESSED_HIGH_BOUNCE` | Multiple bounces escalated |
| `LOCKED_TEMPORARY` | All contacts under company-level send cooldown |

**Valid transitions:**

```
DISCOVERED   --[research_start]--> RESEARCHING
RESEARCHING  --[research_done]--> RESEARCHED
RESEARCHED   --[pqs_pass]--> QUALIFIED
RESEARCHED   --[pqs_fail]--> DISQUALIFIED
QUALIFIED    --[eligible_contact_exists]--> OUTREACH_READY
OUTREACH_READY --[first_contact_sequenced]--> OUTREACH_ACTIVE
OUTREACH_ACTIVE --[positive_reply]--> ACTIVE_CONVERSATION
ACTIVE_CONVERSATION --[meeting_booked]--> CONVERTED
* (any active) --[wrong_fit_signal]--> DISQUALIFIED_LATE
* (any active) --[domain_dnc_signal]--> SUPPRESSED_DOMAIN_DNC
* (any active) --[bounce_escalation]--> SUPPRESSED_HIGH_BOUNCE
OUTREACH_ACTIVE --[send_within_lock_window]--> LOCKED_TEMPORARY
LOCKED_TEMPORARY --[lock_expired]--> OUTREACH_ACTIVE
```

**Illegal transitions:**

- `CONVERTED` → anything except an audit-only `REOPENED` (out of scope).
- `SUPPRESSED_*` at company → unsuppressed (manual operator with override audit).
- `DISCOVERED` → `OUTREACH_*` without going through QUALIFIED/OUTREACH_READY.

**Required invariants:**

- `OUTREACH_ACTIVE` → at least one `contacts.lifecycle_state IN ('SEQUENCED','WARMING','HOT','RESPONDED')`.
- `LOCKED_TEMPORARY` → derived; an active row in `company_outreach_locks` table with `expires_at > NOW()`.
- `ACTIVE_CONVERSATION` → at least one `contacts.lifecycle_state = 'RESPONDED'` or `HOT`.
- `SUPPRESSED_HIGH_BOUNCE` → 2+ rows in `suppression_log` for distinct contacts within 30 days.

**Company-level lock semantics:** Locks are advisory at the company level — a row in `company_outreach_locks (company_id, reason, locked_at, expires_at, created_by)`. The `SendWorker` checks the lock table inside the send transaction. Locks are not a `lifecycle_state` themselves — they overlay the state. The `LOCKED_TEMPORARY` lifecycle state is a UI convenience derived from `(lifecycle_state='OUTREACH_ACTIVE' AND active_lock_exists)`.

**Events:** `company_researched`, `company_qualified`, `company_outreach_started`, `company_active_conversation`, `company_converted`, `company_suppressed`, `company_locked`, `company_unlocked`.

ASCII:
```
DISCOVERED --research--> RESEARCHING --done--> RESEARCHED
                                                  |
                                            pqs_pass|pqs_fail
                                                  v       v
                                            QUALIFIED  DISQUALIFIED*
                                                  |
                                       eligible_contact
                                                  v
                                          OUTREACH_READY
                                                  |
                                          first_send
                                                  v
                                       OUTREACH_ACTIVE <--unlock-- LOCKED_TEMP
                                          | |                          ^
                                       reply| |lock                    |
                                          v |                          |
                                ACTIVE_CONVERSATION --book--> CONVERTED*
       any-active --domain_dnc--> SUPPRESSED_DOMAIN_DNC*
       any-active --bounces--> SUPPRESSED_HIGH_BOUNCE*
       any-active --wrong_fit--> DISQUALIFIED_LATE*
```

### C.4 `engagement_sequence` lifecycle

**Owner:** `SequenceOrchestrator`.

**States:** `SCHEDULED`, `ACTIVE`, `PAUSED`, `COMPLETED`, `ABANDONED`.

**Step-level states (per `sequence_step_state` — Section D.8):** `PENDING`, `DRAFT_GENERATED`, `DRAFT_APPROVED`, `DRAFT_SENT`, `STEP_SKIPPED`, `STEP_BLOCKED`.

**Transitions:**

```
SCHEDULED  --[first_step_due]--> ACTIVE
ACTIVE     --[reply_classified_positive]--> PAUSED
ACTIVE     --[reply_unsubscribe]--> ABANDONED
ACTIVE     --[contact_suppressed]--> ABANDONED
ACTIVE     --[bounce_terminal]--> ABANDONED
ACTIVE     --[final_step_sent]--> COMPLETED
PAUSED     --[reviewer_resume]--> ACTIVE
PAUSED     --[converted]--> COMPLETED
```

**Step transitions:**

```
PENDING            --[jit_pregen]--> DRAFT_GENERATED
DRAFT_GENERATED    --[approval]--> DRAFT_APPROVED
DRAFT_GENERATED    --[step_gap_unmet]--> STEP_BLOCKED
STEP_BLOCKED       --[gap_satisfied]--> DRAFT_GENERATED
DRAFT_APPROVED     --[send_attempt_delivered]--> DRAFT_SENT
DRAFT_APPROVED     --[contact_suppressed]--> STEP_SKIPPED
```

**Invariants:**

- `ACTIVE` sequences must have at least one `sequence_step_state` in `PENDING` or beyond.
- A `DRAFT_SENT` step requires a `send_attempts` row in `DELIVERED`.
- `ABANDONED` requires a reason: `bounce | unsubscribe | suppression | manual`.

**DB constraints:**

```sql
ALTER TABLE engagement_sequences ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'SCHEDULED';
ALTER TABLE engagement_sequences ADD CONSTRAINT engagement_sequences_state_check
  CHECK (lifecycle_state IN ('SCHEDULED','ACTIVE','PAUSED','COMPLETED','ABANDONED'));
ALTER TABLE engagement_sequences ADD COLUMN abandoned_reason TEXT;
ALTER TABLE engagement_sequences ADD CONSTRAINT abandoned_reason_required
  CHECK (lifecycle_state <> 'ABANDONED' OR abandoned_reason IS NOT NULL);
```

ASCII:
```
SCHEDULED --due--> ACTIVE <-->PAUSED
                    | |          |
                    | |          v
                    | +-->COMPLETED
                    |
                    +-->ABANDONED (bounce|unsub|suppression|manual)
```

### C.5 `send_attempt` lifecycle (NEW TABLE)

**Owner:** `SendWorker`.

**States:**

| State | Description |
|---|---|
| `CLAIMED` | Worker has claimed the outbox row; assertions not yet run |
| `ASSERTING` | `run_pre_send_assertions` is executing |
| `ASSERT_FAILED` * | Assertions failed; not retryable on this attempt; outbox row stays for next attempt |
| `DISPATCHED` | Resend SDK returned `id`; awaiting delivery webhook |
| `DELIVERED` * | Resend `email.delivered` webhook received |
| `DISPATCH_FAILED_RETRYABLE` | Resend returned 5xx or timed out; outbox keeps row, attempt is terminal but next attempt may succeed |
| `DISPATCH_FAILED_TERMINAL` * | Resend rejected (invalid_to, etc.) |
| `BOUNCED` * | `email.bounced` webhook received |
| `COMPLAINED` * | `email.complained` webhook received |

**Transitions:**

```
(new row created by SendWorker on outbox claim)
CLAIMED                       --[start_asserting]--> ASSERTING
ASSERTING                     --[assertion_pass]--> DISPATCHED  -- in same tx as Resend call success
ASSERTING                     --[assertion_fail]--> ASSERT_FAILED *
ASSERTING                     --[assertion_exception]--> ASSERT_FAILED *
CLAIMED/ASSERTING/DISPATCHED  --[provider_5xx_or_timeout]--> DISPATCH_FAILED_RETRYABLE
ASSERTING                     --[provider_4xx]--> DISPATCH_FAILED_TERMINAL *
DISPATCHED                    --[delivered_webhook]--> DELIVERED *
DISPATCHED                    --[bounce_webhook]--> BOUNCED *
DISPATCHED                    --[complaint_webhook]--> COMPLAINED *
```

**Illegal transitions:**

- `DELIVERED` → any other state.
- `CLAIMED` → `DELIVERED` (must go through ASSERTING → DISPATCHED).
- `DISPATCH_FAILED_TERMINAL` → `DISPATCHED` (terminal).

**Required invariants:**

- Exactly one `send_attempts` row in `CLAIMED`/`ASSERTING`/`DISPATCHED` at any time per `outbound_queue.id` (enforced by partial unique index on `outbound_queue_id` where state in those values).
- `DISPATCHED` → `provider_message_id IS NOT NULL`.
- `DELIVERED` → `delivery_confirmed_at IS NOT NULL`.
- An `ASSERT_FAILED` attempt must reference a `send_assertions` row that records the failed assertion.

**DB constraints:**

```sql
CREATE TABLE send_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  outbound_queue_id UUID NOT NULL REFERENCES outbound_queue(id) ON DELETE RESTRICT,
  workspace_id UUID NOT NULL,
  attempt_number INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'CLAIMED',
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  asserting_at TIMESTAMPTZ,
  dispatched_at TIMESTAMPTZ,
  delivery_confirmed_at TIMESTAMPTZ,
  terminal_at TIMESTAMPTZ,
  provider TEXT NOT NULL DEFAULT 'resend',
  provider_message_id TEXT,
  provider_response JSONB,
  failure_reason TEXT,
  failed_assertion TEXT REFERENCES send_assertions(id),
  policy_snapshot_id UUID REFERENCES policy_snapshots(id),
  sender_email TEXT,
  CONSTRAINT send_attempts_state_check CHECK (state IN
    ('CLAIMED','ASSERTING','DISPATCHED','DELIVERED',
     'ASSERT_FAILED','DISPATCH_FAILED_RETRYABLE','DISPATCH_FAILED_TERMINAL',
     'BOUNCED','COMPLAINED')),
  CONSTRAINT send_attempts_unique_attempt
    UNIQUE (draft_id, attempt_number)
);
CREATE UNIQUE INDEX uniq_active_attempt_per_outbox
  ON send_attempts (outbound_queue_id)
  WHERE state IN ('CLAIMED','ASSERTING','DISPATCHED');
CREATE INDEX idx_send_attempts_draft ON send_attempts(draft_id);
CREATE INDEX idx_send_attempts_state ON send_attempts(state, claimed_at);
```

**Events:** `send_claimed`, `send_asserted`, `send_dispatched`, `send_delivered`, `send_assert_failed`, `send_dispatch_failed`, `send_bounced`, `send_complained`.

ASCII:
```
CLAIMED --start--> ASSERTING --pass--> DISPATCHED
                       |                  |
                  fail | exception   provider 5xx
                       v                  |
                  ASSERT_FAILED*          v
                                  DISPATCH_FAILED_RETRYABLE
                                          |
                       provider 4xx       |
                                  DISPATCH_FAILED_TERMINAL*

DISPATCHED --delivered--> DELIVERED*
DISPATCHED --bounce--> BOUNCED*
DISPATCHED --complaint--> COMPLAINED*
```

### C.6 `inbound_reply` lifecycle

**Owner:** `ReplyService`.

**States:** `RECEIVED`, `DEDUP_DROPPED`, `CLASSIFYING`, `CLASSIFIED`, `AUTO_ACTIONED`, `QUEUED_HITL`, `ACTIONED`, `ESCALATED`, `CLOSED`.

**Transitions:**

```
(new row created by webhook idempotent insert)
RECEIVED       --[dup_detected]--> DEDUP_DROPPED *
RECEIVED       --[classify_start]--> CLASSIFYING
CLASSIFYING    --[classify_ok]--> CLASSIFIED
CLASSIFYING    --[classify_error]--> QUEUED_HITL  -- failure mode = needs human
CLASSIFIED     --[high_confidence_unsub|bounce]--> AUTO_ACTIONED --[auto_action_done]--> CLOSED *
CLASSIFIED     --[high_confidence_oof]--> AUTO_ACTIONED --> CLOSED *
CLASSIFIED     --[needs_human]--> QUEUED_HITL
QUEUED_HITL    --[reviewer_actioned]--> ACTIONED --> CLOSED *
QUEUED_HITL    --[reviewer_escalates]--> ESCALATED --> ACTIONED --> CLOSED *
QUEUED_HITL    --[sla_breached_24h]--> ESCALATED
```

**Illegal transitions:**

- `CLOSED` → anything.
- `RECEIVED` → `ACTIONED` (must pass through classification or HITL).

**Required invariants:**

- `CLASSIFIED` → `classification IN ('interested','objection','referral','soft_no','out_of_office','bounce','unsubscribe','other')`.
- `AUTO_ACTIONED` → classification ∈ allowlist of auto-actionable.
- `ESCALATED` → `escalation_reason IS NOT NULL`.

**DB constraints:** `inbound_replies` table with `state` CHECK and a partial unique on `provider_message_id` to prevent re-intake.

**Events:** `reply_received`, `reply_classified`, `reply_auto_actioned`, `reply_hitl_queued`, `reply_actioned`, `reply_escalated`, `reply_closed`.

ASCII:
```
RECEIVED --dup--> DEDUP_DROPPED*
   |
   v
CLASSIFYING --ok--> CLASSIFIED --auto--> AUTO_ACTIONED --> CLOSED*
   |error                  |needs_human
   v                       v
   +----------------> QUEUED_HITL --action--> ACTIONED --> CLOSED*
                          |  |sla_breach
                          |  v
                          +ESCALATED --> ACTIONED --> CLOSED*
```

### C.7 `suppression` lifecycle (per contact)

**Owner:** `SuppressionService`.

**States:** `CLEAN`, `SOFT_BOUNCE`, `HARD_BOUNCE`, `COMPLAINT`, `UNSUBSCRIBED`, `DEPARTED`, `DOMAIN_DNC`, `MANUAL_DNC`, `COOLDOWN`, `MONITORING`.

**Note:** these run in parallel with `contacts.lifecycle_state`; the suppression machine carries the reason, while the contact machine carries the SUPPRESSED_* state.

**Transitions:**

```
CLEAN          --[soft_bounce]--> SOFT_BOUNCE
SOFT_BOUNCE    --[2nd_soft_bounce_within_24h]--> HARD_BOUNCE
SOFT_BOUNCE    --[clear_after_30d_no_recur]--> CLEAN
*              --[hard_bounce]--> HARD_BOUNCE
*              --[complaint]--> COMPLAINT *
*              --[unsubscribe_event]--> UNSUBSCRIBED *
*              --[apollo_departure_signal]--> DEPARTED *
*              --[domain_dnc_flag]--> DOMAIN_DNC *
*              --[manual_dnc]--> MANUAL_DNC *
CLEAN          --[reply_negative_sentiment]--> COOLDOWN
COOLDOWN       --[cooldown_90d_elapsed]--> CLEAN
HARD_BOUNCE    --[manual_release_with_override]--> MONITORING
MONITORING     --[14d_no_send_attempt]--> CLEAN
MONITORING     --[bounce_recurrence]--> HARD_BOUNCE
```

**Reactivation conditions:**

- `SOFT_BOUNCE` → `CLEAN` automatically after 30 days with no new soft bounce.
- `COOLDOWN` → `CLEAN` automatically after 90 days.
- `HARD_BOUNCE`/`MANUAL_DNC`/`UNSUBSCRIBED`/`COMPLAINT` → no automatic reactivation; explicit operator override path through `MONITORING` only for `HARD_BOUNCE`.
- `DEPARTED` → no reactivation (the contact left the company; create a new contact at the new company if applicable).
- `DOMAIN_DNC` → released only when the domain is removed from `do_not_contact` (manual operation).

**DB constraints:**

```sql
ALTER TABLE suppression_log ADD COLUMN suppression_state TEXT NOT NULL DEFAULT 'CLEAN';
ALTER TABLE suppression_log ADD CONSTRAINT suppression_state_check
  CHECK (suppression_state IN ('CLEAN','SOFT_BOUNCE','HARD_BOUNCE','COMPLAINT',
    'UNSUBSCRIBED','DEPARTED','DOMAIN_DNC','MANUAL_DNC','COOLDOWN','MONITORING'));
-- Each contact has at most one active (non-CLEAN) suppression row.
CREATE UNIQUE INDEX uniq_active_suppression_per_contact
  ON suppression_log (contact_id)
  WHERE suppression_state <> 'CLEAN';
```

ASCII:
```
CLEAN --soft--> SOFT_BOUNCE --2nd-> HARD_BOUNCE* --override--> MONITORING --recur--> HARD_BOUNCE
   |                       \--clear_30d--> CLEAN
   |--hard--> HARD_BOUNCE*
   |--complaint--> COMPLAINT*
   |--unsub--> UNSUBSCRIBED*
   |--departed--> DEPARTED*
   |--domain_dnc--> DOMAIN_DNC*
   |--manual--> MANUAL_DNC*
   |--neg_reply--> COOLDOWN --90d--> CLEAN
```

### C.8 `approval_workflow` lifecycle

**Owner:** `ApprovalService` (single writer).

**States:** `DRAFT_SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `ESCALATED_FOR_DUAL_REVIEW`, `ATTESTED`, `FORCE_APPROVED_PENDING_AUDIT`.

**Every state has an immutable event in `workflow_events` + a row in `approval_attestations`** for terminal states.

**Transitions:**

```
DRAFT_SUBMITTED                --[reviewer_open]--> UNDER_REVIEW
UNDER_REVIEW                   --[reviewer_close_no_action]--> DRAFT_SUBMITTED
UNDER_REVIEW                   --[approve_full_attestation]--> ATTESTED --> APPROVED
UNDER_REVIEW                   --[approve_tier1_first]--> ESCALATED_FOR_DUAL_REVIEW
ESCALATED_FOR_DUAL_REVIEW      --[second_reviewer_approve]--> ATTESTED --> APPROVED
ESCALATED_FOR_DUAL_REVIEW      --[second_reviewer_reject]--> REJECTED
UNDER_REVIEW                   --[reject]--> REJECTED
UNDER_REVIEW                   --[override_request]--> FORCE_APPROVED_PENDING_AUDIT
FORCE_APPROVED_PENDING_AUDIT   --[audit_acknowledged]--> ATTESTED --> APPROVED
FORCE_APPROVED_PENDING_AUDIT   --[audit_rejection]--> REJECTED
```

**Illegal transitions:**

- Any state → `APPROVED` without going through `ATTESTED`.
- `APPROVED` or `REJECTED` → anything (terminal).
- `FORCE_APPROVED_PENDING_AUDIT` → `APPROVED` without explicit `audit_acknowledged` event.

**Required invariants:**

- `ATTESTED` → `approval_attestations` row exists.
- `APPROVED` → `outreach_drafts.lifecycle_state IN ('APPROVED','EDITED')`.
- `FORCE_APPROVED_PENDING_AUDIT` → `approval_attestations.is_override = TRUE AND override_reason IS NOT NULL`.

**DB constraints:** `approval_attestations` table (Section D.3) is INSERT-only via Postgres role grants. The `is_override` flag plus `override_reason` are required for force-approvals.

**Events:** `approval_submitted`, `approval_reviewed`, `approval_dual_escalated`, `approval_second_approved`, `approval_attested`, `approval_rejected`, `approval_override_requested`, `approval_override_audited`.

ASCII:
```
DRAFT_SUBMITTED --open--> UNDER_REVIEW
                              |
              +-------------- + ----------+--------+
              |               |           |        |
            approve       reject     tier1_first  override
              |               |           |        |
              v               v           v        v
        ATTESTED        REJECTED*  ESCALATED_FOR_  FORCE_APPROVED_
              |                    DUAL_REVIEW     PENDING_AUDIT
              v                       |               |
        APPROVED*                 +---+---+      +---+---+
                              second_ok second_no  audit_ok audit_no
                                  |       |          |      |
                                  v       v          v      v
                              ATTESTED REJECTED* ATTESTED REJECTED*
                                  |                 |
                                  v                 v
                              APPROVED*        APPROVED*
```

---

## SECTION D — Proposed Data Model Changes

For each table: purpose, key columns, FKs, constraints, retention, migration. Full DDL at the end of each subsection.

### D.1 `send_attempts` — NEW

**Purpose:** One row per attempt to dispatch an outreach draft; decouples delivery state from draft state.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK `outreach_drafts(id)` |
| `outbound_queue_id` | UUID | NO | FK `outbound_queue(id)` |
| `workspace_id` | UUID | NO | Tenancy |
| `attempt_number` | INT | NO | 1, 2, 3 ... per `draft_id` |
| `state` | TEXT | NO | Section C.5 states |
| `provider` | TEXT | NO | `'resend'` etc. |
| `provider_message_id` | TEXT | YES | Set on DISPATCHED |
| `provider_response` | JSONB | YES | Raw response payload |
| `policy_snapshot_id` | UUID | NO | FK `policy_snapshots(id)` — pins policy at send time |
| `sender_email` | TEXT | YES | Selected sender |
| `claimed_at` | TIMESTAMPTZ | NO | Set on row create |
| `asserting_at` | TIMESTAMPTZ | YES | When assertions began |
| `dispatched_at` | TIMESTAMPTZ | YES | When Resend SDK returned `id` |
| `delivery_confirmed_at` | TIMESTAMPTZ | YES | When delivery webhook arrived |
| `terminal_at` | TIMESTAMPTZ | YES | When state became terminal |
| `failure_reason` | TEXT | YES | Set on any FAILED state |
| `failed_assertion` | UUID | YES | FK `send_assertions(id)` |

**Migration from current:**

- `outreach_drafts.sent_at` becomes a generated column: `GENERATED ALWAYS AS (SELECT MIN(delivery_confirmed_at) FROM send_attempts WHERE draft_id = outreach_drafts.id AND state='DELIVERED') STORED` — OR (preferred) stays as a denormalized column updated by trigger from `send_attempts` insert/update. Existing rows: backfill `send_attempts` rows from `outreach_drafts` where `sent_at IS NOT NULL`: one row per draft with `state='DELIVERED'`, `delivery_confirmed_at=sent_at`, `provider_message_id=resend_message_id`, `attempt_number=1`.
- `outreach_drafts.resend_message_id`, `resend_status`, `opened_at`, `clicked_at`, `bounced_at`, `complained_at` become per-attempt columns; kept on `outreach_drafts` as denormalized "last attempt" cache.

**Retention:** Indefinite. ~1 row per send; even at 100k sends/year this is small.

**DDL:**

```sql
CREATE TABLE send_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  outbound_queue_id UUID NOT NULL REFERENCES outbound_queue(id) ON DELETE RESTRICT,
  workspace_id UUID NOT NULL,
  attempt_number INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'CLAIMED',
  provider TEXT NOT NULL DEFAULT 'resend',
  provider_message_id TEXT,
  provider_response JSONB,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  sender_email TEXT,
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  asserting_at TIMESTAMPTZ,
  dispatched_at TIMESTAMPTZ,
  delivery_confirmed_at TIMESTAMPTZ,
  terminal_at TIMESTAMPTZ,
  failure_reason TEXT,
  failed_assertion UUID REFERENCES send_assertions(id),
  CONSTRAINT send_attempts_state_check CHECK (state IN
    ('CLAIMED','ASSERTING','DISPATCHED','DELIVERED',
     'ASSERT_FAILED','DISPATCH_FAILED_RETRYABLE','DISPATCH_FAILED_TERMINAL',
     'BOUNCED','COMPLAINED')),
  CONSTRAINT send_attempts_unique_attempt UNIQUE (draft_id, attempt_number)
);
CREATE UNIQUE INDEX uniq_active_attempt_per_outbox
  ON send_attempts (outbound_queue_id)
  WHERE state IN ('CLAIMED','ASSERTING','DISPATCHED');
CREATE INDEX idx_send_attempts_state ON send_attempts(state, claimed_at);
CREATE INDEX idx_send_attempts_provider_message
  ON send_attempts(provider_message_id) WHERE provider_message_id IS NOT NULL;

-- INSERT-only role grants — no UPDATE/DELETE for app role except state column.
REVOKE UPDATE, DELETE ON send_attempts FROM prospectiq_app;
GRANT INSERT, SELECT ON send_attempts TO prospectiq_app;
GRANT UPDATE (state, asserting_at, dispatched_at, delivery_confirmed_at,
              terminal_at, provider_message_id, provider_response,
              failure_reason, failed_assertion)
  ON send_attempts TO prospectiq_writer_send_worker;
```

### D.2 `workflow_events` — NEW

**Purpose:** Append-only authoritative event log of every lifecycle transition across every entity. Source for replay; basis for the future event-driven projections.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `event_id` | UUID | NO | UNIQUE — deterministic from `(target_type, target_id, transition, occurred_at)` for idempotency |
| `target_type` | TEXT | NO | `'outreach_draft'`, `'contact'`, `'company'`, `'send_attempt'`, `'sequence'`, `'inbound_reply'`, `'approval'`, `'suppression'`, `'webhook'` |
| `target_id` | UUID | NO | The entity's PK |
| `transition` | TEXT | NO | Event name from Section C ('draft_approved', 'send_dispatched', ...) |
| `from_state` | TEXT | YES | NULL when target is being created |
| `to_state` | TEXT | NO | New state |
| `actor_type` | TEXT | NO | `'user'`, `'service'`, `'webhook'`, `'system'` |
| `actor_id` | TEXT | YES | UUID for user; service name for service |
| `workspace_id` | UUID | NO | Tenancy |
| `occurred_at` | TIMESTAMPTZ | NO | When the transition happened |
| `recorded_at` | TIMESTAMPTZ | NO | When the row was written (may lag occurred_at on reconciliation) |
| `payload` | JSONB | YES | Transition-specific data (assertion details, reviewer attestation, etc.) |
| `correlation_id` | UUID | YES | Groups events from one logical operation |
| `causation_id` | UUID | YES | The event that caused this event |
| `policy_snapshot_id` | UUID | YES | FK `policy_snapshots(id)` if relevant |

**FK relationships:** None hard — `target_id` is polymorphic. Logical references documented per `target_type`.

**Constraints:**

```sql
CREATE TABLE workflow_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL UNIQUE,
  target_type TEXT NOT NULL,
  target_id UUID NOT NULL,
  transition TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user','service','webhook','system','operator_cli')),
  actor_id TEXT,
  workspace_id UUID NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  payload JSONB,
  correlation_id UUID,
  causation_id UUID,
  policy_snapshot_id UUID REFERENCES policy_snapshots(id),
  CONSTRAINT workflow_events_target_type_check
    CHECK (target_type IN ('outreach_draft','contact','company','send_attempt',
      'sequence','inbound_reply','approval','suppression','webhook'))
);
CREATE INDEX idx_workflow_events_target ON workflow_events(target_type, target_id, occurred_at);
CREATE INDEX idx_workflow_events_transition ON workflow_events(transition, occurred_at);
CREATE INDEX idx_workflow_events_correlation ON workflow_events(correlation_id);
REVOKE UPDATE, DELETE ON workflow_events FROM PUBLIC;
GRANT INSERT, SELECT ON workflow_events TO prospectiq_app;
```

**Retention:** Indefinite. At expected scale (~100 transitions/draft × 100k drafts/year × N years) the table will be large but query patterns are `target_id`-bounded so indexes scale.

**Migration:** No backfill possible — start fresh. Old transitions remain implicit in `interactions`/`outreach_state_log`/`workspace_audit_log`. After cutover, those tables continue to be written as projections but the authoritative source is `workflow_events`.

### D.3 `approval_attestations` — NEW

**Purpose:** One row per approval action. FK from `outreach_drafts.approval_attestation_id`. Immutable.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK `outreach_drafts(id)` |
| `reviewer_id` | UUID | NO | FK `users(id)` — REAL user UUID, not text |
| `second_reviewer_id` | UUID | YES | FK `users(id)` for tier-1 dual review |
| `attested_at` | TIMESTAMPTZ | NO | When the attestation was recorded |
| `attestation_payload` | JSONB | NO | The five booleans (or whatever the version-N schema requires) |
| `quality_gate_result` | JSONB | NO | `{result: 'pass'/'fail', issues: [...]}` from `validate_draft` |
| `policy_snapshot_id` | UUID | NO | FK `policy_snapshots(id)` — what policy was in force |
| `body_version_id` | UUID | NO | FK `draft_content_versions(id)` — what was approved |
| `reviewer_ip` | INET | YES | Source IP |
| `reviewer_user_agent` | TEXT | YES | UA |
| `is_override` | BOOL | NO | TRUE if approved via override path |
| `override_reason` | TEXT | YES | Required when `is_override=true` |
| `override_audited_by` | UUID | YES | FK `users(id)` for override audit |
| `override_audited_at` | TIMESTAMPTZ | YES | Audit ack timestamp |

**Constraints:**

```sql
CREATE TABLE approval_attestations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL UNIQUE REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  reviewer_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  second_reviewer_id UUID REFERENCES users(id) ON DELETE RESTRICT,
  attested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  attestation_payload JSONB NOT NULL,
  quality_gate_result JSONB NOT NULL,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  body_version_id UUID NOT NULL REFERENCES draft_content_versions(id),
  reviewer_ip INET,
  reviewer_user_agent TEXT,
  is_override BOOLEAN NOT NULL DEFAULT FALSE,
  override_reason TEXT,
  override_audited_by UUID REFERENCES users(id),
  override_audited_at TIMESTAMPTZ,
  CONSTRAINT override_reason_required
    CHECK (is_override = FALSE OR override_reason IS NOT NULL),
  CONSTRAINT override_audit_consistent
    CHECK ((override_audited_by IS NULL) = (override_audited_at IS NULL))
);
CREATE INDEX idx_attest_reviewer_attested
  ON approval_attestations(reviewer_id, attested_at);

REVOKE UPDATE, DELETE ON approval_attestations FROM PUBLIC;
GRANT INSERT, SELECT ON approval_attestations TO prospectiq_writer_approval_svc;
GRANT SELECT ON approval_attestations TO prospectiq_app;
```

**Retention:** Indefinite.

**Migration:** Backfill from existing approved drafts where `approved_by` is a real UUID and `reviewed_at IS NOT NULL`. Drafts where `approved_by='avanish'` or both fields NULL get a placeholder `approval_attestations` row with `is_override=true` and `override_reason='migration_backfill_unauthenticated_approval'` to preserve audit while flagging the unsigned-historical population.

### D.4 `policy_snapshots` — NEW

**Purpose:** Versioned snapshots of active send policy at approval and send time.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `version` | INTEGER | NO | Monotonically increasing |
| `created_at` | TIMESTAMPTZ | NO | When this snapshot became active |
| `superseded_at` | TIMESTAMPTZ | YES | NULL = active |
| `workspace_id` | UUID | YES | NULL = global policy |
| `payload` | JSONB | NO | Full policy: limits, step gaps, cooldown windows, channel rules, bounce thresholds, content guidelines, sequences, sender pool, max approvals per reviewer per day |
| `payload_hash` | TEXT | NO | sha256 of payload |
| `created_by` | UUID | NO | FK `users(id)` |
| `description` | TEXT | YES | Human-readable change note |

**Constraints:**

```sql
CREATE TABLE policy_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version INTEGER NOT NULL,
  workspace_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  superseded_at TIMESTAMPTZ,
  payload JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  created_by UUID NOT NULL REFERENCES users(id),
  description TEXT,
  CONSTRAINT policy_snapshots_unique_version UNIQUE (workspace_id, version)
);
-- Only one active snapshot per workspace at a time.
CREATE UNIQUE INDEX uniq_active_policy
  ON policy_snapshots(workspace_id)
  WHERE superseded_at IS NULL;
REVOKE UPDATE, DELETE ON policy_snapshots FROM PUBLIC;
GRANT INSERT, SELECT ON policy_snapshots TO prospectiq_writer_policy_svc;
GRANT UPDATE (superseded_at) ON policy_snapshots TO prospectiq_writer_policy_svc;
GRANT SELECT ON policy_snapshots TO prospectiq_app;
```

**Retention:** Indefinite — needed for audit replay.

**Migration:** On first deploy, insert a `version=1` snapshot capturing the current state of `limits.yaml`, `outreach_send_config`, `outreach_guidelines.yaml`, `sequences.yaml`. All historical approval/send records can reference this `version=1` snapshot for the cutover.

### D.5 `webhook_event_log` — NEW

**Purpose:** Idempotency table for all inbound webhook events. Keyed on `(provider, event_id)`. Written before any handler logic runs.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `provider` | TEXT | NO | `'resend'`, `'instantly'`, `'unipile'`, `'trigify'`, `'gmail'`, `'apollo'` |
| `event_id` | TEXT | NO | Provider's event id |
| `event_type` | TEXT | NO | Normalized type |
| `payload` | JSONB | NO | Raw payload |
| `received_at` | TIMESTAMPTZ | NO | Receipt time |
| `processed_at` | TIMESTAMPTZ | YES | When handler finished |
| `processing_state` | TEXT | NO | `'received'`, `'processing'`, `'processed'`, `'failed'`, `'duplicate'` |
| `correlation_id` | UUID | YES | Links to the resulting workflow event(s) |
| `signature_verified` | BOOL | NO | TRUE if signature passed |
| `error` | TEXT | YES | If processing failed |

**Constraints:**

```sql
CREATE TABLE webhook_event_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  processing_state TEXT NOT NULL DEFAULT 'received',
  correlation_id UUID,
  signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
  error TEXT,
  CONSTRAINT webhook_event_log_unique_event UNIQUE (provider, event_id),
  CONSTRAINT webhook_event_log_state_check
    CHECK (processing_state IN ('received','processing','processed','failed','duplicate'))
);
CREATE INDEX idx_webhook_event_log_state_received
  ON webhook_event_log(processing_state, received_at);

-- Append-only — only the processing_state may be updated.
REVOKE UPDATE, DELETE ON webhook_event_log FROM PUBLIC;
GRANT INSERT, SELECT ON webhook_event_log TO prospectiq_app;
GRANT UPDATE (processing_state, processed_at, correlation_id, error)
  ON webhook_event_log TO prospectiq_app;
```

**Retention:** 180 days (configurable). Old rows can be archived; the UNIQUE constraint protects against re-ingestion within the retention window.

**Migration:** No backfill. Start fresh.

### D.6 `draft_content_versions` — NEW

**Purpose:** Immutable version history for draft body/subject.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK `outreach_drafts(id)` |
| `version_number` | INTEGER | NO | 1 = original generation; 2+ = edits |
| `subject` | TEXT | NO | |
| `body` | TEXT | NO | |
| `content_hash` | TEXT | NO | sha256(subject || body) |
| `created_at` | TIMESTAMPTZ | NO | |
| `created_by` | TEXT | NO | `'generator:claude-sonnet-X'` or `'user:<uuid>'` |
| `created_by_type` | TEXT | NO | `'generator'` / `'reviewer_edit'` / `'override_rewrite'` |
| `generation_metadata` | JSONB | YES | Model, temperature, registered claims used (FKs to `content_claims`) |

**Constraints:**

```sql
CREATE TABLE draft_content_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  version_number INTEGER NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by TEXT NOT NULL,
  created_by_type TEXT NOT NULL CHECK (created_by_type IN
    ('generator','reviewer_edit','override_rewrite','migration_backfill')),
  generation_metadata JSONB,
  CONSTRAINT dcv_unique_version_per_draft UNIQUE (draft_id, version_number),
  CONSTRAINT dcv_unique_content_per_draft UNIQUE (draft_id, content_hash)
);

-- outreach_drafts gains pointers; body/subject become deprecated columns
-- maintained as cache of the active version.
ALTER TABLE outreach_drafts
  ADD COLUMN body_version_id UUID REFERENCES draft_content_versions(id),
  ADD COLUMN edited_body_version_id UUID REFERENCES draft_content_versions(id);

REVOKE UPDATE, DELETE ON draft_content_versions FROM PUBLIC;
GRANT INSERT, SELECT ON draft_content_versions TO prospectiq_app;
```

**Retention:** Indefinite.

**Migration:** For every existing `outreach_drafts` row, INSERT one `draft_content_versions` row with `version_number=1`, `subject`/`body` from the draft, `created_by='migration_backfill'`. Set `body_version_id` accordingly. If `edited_body IS NOT NULL`, insert a second row `version_number=2` and set `edited_body_version_id`.

### D.7 `content_claims` — NEW

**Purpose:** Registry of factual claims allowed in outreach. Drafts must ground claims here.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `claim_type` | TEXT | NO | `'product_fact'`, `'benchmark'`, `'client_outcome'`, `'regulatory_reference'`, `'public_signal'` |
| `claim_text` | TEXT | NO | The exact claim phrasing approved for use |
| `claim_pattern` | TEXT | YES | Regex pattern matching equivalent phrasings (for validator) |
| `confidence` | TEXT | NO | `'high'`/`'medium'`/`'low'` |
| `source` | TEXT | NO | Citation: URL, doc reference, internal ticket |
| `source_url` | TEXT | YES | |
| `created_at` | TIMESTAMPTZ | NO | |
| `created_by` | UUID | NO | FK `users(id)` |
| `approved_at` | TIMESTAMPTZ | YES | Distinct from created; reviewed by second party |
| `approved_by` | UUID | YES | FK `users(id)` |
| `effective_from` | TIMESTAMPTZ | NO | When the claim becomes usable |
| `expires_at` | TIMESTAMPTZ | YES | NULL = no expiry |
| `applicable_sectors` | TEXT[] | YES | NAICS / sub-sectors where the claim is relevant |
| `is_active` | BOOL | NO | DEFAULT TRUE |

**Constraints:**

```sql
CREATE TABLE content_claims (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_type TEXT NOT NULL CHECK (claim_type IN
    ('product_fact','benchmark','client_outcome','regulatory_reference','public_signal')),
  claim_text TEXT NOT NULL,
  claim_pattern TEXT,
  confidence TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),
  source TEXT NOT NULL,
  source_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by UUID NOT NULL REFERENCES users(id),
  approved_at TIMESTAMPTZ,
  approved_by UUID REFERENCES users(id),
  effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  applicable_sectors TEXT[],
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_content_claims_active_type
  ON content_claims(is_active, claim_type)
  WHERE is_active = TRUE;
```

**Retention:** Indefinite.

**Migration:** Seed from `offer_context.yaml::product_facts`, `outreach_guidelines.yaml::must_include`/`never_include` (negated as anti-claims), competitor names, validated case studies.

### D.8 `sequence_step_state` — NEW

**Purpose:** Per-contact, per-step state record replacing implicit derivation.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `sequence_id` | UUID | NO | FK `engagement_sequences(id)` |
| `contact_id` | UUID | NO | FK |
| `step_number` | INTEGER | NO | |
| `state` | TEXT | NO | From Section C.4 |
| `draft_id` | UUID | YES | FK `outreach_drafts(id)` — set when draft exists |
| `send_attempt_id` | UUID | YES | FK `send_attempts(id)` — set when dispatched |
| `due_at` | TIMESTAMPTZ | YES | When this step is due |
| `entered_state_at` | TIMESTAMPTZ | NO | |
| `notes` | JSONB | YES | Skip/block reason |

**Constraints:**

```sql
CREATE TABLE sequence_step_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sequence_id UUID NOT NULL REFERENCES engagement_sequences(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id),
  step_number INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING',
  draft_id UUID REFERENCES outreach_drafts(id),
  send_attempt_id UUID REFERENCES send_attempts(id),
  due_at TIMESTAMPTZ,
  entered_state_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notes JSONB,
  CONSTRAINT sss_state_check CHECK (state IN
    ('PENDING','DRAFT_GENERATED','DRAFT_APPROVED','DRAFT_SENT','STEP_SKIPPED','STEP_BLOCKED')),
  CONSTRAINT sss_unique_step UNIQUE (sequence_id, contact_id, step_number)
);
CREATE INDEX idx_sss_due ON sequence_step_state(due_at, state)
  WHERE state IN ('PENDING','STEP_BLOCKED');
```

**Retention:** Indefinite.

**Migration:** Backfill one row per `(sequence_id, step_number)` derived from `outreach_drafts` history per contact in the sequence; state inferred from join with `outreach_drafts.sent_at`.

### D.9 `outbound_queue` — NEW (transactional outbox)

**Purpose:** Explicit outbox table. After approval, a row is inserted here in the same transaction. `SendWorker` consumes from here.

**Key columns:**

| Column | Type | Nullable | Description |
|---|---|---|---|
| `id` | UUID | NO | PK |
| `draft_id` | UUID | NO | FK `outreach_drafts(id)` |
| `workspace_id` | UUID | NO | |
| `state` | TEXT | NO | `'PENDING'`, `'CLAIMED'`, `'RETRYING'`, `'COMPLETED'`, `'DEAD_LETTERED'` |
| `priority` | INTEGER | NO | Lower runs first |
| `available_at` | TIMESTAMPTZ | NO | When eligible for claim |
| `attempt_count` | INTEGER | NO | DEFAULT 0 |
| `max_attempts` | INTEGER | NO | DEFAULT 3 |
| `last_error` | TEXT | YES | |
| `claimed_by` | TEXT | YES | Worker identity (host:pid) |
| `claimed_at` | TIMESTAMPTZ | YES | |
| `claim_expires_at` | TIMESTAMPTZ | YES | Lease expiry |
| `completed_at` | TIMESTAMPTZ | YES | |
| `policy_snapshot_id` | UUID | NO | Pins policy at enqueue time |

**Constraints:**

```sql
CREATE TABLE outbound_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL UNIQUE REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  workspace_id UUID NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING',
  priority INTEGER NOT NULL DEFAULT 100,
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_error TEXT,
  claimed_by TEXT,
  claimed_at TIMESTAMPTZ,
  claim_expires_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  CONSTRAINT outbound_queue_state_check CHECK (state IN
    ('PENDING','CLAIMED','RETRYING','COMPLETED','DEAD_LETTERED'))
);
CREATE INDEX idx_outbox_ready ON outbound_queue(state, available_at, priority)
  WHERE state IN ('PENDING','RETRYING');
CREATE INDEX idx_outbox_claimed ON outbound_queue(state, claim_expires_at)
  WHERE state = 'CLAIMED';
```

**Retention:** `COMPLETED` rows can be archived after 30 days; `DEAD_LETTERED` rows retained indefinitely for forensics.

**Migration:** No backfill. The new approval flow inserts rows from cutover forward. Drafts already approved as of cutover that haven't sent are migrated by a one-time INSERT script.

---

## SECTION E — Governance Architecture

### E.1 Policy Registry design

**Where policy lives:** `policy_snapshots` table (D.4) is the single source of truth at runtime. Files in `config/*.yaml` become the editor's input; a `PolicyService` reads them, normalizes them, and produces snapshot payloads.

**Versioning:** Each snapshot has `version`, `created_at`, `superseded_at`. Exactly one row has `superseded_at IS NULL` per `workspace_id` (enforced by the partial UNIQUE index). `version` is monotonic per workspace.

**Runtime read:** `PolicyService.active(workspace_id)` returns the active snapshot, cached for 60 seconds in-process. The cache TTL is short enough that policy edits propagate quickly; the snapshot is short enough that reading is cheap. Every assertion/approval/send attaches the active `policy_snapshot_id` to its row.

**Edits without restart:** `PolicyService.publish(payload, description, created_by)` inserts a new row, sets `superseded_at=NOW()` on the prior active row in the same transaction, increments `version`. Cache invalidates on next read. No restart required.

**Historical retrieval:** Every `approval_attestations` row references `policy_snapshot_id`; every `send_attempts` row references `policy_snapshot_id`; every `workflow_events` row optionally references one. A replay/audit query joins these and gets the exact policy in force at that moment.

```
+---------------+         +-------------------+
| limits.yaml   |         | sequences.yaml    |
+-------+-------+         +---------+---------+
        |                           |
        +-----------+   +-----------+
                    v   v
              +-------------+
              | PolicyEditor|
              | (CLI/Admin) |
              +------+------+
                     |
                     v
              +-------------+         (single source of truth at runtime)
              | PolicyService|------>+-----------------+
              | .publish()   |       | policy_snapshots|
              +------+-------+       +-----------------+
                     ^                       ^
                     |                       |
                     |60s cache              |
              +------+-------+               |
              | runtime read |---read--------+
              +--------------+
```

### E.2 Approval service design

**Single class `ApprovalService`:** the only writer to `outreach_drafts.approval_attestation_id` and the only writer to `outreach_drafts.lifecycle_state` for approval-related transitions. Backed by the `prospectiq_writer_approval_svc` Postgres role.

**Public methods (the only public surface for approvals):**

```
ApprovalService.submit_for_review(draft_id, reviewer_id) -> Attestation
ApprovalService.open_for_review(draft_id, reviewer_id) -> None      # advisory soft lock
ApprovalService.approve(draft_id, reviewer_id, attestation, edited_body=None, content_version_id=None) -> ApprovalAttestation
ApprovalService.reject(draft_id, reviewer_id, reason) -> Rejection
ApprovalService.second_review_approve(draft_id, reviewer_id, attestation) -> ApprovalAttestation
ApprovalService.request_override(draft_id, reviewer_id, override_reason) -> OverridePending
ApprovalService.audit_override(override_id, auditor_id, audit_decision) -> ApprovalAttestation | Rejection
ApprovalService.list_quarantined(workspace_id) -> list[Draft]
ApprovalService.release_quarantine(draft_id, reviewer_id) -> None   # sends back to QUEUED
```

**What `approve()` checks, in order:**

1. Reviewer is authenticated; role allows approval.
2. Draft is in state `QUEUED`, `UNDER_REVIEW`, `EDITED`, or `PENDING_SECOND_REVIEW` (only).
3. Draft has not been approved (no existing `approval_attestation_id`).
4. Quality gate passes against the resolved body content version (errors block; warnings recorded).
5. Reviewer's 24h approval count is below the active policy cap.
6. For tier-1 companies, this is not the original reviewer (dual review).
7. Attestation payload is complete (all five booleans true), or `is_override=true` with reason.
8. Suppression check: contact and company are NOT currently suppressed (re-check at approval, not just at generation).
9. Body content version exists and matches the supplied `content_version_id` or is the current head version.

**What `approve()` writes, atomically (single DB transaction):**

```sql
BEGIN;
  INSERT INTO approval_attestations (draft_id, reviewer_id, ...) RETURNING id;
  UPDATE outreach_drafts SET
    lifecycle_state = (CASE tier1 AND first_review THEN 'PENDING_SECOND_REVIEW'
                       WHEN edited THEN 'EDITED' ELSE 'APPROVED' END),
    approval_attestation_id = <new id>,
    edited_body_version_id = <if edited>
  WHERE id = :draft_id AND lifecycle_state IN ('QUEUED','UNDER_REVIEW',...);
  INSERT INTO workflow_events (target_type='outreach_draft', target_id=:draft_id,
    transition='draft_approved', from_state=<prior>, to_state=<new>, ...);
  INSERT INTO outbound_queue (draft_id, ...) VALUES (...);  -- only when reaching APPROVED
  INSERT INTO workflow_events (target_type='outreach_draft', target_id=:draft_id,
    transition='draft_enqueued', ...);
COMMIT;
```

Note: enqueue happens in the same transaction. This is the transactional outbox pattern (Section F.2). If the transaction fails, no part is committed.

**Bypass paths eliminated or controlled:**

- Scripts removed (Section A.3).
- `?force=true` removed; replaced by `request_override` + `audit_override` two-step.
- Manifest approval routed through `ApprovalService.approve` per-draft (manifest becomes a UI grouping, not a separate writer).
- `threads.py::approve_and_send` rerouted to call `ApprovalService.approve` then trigger send.
- `linkedin_sender._register_send` separated: LinkedIn draft "marked posted" no longer reuses `approval_status='approved'`; instead it has its own `linkedin_post_state` machine.
- HTTP `OutreachAgent.generate_draft` rerouted to share the same `DraftGenerator` core as the scheduler; both paths run all gates.

**`?force=true` replaced by override two-step:**

1. `ApprovalService.request_override(draft_id, reviewer_id, reason)` — moves draft to `FORCE_APPROVED_PENDING_AUDIT`, writes `approval_attestations.is_override=true`, but does NOT enqueue.
2. A different user (operator+admin role) calls `ApprovalService.audit_override(...)`. Audit can approve or reject. Approve commits the attestation and enqueues. Reject moves draft to `REJECTED`.

**Dual review enforcement:**

- `ApprovalService.approve(draft_id=..., reviewer_id=R)` for a tier-1 company transitions to `PENDING_SECOND_REVIEW` and writes a partial attestation.
- A different reviewer `R'` calls `second_review_approve(draft_id, reviewer_id=R')`. The service rejects if `R' == R`. On success, the attestation is finalized (second_reviewer_id set), state moves to `APPROVED`, outbox row inserted.

**Reviewer cap enforcement:**

- The check at step (5) reads from `approval_attestations WHERE reviewer_id=:R AND attested_at >= NOW() - INTERVAL '24 hours'` and counts. If `>= active_policy.max_approvals_per_reviewer_per_day`, raises `ReviewerCapExceeded`. There is no env var fallback that bypasses this check.

### E.3 Runtime governance enforcement

| Layer | What it enforces | How |
|---|---|---|
| **Schema** | (a) `lifecycle_state` ∈ valid set; (b) `approval_status='approved'` requires `approval_attestation_id IS NOT NULL`; (c) body immutability post-approval; (d) state-transition guard via trigger; (e) UNIQUE (workspace,contact,step) for non-terminal; (f) webhook UNIQUE (provider,event_id); (g) one active attempt per outbox row | CHECK constraints, FK, UNIQUE, triggers, role grants |
| **Service** | (a) Quality gate; (b) reviewer cap; (c) dual review; (d) suppression re-check at approval; (e) attestation payload completeness; (f) state transition legality (in-code, in addition to trigger) | `ApprovalService` Python module — all approval writes flow through it |
| **API** | (a) Authentication; (b) authorization (role check); (c) input validation (Pydantic) | FastAPI dependency injections — `require_role`, `get_current_user` |

**Testing:** every constraint is unit-tested. The `ApprovalService` has an integration test suite that exercises every transition in Section C.1 plus the cap, dual review, override, and suppression-at-approval edge cases. The schema constraints are tested in pgTAP or via Python tests that issue raw INSERTs and assert the expected exception.

**Policy change propagation to in-flight drafts:** Drafts that are already `APPROVED` carry their `policy_snapshot_id`. The send worker honors the pinned snapshot for that send attempt. So a policy edit between approval and send does NOT change what was approved. The next-step draft of the same sequence picks up the new snapshot at its own approval. This is the same approach Stage 2 D documented as the implicit "right" behavior — made explicit here.

### E.4 Audit trail design

**What goes into `workflow_events`:**

- Every state transition listed in Section C.
- Every approval action (submit/open/approve/reject/override/audit).
- Every send attempt phase (claim, assert, dispatch, deliver, fail).
- Every webhook event (received with idempotent insert; on dup, the row's `processing_state='duplicate'` is the dedup signal).
- Every suppression decision.
- Every policy publication.

**Where:** `workflow_events` is the primary audit; `workspace_audit_log` becomes a UI-friendly projection. `interactions` becomes a read-side projection for analytics.

**Queryability:** Indexed by `(target_type, target_id, occurred_at)` for entity-history queries, by `(transition, occurred_at)` for cross-entity audits ("show me every `force_approved` in the last 30 days"), by `correlation_id` for "what happened in one approval+send transaction."

**Mutation protection:** Postgres role grants — `INSERT, SELECT` only. No UPDATE or DELETE. The role grants are validated by a migration test.

---

## SECTION F — Workflow Orchestration Architecture

### F.1 Recommendation: separate Railway `worker:` process running APScheduler with a postgres advisory lock

**Decision: keep APScheduler, move it to a separate Railway process, take a postgres advisory lock at worker startup so only one instance runs at a time.** Do NOT introduce Celery/Redis or Temporal at this stage.

**Rationale:**

- Stage 2 B confirmed Railway runs a Procfile `web:` process; replica count is in the Railway dashboard. A second Procfile process is the minimal change.
- The current scheduler code (`main.py:2029–2227`) is sound; the only flaws are (a) it runs inside the API process, (b) no singleton check. Both are fixed by moving the scheduler to its own process and adding a `pg_advisory_lock(<known_int>)` at startup.
- APScheduler's `BackgroundScheduler` with `BlockingScheduler` is a one-file rewrite; the jobs themselves don't change.
- Adding Celery+Redis adds an operational dependency (Redis), a new failure mode (Celery worker liveness), and a configuration surface (queue routing). At current scale (hundreds of sends/day, dozens of contacts/hour) the complexity is unwarranted.
- Adding Temporal is even heavier. Temporal is right when you need durable workflow state across retries with explicit activity boundaries; here, the workflows are short, the retry policy is simple (outbox attempt counter), and the DB already holds the state. Temporal would replace the outbox table with Temporal state — strictly more complex.
- Once we have the outbox + send_attempts tables and the worker process, we can move to Celery later if scale demands. The outbox interface is the same.

**Procfile change:**

```
web:    pip install -r backend/requirements.txt && uvicorn backend.app.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
worker: pip install -r backend/requirements.txt && python -m backend.app.worker.main
```

**`worker/main.py` startup pseudocode:**

```python
def main():
    db = Database(workspace_id=None)
    # Advisory lock with a fixed app key. Only one process holds it.
    LOCK_KEY = 0xPROSPECTIQ_SCHEDULER  # fixed int constant
    lock_acquired = db.client.rpc("pg_try_advisory_lock", {"key": LOCK_KEY}).execute()
    if not lock_acquired.data:
        logger.critical("Another worker holds the scheduler lock. Exiting.")
        sys.exit(0)
    try:
        scheduler = BlockingScheduler(timezone="America/Chicago")
        register_all_jobs(scheduler)   # the existing add_job calls, factored out
        scheduler.start()
    finally:
        db.client.rpc("pg_advisory_unlock", {"key": LOCK_KEY}).execute()
```

`BlockingScheduler` keeps the process alive; if the process crashes, Railway restarts it; the advisory lock is automatically released when the previous connection dies.

The API process must NOT register the scheduler. Remove the lifespan scheduler startup from `main.py`.

### F.2 Transactional outbox pattern

**Flow:**

```
+-------------------+     same transaction      +------------------+
| ApprovalService   |---------------------------|outbound_queue    |
|   .approve()      | INSERT outreach_drafts    | INSERT row       |
|                   | INSERT approval_atts      |  state=PENDING   |
|                   | INSERT workflow_events    +--------+---------+
+-------------------+                                    |
                                                         |   (separate tx, separate process)
                                                         v
                                +------------------------------------+
                                | SendWorker.poll_outbox()           |
                                +-------+----------------------------+
                                        |
                  1. SELECT FOR UPDATE SKIP LOCKED ... WHERE state=PENDING AND available_at <= NOW()
                                        |
                                        v
                  2. UPDATE outbound_queue SET state='CLAIMED', claimed_by=..., claim_expires_at=NOW()+10min;
                     INSERT send_attempts(state='CLAIMED');
                     INSERT workflow_events(transition='draft_claimed');
                     COMMIT (claim transaction)
                                        |
                                        v
                  3. run_pre_send_assertions(...)
                     INSERT send_assertions
                     update send_attempts.state='ASSERTING' then 'DISPATCHED' or 'ASSERT_FAILED'
                                        |
                            +-----------+-----------+
                            | pass                  | fail
                            v                       v
                  4a. resend.Emails.send(...)    UPDATE outbound_queue
                      capture id                    SET state='DEAD_LETTERED'   if assertion failed
                      UPDATE send_attempts          OR SET state='RETRYING',
                        state='DISPATCHED'             available_at=NOW()+backoff
                        provider_message_id=id        attempt_count++
                      COMMIT (dispatch tx)
                                        |
                                        v
                  5. (async, via webhook)
                     ResendAdapter receives email.delivered
                     INSERT webhook_event_log (idempotent)
                     UPDATE send_attempts state='DELIVERED'
                     UPDATE outbound_queue state='COMPLETED'
                     UPDATE outreach_drafts lifecycle_state='SENT'
                     INSERT workflow_events(transition='send_delivered')
```

**ASCII flow:**

```
[Reviewer] ---> [ApprovalService.approve()] (single transaction)
                   |
              writes: outreach_drafts, approval_attestations, workflow_events, outbound_queue
                   |
                   v
              +---------+
              | outbox  |  state=PENDING
              +----+----+
                   |
                   |   (separate process, polls SELECT FOR UPDATE SKIP LOCKED)
                   v
              [SendWorker.claim] -- writes send_attempts(CLAIMED) -- commits
                   |
                   v
              [SendWorker.assert] -- writes send_assertions, updates send_attempts(ASSERTING) -- commits
                   |
              +----+----+
              | pass    | fail
              v         v
       [SendWorker     [SendWorker
        .dispatch]      .fail_assertion]
              |             |
         resend.Emails    outbox.state=RETRYING (or DEAD_LETTERED if attempts >= max)
         send (external)   send_attempts.state=ASSERT_FAILED
              |
       update send_attempts.state=DISPATCHED, provider_message_id
       commit
              |
       (wait for webhook)
              |
       ResendAdapter.handle('email.delivered'):
              |
       webhook_event_log INSERT IF NOT EXISTS (dedup)
              |
       UPDATE send_attempts.state=DELIVERED
       UPDATE outbound_queue.state=COMPLETED
       UPDATE outreach_drafts.lifecycle_state=SENT
       INSERT workflow_events
```

**Backoff schedule:** attempts 1/2/3 with `available_at = NOW() + (5min × 2^attempt_count)`. After `max_attempts` (default 3), state becomes `DEAD_LETTERED`. Dead-lettered rows stay forever; an operator UI surfaces them for manual review.

**Dead-letter threshold:** 3 attempts is the default per row; this is configurable in `policy_snapshots.payload.send.max_attempts`. Beyond that the row is dead-lettered and a Slack alert fires.

### F.3 Idempotency design

| Step | Key | Enforcement |
|---|---|---|
| Approval | `(draft_id)` is unique in `approval_attestations` | UNIQUE constraint |
| Outbox enqueue | `(draft_id)` unique in `outbound_queue` | UNIQUE constraint — re-approve of the same draft does not double-enqueue |
| Worker claim | `outbound_queue.claimed_by`, `claim_expires_at` | `SELECT FOR UPDATE SKIP LOCKED` ensures only one worker claims |
| Resend dispatch | `idempotency_key=draft.id` to Resend SDK | Provider-side dedup; complemented by `send_attempts (draft_id, attempt_number)` UNIQUE |
| Resend webhook | `(provider='resend', event_id)` in `webhook_event_log` | UNIQUE — replay drops to `duplicate` |
| Instantly webhook | same | same |

Each idempotency layer is a UNIQUE constraint; the code performs INSERT-IF-NOT-EXISTS by catching the unique violation and short-circuiting. No TOCTOU race because the constraint is the check.

### F.4 Concurrency safety

**Preventing double-send:** Today's compare-and-swap on `sent_at` is replaced by:

1. The `outbound_queue` row's UNIQUE on `draft_id` means at most one queue row exists.
2. `SELECT FOR UPDATE SKIP LOCKED ... WHERE state=PENDING` ensures only one worker grabs the row.
3. UNIQUE on `outbound_queue_id` for `send_attempts` in active states means at most one active attempt.
4. Resend's `idempotency_key=draft.id` is the provider-side safety.

A second worker process attempting to claim the same row will get a no-result from `FOR UPDATE SKIP LOCKED`. A second process attempting to insert a second `send_attempts` row for the same outbox in active state hits the partial UNIQUE.

**Running multiple workers safely (future):** The advisory lock currently restricts to one worker. To run N workers, switch from `pg_try_advisory_lock` to per-row claim semantics — already implemented via `SELECT FOR UPDATE SKIP LOCKED`. Then N workers can poll concurrently; each claims a different row. Stick with N=1 until scale demands.

### F.5 Reconciliation jobs

Drift the reconciliation watcher must detect:

1. `outreach_drafts.lifecycle_state='SENT'` but no `send_attempts` row in DELIVERED — query F.5 from Stage 2.
2. `send_attempts.state='DISPATCHED'` but no delivery webhook after 4 hours — auto-mark as `DISPATCH_FAILED_RETRYABLE`, requeue if attempts < max.
3. `outbound_queue.state='CLAIMED'` but `claim_expires_at < NOW()` — orphaned claim; reset to `PENDING`, increment `attempt_count`.
4. `engagement_sequences.lifecycle_state='ACTIVE'` but no `sequence_step_state` rows in `PENDING` or beyond, and current_step < total_steps — sequence stalled.
5. `contacts.lifecycle_state='SEQUENCED'` but no `send_attempts` in DELIVERED — drift; investigate.
6. `webhook_event_log.processing_state='processing'` older than 1 hour — stuck handler; alert.

**Frequency:** runs hourly; produces an operator dashboard. Auto-repair is limited to the orphaned-claim case (4 above) because the cause is well-understood (worker process died mid-claim). All other drifts produce alerts only; human decides.

---

## SECTION G — Integration Architecture

### G.1 `OutboundProvider` interface

```python
from typing import Protocol

class OutboundProvider(Protocol):
    name: str  # 'resend', 'instantly_warmup', ...

    def send(self, message: NormalizedMessage, *, idempotency_key: str
             ) -> ProviderDispatchResult:
        """Synchronously dispatch a single message. Returns provider_message_id on success."""

    def parse_webhook(self, raw_payload: bytes, headers: dict
                      ) -> NormalizedWebhookEvent | None:
        """Verify signature; normalize to canonical DeliveryEvent."""

    def is_healthy(self) -> ProviderHealth:
        """Self-check: credentials, basic API reachability."""
```

Provider registry:

```python
PROVIDERS = {
    'resend': ResendAdapter(),
    'instantly': InstantlyAdapter(),  # warmup only per project memory
}
```

Send worker calls `PROVIDERS[provider_name].send(...)`. Webhook routes call `PROVIDERS[provider].parse_webhook(...)` before any handler logic. Provider failure shapes (`ProviderTransientError`, `ProviderPermanentError`, `ProviderRateLimited`) are normalized so the send worker's retry logic is the same per provider.

### G.2 Resend adapter

**Outbound:** `send(NormalizedMessage, idempotency_key)` wraps `resend.Emails.send(...)`. Returns provider_message_id on 2xx; raises `ProviderTransientError` on 5xx/timeout, `ProviderPermanentError` on 4xx.

**Inbound webhook:** `parse_webhook(payload, headers)`:

1. Verify `Svix-Signature` header (Resend uses Svix). If `RESEND_WEBHOOK_SECRET` is unset, **return None and log critical** — do NOT fall open.
2. Extract `data.id` as the canonical event_id.
3. Normalize to `NormalizedWebhookEvent` (provider='resend', event_id=data.id, event_type=event.type, target_message_id=data.email_id, occurred_at=event.created_at).

**Idempotency:** the webhook route INSERTs into `webhook_event_log` with `(provider='resend', event_id=data.id)` UNIQUE; on conflict, sets `processing_state='duplicate'` and returns 200.

**Retry:** dispatch retries follow the outbox backoff schedule. Webhook receives no retry — the dedup constraint handles replays.

**Failure containment:** A Resend 4xx ('to' invalid, body malformed) puts the attempt into `DISPATCH_FAILED_TERMINAL` and the outbox row into `DEAD_LETTERED`. A Resend 5xx puts the attempt into `DISPATCH_FAILED_RETRYABLE`; outbox state moves to `RETRYING`. A complete Resend outage does not stop draft generation, reply intake, or qualification — only the send worker is affected.

### G.3 Instantly adapter

**Current problem:** two webhook routers (Stage 2 E.1), one query-param secret and one HMAC.

**Target:** single normalized path. Pick HMAC (`/webhooks/instantly` in `backend/app/webhooks/instantly.py`). Delete the query-param route in `routes/webhooks.py`.

**Retiring the legacy static method `process_webhook_event`:**

1. Verify no callers remain other than `routes/webhooks.py:716` (already known) and `engagement.py:1680` (in `_poll_instantly_events`).
2. In Phase 4 (Section I), rewrite `_poll_instantly_events` to call the new `InstantlyAdapter.parse_webhook`-like reconciliation path; the legacy static method is then deleted.
3. Keep a one-time `git rm` change as a Phase 4 cleanup; no migration needed because the method has no DB schema.

**Failure containment:** Instantly is warmup-only per project memory. Adapter errors do not affect Resend send path.

### G.4 Gmail/IMAP adapter

**Current problem:** missing credentials cause silent skip (Stage 2 E.7).

**Target:** explicit health check; alert on missing credentials; per-mailbox state machine.

```python
class GmailAdapter(OutboundProvider):
    def is_healthy(self) -> ProviderHealth:
        unhealthy = []
        for mailbox in self.mailboxes:
            creds = self.cred_store.get(f"gmail_{mailbox.safe_key}")
            if not creds:
                unhealthy.append(f"{mailbox.email}: missing credentials")
        if unhealthy:
            return ProviderHealth(healthy=False, issues=unhealthy)
        return ProviderHealth(healthy=True, issues=[])
```

Scheduler runs `is_healthy()` every 6 hours and fires a Slack alert on any failure. The `gmail_intake` job calls `is_healthy()` before polling; if unhealthy, it logs a structured `mailbox_unreachable` event to `workflow_events` rather than silently returning. Credential rotation path: operator stores new app-password in `CredentialStore`, the adapter picks up the new value on next call (no restart).

### G.5 Apollo adapter

**Current problem:** unbounded class-level cache (`apollo.py:40`).

**Target:** bounded LRU cache, TTL, separate enrichment quota tracking.

```python
from cachetools import TTLCache

class ApolloAdapter:
    _cache = TTLCache(maxsize=5000, ttl=86400)
    _quota = QuotaTracker(table='enrichment_quota', provider='apollo')

    def enrich_person(self, ...):
        if cache_hit: return cached
        if not self._quota.check(): raise QuotaExhausted()
        result = self._call_api(...)
        self._cache[key] = result
        self._quota.consume(1)
        return result
```

`enrichment_quota` is a small table tracking calls per day per workspace. Apollo's daily allowance is the policy snapshot's `enrichment.apollo_daily_calls`.

### G.6 ZeroBounce adapter

**Storage:** verification results land in `contacts.email_status` with an additional `email_verified_at` timestamp + `email_verification_provider` text. The verification record itself is in `email_verifications` (new): `(contact_id, provider, verified_at, status, raw_response)` for full audit.

**Stale detection:** rows with `email_verified_at < NOW() - INTERVAL '180 days'` are flagged stale; an operator UI surfaces them; re-verification is triggered manually or by scheduled job.

**Rate limit handling:** adapter respects per-second limits; on 429, raises `ProviderRateLimited`; outbox-style retry not relevant (this is enrichment, not send).

---

## SECTION H — Content Integrity Architecture

### H.1 Evidence Registry

`content_claims` table (D.7) is the registry. Three classes of records:

| `claim_type` | Examples | Approval flow |
|---|---|---|
| `product_fact` | "Digitillis provides AI-driven OEE/PdM intelligence" | Marketing team adds; second user approves; effective immediately |
| `benchmark` | "Industry average OEE in F&B is 60%" with citation | Research adds with `source_url`; approver verifies citation; expiry 12 months |
| `client_outcome` | "Customer X reduced downtime by Y%" — anonymized | Highest scrutiny; legal sign-off required; explicit `effective_from` after legal review |
| `regulatory_reference` | "FSMA 204 traceability rule effective Jan 2026" | Citation required; expiry follows regulatory dates |
| `public_signal` | "Customer X announced a $50M plant expansion" with URL | Auto-generated from signal scrapers; expiry 90 days |

A claim record's `claim_text` is the exact phrasing approved. `claim_pattern` is an optional regex that matches equivalent phrasings (e.g., "40% to 65%" matches "40-65%" matches "40 to 65 percent").

### H.2 Generation pipeline

**Where:** `DraftGenerator` (the single replacement for both current `OutreachAgent` classes) — lives in `backend/app/services/draft_generator.py`. Called from the scheduler and (via the same code path) from the HTTP endpoint.

**Prompt construction:**

1. Resolve the active `policy_snapshot` for the workspace.
2. Build the system prompt from `outreach_guidelines.yaml` + `offer_context.yaml` + the policy's `voice_and_tone`.
3. Resolve the eligible `content_claims` for the contact's company sector and the active campaign cluster. Insert only these into the prompt context as the allowed evidence set, each tagged with its `id`.
4. Forbidden anti-patterns from policy (expanded from current `outreach_guidelines.yaml::never_include`). Examples to keep banning even after registry exists: bare percentages, "we typically", "one plant found", "10x ROI", any number not tied to a registered claim.
5. The prompt instructs the model: "Every numeric claim, benchmark, or client outcome MUST be drawn from the EVIDENCE list above. Reference the claim id in your draft's metadata field. If no relevant claim is registered, do not invent one — write the message without a claim."

**Generation output:** the model returns a structured JSON: `{subject, body, claim_ids_referenced: [...]}`. The generator runs validation (Section H.3) before persisting.

**Validation before persist:**

1. Every `claim_id` in the model's metadata must exist in `content_claims` and be active.
2. The body is scanned for claim-shaped strings (regex patterns: `\d+%`, `\d+x`, "one X found", etc.); any match must be covered by a `claim_pattern` of a referenced claim.
3. The body is scanned for forbidden anti-patterns; any match rejects the draft.

### H.3 Validation layer (automated)

**Pattern detection:**

```
HARD-REJECT patterns (auto-rejected, no human review):
  - URL in step 1 body
  - Bare unsourced percentage (regex \d{2,3}\s*%) not covered by a referenced claim
  - "10x", "100x", "10X" without claim coverage
  - Banned phrases from policy `never_include`
  - Banned characters (em-dash, en-dash) per policy

WARN-AND-QUARANTINE patterns (auto-flagged, human reviews):
  - "we typically", "we've worked with", "many customers" — vague client references
  - First-person plural with implied client outcome ("we helped X reduce Y")
  - Specific company names not in our customer roster
  - Numbers that look like benchmarks but lack claim coverage

PASS patterns:
  - Numbers covered by an active referenced claim
  - Phrases matching a registered claim_pattern
```

**Where it runs:** inside `DraftGenerator.persist()`, before INSERT. Hard-rejects route to `lifecycle_state='REJECTED'` with `rejection_reason='auto_rejected:<category>'`. Warn-and-quarantine route to `QUARANTINED`. Pass routes to `QUEUED`.

### H.4 Human review ergonomics

**Reviewer dashboard for each draft shows:**

1. The draft body, with every claim-shaped phrase highlighted.
2. For each highlight: the source `content_claims` record (claim text, source URL, confidence, expiry).
3. Phrases not covered by any claim are highlighted in red — these must be edited out or a new claim must be registered.
4. A "Flag this claim" button next to each highlight that lets the reviewer remove the claim from the draft and log the reason.
5. A "Register new claim" button to add a claim to the registry from the review screen.

**Rejection feedback:** when a reviewer rejects, they pick a reason from a dropdown (mapped to `outreach_edit_feedback.rejection_category`) plus optional free text. The feedback is written to `outreach_edit_feedback` (existing migration 044) and is fed back to the generator prompt as anti-patterns for the next generation.

### H.5 Tracing

**Trace from sent email to evidence:**

1. Sent email's `provider_message_id` → `send_attempts` row.
2. `send_attempts.draft_id` → `outreach_drafts` row.
3. `outreach_drafts.body_version_id` (or `edited_body_version_id`) → `draft_content_versions` row.
4. `draft_content_versions.generation_metadata.claim_ids_referenced` → list of `content_claims` ids.
5. Each claim row carries its source/citation/approver.

```
provider_message_id ---> send_attempts ---> outreach_drafts ---> draft_content_versions ---> content_claims
                                                                                                |
                                                                                  source, source_url,
                                                                                  approved_by, citation
```

A single SQL query joins all five and produces the full audit chain.

---

## SECTION I — Migration Strategy

Each phase is independently deliverable. Each phase has a strangler-pattern option where old and new behavior coexist. Schema changes are additive until Phase 7. Every phase has measurable cutover criteria.

### Phase 0: Stabilization (in progress)

**Objective:** safe to run the next send without architectural changes.

**Built/changed:** Stage 3 Section 1 actions (1.1–1.8): SEND_ENABLED=false, snapshots, secret verification, replica=1, scripts disabled, quarantine queries.

**Same:** schema, code (only env vars and config flips).

**Compatibility:** N/A — the system is paused.

**Schema changes:** none.

**Cutover criteria:** Stage 3 Section 12.12 hard-stop is cleared; sends resume.

**Rollback:** Stage 3 Section 12.

**Observability:** Stage 3 Section 5 SQL queries run before each send window.

**Complexity:** S.

**Dependencies:** none.

---

### Phase 1: Schema hardening (additive, no app changes)

**Objective:** add the constraints that should always have been there; do not change app behavior.

**Built/changed:**

- Add `outreach_drafts.lifecycle_state` (default derived from existing columns; backfilled).
- Add UNIQUE on `(workspace_id, contact_id, sequence_name, sequence_step)` for non-terminal `approval_status` — partial index.
- Add CHECK constraints linking states.
- Add UPDATE-blocking trigger on `(body, subject)` for `sent_at IS NOT NULL`.
- Add `workflow_events` table and start writing to it from existing code paths (additive — does not replace `interactions` or `workspace_audit_log`).
- Add `webhook_event_log` table and route every webhook through it (INSERT IF NOT EXISTS at handler entry).
- Add `policy_snapshots` with `version=1` capturing current YAML state.

**Same:** all approval/send paths still work as today.

**Compatibility:** every new table is additive; old code reads/writes the same columns. New code (`workflow_events` writers) is wrapped in try/except to not break the old paths if a constraint trips.

**Schema changes:** all additive; rollback is `DROP TABLE / DROP CONSTRAINT`.

**Cutover criteria:**

- 0 duplicate-draft inserts blocked in 7 days (UNIQUE is correctly aligned with code dedup);
- 0 illegal UPDATE attempts (immutability trigger);
- `workflow_events` row count = `interactions` row count delta in the same window (events are being written everywhere `interactions` are);
- every webhook handler invocation has a corresponding `webhook_event_log` row.

**Rollback:** drop constraints, drop new tables. Old code unaffected.

**Observability:** Slack alert on every CHECK or trigger violation; dashboard panel for `workflow_events` write rate; CSV diff of duplicate-draft attempts (should drop to 0).

**Complexity:** M.

**Dependencies:** Phase 0.

**Strangler:** the immutability trigger raises only on UPDATE of `body`/`subject` after `sent_at IS NOT NULL` — operator scripts are still disabled; existing code does not need to change.

---

### Phase 2: `send_attempts` + `outbound_queue` (decouple delivery from draft state)

**Objective:** introduce the new lifecycle tables and run them in parallel with the existing `sent_at` column.

**Built/changed:**

- Create `send_attempts` and `outbound_queue` tables.
- `EngagementAgent._send_approved_drafts` writes both: legacy `sent_at` AND the new tables. Reads are still from `sent_at` for the dashboard; analytics begin reading `send_attempts`.
- Webhook handlers update `send_attempts` AND legacy columns.
- Add the reconciliation job that detects drift between `sent_at` and `send_attempts`.

**Same:** API endpoints, scheduler config, dashboard UI.

**Compatibility:** dual-write. The old `sent_at` column is canonical; the new tables shadow it.

**Schema changes:** additive. Migration backfills `send_attempts` rows for every existing `outreach_drafts.sent_at IS NOT NULL`.

**Cutover criteria:**

- 14 days of dual-write with 0 drift detected by reconciliation;
- 0 send_attempts rows orphaned (no matching outreach_drafts);
- `send_attempts.state='DELIVERED'` count matches `COUNT(*) FROM outreach_drafts WHERE sent_at IS NOT NULL` exactly each day.

After cutover criteria pass, flip the dashboard to read from `send_attempts`; `sent_at` becomes a denormalized cache maintained by trigger.

**Rollback:** remove the new write paths; old paths still function unchanged.

**Observability:** drift report (Phase 2 reconciliation), dashboard showing parallel counts.

**Complexity:** L.

**Dependencies:** Phase 1.

**Strangler:** dual-write means both old and new readers coexist. After cutover criteria met, gradually move readers; deprecate `sent_at` writes in Phase 7.

---

### Phase 3: Governance consolidation (single ApprovalService, policy registry)

**Objective:** route every approval through one writer; retire script-based approval; bind every approval to a policy snapshot.

**Built/changed:**

- `ApprovalService` Python module with `approve`, `reject`, `request_override`, `audit_override`, `second_review_approve` (Section E.2).
- Create `approval_attestations` table.
- Wire `POST /api/approvals/{id}/approve` to `ApprovalService.approve`. Remove `?force=true`; add `POST /api/approvals/{id}/override-request` and `POST /api/approvals/overrides/{id}/audit`.
- Rewrite `pending_draft_reconciliation.py` and `rejected_draft_reassessment.py` as thin clients that call the API endpoint (no service-role key).
- Rewrite `review_manifest.approve_manifest` to iterate the manifest and call `ApprovalService.approve` per-draft; preserve the body-hash binding.
- Remove `manage_thread.py::send` direct approval write; the script's "send" mode becomes a call to the approval endpoint followed by a queue-claim trigger.
- Remove `threads.py::approve_and_send` direct write; route through the service.

**Same:** the approval queue UI, the visual dashboard.

**Compatibility:** the old write paths are deleted; if any caller still exists, it errors. A short window of dual-acceptance is possible: write through the service AND accept legacy writes for 7 days while monitoring.

**Schema changes:**

- Add `outreach_drafts.approval_attestation_id` FK.
- Add CHECK linking `lifecycle_state='APPROVED'` or `EDITED` to `approval_attestation_id IS NOT NULL`.
- Postgres role grants enforce that only `prospectiq_writer_approval_svc` can write `lifecycle_state` for approval-related values.

**Cutover criteria:**

- 100% of new approvals have an `approval_attestations` row;
- 0 approval writes from roles other than `approval_svc` (Postgres role-grant violation = build error);
- `?force=true` returns 410 for 14 days.

**Rollback:** revert role grants; restore old endpoint behavior; the service is unused; new attestation rows persist as historical record.

**Observability:** dashboard panel "approvals by writer," should be 100% `approval_svc`; alert if any non-service writes.

**Complexity:** L.

**Dependencies:** Phase 1 (CHECK constraints), Phase 2 (outbox table for the same-tx outbox insert).

**Strangler:** during cutover, scripts call the new endpoint via JWT (operator's own user account); migration includes rewriting the scripts to use the API.

---

### Phase 4: Webhook normalization (idempotent, single Instantly path)

**Objective:** every webhook handler is idempotent; remove the duplicate Instantly router; retire the legacy `process_webhook_event` static method.

**Built/changed:**

- All webhook routes (resend, instantly, unipile, trigify, gmail) prepended with an INSERT into `webhook_event_log` keyed on `(provider, event_id)`. On UNIQUE violation, immediately return 200 with `{"status":"duplicate"}`.
- Confirm which Instantly URL is configured (Stage 3 Section 9). Unmount the unused router.
- Replace `EngagementAgent.process_webhook_event` callers with adapter-based handlers.
- Adapters (Section G) become the entry point; the existing handler functions are reorganized under the adapter namespace.

**Same:** webhook URLs (only one Instantly URL changes if the unused one is removed; rest unchanged).

**Compatibility:** old handlers continue to work; the idempotency layer is purely additive.

**Schema changes:** `webhook_event_log` already added in Phase 1.

**Cutover criteria:**

- 0 duplicate `interactions` rows in 7-day window;
- 0 `companies.status='bounced'` writes (legacy contradicting tiered suppression);
- `process_webhook_event` is unreachable (verified by removing all call sites and running for 7 days with no errors).

**Rollback:** restore the legacy fallback; restore the duplicate router.

**Observability:** dashboard panel showing `webhook_event_log` rows by provider, `processing_state='duplicate'` count.

**Complexity:** M.

**Dependencies:** Phase 1.

**Strangler:** the idempotency layer protects the old handlers; consolidating handlers can proceed at any time.

---

### Phase 5: Content integrity pipeline (evidence registry, generation validation)

**Objective:** every claim in a draft body is registered; the validator catches unauthorized claims.

**Built/changed:**

- Create `content_claims` table; seed from `offer_context.yaml`, banned phrases, validated case studies.
- Create `draft_content_versions` table; migrate existing draft bodies into versions.
- Build the UI for managing claims (add/approve/expire).
- Replace `outreach_guidelines.yaml::never_include` with a richer hardcoded HARD-REJECT + WARN-AND-QUARANTINE pattern set.
- Update `DraftGenerator` prompt construction (Section H.2) to inject only registered claims.
- Update `DraftGenerator.validate()` to enforce H.3 rules before INSERT.
- Update the approval UI to highlight claims (Section H.4).

**Same:** the rest of the system; sends continue.

**Compatibility:** existing drafts without registered claims continue to flow through the approval queue but are flagged. Older drafts (pre-Phase 5) have `body_version_id` from the backfill but no `generation_metadata.claim_ids_referenced`.

**Schema changes:** additive (`content_claims`, `draft_content_versions`, `outreach_drafts.body_version_id` etc.).

**Cutover criteria:**

- 100% of new drafts have at least an empty `claim_ids_referenced` array;
- 0% of new HARD-REJECT pattern matches in approved drafts;
- < 5% of new drafts hit WARN-AND-QUARANTINE (this is the policy target — too high means the patterns are too aggressive; tune).

**Rollback:** disable the validator (env flag); revert prompt to old form. The tables persist.

**Observability:** dashboards on rejection rates by category; reviewer feedback rate.

**Complexity:** XL.

**Dependencies:** Phase 1 (tables exist), Phase 3 (ApprovalService stores `body_version_id` on attestation).

**Strangler:** the validator runs in shadow mode for 14 days — logging would-have-rejected without blocking — before enforcing.

---

### Phase 6: Workflow orchestration (separate worker process)

**Objective:** scheduler runs in its own Railway process with a singleton guard.

**Built/changed:**

- Add `backend/app/worker/main.py` with the BlockingScheduler + advisory lock startup (Section F.1).
- Update Procfile: add `worker:` line, remove scheduler startup from API `lifespan`.
- Update Railway configuration to deploy two processes.

**Same:** every job function (no logic changes), just the runtime location.

**Compatibility:** during cutover, the new `worker:` process runs while the API process's scheduler is removed. There is a brief window where neither runs — schedule the deploy outside the 8-11am send window.

**Schema changes:** none.

**Cutover criteria:**

- `worker:` process running for 7 days without crash;
- No "scheduler started" log line appears in the `web:` process logs after the deploy;
- Send rate matches prior week;
- Replica count of `web:` can safely be set > 1 (Stage 3 Section 8 risk lifts).

**Rollback:** revert Procfile; redeploy.

**Observability:** Slack alert if the advisory lock is contested (which means a second worker tried to start — should never happen with a single Procfile `worker:` line).

**Complexity:** M.

**Dependencies:** none (independent of other phases).

**Strangler:** N/A — the cut is binary; do it during a no-send window (Saturday morning, for example).

---

### Phase 7: Full state machine enforcement (sequence_step_state; DB-level state guards)

**Objective:** every state machine in Section C is enforced by DB triggers; implicit state derivations are removed from app code.

**Built/changed:**

- Create `sequence_step_state` table; backfill from history.
- Migrate `_process_due_sequences` to read from `sequence_step_state` rather than reconstructing from `outreach_drafts.sent_at`.
- Add state-transition triggers (Section C.1, C.2, C.3) to outreach_drafts, contacts, companies.
- Remove the legacy `sent_at` column write from app code (the trigger from Phase 2 maintains it as a denorm cache from `send_attempts`).

**Same:** the dashboard UI; the user-facing flows.

**Compatibility:** triggers run alongside app code for 14 days in shadow mode (the trigger logs would-have-rejected violations to `workflow_events.transition='trigger_warn'` but allows the write). After 14 days clean, triggers are switched to enforcing.

**Schema changes:** additive triggers; one column drop (`sent_at` becomes generated/trigger-maintained).

**Cutover criteria:**

- 0 trigger violations during the 14-day shadow period;
- `outreach_drafts.sent_at` matches `(SELECT MIN(delivery_confirmed_at) FROM send_attempts WHERE draft_id = outreach_drafts.id AND state='DELIVERED')` for 100% of rows;
- Stage 2 F.6, F.7 queries return 0 rows (no sent drafts without engagement_sequences or interactions — handled by the post-send transaction in Phase 2).

**Rollback:** disable triggers; restore app-code state derivations.

**Observability:** dashboard panel "state machine violations (last 24h)."

**Complexity:** XL.

**Dependencies:** Phases 1–6.

**Strangler:** triggers in shadow mode for 14 days before enforcing.

---

## SECTION J — Immediate vs Deferred Work

### J.1 Immediate (before next send run)

Stage 3 Section 1 actions confirmed. The 8 actions:

1. Snapshot every at-risk table (Action 1.1) — S.
2. `SEND_ENABLED=false` in Railway env (Action 1.2) — S.
3. `outreach_send_config.send_enabled=false` per workspace (Action 1.3) — S.
4. Confirm Railway replica count = 1 (Action 1.4) — S.
5. Verify migration 045 columns are present (Action 1.5) — S.
6. Verify per-workspace `outreach_send_config.daily_limit` (Action 1.6) — S.
7. Disable operator scripts via rename (Action 1.7) — S.
8. Set `RESEND_WEBHOOK_SECRET` and `INSTANTLY_WEBHOOK_SECRET` in Railway env (Action 1.8) — S.

All confirmed; no additions.

### J.2 Short-term hardening (within 2 weeks, no rearchitecture)

| Item | Complexity | Risk if deferred one sprint | Blocks next tier? |
|---|---|---|---|
| Add UNIQUE on `outreach_drafts(workspace_id, contact_id, sequence_name, sequence_step)` for non-terminal states (partial index) | S | Duplicate drafts continue to slip in via the read-then-write dedup race | Yes — Phase 2 transactional semantics assume uniqueness |
| Add CHECK linking `approval_status` to `(approved_by IS NOT NULL AND reviewed_at IS NOT NULL)` | S | Unsigned approvals continue to be sendable under the fallback filter | Yes — Phase 3 ApprovalService assumes the constraint |
| Add UPDATE-blocking trigger on `(body, subject, sequence_name, sequence_step)` once `sent_at IS NOT NULL` | S | Operator scripts (if re-enabled) can corrupt audit | Yes |
| Single canonical Instantly webhook path (unmount the unused one) | S | Dual-mount means both paths active; risk of double-writes | No (but reduces noise) |
| Remove the duplicate `OutreachAgent` (delete `agents/outreach_agent.py`) | S | HTTP draft generation continues to bypass scheduler gates | Yes — Phase 5 needs one generator |
| Fix `db.update_company(allow_downgrade=False)` TypeError on spam complaint path | S | Spam complaints fail to update company status (Stage 2 risk 17) | No |
| Replace `?force=true` parameter with `override-request`/`audit` two-step endpoint | M | Quality + cap bypass remains a single query-string parameter | Yes — Phase 3 contract |
| Add audit logging for the column-write fallback in `approve_draft` (Stage 3 patch 10.2) | S | Invisible unsigned approvals continue | No |
| Add `webhook_event_log` table and route handlers through it for idempotency | M | Duplicate webhook events double-count opens/clicks (Stage 2 E.8) | Yes — Phase 4 |
| Disable legacy `EngagementAgent.process_webhook_event` fallback | S | Legacy bounce handling writes `companies.status='bounced'` contradicting tiered suppression | No |
| Add an env gate to HTTP `/api/outreach/generate*` endpoints until consolidated | S | HTTP draft path bypasses every gate | No (gate is a band-aid for Phase 5) |
| Rename `weekly_contact_backup` target from `/Volumes/...` to a Supabase Storage / S3 path (or delete) | S | No backup; we are operating without an automatic safety net | No |

### J.3 Medium-term refactors (2–8 weeks)

| Item | Complexity | Risk if deferred one sprint | Blocks next tier? |
|---|---|---|---|
| `send_attempts` table + dual-write | L | Failed rollback orphans drafts; concurrent send risk if replicas > 1 | Yes — Phase 7 state machine enforcement |
| `outbound_queue` transactional outbox | L | Non-transactional post-send fan-out continues; silent failures invisible | Yes — full Phase 2 |
| Single `ApprovalService` consolidating eight writers | L | Governance bypass surface area remains large | Yes — full Phase 3 |
| Move APScheduler to separate Railway `worker:` process with advisory lock | M | Multi-replica deploys remain risky; many jobs unsafe under concurrency | Yes — Phase 6 |
| Policy snapshots and binding each approval/send to a snapshot | M | Policy edits cannot be replayed; audit can't reconstruct the rule in force | Yes — Phase 5 (validator needs policy snapshot) |
| Adapter layer for Resend, Instantly, Gmail, Apollo, ZeroBounce | M | Provider-specific quirks scattered across agents; tests must mock SDK calls directly | No |
| Reconciliation job for state drift (Stage 2 F.5, F.6, F.7) | M | Stuck pipelines remain invisible | No |

### J.4 Full redesign elements (8–16 weeks)

| Item | Complexity | Risk if deferred one sprint | Blocks next tier? |
|---|---|---|---|
| Content integrity pipeline + evidence registry + claim grounding | XL | Fabricated claims continue to require regex blacklist enforcement; an LLM that learns to evade the blacklist sends false claims | Eventually — without it, every send risks brand harm |
| `draft_content_versions` + immutable body history | M | Body mutation by operator scripts continues to destroy audit | Yes for Phase 5 |
| Full state machine enforcement via DB triggers (Phase 7) | XL | Implicit state continues to drift; reconciliation is reactive rather than preventive | No — last phase |
| `workflow_events` as authoritative event store + replay capability | L | Recovery from data corruption remains impossible | No (but valuable) |
| `sequence_step_state` per-contact-per-step explicit state | M | Sequences continue to drop contacts on silent post-send failures | Yes for full Phase 7 |

### J.5 Explicitly not worth building yet

| Item | Why not |
|---|---|
| Kafka or any stream-processing platform | Current scale is < 1000 events/day. Postgres notify + outbox is simpler and sufficient for the next 12 months. |
| Microservices split (separate approval service / send service / webhook service as independent deployments) | Monolith deploys are still right for one team; the boundaries should be enforced in code (modules + DB roles), not network. The eventual split is straightforward once modules are clean. |
| Multi-tenant isolation redesign (separate database per tenant) | Current RLS is adequate; the cross-tenant risk in `process_webhook_event` (Stage 1 H tenant leak) is fixable by routing webhooks through the adapter layer that resolves workspace first. |
| Celery + Redis | Procfile `worker:` with advisory lock is enough at current scale. Migrate when send volume crosses 10k/day or scheduler ticks become contended. |
| Temporal | Workflows here are short-lived; the outbox table holds the state. Temporal pays off when workflows span hours/days with multiple manual steps; our approval workflow does span days but is sequential and durable in the DB. |
| Event sourcing as the primary state store (event-sourced CQRS) | The platform documented in the parent project is event-sourced; ProspectIQ is not, and converting it would be a multi-month rewrite for marginal benefit. `workflow_events` is an event LOG, not event sourcing. |
| Custom rules engine | The current YAML config plus policy snapshots is enough. Adding a Drools/CEP layer would let us encode richer rules but at the cost of debuggability and reviewability. |
| Real-time analytics dashboard | The cron-based daily/weekly reports plus the existing `interactions` projection are enough. Real-time requires a streaming layer we don't have. |
| Multi-region deployment | Single-region Supabase + Railway is fine. Latency to Resend/Apollo is the bottleneck, not multi-region. |
| Customer-facing API (B2B) | Current product is internal-facing; no third-party developers depend on the contract. Build when there is a paying customer who needs it. |
| ML-based reply classification beyond the existing Claude classifier | The Claude classifier works. A custom model would need training data we don't have at scale and would underperform Sonnet. |
| Self-service workspace onboarding (full multi-tenant SaaS) | We have one workspace. Generalize when there are 3+. |

---

## SECTION K — Final Recommendation

### K.1 The target architecture in one paragraph

ProspectIQ vNext is a monolithic Python application on Postgres with two processes: a FastAPI `web:` process serving the dashboard and APIs, and a separate `worker:` process running APScheduler under a postgres advisory-lock singleton. Every lifecycle state — for drafts, contacts, companies, sequences, send attempts, replies, and approvals — is an explicit column with a CHECK constraint and a state-transition trigger; every transition writes a row to an append-only `workflow_events` log. Approvals flow exclusively through a single `ApprovalService` that writes an immutable `approval_attestations` row, pinned to a `policy_snapshots` version and a `draft_content_versions` body version, inside one transaction that also inserts an `outbound_queue` row. The send worker consumes from `outbound_queue` via `SELECT FOR UPDATE SKIP LOCKED`, creates a `send_attempts` row, runs assertions, calls Resend, and updates `send_attempts` plus the projections in a second transaction; webhooks land in a `webhook_event_log` UNIQUE-keyed table that drops duplicates before any handler logic runs. Every external integration (Resend, Instantly, Gmail, Apollo, ZeroBounce) is accessed through an adapter exposing a single `OutboundProvider` interface; agents no longer call provider SDKs directly. Content claims live in a registry; the draft generator can only assert claims that exist in the registry; the validator rejects drafts that introduce unauthorized claims. The schema enforces lifecycle invariants; the service layer enforces business rules; the API layer enforces authentication; logs are for debugging and `workflow_events` is the audit truth.

### K.2 Recommended migration sequence

Execute strictly in the order Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7. The ordering is determined by data dependencies and risk:

1. **Phase 0 (stabilization)** must be in place before any architectural work — it is the safety baseline for the next send and provides the snapshots needed for any later cleanup.
2. **Phase 1 (schema hardening)** is purely additive and unblocks every subsequent phase. Its CHECK constraints make Phase 3's writer consolidation enforceable; its `workflow_events` table is the foundation for Phases 3–7 audit; its `webhook_event_log` is the prerequisite for Phase 4.
3. **Phase 2 (`send_attempts` + `outbound_queue`)** is the highest-impact structural change for delivery reliability. It cannot precede Phase 1 (needs `workflow_events`) and must precede Phase 3 (ApprovalService's same-transaction outbox insert).
4. **Phase 3 (governance consolidation)** reduces the governance bypass surface to one writer. Must follow Phase 2 because the same-transaction enqueue depends on the outbox.
5. **Phase 4 (webhook normalization)** is independent of Phase 3 but small enough to ride alongside it. Run after Phase 1's `webhook_event_log` is in place. Order between 3 and 4 is flexible; doing 4 first reduces noise during Phase 3 testing.
6. **Phase 5 (content integrity)** is the second-largest cultural change and depends on Phase 3's attestation flow. It also has the longest cutover (14-day shadow validator). Schedule once Phase 3 is steady.
7. **Phase 6 (worker process)** is independent of 1–5 and can be slotted at any quiet moment. Doing it after Phases 2 and 3 is preferred because the new tables make rollback easier.
8. **Phase 7 (full state machine enforcement)** is the consolidation phase; it requires all prior phases.

Estimated calendar time: Phase 0–4 in 6–8 weeks; Phase 5 adds 6–8 weeks; Phases 6–7 add 4–6 weeks. Total ~16–22 weeks of focused engineering with current team size.

### K.3 Three highest-risk current architectural weaknesses (ranked)

1. **`sent_at` overloaded as both claim and delivery indicator with no transactional boundary across assertions and Resend dispatch.** Stage 1 H + Stage 2 F.4–F.7. A failed rollback orphans drafts forever; a successful claim followed by a failed projection write silently drops a contact from the sequence. Highest-impact single weakness because it directly damages deliverability metrics and trust in the dashboard.

2. **Eight independent writers to `approval_status='approved'`, schema-permitted unsigned approvals.** Stage 2 C. Governance is only as strong as the weakest writer; today seven of the eight skip at least one gate. Combined with the existence of operator scripts that mutate `body` in-place (Stage 2 G.1, G.2), the audit trail is corrupted whenever a script runs.

3. **In-process APScheduler with no singleton guard, mounted in every API replica, with 22 of 23 jobs unsafe under concurrency.** Stage 2 B.2, B.3. The only thing currently preventing duplicate sends, duplicate Anthropic spend, duplicate FDA scrapes, and duplicate webhook double-counting is the operational discipline of keeping Railway replicas at 1 — a discipline enforced by no code, no env, no alert.

### K.4 Three most important simplifications (remove, don't improve)

1. **Delete `backend/app/agents/outreach_agent.py` (the second `OutreachAgent`).** It bypasses every scheduler-side gate, uses a different model router, and writes drafts under a different `sequence_name` namespace that defeats the existing dedup. The HTTP path can be served by the same generator core the scheduler uses; the second class adds risk with no benefit.

2. **Delete `scripts/pending_draft_reconciliation.py` and `scripts/rejected_draft_reassessment.py`.** They are responsible for `body` mutation, `approved_by="avanish"` literal, and silent reviewer-cap bypass. Replace with thin CLI clients that invoke the approval endpoint with an operator JWT. The substantive logic — content-fix regex, classification — belongs in the `ApprovalService` and the generator validator, not in standalone scripts.

3. **Delete `EngagementAgent.process_webhook_event` (the static method) and `pace_limiter.PaceLimiter`.** Both are dead-but-reachable code. The legacy webhook handler writes `companies.status='bounced'` contradicting tiered suppression; the pace limiter is a third "daily cap" source no one reads. Removing them eliminates two persistent confusion sources without changing observable behavior.

### K.5 Three biggest operational wins available with the least engineering effort

1. **Apply the UNIQUE constraint on `outreach_drafts(workspace_id, contact_id, sequence_name, sequence_step)` for non-terminal states (~ 1 SQL line).** Eliminates the duplicate-draft race that Stage 1 H concurrency #3 documents. Reduces reviewer queue noise immediately; prevents `_run_jit_pregenerate` from racing against itself or `draft_generation`.

2. **Add the immutability trigger on `(body, subject)` for `sent_at IS NOT NULL` (~ 10 SQL lines).** Closes the audit-trail hole that operator scripts have been exploiting. Reversible if it misfires (`DROP TRIGGER`). Provides forensic-grade body preservation for sent emails immediately.

3. **Move APScheduler into a separate `worker:` Procfile process with a postgres advisory lock (~ 50 lines of code, 1 Procfile line).** Eliminates the multi-replica risk for every scheduler job in one change. Unlocks the ability to scale the API tier independently. The hardest part is the operational coordination of the deploy (do it during a no-send window); the code is small.

### K.6 Three biggest risks of overengineering (do not build)

1. **Microservices split.** Splitting ApprovalService, SendWorker, WebhookService, and DraftGenerator into separate deployments would require network boundaries, service discovery, cross-service auth, and distributed tracing — and would replace the single Postgres transaction (Section E.2's atomicity) with eventual consistency between services. The current monolith with module boundaries enforced by Postgres roles achieves the same governance with one tenth the operational surface area.

2. **Event-sourced rewrite using a stream platform (Kafka/Kinesis).** ProspectIQ is event-LOGGED, not event-sourced; `workflow_events` (Section D.2) is an audit trail, not the source of truth. Converting to true event sourcing would mean rebuilding every projection (`outreach_drafts`, `contacts`, `companies`) as a CQRS read model from the event stream — a multi-month effort with no observable benefit at current scale. Keep `workflow_events` as an append-only log; keep the projections in normal tables.

3. **Custom workflow engine (Temporal, Airflow, custom DSL) for the send/approval flow.** The send flow is sequential, short-lived, and durable in the DB via the outbox pattern. Temporal pays off when workflows span hours with multiple manual checkpoints, branching, and long-running activities; ours have one branch (assertion pass/fail), one external call (Resend), and one outcome (delivery). Adding a workflow engine to manage these adds learning curve, new failure modes, and operational responsibility without simplifying anything. Keep the outbox table and a simple polling worker; revisit only if multiple workflow patterns emerge and the outbox starts being cargo-culted into every new feature.


---
# Stage 5: Autonomous Engine Design
- Date: 2026-05-14
- Status: DESIGN — not yet implemented
- Owner: Avanish Mehrotra
- Governing principle: ProspectIQ is an autonomous execution engine with enforced human approval checkpoints, not a human-operated queue with scattered automations.

The system today treats human approval as the default path for every draft. Stage 1–4 documented why this fails: eight writers to `approval_status='approved'`, attestation that "isn't enforced as a hard gate", a `?force=true` query parameter that bypasses quality and cap, scripts that mutate `body` and write `approved_by='avanish'` as a literal string. Adding more human checkpoints on top of that does not increase safety — it increases the number of paths through which an unsafe draft can be sent without any human ever seeing it.

The corrected posture: most actions are autonomous, gated by enforceable invariants, with humans pulled in only where their judgment is structurally required (positive replies, overrides, high-risk content, ambiguous suppression signals). Every autonomous action is auditable, reversible, and bounded by hard policy limits.

---

## SECTION A — Autonomous Operating Model

For each of the 16 workflows: classification, rationale, guardrails, escalation trigger, current state (file/line), target state.

### A.1 prospect_ingestion — adding contacts/companies to the DB from Apollo or import

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Adding rows to `companies`/`contacts` is structurally low-risk — these are inputs, not outputs. Stage 1 D and Stage 4 C.2 confirm the system already has clean enrichment/eligibility state machines. The risk is volume (burning Apollo credits) and tenant leak (Stage 1 H, `process_webhook_event` cross-tenant query), not correctness of any single ingest.

**Guardrails:**
- Daily Apollo credit consumption capped per workspace via `provider_state.apollo_daily_calls` policy snapshot value.
- Bulk imports > 100 rows require operator initiation; CSV import requires `import_attestation` (operator's named identity, source file hash, row count).
- Tenant scoping: every insert resolves `workspace_id` from the import session, not from row contents.
- Title-classifier prefilter runs synchronously; `is_outreach_eligible` is set at insert time.

**Escalation trigger:** Apollo credit balance falls below `apollo_min_buffer` (currently 2000); per-source duplicate rate exceeds 25% in a single batch (signals a stale list); company name fuzzy-match collides with > 5 existing rows (signals a sloppy import).

**Current state:** `backend/app/agents/discovery.py`, `backend/app/agents/enrichment.py`, scheduler jobs `intent_refresh` and `qualification` run autonomously. Imports via `scripts/import_instantly_leadfinder.py`, `scripts/seed_fb_named_companies.py` are operator-initiated. No DB-level tenant guard on inserts (Stage 1 H tenant leak applies to webhook resolution, not ingest).

**Target state:** Same autonomy, with a `provider_state` table tracking per-day Apollo/Anthropic/ZeroBounce spend; ingest jobs read this table before each batch and halt if over budget. Bulk import endpoint `POST /api/imports` requires an attestation payload before any row is written, and writes a `workflow_events` row of type `bulk_import_started`.

---

### A.2 enrichment — populating contact/company fields from Apollo

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Enrichment is a pure read-from-Apollo / write-to-local-DB operation with no outbound impact. Stage 1 F.Apollo noted unbounded `_enrich_cache`; Stage 4 G.5 corrects this with a bounded `TTLCache`. The cost surface is the main risk (real dollars, not safety).

**Guardrails:**
- Per-contact: skip if `apollo_enriched_at > NOW() - INTERVAL '30 days'` (idempotency).
- Per-day quota: `provider_state.apollo_daily_calls` policy cap; halt and emit `provider_quota_reached` event when crossed.
- Per-workspace monthly cap from `policy_snapshot.payload.spend.workspace_monthly_default_usd`.
- Result quality check: if Apollo returns a payload with `confidence='low'` or missing email/title, mark `enrichment_state='ENRICHMENT_PARTIAL'` and do not promote to `ENRICHED`.

**Escalation trigger:** Apollo 5xx rate > 10% over 1h (provider outage); workspace monthly spend > 80% of cap; ZeroBounce verification fail rate > 50% on Apollo-enriched emails (indicates Apollo data quality regression — operator decides whether to keep enriching).

**Current state:** `backend/app/agents/enrichment.py` runs autonomously when `agents.enrichment.enabled=true` in `limits.yaml`. Currently frozen (`enabled: false`) per Stage 1 G. Class-level cache in `ApolloClient._enrich_cache` (Stage 1 F.Apollo) — never evicts.

**Target state:** TTL+LRU cache (Stage 4 G.5). Per-day quota counter in `provider_state`. Enrichment-failed contacts written to `contacts.lifecycle_state='ENRICHMENT_FAILED'` (Stage 4 C.2) with a retry policy of one re-attempt after 30 days.

---

### A.3 qualification — PQS scoring + LLM qualification

**Classification:** FULLY_AUTONOMOUS

**Rationale:** PQS is a deterministic computation over enriched fields; the LLM qualifier is a Claude call against `research_intelligence` returning a structured verdict. Both are idempotent (same input → same output) and have no direct outbound impact. Stage 1 D scheduler inventory and Stage 1 F.Anthropic confirm the pattern. No human judgment improves the score.

**Guardrails:** None at action level — qualifying a contact has no external effect. Cost is tracked via `api_costs` and capped by the workspace monthly budget.

**Escalation trigger:** Sustained 5xx from Anthropic > 15 min (provider outage); qualification verdict distribution swings > 30% week-over-week (indicates model regression or feature drift — operator reviews next batch).

**Current state:** `backend/app/agents/qualification.py` + `backend/app/agents/llm_qualification.py`. Scheduler `qualification` job runs every 15 min. Already fully autonomous; writes `companies.{pqs_*, status}`.

**Target state:** Unchanged operationally. Cost tracking moves under `provider_state`; verdicts emit `workflow_events.transition='company_qualified'|'company_disqualified'`.

---

### A.4 research_refresh — re-running Perplexity/Claude research on companies

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Research is expensive (~$0.10–0.30 per company per refresh per Stage 1 G `spend.research_cap_usd: $93/month`). Same write pattern as enrichment — populates `research_intelligence`. The risk is cost, not correctness.

**Guardrails:**
- Skip if `research_intelligence.updated_at > NOW() - INTERVAL '14 days'` unless `force_refresh=true`.
- Hard cap: `policy_snapshot.payload.spend.research_hard_limit_usd` ($135 currently).
- Refresh only companies in `OUTREACH_ACTIVE` or `ACTIVE_CONVERSATION` (the ones it pays to keep current) and tier-1 candidates.
- Batch size: 10 companies per scheduler tick.

**Escalation trigger:** Per-week research spend tracking > 90% of `research_cap_usd`; Perplexity API consecutive failures > 5.

**Current state:** `backend/app/agents/signal_monitor.py` runs Sunday 6am for tracked companies. `backend/app/agents/research.py` is gated off by default. Research stays paused in production (Stage 1 G `agents` block doesn't list research). Currently triggered manually via `scripts/run_research.py`.

**Target state:** Scheduler `research_refresh` runs daily, picks top 10 stale OUTREACH_ACTIVE companies; `provider_state.research_daily_spend` tracks cumulative cost and short-circuits over budget.

---

### A.5 draft_generation — generating outreach email drafts via LLM

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** The generator should produce drafts continuously and unattended; the gate is the validator and the approval queue, not the generation itself. Stage 1 H found three failure modes here: HTTP-path generator bypassing all gates (`agents/outreach_agent.py`), `outreach_outcomes` written at draft-gen pretending the email shipped, and the integrity regex as the only content gate. Generation autonomy is fine; the surrounding controls are what need work.

**Guardrails:**
- Single `DraftGenerator` (Stage 4 H.2) — the HTTP path and the scheduler path share one code module and one set of gates.
- Every generated draft passes through the 4-pass validator (Section H.3 below) before insert; HARD_REJECT drafts are not persisted as `QUEUED`.
- Only `content_claims`-registered statistics may appear in the body.
- `outreach_outcomes` is no longer written at draft-gen (Stage 4 A.3 deprecation); written only on confirmed send.
- Cost per workspace tracked; halt generation when daily Anthropic spend exceeds `policy_snapshot.payload.spend.workspace_monthly_default_usd / 30`.

**Escalation trigger:** > 20% of new drafts are HARD_REJECT in a 24h window (prompt regression — operator reviews and adjusts); > 30% of new drafts hit QUARANTINE (claim coverage gap — content team adds claims).

**Current state:** `backend/app/agents/outreach.py` (scheduler, full gates) and `backend/app/agents/outreach_agent.py` (HTTP, no gates). Stage 1 H GOVERNANCE BYPASS RISK #5. Scheduler `draft_generation` job every 5 min.

**Target state:** Single `DraftGenerator` module; both entry points use it. Generation continues every 5 min. Per Stage 4 I Phase 5, the validator runs in shadow mode for 14 days before enforcing.

---

### A.6 content_validation — checking generated content for claims, tone, integrity

**Classification:** FULLY_AUTONOMOUS

**Rationale:** The validator is a deterministic rule engine + a Claude classifier pass. It produces a per-draft verdict; no humans are needed in the loop unless the verdict is ambiguous (in which case the draft is quarantined and the human handles it as part of approval, not as part of validation). Stage 4 H.3 specifies four passes; their outcomes are mechanical.

**Guardrails:** Each pass produces an evidence row in `workflow_events.transition='draft_validated'` with the sub-scores. Validator version is pinned in `policy_snapshots` so re-running a validation yields the same result.

**Escalation trigger:** None — the validator's job is to escalate (to human approval) when its own confidence is below threshold.

**Current state:** `backend/app/agents/outreach.py` runs the integrity regex (`_INTEGRITY_RULES`, ~line 966) inline before draft persistence. `backend/app/core/draft_quality.py::validate_draft` runs from the approve endpoint. No grounding against an evidence registry.

**Target state:** New `ContentValidator` module called from `DraftGenerator.persist()` before INSERT (Stage 4 H.3). Hard-reject patterns: URL-in-step-1, bare percentages without claim coverage, banned phrases, banned characters. Warn-and-quarantine patterns: vague client references, unsubstantiated outcomes. Pass: claim-grounded, registered.

---

### A.7 draft_approval — authorizing a draft to enter the send queue

**Classification:** AUTONOMOUS_WITH_GUARDRAILS for LOW-RISK drafts; HUMAN_APPROVAL_REQUIRED for everything else.

**Rationale:** This is the single most important classification in the whole engine. Stage 1 H GOVERNANCE BYPASS RISK and Stage 2 C show that requiring human approval for every draft has produced eight bypass paths — the volume forces shortcuts. Routing low-risk drafts to autonomous approval frees reviewers to spend time on the ones where their judgment matters.

**Guardrails (when autonomous):**
- All four content validator passes PASS.
- Risk score in LOW bucket (Section B).
- Step ≤ 2.
- No sibling traction signal (Section A.13).
- Sender has > 100 successful sends with bounce rate < 1% in past 30 days (sender reputation hurdle).
- All 7 send-eligibility gates (Section C) pre-pass at approval time.

**Escalation trigger:** Risk score MEDIUM or HIGH; any content validator QUARANTINE; manual edits after generation; first use of a new sequence/template; sender reputation degradation.

**Current state:** `backend/app/api/routes/approvals.py::approve_draft` is the only path that runs the full gate. Seven other paths bypass at least one gate (Stage 2 C). `?force=true` bypasses quality and cap.

**Target state:** Single `ApprovalService.approve()` (Stage 4 E.2); writes `approval_attestations` row inside the same DB transaction as the `outbound_queue` insert (Stage 4 F.2). Low-risk drafts can be approved with `actor_type='system'` after passing all validators; medium/high go to the human queue. `?force=true` replaced by override two-step (`request_override` + `audit_override`).

---

### A.8 send_execution — dispatching an approved draft via Resend

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Dispatch is mechanical. Stage 1 H concurrency risk + Stage 2 F.4–F.7 show the failures aren't about WHO sends but about HOW the send transaction is structured. With the outbound queue + send_attempts model (Stage 4 D.1, D.9) the worker dispatches autonomously and a human is only involved when retries are exhausted (dead letter).

**Guardrails:**
- Layer 1–7 gate stack (Section C) runs at claim time, not generation time.
- Per-sender daily cap from policy snapshot.
- Workspace daily cap.
- Bounce-rate gate (system-wide).
- Worker singleton (advisory lock).
- Outbound queue lease (`claim_expires_at`) prevents zombie claims.

**Escalation trigger:** Three consecutive retries fail (dead-letter); bounce-rate gate fires (workspace-wide alert); Resend health check fails (provider outage); dead-letter queue depth > 10 (operator dashboard alert).

**Current state:** `backend/app/agents/engagement.py::_send_approved_drafts` (lines 540–887). Compare-and-swap on `sent_at`; 6+ non-transactional post-send writes.

**Target state:** Worker in separate Procfile process (Stage 4 F.1), pg_advisory_lock on startup, polls `outbound_queue` via `SELECT FOR UPDATE SKIP LOCKED`, writes `send_attempts` rows for each phase, projects to `interactions` in a second transaction after Resend returns.

---

### A.9 follow_up_generation — generating step-2+ drafts after step-1 sent with no reply

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Same as draft_generation but with the additional context that step-1 was sent and acknowledged at the provider. Stage 1 D (`_run_jit_pregenerate` JIT, `_process_due_sequences` hourly) already runs this autonomously today; the failure surface is the implicit step-state derivation (Stage 4 A.4 #7) and the lack of step-state transactional safety.

**Guardrails:**
- `sequence_step_state` row for step N-1 must be in `DRAFT_SENT` state (explicit, not derived from `outreach_drafts.sent_at`).
- Minimum step gap satisfied (3 days for step 2, 2 days for step 3+; from policy snapshot, not module constants).
- No reply received on prior step (the existence of an inbound reply pauses the sequence — Section A.12).
- No sibling positive reply at the company (Section A.13).
- Contact not suppressed.

**Escalation trigger:** Step gap calculation returns negative or > 30 days (data integrity warning); attempt to generate step N when step N-1's `send_attempts` row is in `DISPATCH_FAILED_TERMINAL` (sequence is broken; operator reviews).

**Current state:** `_run_jit_pregenerate` 24h, `_process_due_sequences` 1h. Both call `OutreachAgent.run` with sequence context. Step state is reconstructed from `outreach_drafts.sent_at` per Stage 4 A.4 #7.

**Target state:** Worker reads `sequence_step_state` directly. Step N draft generation reads `sequence_step_state WHERE step_number=N-1 AND state='DRAFT_SENT'`. After draft generation, the `sequence_step_state` row for step N moves from `PENDING` to `DRAFT_GENERATED`.

---

### A.10 reply_classification — parsing and classifying inbound replies

**Classification:** AUTONOMOUS_WITH_GUARDRAILS for clear classifications; HUMAN_ESCALATION_REQUIRED for ambiguous or positive.

**Rationale:** Reply classification is the place where every dollar of pipeline lives. Auto-actioning a positive reply (e.g., archiving it) without human review is the worst possible failure mode of an autonomous system. Auto-actioning a clear bounce or unsubscribe is the highest-leverage win — these accumulate as queue noise today.

**Guardrails (autonomous path for clear classifications):**
- Classifier confidence > 0.85 AND classification ∈ {`bounce`, `auto_reply_ooo`, `auto_reply_no_longer_here`, `unsubscribe`}.
- Suppression action is bounded: `auto_reply_no_longer_here` marks contact `SUPPRESSED_DEPARTED` but does NOT suppress the company.
- All actions write `workflow_events.transition='reply_classified'` with classifier version, confidence, classification, action taken.

**Escalation trigger:** Confidence ≤ 0.85; classification ∈ {`positive`, `question`, `negative`, `other`}; the same inbound thread generates conflicting classifications within 1 hour (parser instability).

**Current state:** `backend/app/agents/reply.py::ReplyAgent`, `backend/app/agents/reply_classifier.py::ReplyClassifier`, `backend/app/api/routes/webhooks.py::_handle_email_reply`. Classifier failures fall back to `intent='other', auto_actionable=False` (Stage 1 H silent failure risk #4). All replies go to HITL queue.

**Target state:** Same classifier; clear cases (bounce/unsubscribe/auto-reply) auto-action with the actions in the guardrails. Positive/question/negative replies go to HITL with the full thread context. Confidence threshold tunable via policy snapshot.

---

### A.11 suppression — applying bounce, unsubscribe, complaint, departed signals

**Classification:** FULLY_AUTONOMOUS for system-generated (bounce, unsubscribe, complaint, departed); HUMAN_APPROVAL_REQUIRED for `manual_dnc` / operator-initiated company-level suppression.

**Rationale:** System-generated suppression signals are unambiguous and reversing them is auditable. Operator-initiated DNC is rare and has high cross-company impact (e.g., suppressing a parent company); it deserves a confirmation step.

**Guardrails (autonomous):**
- Tiered suppression (Stage 1 G migration 048) — contact scope first; escalate to company scope only when `COMPANY_ESCALATION_BOUNCE_COUNT=2` distinct contacts bounce.
- Single writer (`SuppressionService` — Stage 4 B.1), replacing the three writers in Stage 1 H DATA INTEGRITY RISK.
- Webhook idempotency (Section C webhook_event_deduplication) prevents replay double-suppression.

**Escalation trigger:** Suppression decision conflicts with a recent positive reply (replied yesterday, bounced today — operator decides); company-level escalation triggered by < 2 distinct contacts (data drift in the count); legal-flagged suppressions (GDPR/CCPA delete requests — operator confirms).

**Current state:** Three writers to `contacts.status='bounced'` (webhooks.py, bounce_suppressor, legacy engagement.process_webhook_event) — Stage 1 H DATA INTEGRITY RISK. `suppression_log` (migration 048) is the new path but legacy paths still write directly.

**Target state:** Single `SuppressionService.suppress(scope, reason, contact_id, company_id, source)` writes `suppression_events` row (Section E.5) and updates `contacts.lifecycle_state` in one transaction. Three legacy writers deleted (Stage 4 A.3 deprecation).

---

### A.12 sequence_pausing_resuming — holding or restarting an active outreach sequence

**Classification:** FULLY_AUTONOMOUS for system-triggered pauses (reply received, bounce, suppression); HUMAN_APPROVAL_REQUIRED for resume after positive-reply pause; FORBIDDEN_WITHOUT_OVERRIDE for resume after unsubscribe.

**Rationale:** Pausing on signal is safe — it errs on the side of not sending. Resuming requires judgment: did the conversation conclude, or is there genuine intent to continue? The system can't infer this reliably.

**Guardrails:**
- Pause action: write `sequence_step_state.state='STEP_BLOCKED'` for all future steps; `engagement_sequences.lifecycle_state='PAUSED'`. Notify owner.
- Resume from pause requires explicit operator action through the HITL queue (the contact card in HITL has a "resume sequence" button).
- After 30 days paused with no human action, the sequence auto-moves to `ABANDONED` (no further sends; preserved for audit). Owner notified.

**Escalation trigger:** Sequence has been `PAUSED` > 90 days without human action (data hygiene — auto-archive instead of indefinitely paused).

**Current state:** Pausing is implicit — reply classification writes to `hitl_queue` but doesn't update `engagement_sequences.status`. The next scheduled step still tries to generate; relies on suppression check to block.

**Target state:** Explicit pause via `SequenceOrchestrator.pause(reason, triggered_by)`. Writes `engagement_sequences.lifecycle_state='PAUSED'`, updates all future `sequence_step_state` rows to `STEP_BLOCKED`. Resume via `SequenceOrchestrator.resume(operator_id, reason)`.

---

### A.13 sibling_contact_outreach — reaching a second contact at a company where another contact is active

**Classification:** AUTONOMOUS_WITH_GUARDRAILS when no traction on sibling; HUMAN_APPROVAL_REQUIRED when sibling has shown traction.

**Rationale:** This is the case Stage 2 SQL query F.10 detects (company traction with sibling pending). Sending to a second contact while the first has positive engagement risks duplicating effort and looking spammy. Sending to a second contact while the first has just been sent (no engagement yet) is sound multi-stakeholder coverage.

**Guardrails:**
- Stage 4 C.3 `company_outreach_locks` table — a 5-business-day lock around any outbound send blocks any other sibling send.
- After the lock expires: if no traction signal at the company (no opens/clicks/replies from any sibling), proceed autonomously.
- If any sibling has opened/clicked/replied within 30 days, route to human review with the sibling's engagement summary attached.

**Escalation trigger:** Company in `ACTIVE_CONVERSATION` state (`contacts.lifecycle_state='RESPONDED'` on any sibling) — no autonomous siblings at all; human approves explicitly.

**Current state:** `backend/app/core/channel_coordinator.py::is_company_locked` enforces the 5-business-day lock. `get_company_traction()` returns traction signals but the approval queue uses it only as an advisory display — siblings can still be auto-approved by other paths.

**Target state:** Risk-score dimension `traction_signal` (Section B.1) drives routing; siblings of contacts with replies go to `HIGH` risk and HITL.

---

### A.14 company_traction_detection — detecting that a company has shown engagement signals

**Classification:** FULLY_AUTONOMOUS

**Rationale:** Detection is observation — counting opens, clicks, replies and applying a rule. No action follows directly from detection; the detection result feeds into other classifications (sibling outreach, sequence pause, reporting).

**Guardrails:** Computed in real time from `interactions` and `webhook_event_log` (after Stage 4 D.5). Materialized as `company_traction` view refreshed on every webhook ingest.

**Escalation trigger:** None — this is pure read-side derivation.

**Current state:** `channel_coordinator.get_company_traction()` computes on demand. Same logic re-implemented in dashboards. No materialization.

**Target state:** `company_traction_state` projection table maintained by the same transaction that processes the webhook event. Read-only for everything else.

---

### A.15 re_engagement — restarting outreach to a contact after 90+ day cooldown

**Classification:** AUTONOMOUS_WITH_GUARDRAILS

**Rationale:** Re-engagement is regenerating a sequence for a previously-cold contact after a long break. It's safe when (a) the original suppression has expired (90-day cooldown per `suppression.SEQUENCE_COOLDOWN_DAYS`) and (b) no fresh negative signal has surfaced. Autonomous restart respects the same drafting/approval gates as a fresh sequence.

**Guardrails:**
- Original sequence completed `> 90 days ago` (not the contact's last touch — the sequence's `completed_at`).
- No `suppression_events` row for this contact, period.
- No fresh negative signal (`reply_sentiment` IN ('not_interested', 'unsubscribed', 'auto_reply')).
- ICP still matches current `icp.yaml` (re-qualified).
- Generates as a fresh sequence with step counter reset to 1; not a step-N+1 of the original sequence.

**Escalation trigger:** Contact has churned title (no longer in target persona); company has churned NAICS classification; contact has been added to multiple suppression events for related domains since cooldown started.

**Current state:** `backend/app/agents/reengagement.py::ReengagementAgent` runs Sunday 8am. Re-queues by setting `companies.status='qualified'` and writing an interactions note. The actual re-draft happens at the next scheduler tick.

**Target state:** Reengagement creates a new `engagement_sequences` row with `lifecycle_state='SCHEDULED'` and `sequence_step_state` rows. The first draft is generated and goes through the standard approval path (autonomous if low-risk).

---

### A.16 reporting_and_alerts — daily/weekly reports, bounce alerts, queue health

**Classification:** FULLY_AUTONOMOUS

**Rationale:** Read-only summaries with no action attached. The alerts themselves can fire autonomously; what they prompt (operator response) is out of scope for the engine.

**Guardrails:** None at action level. Reports never mutate operational state.

**Escalation trigger:** Reporting job itself fails > 3 times consecutively (operator notified via separate channel that reporting is broken).

**Current state:** Scheduler jobs `daily_report`, `weekly_post_send_audit`, `weekly_approval_audit`, `weekly_cost_summary`. All autonomous; send via Resend.

**Target state:** Unchanged. Reports query `workflow_events` and projection tables; no scheduler-level changes. Add a `reconcile_pipeline_state` job (Section F.5) producing the operator's daily drift dashboard.

---

## SECTION B — Risk-Based Human-in-the-Loop Design

### B.1 Risk Dimensions

Each dimension feeds the final score. Weights sum to 100. The score is a 0–100 number where 0 is safest and 100 is highest risk.

| # | Dimension | How measured | LOW threshold | MEDIUM threshold | HIGH threshold | Weight |
|---|---|---|---|---|---|---|
| 1 | `sequence_step` | `outreach_drafts.sequence_step` | 1 | 2 | 3+ | 8 |
| 2 | `account_tier` | `companies.engagement_tier` (migration 045) — pmfg1/pmfg2/pmfg3 | pmfg3 | pmfg2 | pmfg1 | 12 |
| 3 | `prospect_seniority` | `contacts.seniority` | Director | Manager / VP | C-suite / Owner / Founder / Partner | 8 |
| 4 | `company_size` | `companies.employee_count` | < 200 | 200–1000 | > 1000 (high-visibility brand) | 5 |
| 5 | `prior_engagement` | aggregated `interactions` counts past 30d | 0 opens/clicks | 1–2 opens, 0 clicks | clicks ≥ 1 or any reply | 8 |
| 6 | `traction_signal` | `get_company_traction(company_id, exclude_contact_id)` | no traction on siblings | any sibling open/click | any sibling reply | 12 |
| 7 | `suppression_ambiguity` | `contacts.suppression_reason` IS NULL or stale flag | clean | one stale flag (open with `auto_reply_retired`) | conflicting signals (recent bounce + recent open) | 8 |
| 8 | `unverifiable_claims_detected` | validator pass 3 result | 0 quarantines | 1 WARN-AND-QUARANTINE | any HARD-REJECT | 10 |
| 9 | `fabricated_statistic_risk` | bare `\d+%` not covered by registered claim | none | one borderline match | matches with no claim coverage | 8 |
| 10 | `sender_reputation_risk` | 7-day bounce rate for `sender_email` | < 0.5% | 0.5–1.5% | ≥ 1.5% | 8 |
| 11 | `domain_bounce_risk` | prior bounces on `contact.email` domain | 0 prior bounces | 1 bounce, > 30d ago | ≥ 2 bounces or any in last 30d | 5 |
| 12 | `policy_override_in_use` | `approval_attestations.is_override` for any related approval | none | force-approved sibling within 7d | this draft was force-approved | 3 |
| 13 | `new_sequence_type` | sequence_name × account_tier combo never sent before | sent > 100 times | sent 10–100 times | sent < 10 times (first-use) | 5 |
| 14 | `new_content_template` | `draft_content_versions.generation_metadata.template_id` use count | > 50 times | 10–50 times | first 10 uses | 3 |
| 15 | `manual_edit_after_approval` | `outreach_drafts.edited_body_version_id` differs from approved version | no edit post-approval | edit < 5 % of length | edit ≥ 5 % of length or claim phrasing changed | 3 |
| 16 | `provider_inconsistency` | `send_attempts` vs `interactions` drift for this contact | match | minor (< 1 minute timestamp drift) | major (missing rows in either side) | 2 |

**Score computation:** `score = sum(dimension_value × weight)` where dimension_value ∈ {0, 0.5, 1.0} for LOW/MEDIUM/HIGH. Max possible score = 108 (over 100 because the HIGH thresholds compound); clamp to 100.

### B.2 Risk Buckets and Routing

| Bucket | Score range | Routing | Required guardrail passes | SLA |
|---|---|---|---|---|
| **LOW** | 0–20 | Auto-approve (`actor_type='system'` writes `approval_attestations`) | All 4 validator passes PASS; all 7 gate layers (Section C) pre-pass at approval; sender reputation healthy; step ≤ 2; no sibling traction | Immediate enqueue (same transaction) |
| **MEDIUM** | 21–50 | Human review queue, standard SLA | Validator passes 1–3 PASS; sender reputation healthy | 4 business hours |
| **HIGH** | 51–80 | Human review queue, prioritized; tier-1 companies require **dual review** | Validator passes 1–3 PASS or QUARANTINE | 1 business hour |
| **BLOCKED** | 81–100 | Dead-letter; operator alert; requires explicit override | N/A | No SLA — held until override |

Implementation: routing decision is part of `ApprovalService.intake(draft_id)`. The intake runs the validator, computes the score, writes `risk_scores` row (Section E.2), and either:
- LOW → calls `approve_as_system(draft_id, risk_score_row_id)`.
- MEDIUM/HIGH → leaves `outreach_drafts.lifecycle_state='QUEUED'` (or `UNDER_REVIEW` if a reviewer opens it).
- BLOCKED → writes `outreach_drafts.lifecycle_state='QUARANTINED'` and inserts into `dead_letter_queue` (Section E.4).

### B.3 Override Workflow

**Who can override:**
- `BLOCKED` overrides require role `admin` AND a second user with role `admin` or `super_admin` for the audit step. Two distinct human identities, full stop.
- `HIGH` risk dual-review requires two `member`-or-above reviewers; same-person second-approval rejected.

**Audit record:**
- Override creates `approval_attestations` row with `is_override=true`, `override_reason` (required text), `override_audited_by` (the second user's UUID), `override_audited_at`.
- Two `workflow_events` rows: `transition='override_requested'` (when reviewer #1 requests it) and `transition='override_audited'` (when reviewer #2 audits it).
- `risk_scores.bucket` is preserved as `BLOCKED`; the override does NOT rewrite the risk score — it records that the score was acknowledged and overridden.

**Notifications:**
- Slack to `notifications.workspace_owner_email` (currently `avi@digitillis.io`) on every override request AND every audit decision.
- Daily digest to all `admin`-role users summarizing overrides issued, who requested, who audited, dispositions.

**Override expiry:**
- An approved override is valid for that single draft only. There is no "permanent override" for a contact, company, or sequence.
- A request that has not been audited within 24 hours auto-expires; the draft remains in `QUARANTINED`. Reviewer #1 can re-request.

**Justification:**
- `override_reason` is a TEXT NOT NULL on the attestation when `is_override=true` (Section E + Stage 4 D.3 CHECK).
- Free-form text is required; no dropdowns. Audit log search is full-text indexed.

---

## SECTION C — Automation Safety Gates

The gate stack runs in strict order at every send attempt. A failure at any layer halts the dispatch and routes to the appropriate disposition (retry, dead-letter, suppression-action). Every gate emits a structured event into `workflow_events` so the audit trail is queryable.

```
+-----------------------------------------------------------------------+
| Layer 1: Schema constraints                                           |
|  enforced by Postgres — cannot be bypassed by application code        |
|  - CHECK lifecycle_state ∈ valid set                                  |
|  - CHECK approval_status='approved' ⇒ approval_attestation_id NOT NULL|
|  - UNIQUE (workspace, contact, sequence_name, step) non-terminal      |
|  - UNIQUE (provider, event_id) on webhook_events                      |
|  - Trigger: body immutability post-approval                           |
|  - Trigger: state-transition guard                                    |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 2: Suppression gate                                             |
|  single function suppression_service.is_eligible(contact_id, ...)     |
|  checked before any send path                                         |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 3: Policy gate                                                  |
|  - Workspace daily cap, sender daily cap                              |
|  - Company cooldown, step gap                                         |
|  - Send-window time-of-day                                            |
|  - Workspace send_enabled                                             |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 4: Content integrity gate                                       |
|  - Validator HARD_REJECT patterns                                     |
|  - Claim grounding (claim_ids referenced exist and active)            |
|  - Prohibited patterns                                                |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 5: Approval provenance gate                                     |
|  - approval_attestation_id NOT NULL                                   |
|  - attestation references the body version being sent                 |
|  - reviewer is real user (UUID FK to users)                           |
|  - policy_snapshot pinned to approval is still current OR override    |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 6: Provider readiness gate                                      |
|  - resend_health (last 5 min: 2xx rate > 95%)                         |
|  - idempotency_key not previously used                                |
|  - workspace not in send_freeze                                       |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
| Layer 7: Send-path assertion gate                                     |
|  current pre_send_assertions.py — keep and extend                     |
|  - email_deliverable, email_status_verified, email_name_consistent    |
|  - outreach_eligible, persona_target                                  |
|  - no_recent_company_send, sender_under_daily_cap                     |
|  - prior_step_sent, minimum_step_gap                                  |
|  - bounce_rate_ok (system-wide; runs once per claim)                  |
+-----------------------------------------------------------------------+
                                |
                                v
                        Resend dispatch
```

### Per-gate detail

| Gate | What it checks | Where enforced | Fail-open / fail-closed | Event emitted on failure | Current gap | Target implementation |
|---|---|---|---|---|---|---|
| `send_eligibility` | Contact `lifecycle_state` ∈ {`ELIGIBLE`,`SEQUENCED`,`WARMING`,`HOT`}; not in `SUPPRESSED_*` | DB constraint (Stage 4 C.2) + worker-side check | fail-closed | `gate_send_eligibility_fail` | Today: `outbound_eligible_contacts` SQL view (migration 033) checked at draft-gen, not at send-claim | Worker re-checks `contacts.lifecycle_state` at claim time; in same transaction as claim |
| `approval_provenance` | `outreach_drafts.approval_attestation_id IS NOT NULL` AND attestation row exists AND `body_version_id` matches | DB CHECK constraint (Stage 4 D.3) | fail-closed | `gate_approval_provenance_fail` | Today: no CHECK constraint; Stage 2 A.4 confirms approval can be approved with NULL reviewer | Schema CHECK added in Stage 4 I Phase 3 |
| `content_integrity` | Body hash matches `approval_attestations.body_version_id.content_hash`; no banned patterns in body | Python validator at worker, schema CHECK on body_version_id | fail-closed | `gate_content_integrity_fail` | Today: integrity regex in `agents/outreach.py:_INTEGRITY_RULES`; runs only at draft-gen, not at send | Validator re-runs at send-claim against the resolved body version |
| `suppression_status` | No active `suppression_events` row for the contact or company at suppression `scope='contact'`/`scope='company'`/`scope='domain'` | Python `SuppressionService.is_eligible(contact_id)` at worker claim | fail-closed | `gate_suppression_status_fail` | Today: `suppression.is_suppressed(db, company_id, contact_id)` (lines 162–319) checked at draft-gen; suppression after approval but before send is not re-checked | Re-check at claim time inside the claim transaction |
| `company_cooldown` | No send to this company within `policy_snapshot.payload.send_limits.company_cooldown_days` | Worker Python; query against `send_attempts` | fail-closed | `gate_company_cooldown_fail` | Today: `pre_send_assertions.assert_no_recent_company_send` (`pre_send_assertions.py:206`) at draft-gen — also runs at send-path | Keep current logic; switch source from `outreach_drafts.sent_at` to `send_attempts.delivery_confirmed_at` |
| `contact_cooldown` | No send to this contact within `policy_snapshot.payload.send_limits.contact_cooldown_days` (new field — default 30 days for re-engagement, infinite within an active sequence) | Worker Python | fail-closed | `gate_contact_cooldown_fail` | Today: implicit in sequence semantics; no explicit gate | New worker check against `send_attempts` |
| `sequence_step_validity` | `sequence_step_state` row for step N-1 in `DRAFT_SENT` for N ≥ 2; step gap satisfied | Worker Python + DB CHECK (Stage 4 D.8) | fail-closed | `gate_sequence_step_validity_fail` | Today: `assert_prior_step_sent` (pre_send_assertions.py:269) — runs at draft-gen and send-path; reads `outreach_drafts.sent_at` | Switch source to `sequence_step_state.state='DRAFT_SENT'` |
| `sender_daily_capacity` | Sender's sent count today < `policy_snapshot.payload.outreach.daily_send_limit` | Worker Python; query against `send_attempts.delivery_confirmed_at` | fail-closed | `gate_sender_daily_capacity_fail` | Today: `assert_sender_under_daily_cap` (pre_send_assertions.py:243); counts `outreach_drafts` with `sent_at` | Switch source to `send_attempts` |
| `workspace_daily_capacity` | Workspace's sent count today < `outreach_send_config.daily_limit` | Worker Python; runs once per claim (cached for the worker's batch loop) | fail-closed | `gate_workspace_daily_capacity_fail` | Today: implicit in `_load_send_config` + per-contact assertion; `workspace_daily_sends_ok` explicitly DISABLED (main.py:189–194) | Single authoritative read from `outreach_send_config`; `workspace_daily_sends_ok` deleted |
| `bounce_rate_safety` | 7-day rolling bounce rate < `policy_snapshot.payload.send_limits.max_bounce_rate` (0.02 currently) | Worker Python; runs once per worker poll cycle, not per claim | fail-closed (workspace freeze for 1 hour) | `gate_bounce_rate_safety_fail` | Today: `assert_bounce_rate_ok` (pre_send_assertions.py:359); fires on first contact of every batch | Move to once-per-poll-cycle; freeze workspace for `policy_snapshot.payload.send_limits.bounce_rate_freeze_minutes` (default 60) on trigger |
| `duplicate_outreach_guard` | No row in `outbound_queue` or `send_attempts` (active state) for the same `draft_id` | DB UNIQUE on `outbound_queue.draft_id` + partial UNIQUE on `send_attempts` (Stage 4 D.9) | fail-closed | `gate_duplicate_outreach_fail` | Today: compare-and-swap on `sent_at` is the only guard; no UNIQUE | Schema UNIQUE added in Stage 4 I Phase 2 |
| `active_conversation_detection` | No `contacts.lifecycle_state='RESPONDED'` on this contact OR siblings at company AND draft is `sequence_step >= 2` | Worker Python | fail-closed | `gate_active_conversation_fail` | Today: no gate; replies arriving during pending send are not detected (scenario J.5 below) | New worker check; reads `contacts.lifecycle_state` for contact and all siblings |
| `sibling_contact_pause` | No sibling contact at the same company with positive `reply_sentiment` in past 30 days | Worker Python | fail-closed | `gate_sibling_contact_pause_fail` | Today: traction shown advisory in approval UI; not a hard gate at send | New worker check using `get_company_traction` logic |
| `departed_contact_detection` | Contact's `lifecycle_state` ≠ `SUPPRESSED_DEPARTED` (Stage 4 C.2) | Worker Python (subset of suppression check) | fail-closed | `gate_departed_contact_fail` | Today: implicit in `contacts.status='not_interested'` semantics; no `SUPPRESSED_DEPARTED` state | Stage 4 C.2 introduces the explicit state |
| `provider_idempotency` | `idempotency_key=draft.id` not previously sent (provider-side) AND no prior `send_attempts.state='DELIVERED'` for this draft (local-side) | Resend SDK + DB UNIQUE on `send_attempts(draft_id, attempt_number)` (Stage 4 D.1) | fail-closed | `gate_provider_idempotency_fail` | Today: idempotency_key passed to Resend; no local check beyond `sent_at IS NULL` | Schema UNIQUE added in Stage 4 I Phase 2 |
| `webhook_event_deduplication` | INSERT-IF-NOT-EXISTS on `(provider, event_id)` UNIQUE; on duplicate, short-circuit handler | DB UNIQUE on `provider_events.external_event_id` (Section E.7) | fail-closed | `gate_webhook_dedup` | Today: no dedup; Stage 2 E.8 confirms every webhook can be replayed double | Stage 4 I Phase 1 introduces `webhook_event_log` |



---

## SECTION D — Autonomy Control Plane

### D.1 Hierarchy

Each level overrides everything below it. A `HALT` at any level short-circuits the evaluation; lower levels are not consulted.

```
+-----------------------------------------------------------------------+
|                  GLOBAL KILL SWITCH                                   |
|  env var SEND_ENABLED=false in Railway                                |
|  set_by: ops; requires: nothing; logged: workflow_events,             |
|  audit_log, Railway env audit                                         |
|  reversed_by: ops setting SEND_ENABLED=true; same authority           |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
|                  WORKSPACE KILL SWITCH                                |
|  outreach_send_config.send_enabled (per workspace)                    |
|  set_by: admin role; requires: reason; logged: workflow_events        |
+-----------------------------------------------------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
|                  SEND-FREEZE  (transient, system-triggered)           |
|  send_freezes table — one active row per workspace                    |
|  triggered_by: bounce-rate gate, manual ops, content alert            |
|  auto_expires_at; reversed_by: same role or expiry                    |
+-----------------------------------------------------------------------+
                                |
                                v
+--------------------------+ +--------------------------+ +-----------------+
| SEQUENCE KILL SWITCH     | | COMPANY HOLD             | | CONTACT HOLD    |
| engagement_sequences     | | company_hold_events      | | contact_hold_   |
|  .lifecycle_state=PAUSED | |  (active row)            | |  events         |
+--------------------------+ +--------------------------+ +-----------------+
                                |
                                v
+--------------------------+ +--------------------------+
| SENDER HOLD              | | PROVIDER HOLD            |
| sender_hold_events (new) | | provider_state.healthy   |
+--------------------------+ +--------------------------+
                                |
                                v
+-----------------------------------------------------------------------+
|                  CONTENT HOLD                                         |
|  content_validator's HARD_REJECT — per-draft only                     |
+-----------------------------------------------------------------------+
```

### D.2 Per-control storage and authority

| Control | Storage | Read by | Set by | Reason field | How logged | Reversal | Reversal authority |
|---|---|---|---|---|---|---|---|
| Global kill switch | env var `SEND_ENABLED` | Worker startup (refuses to enter send loop if false) | Anyone with Railway env access (ops/admin) | Required as Slack message before flip | Slack post + workflow_events `transition='global_kill_set'` written by worker on next start | Set env to `true` | Same as setter |
| Workspace kill switch | DB column `outreach_send_config.send_enabled` | Worker per-batch | Role `admin` via `POST /api/admin/workspaces/{id}/halt` | Required text field on endpoint | `workflow_events.transition='workspace_kill_set'` | `POST /api/admin/workspaces/{id}/resume` with reason | Same role |
| Send freeze | DB row `send_freezes (workspace_id, reason, set_at, expires_at, set_by, system_triggered)` | Worker per-claim | System (bounce-rate gate) or admin via `POST /api/admin/freezes` | Required (system fills `reason='bounce_rate_exceeded'` automatically) | `workflow_events.transition='send_freeze_set'` | Auto-expiry OR admin `POST /api/admin/freezes/{id}/lift` | Admin role for early lift |
| Sequence kill | DB column `engagement_sequences.lifecycle_state` | Worker per-claim (refuses to claim drafts whose sequence is PAUSED) | `SequenceOrchestrator.pause(sequence_id, reason, triggered_by)` | Required | `workflow_events.transition='sequence_paused'` | `SequenceOrchestrator.resume(sequence_id, operator_id, reason)` | Operator role; positive-reply pause requires the same operator who marked the reply positive |
| Company hold | DB row `company_hold_events (company_id, reason, set_by, set_at, expires_at, released_at, released_by)` | Worker per-claim | Operator via `POST /api/admin/companies/{id}/hold` OR system (legal flag, escalated bounce, manual DNC request) | Required | `workflow_events.transition='company_hold_set'` | Auto-expiry OR explicit release `POST /api/admin/companies/{id}/release-hold` | Same role |
| Contact hold | DB row `contact_hold_events (contact_id, reason, ...)` | Worker per-claim | Operator | Required | `workflow_events.transition='contact_hold_set'` | Same | Same |
| Sender hold | DB row `sender_hold_events (sender_email, reason, ...)` | Worker per-claim | System (sender bounce-rate trigger) or admin | Required | `workflow_events.transition='sender_hold_set'` | Same | Same |
| Provider hold | DB row `provider_state.healthy=false (provider)` | Worker per-poll | System (health check failure) or ops via `POST /api/admin/providers/{name}/disable` | Required | `workflow_events.transition='provider_hold_set'` | Health check pass OR explicit ops re-enable | Ops/admin |
| Content hold | Validator HARD_REJECT — per draft | Validator at generation; revalidator at send | Validator (automatic) | Built-in: rule_id that triggered | `workflow_events.transition='content_hold_set'` | Reject-and-regenerate the draft OR override the rule and re-validate | Override requires admin |

### D.3 Operating modes

These are not in the control plane hierarchy — they are deployment modes that change WHAT the engine does, not WHETHER it acts. Configured by env var.

**`dry_run_mode` (`DRY_RUN=true`):**
- Engine runs all gates, generates drafts, runs the validator, computes risk scores, claims outbound queue rows, runs send-path assertions.
- Resend SDK is mocked — returns a deterministic fake `id` per draft_id.
- No emails leave the system. No webhooks fire.
- All `workflow_events` rows are written normally with an extra `payload.dry_run=true` tag.
- `send_attempts.state='DRY_RUN_DISPATCHED'` (added to the state CHECK).
- Used for: validating gate changes against production data without affecting prospects.

**`shadow_mode` (`AUTONOMY_SHADOW=true`):**
- Engine makes risk-bucket + auto-approve decisions in parallel with the human queue.
- Decisions are written to `autonomy_decisions` table (Section E.1) with `decision='SHADOW_PROCEED'` / `'SHADOW_HOLD'` / `'SHADOW_BLOCK'` / `'SHADOW_ESCALATE'`.
- Humans review every draft normally; the shadow decision is logged for comparison but not acted on.
- Used for: validating the risk model before enabling autonomy. Stage 4 I Phase 3 references this as the 14-day pre-cutover validation period.

**`simulation_mode` (`SIM_REPLAY_FROM=<event_id>` `SIM_REPLAY_TO=<event_id>`):**
- Engine reads `workflow_events` between the two IDs, replays them through the current gate/validator code, and writes hypothetical outcomes to `autonomy_decisions` with `decision='SIM_*'` prefix.
- No state mutations on the production tables — outputs go to a separate `simulation_runs` table with the diff.
- Used for: regression testing gate changes against historical traffic.

The three modes are mutually exclusive at the worker level. Setting two simultaneously raises at worker startup.

---

## SECTION E — Database and State Model for Autonomous Execution

This section refines the Stage 4 D schema with autonomy-specific additions. Every table follows the same conventions: UUID primary key, RLS by `workspace_id` where applicable, append-only enforced by role grants, indexed on the access patterns documented per table.

### E.1 `autonomy_decisions` — NEW

**Purpose:** Append-only log of every decision the engine made autonomously. One row per decision event. Distinct from `workflow_events`: `workflow_events` records WHAT happened, `autonomy_decisions` records WHY the engine acted (or refused).

```sql
CREATE TABLE autonomy_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN (
    'outreach_draft','contact','company','send_attempt','sequence',
    'inbound_reply','suppression','webhook_event','outbox_row')),
  entity_id UUID NOT NULL,
  workflow TEXT NOT NULL CHECK (workflow IN (
    'prospect_ingestion','enrichment','qualification','research_refresh',
    'draft_generation','content_validation','draft_approval','send_execution',
    'follow_up_generation','reply_classification','suppression',
    'sequence_pausing','sibling_contact_outreach','company_traction_detection',
    're_engagement','reporting_alerts')),
  decision TEXT NOT NULL CHECK (decision IN (
    'PROCEED','HOLD','BLOCK','ESCALATE',
    'SHADOW_PROCEED','SHADOW_HOLD','SHADOW_BLOCK','SHADOW_ESCALATE',
    'SIM_PROCEED','SIM_HOLD','SIM_BLOCK','SIM_ESCALATE',
    'DRY_RUN_PROCEED')),
  risk_score NUMERIC(5,2),
  risk_bucket TEXT CHECK (risk_bucket IN ('LOW','MEDIUM','HIGH','BLOCKED')),
  gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,  -- per-gate pass/fail
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  validator_version TEXT,
  classifier_version TEXT,
  worker_instance_id TEXT NOT NULL,  -- host:pid:start_epoch
  correlation_id UUID,                -- ties to workflow_events row
  reason TEXT,                        -- human-readable summary
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_autonomy_decisions_entity
  ON autonomy_decisions(entity_type, entity_id, created_at);
CREATE INDEX idx_autonomy_decisions_workflow_decision
  ON autonomy_decisions(workflow, decision, created_at);
CREATE INDEX idx_autonomy_decisions_correlation
  ON autonomy_decisions(correlation_id);
CREATE INDEX idx_autonomy_decisions_shadow
  ON autonomy_decisions(workflow, created_at)
  WHERE decision LIKE 'SHADOW_%';

REVOKE UPDATE, DELETE ON autonomy_decisions FROM PUBLIC;
GRANT INSERT, SELECT ON autonomy_decisions TO prospectiq_app;
GRANT INSERT, SELECT ON autonomy_decisions TO prospectiq_writer_worker;
```

**Migration note:** Additive. Backfilled retroactively from `interactions` if needed for first-week reporting; no need to rewrite history.

### E.2 `risk_scores` — NEW

**Purpose:** Current computed risk score per outreach_draft. Updated each time a gate runs. Append-only: every recomputation inserts a new row; the latest is queried via `ORDER BY scored_at DESC LIMIT 1` or via a `latest_risk_scores` view.

```sql
CREATE TABLE risk_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  contact_id UUID NOT NULL,
  company_id UUID NOT NULL,
  workspace_id UUID NOT NULL,
  score NUMERIC(5,2) NOT NULL CHECK (score >= 0 AND score <= 100),
  bucket TEXT NOT NULL CHECK (bucket IN ('LOW','MEDIUM','HIGH','BLOCKED')),
  dimension_scores JSONB NOT NULL,    -- {sequence_step: 'LOW', account_tier: 'MEDIUM', ...}
  validator_result JSONB,
  triggered_dimensions TEXT[],         -- which dimensions contributed > 5 points
  scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  scoring_version TEXT NOT NULL,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id)
);
CREATE INDEX idx_risk_scores_draft_latest
  ON risk_scores(draft_id, scored_at DESC);
CREATE INDEX idx_risk_scores_bucket_recent
  ON risk_scores(bucket, scored_at DESC);

CREATE OR REPLACE VIEW latest_risk_scores AS
  SELECT DISTINCT ON (draft_id)
    draft_id, contact_id, company_id, workspace_id,
    score, bucket, dimension_scores, validator_result,
    scored_at, scoring_version, policy_snapshot_id
  FROM risk_scores
  ORDER BY draft_id, scored_at DESC;

REVOKE UPDATE, DELETE ON risk_scores FROM PUBLIC;
GRANT INSERT, SELECT ON risk_scores TO prospectiq_writer_worker;
GRANT SELECT ON risk_scores TO prospectiq_app;
```

**Migration note:** Additive. Initial population: run the scorer against every `outreach_drafts` row in `QUEUED` state at cutover and insert one row per draft. New drafts get a row at `DraftGenerator.persist()`.

### E.3 `outbound_queue` — REFINED from Stage 4 D.9

Adds priority calculation, lease renewal, and explicit worker identification. Keeps the existing Stage 4 D.9 contract.

```sql
CREATE TABLE outbound_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL UNIQUE REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  workspace_id UUID NOT NULL,
  priority_score NUMERIC(7,2) NOT NULL DEFAULT 100.00,
  enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at TIMESTAMPTZ,
  claimed_by_worker TEXT,
  claim_expires_at TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_attempt_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED','CLAIMED','SENT','FAILED','DEAD_LETTER')),
  last_error TEXT,
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  completed_at TIMESTAMPTZ,
  CONSTRAINT outbox_dead_letter_must_have_error
    CHECK (status <> 'DEAD_LETTER' OR last_error IS NOT NULL)
);
CREATE INDEX idx_outbox_ready
  ON outbound_queue(workspace_id, priority_score DESC, enqueued_at ASC)
  WHERE status = 'QUEUED' AND available_at <= NOW();
CREATE INDEX idx_outbox_orphan_claims
  ON outbound_queue(status, claim_expires_at)
  WHERE status = 'CLAIMED';

REVOKE UPDATE, DELETE ON outbound_queue FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (status, claimed_at, claimed_by_worker,
       claim_expires_at, attempt_count, next_attempt_at, last_error,
       completed_at) ON outbound_queue TO prospectiq_writer_worker;
GRANT INSERT ON outbound_queue TO prospectiq_writer_approval_svc;
GRANT SELECT ON outbound_queue TO prospectiq_app;
```

**Migration note:** Additive over Stage 4 D.9. Existing approvals that have not yet sent need to be backfilled into the queue: `INSERT INTO outbound_queue (draft_id, workspace_id, policy_snapshot_id) SELECT id, workspace_id, <current_snapshot_id> FROM outreach_drafts WHERE approval_status IN ('approved','edited') AND sent_at IS NULL;`.

### E.4 `dead_letter_queue` — NEW

```sql
CREATE TABLE dead_letter_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id UUID NOT NULL REFERENCES outreach_drafts(id) ON DELETE RESTRICT,
  original_queue_entry_id UUID REFERENCES outbound_queue(id),
  workspace_id UUID NOT NULL,
  failure_reason TEXT NOT NULL,
  failure_category TEXT NOT NULL CHECK (failure_category IN (
    'ASSERTION_FAILURE','PROVIDER_ERROR','CONTENT_BLOCKED',
    'POLICY_VIOLATION','SUPPRESSION','MAX_ATTEMPTS_EXCEEDED',
    'PROVIDER_PERMANENT_4XX','WORKER_CRASH')),
  failure_payload JSONB,        -- raw provider error, assertion details, etc.
  failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES users(id),
  resolution_action TEXT,
  CONSTRAINT dlq_resolution_consistent
    CHECK ((resolved_at IS NULL) = (resolved_by IS NULL))
);
CREATE INDEX idx_dlq_unresolved
  ON dead_letter_queue(workspace_id, failed_at)
  WHERE resolved_at IS NULL;
CREATE INDEX idx_dlq_draft
  ON dead_letter_queue(draft_id, failed_at);

REVOKE UPDATE, DELETE ON dead_letter_queue FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (resolved_at, resolved_by, resolution_action)
  ON dead_letter_queue TO prospectiq_writer_worker;
GRANT SELECT ON dead_letter_queue TO prospectiq_app;
```

**Migration note:** Additive. No backfill needed; the queue grows from cutover forward.

### E.5 `suppression_events` — REPLACES the current `suppression_log`

The current `suppression_log` (migration 048) is sound but is not append-only at the schema level and has three independent writers (Stage 1 H DATA INTEGRITY RISK). `suppression_events` is the strictly append-only successor.

```sql
CREATE TABLE suppression_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  contact_id UUID REFERENCES contacts(id),
  company_id UUID REFERENCES companies(id),
  email TEXT,
  domain TEXT,
  suppression_type TEXT NOT NULL CHECK (suppression_type IN (
    'BOUNCE','COMPLAINT','UNSUBSCRIBE','DEPARTED','NOT_INTERESTED',
    'COOLDOWN','DNC','LEGAL_HOLD','COMPETITOR','SYSTEM_RULE')),
  suppression_scope TEXT NOT NULL CHECK (suppression_scope IN (
    'CONTACT','DOMAIN','COMPANY','EMAIL')),
  source TEXT NOT NULL CHECK (source IN (
    'WEBHOOK','OPERATOR','IMPORT','SYSTEM_RULE','RECONCILIATION',
    'CLASSIFIER','LEGAL')),
  provider_event_id UUID REFERENCES provider_events(id),
  triggered_by_contact_id UUID REFERENCES contacts(id),    -- for escalation chains
  escalated_from UUID REFERENCES suppression_events(id),
  reason TEXT NOT NULL,
  classifier_confidence NUMERIC(3,2),
  policy_snapshot_id UUID NOT NULL REFERENCES policy_snapshots(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,                                  -- NULL = permanent
  revoked_at TIMESTAMPTZ,                                  -- soft un-suppression
  revoked_by UUID REFERENCES users(id),
  revoked_reason TEXT,
  metadata JSONB,
  CONSTRAINT supp_scope_id_consistent CHECK (
    (suppression_scope = 'CONTACT' AND contact_id IS NOT NULL) OR
    (suppression_scope = 'EMAIL' AND email IS NOT NULL) OR
    (suppression_scope = 'COMPANY' AND company_id IS NOT NULL) OR
    (suppression_scope = 'DOMAIN' AND domain IS NOT NULL)
  ),
  CONSTRAINT supp_revoke_consistent
    CHECK ((revoked_at IS NULL) = (revoked_by IS NULL) AND
           (revoked_at IS NULL OR revoked_reason IS NOT NULL))
);
CREATE INDEX idx_supp_events_contact_active
  ON suppression_events(contact_id, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_supp_events_company_active
  ON suppression_events(company_id, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_supp_events_domain_active
  ON suppression_events(domain, created_at DESC)
  WHERE revoked_at IS NULL;
CREATE INDEX idx_supp_events_email_active
  ON suppression_events(email, created_at DESC)
  WHERE revoked_at IS NULL;

REVOKE UPDATE, DELETE ON suppression_events FROM PUBLIC;
GRANT INSERT, SELECT ON suppression_events TO prospectiq_writer_suppression_svc;
GRANT UPDATE (revoked_at, revoked_by, revoked_reason) ON suppression_events
  TO prospectiq_writer_suppression_svc;
GRANT SELECT ON suppression_events TO prospectiq_app;
```

**RLS:** Workspace-scoped. `INSERT` and revoke-UPDATE only by `suppression_svc` role. Application code reads via the role; webhook handlers call `SuppressionService` which holds the role-bound connection.

**Migration note:** Replaces `suppression_log` over Phase 3. Backfill via `INSERT INTO suppression_events SELECT ... FROM suppression_log`. Keep `suppression_log` for 30 days dual-write, then drop.

### E.6 `company_hold_events` + `contact_hold_events` — NEW

Operator-initiated holds, distinct from system-triggered suppressions.

```sql
CREATE TABLE company_hold_events (
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
  expires_at TIMESTAMPTZ,                          -- NULL = until released
  released_at TIMESTAMPTZ,
  released_by UUID REFERENCES users(id),
  released_reason TEXT,
  CONSTRAINT che_release_consistent
    CHECK ((released_at IS NULL) = (released_by IS NULL))
);
CREATE INDEX idx_che_active
  ON company_hold_events(workspace_id, company_id)
  WHERE released_at IS NULL;

CREATE TABLE contact_hold_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  contact_id UUID NOT NULL REFERENCES contacts(id),
  hold_type TEXT NOT NULL CHECK (hold_type IN (
    'OPERATOR_PAUSE','VERIFY_TITLE','VERIFY_EMAIL','MEETING_BOOKED',
    'INTERNAL_REFERRAL')),
  reason TEXT NOT NULL,
  set_by UUID NOT NULL REFERENCES users(id),
  set_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  released_at TIMESTAMPTZ,
  released_by UUID REFERENCES users(id),
  released_reason TEXT,
  CONSTRAINT cohe_release_consistent
    CHECK ((released_at IS NULL) = (released_by IS NULL))
);
CREATE INDEX idx_cohe_active
  ON contact_hold_events(workspace_id, contact_id)
  WHERE released_at IS NULL;

REVOKE UPDATE, DELETE ON company_hold_events, contact_hold_events FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (released_at, released_by, released_reason)
  ON company_hold_events, contact_hold_events TO prospectiq_writer_operator_svc;
GRANT SELECT ON company_hold_events, contact_hold_events TO prospectiq_app;
```

**Migration note:** Additive. No backfill required.

### E.7 `provider_events` — NEW

Normalized inbound events from all providers (Resend, Instantly, Gmail, Apollo, Unipile). Separate from `interactions` (which is a projection). `provider_events` is the source; `interactions` is derived.

```sql
CREATE TABLE provider_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN (
    'resend','instantly','gmail','unipile','trigify','apollo','zerobounce')),
  event_type TEXT NOT NULL,           -- normalized: 'email_delivered','email_bounced','reply_received',...
  external_event_id TEXT NOT NULL,    -- provider's id
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  processing_state TEXT NOT NULL DEFAULT 'received'
    CHECK (processing_state IN ('received','processing','processed','duplicate','failed')),
  signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
  contact_id UUID REFERENCES contacts(id),  -- resolved during processing
  company_id UUID REFERENCES companies(id),
  draft_id UUID REFERENCES outreach_drafts(id),
  send_attempt_id UUID REFERENCES send_attempts(id),
  correlation_id UUID,
  error TEXT,
  CONSTRAINT pe_external_unique UNIQUE (provider, external_event_id)
);
CREATE INDEX idx_pe_unprocessed
  ON provider_events(provider, received_at)
  WHERE processing_state = 'received';
CREATE INDEX idx_pe_draft
  ON provider_events(draft_id)
  WHERE draft_id IS NOT NULL;

REVOKE UPDATE, DELETE ON provider_events FROM PUBLIC;
GRANT INSERT, SELECT, UPDATE (processed_at, processing_state, contact_id,
       company_id, draft_id, send_attempt_id, correlation_id, error)
  ON provider_events TO prospectiq_writer_webhook_svc;
GRANT SELECT ON provider_events TO prospectiq_app;
```

**RLS:** Webhook routes run as `webhook_svc`; nothing else can INSERT.

**Migration note:** This is the Stage 4 D.5 `webhook_event_log` with two additions: explicit FKs to `draft_id`/`contact_id`/`company_id`/`send_attempt_id` resolved during processing, and the UNIQUE on `(provider, external_event_id)` is the idempotency anchor for every webhook handler. Replaces the partial `webhook_event_log` rename; treat this as the canonical name.

### E.8 `workflow_events` — REFINED from Stage 4 D.2

Stage 4 D.2 is correct. The autonomy-specific addition is the `autonomy_decision_id` FK and a tighter `actor_type` constraint.

```sql
-- Additions on top of Stage 4 D.2:
ALTER TABLE workflow_events
  ADD COLUMN autonomy_decision_id UUID REFERENCES autonomy_decisions(id);

-- Tighten actor_type to include 'autonomy_engine':
ALTER TABLE workflow_events DROP CONSTRAINT workflow_events_actor_type_check;
ALTER TABLE workflow_events ADD CONSTRAINT workflow_events_actor_type_check
  CHECK (actor_type IN (
    'SYSTEM','HUMAN','PROVIDER','autonomy_engine','operator_cli'));

CREATE INDEX idx_we_autonomy_decision
  ON workflow_events(autonomy_decision_id)
  WHERE autonomy_decision_id IS NOT NULL;
```

When a decision in `autonomy_decisions` results in a state transition, both rows are written in the same transaction with `workflow_events.autonomy_decision_id` pointing back. Replay queries: `SELECT we.*, ad.gate_results FROM workflow_events we LEFT JOIN autonomy_decisions ad ON ad.id = we.autonomy_decision_id WHERE we.target_id = $1 ORDER BY we.occurred_at`.



---

## SECTION F — Autonomous Scheduler / Worker Design

### F.1 Process Architecture

```
+------------------------------------------------------------+
|  web:    uvicorn backend.app.api.main:app                  |
|          - FastAPI HTTP API                                |
|          - serves dashboard, approvals, admin, webhooks    |
|          - NO scheduler                                    |
|          - NO send logic                                   |
|          - all writes go through services                  |
+------------------------------------------------------------+

+------------------------------------------------------------+
|  worker: python -m backend.app.worker.main                 |
|          - BlockingScheduler (APScheduler)                 |
|          - all background jobs                             |
|          - send dispatch loop                              |
|          - webhook reprocessing loop                       |
|          - reconciliation jobs                             |
|          - singleton via pg_try_advisory_lock              |
+------------------------------------------------------------+
```

**What lives in `web:` (after migration):**
- `backend/app/api/main.py` — FastAPI app, lifespan with NO scheduler block.
- `backend/app/api/routes/*` — HTTP route handlers.
- Webhook routes — accept POST, INSERT into `provider_events`, return 200. Actual processing deferred to worker.
- `ApprovalService` synchronous calls (a user approval is a web request).
- `DraftGenerator` synchronous calls (HTTP `/api/outreach/generate` is fine; same code shared with worker scheduler).

**What lives in `worker:`:**
- APScheduler `BlockingScheduler` with all the jobs from current `main.py:2029–2227`.
- The send dispatch loop (`SendWorker.poll_outbox`).
- The webhook processing loop (`WebhookProcessor.process_received`).
- Reconciliation jobs (`reconcile_pipeline_state`, orphan-claim sweeper).
- Health snapshot job.

After Phase 6, `main.py` lifespan has zero scheduler code. The Procfile change is one line, the lifespan removal is ~200 lines of code lifted into `backend/app/worker/main.py`.

### F.2 Worker Startup and Singleton Guard

```python
# backend/app/worker/main.py

import os, sys, time, logging, hashlib
from apscheduler.schedulers.blocking import BlockingScheduler
from backend.app.core.database import get_supabase_client
from backend.app.worker.jobs import register_all_jobs
from backend.app.worker.send_worker import SendWorker

logger = logging.getLogger(__name__)

# Fixed advisory key — deterministic so any instance computes the same value.
LOCK_KEY = int(hashlib.sha256(b"prospectiq_worker_v1").hexdigest()[:15], 16) % (2**31)

def main():
    client = get_supabase_client()
    # pg_try_advisory_lock returns true if acquired, false if held by another session.
    result = client.rpc("pg_try_advisory_lock", {"key": LOCK_KEY}).execute()
    acquired = bool(result.data)
    if not acquired:
        logger.critical(
            "worker_singleton_failed: another worker holds advisory lock %s. Exiting cleanly.",
            LOCK_KEY,
            extra={"event": "worker_singleton_failed", "lock_key": LOCK_KEY},
        )
        # Railway health check is satisfied by the process exiting cleanly here
        # and Railway restarting it; the lock is held by the active instance,
        # so this exit is the correct behavior.
        sys.exit(0)

    logger.info(
        "worker_singleton_acquired lock_key=%s host=%s pid=%s",
        LOCK_KEY, os.uname().nodename, os.getpid(),
        extra={"event": "worker_singleton_acquired", "lock_key": LOCK_KEY},
    )

    try:
        scheduler = BlockingScheduler(timezone="America/Chicago")
        register_all_jobs(scheduler)
        send_worker = SendWorker()
        scheduler.add_job(send_worker.poll_outbox, "interval", seconds=10,
                          id="send_outbox_poll", max_instances=1, coalesce=True)
        logger.info("worker_starting jobs=%s", [j.id for j in scheduler.get_jobs()])
        scheduler.start()  # blocks
    finally:
        try:
            client.rpc("pg_advisory_unlock", {"key": LOCK_KEY}).execute()
        except Exception:
            pass

if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
```

**Behavior:**
- **Lock acquired:** worker proceeds, registers jobs, calls `scheduler.start()` which blocks. Process runs until killed.
- **Lock NOT acquired:** worker logs `worker_singleton_failed` (CRITICAL severity, includes lock_key for ops dashboards), `sys.exit(0)` so Railway treats it as a clean termination. Railway restarts the container after the configured backoff; if the legitimate worker is still up and holding the lock, the restart loops at low frequency. Logs accumulate in Railway with the `worker_singleton_failed` event so an alert can fire.

**Railway health checks:** The `worker:` process has no HTTP port; Railway's process-monitoring health check (TCP, restart-on-exit-nonzero) is satisfied because `sys.exit(0)` is clean. We do not need an HTTP health check on the worker because the active worker is identifiable by the held lock; the `web:` process exposes `/health` which queries `pg_locks` to confirm one worker holds `LOCK_KEY`.

**Singleton detection in logs:**
- Acquired: search for `worker_singleton_acquired lock_key=`.
- Contested: search for `worker_singleton_failed lock_key=`.
- Verify exactly one process holds the lock at any time:
  ```sql
  SELECT pid, granted FROM pg_locks
  WHERE locktype = 'advisory' AND objid = <LOCK_KEY>;
  ```
  Expect exactly one row with `granted=true`.

### F.3 Outbound Queue Consumer Design

Pseudocode for the main send loop. The `claim` and `dispatch` phases run as two separate transactions; Resend is called between them.

```python
class SendWorker:
    WORKER_ID = f"{os.uname().nodename}:{os.getpid()}:{int(time.time())}"
    CLAIM_LEASE_SECONDS = 600          # 10 min — long enough for slow Resend; reset on crash
    POLL_INTERVAL_SECONDS = 10
    PROVIDER = ResendAdapter()

    def poll_outbox(self):
        while True:
            row = self._claim_one()
            if not row:
                time.sleep(self.POLL_INTERVAL_SECONDS)
                continue
            try:
                result = self._dispatch(row)
                self._handle_result(row, result)
            except Exception as exc:
                self._handle_unexpected(row, exc)

    def _claim_one(self) -> dict | None:
        with db.transaction() as tx:
            # Workspace-scoped (RLS) — the worker connection sets the active workspace
            # per-tick from a round-robin over active workspaces.
            row = tx.execute(
                "SELECT * FROM outbound_queue "
                "WHERE status = 'QUEUED' "
                "  AND available_at <= NOW() "
                "  AND workspace_id = $1 "
                "ORDER BY priority_score DESC, enqueued_at ASC "
                "LIMIT 1 "
                "FOR UPDATE SKIP LOCKED",
                self.current_workspace_id,
            ).fetchone()
            if not row:
                return None

            tx.execute(
                "UPDATE outbound_queue SET "
                "  status='CLAIMED', "
                "  claimed_at=NOW(), "
                "  claimed_by_worker=$1, "
                "  claim_expires_at=NOW() + interval '10 minutes' "
                "WHERE id=$2",
                self.WORKER_ID, row["id"],
            )
            tx.execute(
                "INSERT INTO send_attempts "
                "  (draft_id, outbound_queue_id, workspace_id, attempt_number, state, "
                "   policy_snapshot_id, claimed_at) "
                "VALUES ($1, $2, $3, $4, 'CLAIMED', $5, NOW()) "
                "RETURNING id",
                row["draft_id"], row["id"], row["workspace_id"],
                row["attempt_count"] + 1, row["policy_snapshot_id"],
            )
            tx.execute(
                "INSERT INTO workflow_events "
                "  (target_type, target_id, transition, from_state, to_state, "
                "   actor_type, actor_id, workspace_id, correlation_id) "
                "VALUES ('outreach_draft', $1, 'draft_claimed', 'ENQUEUED', 'SENDING', "
                "        'autonomy_engine', $2, $3, $4)",
                row["draft_id"], self.WORKER_ID, row["workspace_id"], row["id"],
            )
        return row

    def _dispatch(self, row):
        # Re-run the gate stack (Section C) against current state.
        gates = run_gate_stack(self.db, draft_id=row["draft_id"])
        if not gates.passed:
            return DispatchResult.assertion_failure(gates.failed_gate, gates.detail)

        # Resolve body version, sender, recipient from current state.
        message = build_message_from_draft(self.db, row["draft_id"])
        try:
            provider_result = self.PROVIDER.send(
                message, idempotency_key=str(row["draft_id"])
            )
            return DispatchResult.success(provider_result.message_id, provider_result.raw)
        except ProviderTransientError as exc:
            return DispatchResult.transient_failure(str(exc))
        except ProviderPermanentError as exc:
            return DispatchResult.permanent_failure(str(exc))

    def _handle_result(self, row, result):
        with db.transaction() as tx:
            if result.is_success:
                tx.execute(
                    "UPDATE send_attempts SET "
                    "  state='DISPATCHED', dispatched_at=NOW(), "
                    "  provider_message_id=$1, provider_response=$2 "
                    "WHERE outbound_queue_id=$3 AND state='CLAIMED'",
                    result.message_id, result.raw, row["id"],
                )
                tx.execute(
                    "UPDATE outbound_queue SET status='SENT', completed_at=NOW() "
                    "WHERE id=$1",
                    row["id"],
                )
                tx.execute(
                    "UPDATE outreach_drafts SET "
                    "  resend_message_id=$1, resend_status='sent', "
                    "  sent_at=NOW(), lifecycle_state='SENDING' "
                    "WHERE id=$2",
                    result.message_id, row["draft_id"],
                )
                tx.execute(
                    "INSERT INTO interactions "
                    "  (contact_id, company_id, type, subject, workspace_id) "
                    "SELECT contact_id, company_id, 'email_sent', subject, workspace_id "
                    "FROM outreach_drafts WHERE id=$1",
                    row["draft_id"],
                )
                tx.execute(
                    "UPDATE sequence_step_state SET state='DRAFT_SENT', send_attempt_id=$1 "
                    "WHERE draft_id=$2",
                    result.send_attempt_id, row["draft_id"],
                )
                tx.execute(
                    "UPDATE contacts SET lifecycle_state='SEQUENCED' "
                    "WHERE id=(SELECT contact_id FROM outreach_drafts WHERE id=$1) "
                    "  AND lifecycle_state IN ('ELIGIBLE','QUALIFIED')",
                    row["draft_id"],
                )
                tx.execute(
                    "UPDATE companies SET lifecycle_state='OUTREACH_ACTIVE' "
                    "WHERE id=(SELECT company_id FROM outreach_drafts WHERE id=$1) "
                    "  AND lifecycle_state IN ('OUTREACH_READY','QUALIFIED')",
                    row["draft_id"],
                )
                tx.execute(
                    "INSERT INTO workflow_events "
                    "  (target_type, target_id, transition, from_state, to_state, "
                    "   actor_type, actor_id, workspace_id, payload, correlation_id) "
                    "VALUES ('send_attempt', $1, 'dispatch_succeeded', 'CLAIMED', 'DISPATCHED', "
                    "        'autonomy_engine', $2, $3, $4, $5)",
                    result.send_attempt_id, self.WORKER_ID, row["workspace_id"],
                    {"provider_message_id": result.message_id}, row["id"],
                )
            elif result.is_transient_failure:
                # Retryable provider error — backoff, requeue
                next_at = compute_backoff(row["attempt_count"] + 1)
                if row["attempt_count"] + 1 >= row["max_attempts"]:
                    self._move_to_dead_letter(tx, row, "PROVIDER_ERROR",
                                              "max_attempts_reached", result.detail)
                else:
                    tx.execute(
                        "UPDATE outbound_queue SET "
                        "  status='QUEUED', claimed_at=NULL, claimed_by_worker=NULL, "
                        "  claim_expires_at=NULL, attempt_count=attempt_count+1, "
                        "  next_attempt_at=$1, available_at=$1, last_error=$2 "
                        "WHERE id=$3",
                        next_at, result.detail, row["id"],
                    )
                    tx.execute(
                        "UPDATE send_attempts SET "
                        "  state='DISPATCH_FAILED_RETRYABLE', terminal_at=NOW(), "
                        "  failure_reason=$1 "
                        "WHERE outbound_queue_id=$2 AND state='CLAIMED'",
                        result.detail, row["id"],
                    )
            elif result.is_permanent_failure:
                self._move_to_dead_letter(tx, row, "PROVIDER_PERMANENT_4XX",
                                          result.detail, result.detail)
                tx.execute(
                    "UPDATE send_attempts SET "
                    "  state='DISPATCH_FAILED_TERMINAL', terminal_at=NOW(), "
                    "  failure_reason=$1 "
                    "WHERE outbound_queue_id=$2 AND state='CLAIMED'",
                    result.detail, row["id"],
                )
            elif result.is_assertion_failure:
                # Block this draft, do not retry. The assertion failure means
                # current state (suppression, cooldown, ...) makes this draft
                # ineligible — won't change by retrying.
                self._move_to_dead_letter(tx, row, "ASSERTION_FAILURE",
                                          result.gate_name, result.detail)
                tx.execute(
                    "UPDATE send_attempts SET "
                    "  state='ASSERT_FAILED', terminal_at=NOW(), "
                    "  failed_assertion_gate=$1, failure_reason=$2 "
                    "WHERE outbound_queue_id=$3 AND state='CLAIMED'",
                    result.gate_name, result.detail, row["id"],
                )
```

**Failure branches expanded:**

| Failure | Outbox status | send_attempts state | Action |
|---|---|---|---|
| Provider transient (5xx, 429, timeout) | `QUEUED` again with `next_attempt_at = NOW() + 5min × 2^attempt` | `DISPATCH_FAILED_RETRYABLE` | Backoff and retry |
| Provider transient + max_attempts reached | `DEAD_LETTER` | `DISPATCH_FAILED_RETRYABLE` then final attempt `DISPATCH_FAILED_TERMINAL` | Operator alert; manual re-queue |
| Provider permanent (4xx — invalid email, malformed body) | `DEAD_LETTER` | `DISPATCH_FAILED_TERMINAL` | Operator alert; usually requires draft regeneration |
| Assertion gate failure (suppression appeared post-approval, cooldown, capacity) | `DEAD_LETTER` | `ASSERT_FAILED` | Operator alert; draft cancelled |
| Worker crash mid-dispatch (after Resend accepted, before transaction commit) | `CLAIMED` with `claim_expires_at < NOW()` | `CLAIMED` (zombie) | Reconciliation job detects after 10 min; queries Resend by `idempotency_key`; if delivered, marks DISPATCHED and queue COMPLETED; if not, returns to QUEUED |
| Database write failure after Resend success | `CLAIMED` (zombie) | `CLAIMED` (zombie) | Same as worker crash — reconciliation recovers |

### F.4 Job Inventory for Worker Process

Mapping the 23 current APScheduler jobs to keep/redesign/remove decisions.

| Job ID | Current trigger | Decision | Concurrency guard | Notes |
|---|---|---|---|---|
| `health_snapshot` | interval 15m | KEEP | none (idempotent, read-only) | Move to worker process |
| `pipeline_qc` | interval 15m | KEEP_WITH_GUARD | `pg_try_advisory_lock(<hash('pipeline_qc')>)` | Auto-fixes `refresh_outbound_eligible`; needs single-runner |
| `send_approved` | cron 8–11 Chicago | **REDESIGN as `send_outbox_poll`** | DB-level via `SELECT FOR UPDATE SKIP LOCKED` on `outbound_queue` | Continuous poll every 10s instead of half-hourly cron. Send-window check happens inside the poll. |
| `process_due` | interval 1h | KEEP_WITH_GUARD | per-sequence advisory lock | Reads `sequence_step_state` now; generates step-N drafts via `DraftGenerator` |
| `poll_instantly` | interval 6h | KEEP_WITH_GUARD | advisory lock | Reconciliation-style; reads Instantly API for missing events |
| `hitl_snoozed` | interval 15m | KEEP | idempotent UPDATE | Move to worker |
| `hitl_auto_archive` | interval 1h | KEEP_WITH_GUARD | advisory lock | Bulk UPDATE — single runner |
| `personalization_refresh` | interval 24h | KEEP_WITH_GUARD | advisory lock | Anthropic spend at risk; single runner |
| `jit_pregenerate` | interval 24h | KEEP_WITH_GUARD | advisory lock | Reads `sequence_step_state.due_at`; calls `DraftGenerator` |
| `gmail_intake` | interval 15m | KEEP_WITH_GUARD | per-mailbox advisory lock | Each Gmail mailbox is its own lock so multiple workers could process in parallel; currently still one worker total |
| `qualification` | interval 15m | KEEP_WITH_GUARD | advisory lock | Anthropic spend at risk |
| `draft_generation` | interval 5m | KEEP_WITH_GUARD | advisory lock | Anthropic spend at risk; calls `DraftGenerator` |
| `weekly_post_send_audit` | cron Sun 7am | KEEP | none (read + email) | Move to worker |
| `weekly_approval_audit` | cron Fri 9am | KEEP | none | Move to worker |
| `weekly_contact_backup` | cron Sat 5am | **REMOVE** | — | Path `/Volumes/Digitillis/...` doesn't exist on Railway. Replace with Supabase Storage export job (separate ticket) or delete. |
| `weekly_signal_scrapers` | cron Sat 6am | KEEP_WITH_GUARD | advisory lock | External scrape rate-limited; single runner |
| `signal_monitor` | cron Sun 6am | KEEP_WITH_GUARD | advisory lock | Anthropic/Perplexity spend |
| `reengagement` | cron Sun 8am | KEEP_WITH_GUARD | advisory lock | Bulk re-queue; single runner |
| `weekly_cost_summary` | cron Mon 8am | KEEP | none | Move to worker |
| `daily_report` | cron Mon–Fri 6am | KEEP | none | Move to worker |
| `intent_refresh` | cron 5am daily | KEEP_WITH_GUARD | advisory lock | Apollo spend; single runner |
| `bounce_hygiene` | cron 3am daily | **REDESIGN** | — | Replaced by suppression event handlers + `reconcile_pipeline_state` |
| NEW: `reconcile_pipeline_state` | interval 4h | NEW | advisory lock | See F.5 |
| NEW: `send_outbox_poll` | interval 10s | NEW | DB-level (skip locked) | Replaces `send_approved` |
| NEW: `provider_events_processor` | interval 30s | NEW | advisory lock | Drains `provider_events.processing_state='received'` rows |
| NEW: `orphan_claim_sweeper` | interval 5m | NEW | advisory lock | Resets `outbound_queue.status='CLAIMED' AND claim_expires_at < NOW()` to `QUEUED` |

**Concurrency-guard helper:**

```python
def with_advisory_lock(job_name: str):
    key = int(hashlib.sha256(f"prospectiq_job_{job_name}".encode()).hexdigest()[:15], 16) % (2**31)
    def wrap(fn):
        def inner(*a, **kw):
            with get_db_connection() as conn:
                got = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
                if not got:
                    logger.info("job_skip job=%s reason=lock_held", job_name)
                    return
                try:
                    return fn(*a, **kw)
                finally:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
        return inner
    return wrap
```

The `_singleton_lock` covers the worker process itself; the per-job advisory lock is defense-in-depth (e.g., if two workers ever ran during a deploy overlap). Per-job locks are cheap; they cost nothing when contention is rare.

### F.5 Reconciliation Job Design

`reconcile_pipeline_state` runs every 4 hours and DETECTS (does not auto-fix, with one exception) state drift.

```python
@with_advisory_lock("reconcile_pipeline_state")
def reconcile_pipeline_state():
    drifts = []

    # 1. outbound_queue CLAIMED for > 30 min — orphaned claim (worker crash).
    #    SAFE TO AUTO-FIX: reset to QUEUED.
    orphans = db.fetchall("""
      SELECT id, draft_id, claimed_by_worker, claimed_at
        FROM outbound_queue
       WHERE status = 'CLAIMED' AND claim_expires_at < NOW()
    """)
    for o in orphans:
        with db.transaction() as tx:
            tx.execute("""
              UPDATE outbound_queue SET
                status='QUEUED', claimed_by_worker=NULL,
                claimed_at=NULL, claim_expires_at=NULL,
                attempt_count=attempt_count + 1,
                last_error='reconciliation_reset_orphan_claim'
              WHERE id=$1 AND status='CLAIMED' AND claim_expires_at < NOW()
            """, o["id"])
            tx.execute("""
              UPDATE send_attempts SET
                state='ASSERT_FAILED', terminal_at=NOW(),
                failure_reason='worker_crash_orphan_claim'
              WHERE outbound_queue_id=$1 AND state='CLAIMED'
            """, o["id"])
            write_workflow_event(tx, "outbox_orphan_reset", o["id"])
            # Before re-queueing, query Resend by idempotency_key to check if
            # the original send actually went out.
            resend_status = provider.lookup_by_idempotency_key(str(o["draft_id"]))
            if resend_status and resend_status.was_delivered:
                tx.execute("""
                  UPDATE outbound_queue SET status='SENT', completed_at=NOW()
                  WHERE id=$1
                """, o["id"])
                tx.execute("""
                  UPDATE send_attempts SET
                    state='DISPATCHED', dispatched_at=$1,
                    provider_message_id=$2, provider_response=$3
                  WHERE outbound_queue_id=$4 AND state='ASSERT_FAILED'
                """, resend_status.dispatched_at, resend_status.message_id,
                     resend_status.raw, o["id"])

    # 2. send_attempts.DISPATCHED but no delivery webhook after 4h — provider lost.
    #    DETECT ONLY.
    lost = db.fetchall("""
      SELECT id, draft_id, provider_message_id, dispatched_at
        FROM send_attempts
       WHERE state='DISPATCHED'
         AND dispatched_at < NOW() - interval '4 hours'
         AND delivery_confirmed_at IS NULL
    """)
    for r in lost:
        write_workflow_event(None, "STATE_DRIFT_DETECTED",
            payload={"type": "send_attempt_no_delivery_confirmation",
                     "send_attempt_id": r["id"],
                     "age_hours": (now() - r["dispatched_at"]).total_seconds() / 3600})
        drifts.append(r)

    # 3. outreach_drafts.sent_at vs send_attempts.delivery_confirmed_at drift.
    #    DETECT ONLY.
    sent_at_drift = db.fetchall(STAGE2_F5_QUERY)
    for r in sent_at_drift:
        write_workflow_event(None, "STATE_DRIFT_DETECTED",
            payload={"type": "sent_at_no_send_attempt", "draft_id": r["id"]})
        drifts.append(r)

    # 4. send_attempts.DELIVERED but no email_sent interaction.
    #    DETECT ONLY.
    interaction_drift = db.fetchall(STAGE2_F7_QUERY)
    for r in interaction_drift:
        write_workflow_event(None, "STATE_DRIFT_DETECTED",
            payload={"type": "send_attempt_no_interaction", "draft_id": r["draft_id"]})
        drifts.append(r)

    # 5. engagement_sequences ACTIVE but no sequence_step_state in PENDING/SENT.
    #    DETECT ONLY.
    sequence_drift = db.fetchall("""
      SELECT s.id, s.contact_id, s.current_step
        FROM engagement_sequences s
       WHERE s.lifecycle_state = 'ACTIVE'
         AND NOT EXISTS (
           SELECT 1 FROM sequence_step_state sss
            WHERE sss.sequence_id = s.id
              AND sss.state IN ('PENDING','DRAFT_GENERATED','DRAFT_APPROVED','DRAFT_SENT')
         )
    """)
    for r in sequence_drift:
        write_workflow_event(None, "STATE_DRIFT_DETECTED",
            payload={"type": "active_sequence_no_step_state", "sequence_id": r["id"]})
        drifts.append(r)

    # 6. suppression_events vs contacts.lifecycle_state drift.
    #    DETECT ONLY.
    suppression_drift = db.fetchall("""
      SELECT se.id, se.contact_id, se.suppression_type, c.lifecycle_state
        FROM suppression_events se
        JOIN contacts c ON c.id = se.contact_id
       WHERE se.revoked_at IS NULL
         AND se.suppression_scope = 'CONTACT'
         AND c.lifecycle_state NOT LIKE 'SUPPRESSED_%'
    """)
    for r in suppression_drift:
        write_workflow_event(None, "STATE_DRIFT_DETECTED",
            payload={"type": "suppressed_event_no_contact_state",
                     "contact_id": r["contact_id"]})
        drifts.append(r)

    # Operator dashboard card
    upsert_dashboard_card("drift", count=len(drifts), last_run=now())
```

**Auto-fix rules:**

| Drift | Auto-fix | Reason |
|---|---|---|
| Outbox `CLAIMED` > 30 min orphan | YES — reset to `QUEUED`, increment `attempt_count`, query Resend to see if delivery actually happened | Cause is well-understood (worker crash); safe to recover |
| `DISPATCHED` > 4h with no delivery confirmation | NO — alert only | Could be Resend backlog, recipient grey-list, or webhook outage; human inspects |
| `sent_at` set but no `send_attempts` row | NO — alert | Indicates a write path bypassed the canonical flow; human inspects |
| `DELIVERED` but no `interactions` row | NO — alert | Indicates the projection write failed; human decides whether to backfill |
| Active sequence with no `sequence_step_state` | NO — alert | Could be a sequence-migration backfill issue |
| Active `suppression_events` but contact not in `SUPPRESSED_*` | NO — alert | Indicates the contact state was overwritten somewhere |

Operator dashboard renders the drift card:

```
+----------------------------------------------------------------+
| Pipeline Drift — last run 2026-05-14 14:00 CDT                 |
+----------------------------------------------------------------+
|  3 orphan-claim resets (auto-fixed)                            |
|  1 dispatched-no-delivery >4h                  [view]          |
|  0 sent_at-no-send_attempt                                     |
|  2 delivered-no-interaction                    [view]          |
|  0 active-sequence-no-step-state                               |
|  0 suppression-state-mismatch                                  |
+----------------------------------------------------------------+
```

---

## SECTION G — Integration Strategy

### G.1 `OutboundProvider` interface

```python
from typing import Protocol
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class NormalizedMessage:
    to: str
    subject: str
    body: str
    from_addr: str
    reply_to: str | None
    headers: dict[str, str]
    workspace_id: str
    draft_id: str

@dataclass(frozen=True)
class ProviderDispatchResult:
    message_id: str
    raw: dict
    accepted_at: datetime

@dataclass(frozen=True)
class NormalizedWebhookEvent:
    provider: str
    external_event_id: str
    event_type: str  # 'delivered','opened','clicked','bounced','complained','replied','unsubscribed'
    occurred_at: datetime
    target_message_id: str | None
    payload: dict

@dataclass(frozen=True)
class DeliveryStatus:
    state: str  # 'queued','dispatched','delivered','bounced','complained','unknown'
    last_event_at: datetime | None

class OutboundProvider(Protocol):
    name: str
    
    def send(self, draft_id: str, to: str, subject: str, body: str,
             from_addr: str, reply_to: str | None,
             idempotency_key: str) -> ProviderDispatchResult:
        """Synchronously dispatch a single message.
        Raises ProviderTransientError or ProviderPermanentError on failure."""
    
    def get_delivery_status(self, message_id: str) -> DeliveryStatus:
        """Poll the provider for current status (reconciliation only)."""
    
    def handle_webhook_event(self, payload: bytes, headers: dict
                             ) -> NormalizedWebhookEvent | None:
        """Verify signature; normalize the event. Return None on invalid signature."""
    
    def is_healthy(self) -> tuple[bool, list[str]]:
        """Return (healthy, list_of_issues)."""
```

### G.2 Resend adapter

**Autonomous:**
- `send()` — dispatch via SDK with `idempotency_key=draft_id`.
- Delivery status polling via `/emails/{id}` (used by reconciliation).
- Webhook intake via `handle_webhook_event()`.

**Not autonomous (operator-initiated):**
- Adding new sender domains (Resend dashboard).
- Configuring DKIM/SPF records.
- Viewing aggregated delivery analytics (operator dashboard read-only).

**Rate limit and quota tracking:**
- Resend's published limit: 10 emails/sec on standard plan, higher on enterprise.
- Per-day credit count tracked in `provider_state(provider='resend', metric='daily_sends', date, count)`.
- Adapter increments `count` on successful dispatch in the same transaction as `send_attempts.DISPATCHED`.

**Idempotency:**
- Use `draft_id` as `idempotency_key` (current behavior). Resend's docs confirm the key is valid for 24 hours; for retries beyond that window, the worker will already have moved the row to dead-letter.

**Retry policy:**
- HTTP 429 (rate limit): exponential backoff `5min × 2^attempt`. Up to 3 attempts.
- HTTP 5xx: same backoff. Up to 3 attempts.
- HTTP 4xx hard codes (`400 Bad Request`, `422 Unprocessable`): no retry, move to dead_letter.
- Timeout / connection refused: treated as 5xx — retry.

**Webhook intake:**
1. Verify `Svix-Signature` header against `RESEND_WEBHOOK_SECRET`. If missing or invalid, **return 401** (do not fall open as Stage 2 E.4 noted; the Stage 3 hardening forbids this).
2. `external_event_id = data.id` from the payload.
3. Insert into `provider_events` with `ON CONFLICT (provider, external_event_id) DO NOTHING`. Return 200 in both branches.
4. If the insert was a no-op (duplicate), update `processing_state='duplicate'` and return.
5. If the insert succeeded, defer processing — the `provider_events_processor` job picks it up.

**Failure containment:**
- Resend outage: `send()` raises `ProviderTransientError`; worker handles per F.3 — only the current draft is impacted; outbox keeps polling but every dispatch retries. After enough consecutive transient errors, `resend.is_healthy()` returns false; the worker pauses dispatch until health returns. **Draft generation, qualification, reply intake all continue.**

### G.3 Instantly adapter

**Current problem (Stage 2 E.1):** Two routers mounted at different prefixes with different verification (`/api/webhooks/instantly` query-param vs `/webhooks/instantly` HMAC).

**Target:**
- Single canonical path: `/api/webhooks/instantly` with HMAC verification.
- Delete `backend/app/webhooks/instantly.py`.
- All Instantly handling consolidated into `InstantlyAdapter` exposed through the standard `OutboundProvider` interface.

**Autonomous:**
- Sequence sync (read Instantly campaign state, mirror into local DB).
- Event intake (webhook + 6h polling reconciliation).

**Not autonomous:**
- Creating new sequences in Instantly dashboard.
- Pausing/resuming warmup sequences (Instantly is used as warmup-only per project memory — never for sends).
- Modifying sender pool assignments at Instantly.

**Idempotency:**
- `external_event_id` from Instantly payload (their `event_id` field).
- Same `provider_events` UNIQUE pattern.

**Retiring legacy:**
- `EngagementAgent.process_webhook_event` (engagement.py:1697) — delete after the new adapter is live (Stage 4 I Phase 4).
- `_poll_instantly_events` calls the new adapter instead of the static method.

### G.4 Gmail/IMAP adapter

**Current problem (Stage 2 E.7):** Missing app password causes silent skip.

**Target:**
- Adapter has `is_healthy()` that checks every configured mailbox.
- On startup: `worker:` process calls `gmail.is_healthy()`; if any mailbox is unhealthy, write `workflow_events.transition='STARTUP_HEALTH_FAILURE'` with `payload={'provider':'gmail','mailboxes':[...]}` and alert via Slack. Do not silently skip.
- Per-tick: `gmail_intake` job calls `is_healthy()` before fetching; unhealthy mailbox alerts and is skipped for this tick only.

**Autonomous:**
- Polling for replies every 15 min.
- Delivering parsed replies to `provider_events` table.
- Marking IMAP messages as `\Seen` after `provider_events` insert succeeds.

**Idempotency:**
- `external_event_id = Message-Id` header (RFC 5322 unique id).
- If `Message-Id` is absent or malformed, fall back to `sha256(From + Date + Subject + first_2KB_of_body)`.
- `provider_events` UNIQUE prevents replay processing.

**Credential rotation:**
- App passwords stored in `CredentialStore` keyed `gmail_<safe_email>`.
- Adapter reads each call; new password takes effect immediately.

### G.5 Apollo adapter

**Current problem (Stage 1 H):** Unbounded class-level cache.

**Target:**
- LRU+TTL cache: `cachetools.TTLCache(maxsize=500, ttl=86400)` per worker process.
- Cache key: `apollo_id` or `email+company_id` for matches; misses fall through to API.
- Per-day quota tracked in `provider_state(provider='apollo', metric='daily_calls')`.

**Autonomous:**
- Per-contact enrichment.
- Per-company enrichment.
- People search (top-of-funnel discovery).

**Not autonomous:**
- Bulk enrichment runs > 100 contacts (require operator initiation via `POST /api/admin/imports/bulk-enrich` with budget confirmation).
- Apollo plan changes / billing.

**Idempotency:**
- `apollo_id` is the natural key per contact and company.
- Re-enrichment skipped if `apollo_enriched_at > NOW() - INTERVAL '30 days'`.
- Force re-enrich requires `force=true` operator parameter; logged as `workflow_events.transition='enrichment_force_refresh'`.

### G.6 ZeroBounce adapter

**Autonomous:**
- Verify email on draft generation gate (the `assert_email_status_verified` gate calls this if `contacts.email_status` is NULL or stale).

**Not autonomous:**
- Bulk re-verification campaigns (budget-gated, operator-initiated).
- ZeroBounce account purchases.

**Idempotency:**
- `email_address` + `verification_date` is the natural key.
- Re-verify only if `verified_at > NOW() - INTERVAL '30 days'`.

**Storage:**
- Results stored immutably in `email_verifications (contact_id, provider, email, verified_at, status, raw_response)` — never overwritten; each verification is a new row.
- `contacts.email_status` and `email_verified_at` are denormalized cache of the latest verification.

**Stale handling:**
- Daily reconciliation: flag contacts where `email_verified_at < NOW() - INTERVAL '90 days'` and put them in a `stale_verification` queue.
- Operator decides whether to re-verify (budget call) or accept the stale value.



---

## SECTION H — Content Autonomy Pipeline

This is how draft generation becomes autonomous without hallucinated claims. Stage 4 H sketched the architecture; this section is the operational specification for the autonomous engine.

### H.1 Evidence Registry (`content_claims` from Stage 4 D.7)

A claim record is one of:

| `claim_type` | Definition | Required source | Who adds | Review required | Expiry |
|---|---|---|---|---|---|
| `product_fact` | Verifiable feature or capability of Digitillis | Internal product spec (URL or doc reference) | Product/marketing team | Second user approves | Manual (no automatic expiry) |
| `benchmark_citation` | Third-party published statistic (SMRP, LNS Research, McKinsey, government data) | Citation: publisher, year, page or section, exact quote | Research / GTM | Second user approves, verifies citation | 12 months from publication date |
| `outcome_statement` | Performance outcome Digitillis has observed in a paid pilot or production deployment | Internal customer reference, anonymized client name OR signed-off case study | GTM | Two-person review + legal sign-off | Manual — re-attested annually |
| `regulatory_reference` | Citation of a regulatory requirement | Government URL with section number | Legal team | Single sign-off | Follows regulation effective dates |
| `public_signal` | Public announcement about a prospect (funding, expansion, leadership change) | Source URL | Auto-generated from signal scrapers | None — auto-active for 90 days | 90 days from `effective_from` |
| `anti_pattern` | A phrase or claim type that is always prohibited | Internal style guide reference | Anyone with admin role | Second user approves | Manual |

**Access:** Active claims for a given draft are resolved by `ContentClaimResolver.resolve(workspace_id, company_id, contact_id, sequence_step) -> list[Claim]`. The resolver filters by sector (`applicable_sectors`), step (some claims only apply to step 1 vs follow-ups), and active window (`effective_from <= NOW() < expires_at`).

**Generator access:** Claims are injected into the prompt as JSON, not free text:
```json
{
  "evidence_pool": [
    {
      "id": "c1a2b3c4-...",
      "type": "benchmark_citation",
      "text": "Best-in-class OEE in food & beverage manufacturing averages 85%, while industry average is 60%.",
      "source": "LNS Research, 'Manufacturing OEE Benchmarks 2025', page 14",
      "applicable_sectors": ["311", "312"],
      "confidence": "high",
      "expires_at": "2027-01-01"
    },
    ...
  ]
}
```

The generator's system prompt instructs: "Every numeric claim, percentage, dollar figure, or named statistic in the body MUST be drawn from `evidence_pool[*]`. Reference the `id` in the metadata field of your output. If no relevant claim is available, write a message without that statistic — do not improvise."

### H.2 Generator constraints

The `DraftGenerator` constructs the model prompt with three injected payloads:

1. **`evidence_pool`** — the JSON array above. Up to 10 claims, filtered to the draft's context.
2. **`prohibited_patterns`** — regex + semantic descriptions:
   - Regex: `\d{2,3}\s*%` (any 2-3 digit percentage); `\$\d+[KMB]?` (any dollar figure); `\d+\s*(x|X)\s*(ROI|return)`; em-dash, en-dash, double-dash.
   - Semantic: "vague client reference without anonymization", "specific company name not in customer roster", "open-ended commitment".
3. **`voice_rules`** — from `outreach_guidelines.yaml::voice_and_tone` (already-existing).

The generator's output schema is structured JSON:
```json
{
  "subject": "Reducing changeover variance at Acme",
  "body": "...",
  "claim_ids_referenced": ["c1a2b3c4-...", "d2e3f4a5-..."],
  "generation_metadata": {
    "model": "claude-sonnet-4-5",
    "temperature": 0.5,
    "evidence_pool_size": 7,
    "claims_used": 2
  }
}
```

### H.3 Validation pipeline (post-generation, pre-draft-insert)

Four passes. Each produces a sub-score (`pass` / `quarantine` / `hard_reject`). Final score = MIN over the four. Any HARD_REJECT kills the draft entirely.

**Pass 1: Structural.**
- Greeting present.
- Body length ∈ [policy.min_body_length, policy.max_body_length] (currently 80–250 words).
- CTA present.
- Signature present.
- Subject length ∈ [policy.subject_min, policy.subject_max] (currently 5–60 chars).
- Outcome: `pass` or `hard_reject` (structural is binary).

**Pass 2: Prohibited patterns.**
- Regex sweep for `prohibited_patterns` regex list.
- Claude classification pass: "Does this email contain any of: [list of semantic anti-patterns]?"
- Any match → `hard_reject` with the pattern that matched.
- Outcome: `pass` or `hard_reject`.

**Pass 3: Claim grounding.**
- For every `\d+%`, `\$\d+`, `\d+x`, "X days", and named statistic regex match: must be covered by a `claim_pattern` of one of the `claim_ids_referenced`.
- Each `claim_id` in metadata must exist and be active (`is_active=true`, within `effective_from..expires_at`).
- A claim shape not covered → `quarantine` (human reviews; could be a phrasing the registry hasn't catalogued yet).
- A `claim_id` in metadata that doesn't exist in registry → `hard_reject` (model hallucinated the id).
- Outcome: `pass` / `quarantine` / `hard_reject`.

**Pass 4: Tone/persona.**
- Compare against `outreach_guidelines.yaml::voice_and_tone` rules: no first-person plural where it implies a client outcome, no "we typically" phrasing, no banned phrases from `outreach_guidelines.yaml::never_include`.
- Claude classification pass: "Does this email match the voice rules?" — pass/soft-reject with specific feedback.
- Outcome: `pass` or `soft_reject` (which routes to QUARANTINED for reviewer feedback).

### H.4 Autonomy thresholds

| Validator combined result | Risk score | Routing |
|---|---|---|
| Pass 1=pass AND Pass 2=pass AND Pass 3=pass AND Pass 4=pass AND step ≤ 2 AND no sibling traction | LOW | `ApprovalService.approve_as_system` — `approval_attestations.actor_type='SYSTEM'`, immediate enqueue |
| Pass 1–4 all pass BUT step ≥ 3 OR sibling traction OR account_tier=pmfg1 | MEDIUM/HIGH | Human review queue (Section B routing) |
| Pass 1,2,4=pass AND Pass 3=quarantine | MEDIUM | Human review queue with "claim not registered" UI flag |
| Pass 4=soft_reject | MEDIUM | Human review queue with specific tone feedback shown |
| Pass 1=hard_reject OR Pass 2=hard_reject OR Pass 3=hard_reject | N/A | Draft NOT inserted to `outreach_drafts`. Instead: `workflow_events.transition='generation_failure'` with payload containing the rejected body, pattern that matched, and `claim_ids_referenced`. The reason is fed back to the generator on next retry. |

### H.5 Human review ergonomics for content

When a draft reaches the review queue, the reviewer card surfaces:

- The full draft body, with every claim-shaped phrase highlighted.
  - GREEN highlight: covered by an active claim (hover shows source, citation, expiry).
  - YELLOW highlight: quarantine — claim shape detected but no covering claim. Reviewer sees "claim not registered".
  - RED highlight: hard-reject violation that somehow made it through (defense-in-depth; shouldn't normally appear).
- One-click "**Register this claim**" — opens a side panel; reviewer enters source URL, citation, confidence, expiry; submits. The claim is added to `content_claims` in `pending_review` state and a second reviewer approves it before it becomes usable. The draft itself stays in review until the new claim is approved.
- One-click "**Reject this claim and regenerate**" — marks the specific span as rejected, logs to `outreach_edit_feedback` with the span text + reason, triggers a new draft generation pass that includes this rejection as an anti-pattern in the prompt.
- The sender, contact, company, sequence step, prior interactions, and traction signals are shown in the right panel for context.

### H.6 Provenance after approval

Once approved:

- `draft_content_versions` row written with the approved body + subject; `version_number = 1` for the original, `version_number = 2` for any reviewer edits, etc. Immutable: GRANT INSERT, SELECT only.
- `approval_attestations.body_version_id` FK to the version actually approved.
- A reviewer who edits after approval creates a new `draft_content_versions` row and the system raises `EditedAfterApproval` — moving the draft back to `UNDER_REVIEW` and requiring re-approval (separate attestation). The original attestation is preserved.
- `SendWorker.dispatch()` resolves the body to send by following `outreach_drafts.body_version_id → draft_content_versions.body`. The legacy `outreach_drafts.body` column becomes a denormalized cache (Stage 4 D.6).
- Full audit chain (Stage 4 H.5):
  ```
  provider_message_id → send_attempts → outreach_drafts → draft_content_versions →
  generation_metadata.claim_ids_referenced → content_claims rows → source, citation
  ```

---

## SECTION I — Phased Autonomy Roadmap

Each phase is independently shippable, has measurable success criteria, and can be rolled back without losing data.

### PHASE 0 — Stabilize

**Objective:** Lock down current state so no regression slips out while autonomous engine work begins.

**What becomes autonomous:** Nothing new. The current scheduler-driven flow continues with the Stage 3 Section 1 actions applied: `SEND_ENABLED=false`, operator scripts disabled, webhook secrets enforced, replica count = 1.

**What remains HITL:** Everything that's HITL today.

**Schema changes:** None.

**Application changes:**
- Apply Stage 3 Section 1 actions 1.1–1.8.
- Snapshot every at-risk table.
- Verify migration 045 columns present in production.

**Tests:** Stage 3 SQL queries F.2–F.7 return expected (mostly empty) result sets.

**Success metric:** Zero unauthorized approvals (no `approved_by IS NULL`) in 7 days after resume.

**Rollback:** Re-enable scripts and re-enable sends (none of the work in this phase is destructive).

**Complexity:** S.

**Dependency:** None.

### PHASE 1 — Schema Hardened

**Objective:** Add the constraints that should always have been there. No behavioral change.

**What becomes autonomous:** Nothing new — this is constraint-only.

**What remains HITL:** Same as Phase 0.

**Schema changes (all additive):**
- `outreach_drafts.lifecycle_state` TEXT NOT NULL DEFAULT (derived from existing columns) + CHECK constraint.
- UNIQUE partial index on `outreach_drafts (workspace_id, contact_id, sequence_name, sequence_step)` for non-terminal states.
- CHECK linking `approval_status='approved'` to `(approved_by IS NOT NULL AND reviewed_at IS NOT NULL)`.
- Trigger blocking UPDATE of `(body, subject)` once `sent_at IS NOT NULL`.
- `workflow_events` table (Stage 4 D.2, Section E.8).
- `provider_events` table (Section E.7).
- `policy_snapshots` with `version=1` capturing current `limits.yaml` + `outreach_send_config` + `outreach_guidelines.yaml`.
- `autonomy_decisions` table (Section E.1).

**Application changes:**
- Existing code paths begin writing to `workflow_events` and `provider_events` (additive — does not replace `interactions` or `workspace_audit_log`).
- Webhook handlers route through `provider_events` first (INSERT IF NOT EXISTS), then proceed to existing logic.

**Tests:**
- Test scenario J.6 (bounce webhook replay) must dedup correctly.
- Stage 3 SQL queries return zero rows of new violations.
- Migration applied successfully against snapshot of production data.

**Success metric:** Zero CHECK or trigger violations in 7 days; `provider_events` records every webhook with the right `processing_state` lifecycle.

**Rollback:** Drop the new tables and constraints. Old code unaffected.

**Complexity:** M.

**Dependency:** Phase 0.

### PHASE 2 — Constrained Autonomy (send_attempts + outbound_queue)

**Objective:** Introduce the transactional outbox model. Run dual-write with the legacy `sent_at` path. Add risk scoring in shadow mode.

**What becomes autonomous:**
- Reconciliation of orphan claims (F.5 #1) becomes automatic.
- Risk scoring runs on every new draft and stores results.

**What remains HITL:** All approval decisions. Risk scoring is shadow-only.

**Schema changes (additive):**
- `send_attempts` (Stage 4 D.1).
- `outbound_queue` (Section E.3).
- `dead_letter_queue` (Section E.4).
- `risk_scores` (Section E.2).
- `sequence_step_state` (Stage 4 D.8) — backfilled.

**Application changes:**
- `EngagementAgent._send_approved_drafts` writes BOTH legacy `sent_at` AND new tables.
- Webhook handlers update both legacy and new state.
- `RiskScorer` runs at draft creation; result is written to `risk_scores` but not consulted by routing.
- New reconciliation job for orphan claims (F.5).

**Tests:**
- Test scenarios J.1, J.7, J.14, J.16.
- 14-day dual-write with `reconcile_pipeline_state` reporting zero drift on `sent_at` vs `send_attempts`.

**Success metric:**
- 14 days of dual-write, 0 drift detected.
- `send_attempts.state='DELIVERED'` count matches `COUNT(*) FROM outreach_drafts WHERE sent_at IS NOT NULL` exactly each day.

**Rollback:** Remove new write paths; legacy column remains the source of truth; new tables are unused.

**Complexity:** L.

**Dependency:** Phase 1.

### PHASE 3 — Risk-Based Approval

**Objective:** Route approvals by risk score. Autonomous for low-risk step-1 drafts; human review for medium+.

**What becomes autonomous:**
- Draft approval for LOW-bucket drafts (score 0–20, step ≤ 2, all validator passes pass, no sibling traction). System writes `approval_attestations` with `actor_type='SYSTEM'`.
- Approval routing decision itself (the engine decides who reviews).

**What remains HITL:**
- All MEDIUM and HIGH bucket drafts.
- All BLOCKED bucket drafts (require override).
- Positive-reply triggered actions.
- Tier-1 dual review.

**Schema changes:**
- `approval_attestations` (Stage 4 D.3) — includes `actor_type` distinguishing SYSTEM from HUMAN.
- `outreach_drafts.approval_attestation_id` FK with CHECK constraint.
- Postgres roles `prospectiq_writer_approval_svc`, `prospectiq_writer_worker`, `prospectiq_writer_suppression_svc`, etc.

**Application changes:**
- Single `ApprovalService` (Stage 4 E.2) with `intake`, `approve`, `approve_as_system`, `reject`, `request_override`, `audit_override`.
- `?force=true` removed; `POST /api/approvals/{id}/override-request` + `audit` introduced.
- Operator scripts removed (Stage 2 G.1, G.2).
- `review_manifest.approve_manifest` rerouted through `ApprovalService.approve` per draft.
- HTTP `/api/outreach/generate` uses the same `DraftGenerator` as the scheduler.

**Tests:**
- Test scenarios J.3, J.10.
- Shadow-mode risk scoring from Phase 2: validate that auto-approve decisions match what a human would have done for LOW-bucket drafts (manual audit of 100 such drafts).

**Success metric:**
- 14 days where 100% of new approvals have an `approval_attestations` row (no nulls).
- 0 approval writes from roles other than `approval_svc` (RLS violations would be CI build errors).
- For auto-approved drafts: 0 reviewer-initiated reversal within 24 hours of auto-approve.

**Rollback:** Disable auto-approve via `policy_snapshot.payload.autonomy.auto_approve_enabled=false`. Auto-approval falls back to human queue; risk scores still computed.

**Complexity:** L.

**Dependency:** Phase 2 (`outbound_queue` for the same-transaction enqueue).

### PHASE 4 — Autonomous Follow-Up

**Objective:** Step-2 and step-3 drafts generated and approved autonomously for low-risk sequences. Suppression and sibling hold autonomous.

**What becomes autonomous:**
- Step-2 and step-3 draft generation for sequences where step-1 was auto-approved AND auto-sent AND has clean delivery.
- Step-2 and step-3 auto-approval for LOW-bucket drafts (per the risk scoring).
- Sibling hold (a sibling reply pauses pending drafts at the same company automatically).
- All system-generated suppression (bounce, complaint, unsubscribe, departed) is fully autonomous.

**What remains HITL:**
- Step-3+ drafts (configurable: cap auto-approve at step N via policy).
- Drafts to tier-1 accounts.
- Any draft with sibling traction signal (positive reply at the company).
- Sequence resume from positive-reply pause.

**Schema changes:**
- `company_hold_events`, `contact_hold_events`, `sender_hold_events` (Section E.6).
- `send_freezes` table.
- `suppression_events` replaces `suppression_log`.

**Application changes:**
- `SequenceOrchestrator.pause(sequence_id, reason)` and `.resume()` services.
- `SuppressionService` consolidates the three current writers into one.
- Sibling-traction detection inserted into the gate stack as `gate_sibling_contact_pause`.

**Tests:**
- Test scenarios J.5, J.12, J.13.
- 14-day shadow run on follow-up auto-approval: validate auto-approved step-2/3 drafts against what a human would have decided.

**Success metric:**
- 14 days where follow-up auto-approve decisions have ≥ 95% concordance with human judgment (measured against a manually re-reviewed sample of 50 drafts).
- 0 sends to suppressed contacts (audit query F.8).
- 0 sends to contacts where a sibling has replied positively in past 7 days.

**Rollback:** Set `policy_snapshot.payload.autonomy.follow_up_auto_approve_enabled=false`. Follow-up drafts route to human queue.

**Complexity:** L.

**Dependency:** Phase 3.

### PHASE 5 — Autonomous Signal Processing

**Objective:** Reply classification, suppression, traction detection, sequence hold/resume all autonomous for clear cases. HITL only for ambiguous and positive replies.

**What becomes autonomous:**
- Reply classification for clear cases (`bounce`, `unsubscribe`, `auto_reply_*`) with classifier confidence > 0.85: auto-action (suppress contact, mark departed, etc.) without human.
- Bounce-rate gate firing: workspace send-freeze written automatically; alert fires; operator decides when to lift.
- Traction detection: automatic state machine update; siblings auto-paused.

**What remains HITL:**
- Positive replies (always require human action — even if classifier is 0.99 confident, the action — booking a meeting, responding, etc. — is human).
- Negative replies (operator decides whether to send a "thank you, follow up later" response or move on).
- Ambiguous classifications (confidence ≤ 0.85, intent='other', or thread-classifier disagreement).
- Manual DNC operator-initiated.

**Schema changes:**
- `reply_classifications` (existing migration 035 extended with `confidence`, `classifier_version`).
- `classifier_decisions` log table for shadow / production comparison.

**Application changes:**
- `ReplyService.classify_and_action(provider_event_id)` is a single service that classifies, determines confidence, and either auto-actions or enqueues HITL.
- `provider_events_processor` job calls `ReplyService` for each reply event.

**Tests:**
- Test scenarios J.13 (departed contact auto-reply), J.14 (high bounce rate emergency stop).
- 14-day shadow: log classifier verdict vs human action for every reply.

**Success metric:**
- 14 days where classifier auto-action concordance with human judgment ≥ 98% for clear-case classes.
- 0 cases of auto-actioning a positive reply.
- Bounce-rate gate fires and freezes correctly (verified by chaos test J.14).

**Rollback:** Set classifier confidence threshold to 1.0 (effectively disables auto-action); all replies route to HITL.

**Complexity:** M.

**Dependency:** Phase 1 (`provider_events` for replay idempotency); independent of Phase 4.

### PHASE 6 — Full Governed Autonomy

**Objective:** Content integrity pipeline live; risk model validated on shadow data; end-to-end autonomous with human review only for high-risk, overrides, and positive replies.

**What becomes autonomous:**
- Full content validator (Section H) running enforced (not shadow).
- Claim grounding mandatory; HARD_REJECT drafts not persisted.
- All workflows from Section A operating at their target classification.
- Worker process (`worker:` Procfile) is the singleton runner.

**What remains HITL:**
- Positive replies (forever — by design).
- Override workflow (forever — by design).
- HIGH risk and BLOCKED risk drafts.
- Tier-1 dual review.
- Manual operator-initiated DNC.

**Schema changes:**
- `content_claims` (Stage 4 D.7).
- `draft_content_versions` (Stage 4 D.6).
- `outreach_drafts.body_version_id` FK; `body`/`subject` columns become denormalized cache.
- Sequence state machine triggers (Section C.1 enforcing).

**Application changes:**
- `worker:` Procfile process; `web:` lifespan no longer starts scheduler.
- `DraftGenerator` uses `content_claims` registry; validator enforced.
- Reviewer UI updated for claim-aware review (Section H.5).
- All bypass paths deleted: `pace_limiter.PaceLimiter`, `process_webhook_event`, `outreach_agent.py` duplicate, operator scripts.

**Tests:**
- Full Section J test suite passes.
- 7-day production run with `worker:` process; 0 scheduler-related incidents.
- Content audit: 0 unauthorized claims in approved drafts (manual sample of 100 over the week).

**Success metric:**
- 30-day production run with the full autonomy posture; KPIs:
  - Auto-approval rate for step-1 drafts > 60% (target — adjusts based on policy tightness).
  - Reviewer queue size at start of day ≤ 30 drafts per workspace (was 200+).
  - Time from draft generation to send ≤ 6 hours median (was 24–72h via scheduler queue).
  - Reviewer reversal rate of auto-approvals ≤ 1% (proves the risk model isn't too lenient).
  - Bounce rate ≤ 2% rolling (current threshold).
- 0 "approval bypass" events (no script writes, no force-approvals without override audit).

**Rollback:** Set `policy_snapshot.payload.autonomy.global_enabled=false`. All workflows revert to Phase 0 behavior (human-driven through HITL). Schema and tables persist.

**Complexity:** XL.

**Dependency:** Phases 1–5.

---

## SECTION J — Test Strategy for Autonomous Engine

Adversarial test suite. Each test scenario specifies setup, action, expected behavior, expected DB state, expected events, failure mode, and test type.

### J.1 duplicate_scheduler_workers

- **Setup:** Two worker processes (`process_a`, `process_b`) configured identically. Both started within 1 second of each other.
- **Action:** Both attempt `pg_try_advisory_lock(LOCK_KEY)`.
- **Expected behavior:** First to acquire (deterministic per Postgres ordering) proceeds; runs `register_all_jobs` and `scheduler.start()`. Second fails the lock attempt, writes `worker_singleton_failed` CRITICAL log, exits with code 0.
- **Expected DB state:** Exactly one row in `pg_locks` for the advisory key with `granted=true`; one `workflow_events` row of type `worker_started`.
- **Expected workflow_events:** One `worker_started` from the active process; one `worker_singleton_failed` if the second process logs it (these logs are in Railway, not necessarily in workflow_events).
- **Failure mode:** Both workers acquire; concurrent scheduler ticks produce duplicate Anthropic spend, duplicate sends, double-counted webhooks.
- **Test type:** Chaos / integration. Run with two Docker containers pointed at the same DB.

### J.2 stale_approval

- **Setup:** Draft approved 8 days ago. `outreach_send_config.daily_limit=100`, `send_limits.company_cooldown_days=14`. A different contact at the same company was sent to 5 days ago.
- **Action:** Worker picks up the draft from `outbound_queue` (it has been there 8 days).
- **Expected behavior:** Gate `company_cooldown` fails at the send-path assertion. Worker rolls back; outbox row moves to `DEAD_LETTERED` with `failure_category='ASSERTION_FAILURE'`, `failure_reason='no_recent_company_send: cooldown not met'`. No Resend call.
- **Expected DB state:** `outbound_queue.status='DEAD_LETTER'`; `send_attempts.state='ASSERT_FAILED'`; `outreach_drafts.lifecycle_state='APPROVED'` (no transition because the gate stopped before send).
- **Expected workflow_events:** `gate_company_cooldown_fail` with payload including the gate detail.
- **Failure mode:** Gate skipped because it only ran at draft-gen (a week ago) and was not re-run at send claim time.
- **Test type:** Integration.

### J.3 approval_bypass_via_force

- **Setup:** Pre-cutover environment where the `?force=true` parameter still exists. User attempts `POST /api/approvals/{id}/approve?force=true`.
- **Action:** Endpoint receives the request.
- **Expected behavior (post-cutover):** Endpoint returns 410 Gone with body `{"error":"force_param_deprecated","use":"POST /api/approvals/{id}/override-request"}`. No state change.
- **Expected DB state:** `outreach_drafts.lifecycle_state` unchanged. No `approval_attestations` row written.
- **Expected workflow_events:** `transition='deprecated_endpoint_called'` with payload `{"endpoint":"approve?force=true","ip":"...","user_id":"..."}`.
- **Failure mode (Phase 0–2):** Force param still works; gate bypassed; an unsigned approval enters the queue. Stage 3 hardening mitigates by deprecating but not removing the parameter; full removal in Phase 3.
- **Test type:** Unit + integration. Asserts the deprecated endpoint returns 410.

### J.4 send_after_suppression

- **Setup:** Draft approved at 10:00; outbound_queue row inserted at 10:00. At 10:15, a webhook arrives: contact has been suppressed. At 10:30, the worker claims the outbox row.
- **Action:** Worker runs gate stack at claim time.
- **Expected behavior:** Layer 4 `suppression_status` gate fails. Outbox row → DEAD_LETTERED. No Resend call.
- **Expected DB state:** `outbound_queue.status='DEAD_LETTER'`, `failure_category='SUPPRESSION'`; `send_attempts.state='ASSERT_FAILED'`; contact `lifecycle_state='SUPPRESSED_*'`.
- **Expected workflow_events:** `gate_suppression_status_fail`, `outbox_row_dead_lettered`, `draft_suppressed`.
- **Failure mode:** Suppression checked only at draft-gen or approval (10:00); not re-checked at claim (10:30); send proceeds.
- **Test type:** Integration.

### J.5 reply_arrives_during_pending_send

- **Setup:** Step-2 draft for contact X is approved at 09:00; outbox row inserted. At 09:30, contact X sends a reply (positive). Webhook arrives, processed at 09:31, marks contact `lifecycle_state='RESPONDED'`. At 09:45, worker claims the outbox row.
- **Action:** Worker runs gate stack.
- **Expected behavior:** Layer 4 `active_conversation_detection` gate fails. Outbox row → DEAD_LETTERED. Sequence pauses (`engagement_sequences.lifecycle_state='PAUSED'`). All future `sequence_step_state` rows for this sequence move to `STEP_BLOCKED`.
- **Expected DB state:** Outbox `DEAD_LETTERED`; sequence `PAUSED`; `SEQUENCE_PAUSED` event in `workflow_events`.
- **Expected workflow_events:** `gate_active_conversation_fail`, `sequence_paused` with payload `{"reason":"active_conversation","triggered_by_event_id":"..."}`.
- **Failure mode:** Reply not detected; step-2 sends anyway; appears robotic and risks killing the conversation.
- **Test type:** Integration.

### J.6 bounce_webhook_replay

- **Setup:** Resend sends `email.bounced` event for `provider_message_id='msg_xyz'`. The webhook is received and processed at 10:00. At 10:05, Resend retries the same event.
- **Action:** Second webhook arrives.
- **Expected behavior:** `provider_events` INSERT fails with UNIQUE violation on `(provider='resend', external_event_id='evt_abc')`. Handler sets `processing_state='duplicate'` and returns 200. No second `suppression_events` row inserted.
- **Expected DB state:** Exactly one `suppression_events` row for the contact (with `suppression_type='BOUNCE'`); two `provider_events` rows but second has `processing_state='duplicate'`.
- **Expected workflow_events:** Only the first event's `contact_suppressed` transition. Second event logs `gate_webhook_dedup` but no contact-level transition.
- **Failure mode:** No UNIQUE; suppression event inserted twice; contact double-counted in escalation calculations.
- **Test type:** Integration.

### J.7 resend_timeout_after_provider_accepted

- **Setup:** Worker calls `resend.Emails.send()` at 10:00:00. Resend processes the request and delivers but our HTTP client times out at 10:00:30 before reading the response. The `send_attempts` row remains in `CLAIMED` (the response with `message_id` was never captured). Resend's delivery webhook arrives at 10:02 with `email_id=msg_xyz` matching our `idempotency_key=draft_id`.
- **Action:** Webhook handler resolves the event.
- **Expected behavior:** Reconciliation job (every 5 min) detects `outbound_queue.status='CLAIMED' AND claim_expires_at < NOW()` for this row. It queries Resend's `/emails/?idempotency_key=draft_id` and finds `msg_xyz` in `delivered` state. Worker:
  1. Updates `send_attempts.state='DISPATCHED'`, `provider_message_id='msg_xyz'`, `dispatched_at` (from Resend's API).
  2. Updates outbound_queue `status='SENT'`, `completed_at`.
  3. Inserts `interactions` row (delayed projection).
  4. Updates `outreach_drafts.lifecycle_state='SENT'`.
- **Expected DB state:** Everything matches what would have happened if the original response had been captured.
- **Expected workflow_events:** `state_drift_detected` (reconciliation noticed), `dispatch_recovered_from_idempotency`, `send_delivered`.
- **Failure mode:** Without reconciliation, the draft sits forever in `CLAIMED`; appears stuck.
- **Test type:** Chaos / integration. Inject a 30-second delay then connection-reset on the Resend HTTP client.

### J.8 gmail_duplicate_intake

- **Setup:** IMAP poller fetches mailbox at 10:00; finds message UID 1234 unread. Marks as `\Seen`. At 10:15, the next poll runs; due to a Gmail label sync delay, UID 1234 appears unread again.
- **Action:** Poller fetches the same UID twice.
- **Expected behavior:** Second fetch attempts `provider_events` INSERT with `external_event_id=Message-Id-header`. UNIQUE constraint blocks; `processing_state='duplicate'`. No second `thread_messages` row, no second HITL entry.
- **Expected DB state:** One `thread_messages` row; one `hitl_queue` row; two `provider_events` rows (one `processed`, one `duplicate`).
- **Expected workflow_events:** First: `reply_received`, `reply_classified`. Second: `gate_webhook_dedup`.
- **Failure mode:** Duplicate HITL entries; reviewer responds twice.
- **Test type:** Integration.

### J.9 operator_script_mutation_attempt

- **Setup:** Post-Phase 6, all operator scripts are deleted. A developer attempts to manually run an analogous SQL: `UPDATE outreach_drafts SET body='...' WHERE id=<sent_draft_id>` using a `psql` console connected as the application role.
- **Action:** SQL executes.
- **Expected behavior:** DB trigger `outreach_drafts_content_immutability_guard` raises: `content_immutable: cannot change body_version after approval`. The transaction is rolled back. The attempted mutation is logged via Postgres audit (if `pg_audit` is configured) or via the standard Postgres logs.
- **Expected DB state:** No mutation.
- **Expected workflow_events:** Not directly — the trigger raises before any event can be written by application code. The attempt is visible only in Postgres logs.
- **Failure mode:** Without the trigger, the mutation succeeds silently and the audit trail is corrupted.
- **Test type:** Integration. Run from a script connected as `prospectiq_app` role.

### J.10 policy_config_drift

- **Setup:** `limits.yaml::send_limits.company_cooldown_days=14` is committed at v1. `policy_snapshots.version=1` captured this value. Two days later, `limits.yaml` is edited on disk to `company_cooldown_days=21` but `PolicyService.publish()` is NOT called (operator forgot). The server has been running for 48 hours.
- **Action:** Worker runs a send tick; pulls `policy_snapshots WHERE superseded_at IS NULL` and gets the v1 snapshot (still active).
- **Expected behavior:** Worker uses `company_cooldown_days=14` (from the active snapshot), not the on-disk YAML. The on-disk YAML is ignored by the running system. An operator-facing alert fires: `policy_drift_detected: yaml differs from active snapshot`.
- **Expected DB state:** Sends proceed under the v1 policy.
- **Expected workflow_events:** Per-day `policy_drift_detected` alert event.
- **Failure mode:** If the worker reads YAML directly (current bug per Stage 1 H LRU SCOPE), it gets unpredictable behavior (cached YAML from process start). With policy snapshots, the answer is deterministic — the published snapshot wins.
- **Test type:** Integration. Edit YAML on a test server without calling publish; assert worker behavior reflects the snapshot.

### J.11 content_hallucination

- **Setup:** Generator produces a draft with the body containing "Manufacturers like Acme reduced changeover variance by 40% using our platform." The `claim_ids_referenced` list is empty (model failed to ground).
- **Action:** Validator runs Pass 3 (claim grounding).
- **Expected behavior:** Regex match `\d+%` (40%) finds no covering claim. Pass 3 → `quarantine`. Draft is inserted as `lifecycle_state='QUARANTINED'`. `workflow_events.transition='draft_quarantined'` with payload `{"reason":"claim_not_registered","span":"40%"}`.
- **Variant:** If the model lies and inserts `claim_ids_referenced=["fake-uuid"]`: validator checks claim exists in registry; fails → `hard_reject`. Draft NOT inserted; `workflow_events.transition='generation_failure'` with the fabricated claim id.
- **Failure mode:** Hallucinated stat ships to a prospect; brand damage.
- **Test type:** Unit + integration. Use a mocked LLM that produces the unfounded claim.

### J.12 sibling_contact_outreach_after_traction

- **Setup:** Contact A at Company X received a step-1 email on Monday, replied positively on Tuesday. Contact B at Company X has a step-1 draft in `outbound_queue.status='QUEUED'` since Sunday.
- **Action:** Worker claims Contact B's outbox row on Wednesday.
- **Expected behavior:** Layer 4 `sibling_contact_pause` gate fails (sibling reply detected). Outbox `DEAD_LETTERED` with `failure_category='POLICY_VIOLATION'`, `failure_reason='sibling_traction'`. A `workflow_events.transition='sibling_traction_hold'` is written referencing both contacts.
- **Expected DB state:** Contact B's draft not sent; sequence `PAUSED` for Contact B; alert to operator with both contact summaries.
- **Failure mode:** Two emails go out to the same company within 48 hours, looking like a sales blitz.
- **Test type:** Integration.

### J.13 departed_contact_auto_reply

- **Setup:** Inbound reply to Contact C: "Thank you for reaching out. I am no longer with [Company]. Please contact [Other Name]." Classifier confidence: 0.92 for class `auto_reply_no_longer_here`.
- **Action:** `ReplyService.classify_and_action` processes.
- **Expected behavior:** Contact C `lifecycle_state='SUPPRESSED_DEPARTED'`; all sequences for Contact C move to `ABANDONED`; all pending drafts for Contact C → `SUPPRESSED`. Company X is NOT suppressed. Suggested next contact (the "Other Name" if extractable) routed to enrichment queue if not already in DB.
- **Expected DB state:** Contact C suppressed; Company X status unchanged; new `enrichment_queue` row for the named replacement if applicable.
- **Expected workflow_events:** `reply_classified` (confidence=0.92, class='auto_reply_no_longer_here'), `contact_departed`.
- **Failure mode:** Company-level suppression on Contact C's departure; new outreach to legitimate Contact D at the same company is blocked.
- **Test type:** Integration.

### J.14 high_bounce_rate_emergency_stop

- **Setup:** Sender `avi@digitillis.io` has sent 50 emails in past 7 days; 3 hard bounces in past hour push 7-day bounce rate above 2%.
- **Action:** Bounce-rate gate runs at the next worker poll cycle.
- **Expected behavior:** Gate `bounce_rate_safety` fails. Worker writes `send_freezes` row for the workspace with `reason='bounce_rate_exceeded'`, `expires_at=NOW() + 60min`. All queued outbox rows for this workspace remain `QUEUED` but `available_at` is bumped past the freeze expiry. Operator alert fires.
- **Expected DB state:** Active `send_freezes` row; outbox rows unconsumed; subsequent worker polls return zero claimed rows for this workspace.
- **Expected workflow_events:** `bounce_rate_threshold_exceeded` with payload `{"rate":0.026,"threshold":0.02,"sample_size":50,"bounces":3}`. `send_freeze_set`.
- **Failure mode:** Sends continue mid-spike; bounce rate escalates; ISP reputation damaged.
- **Test type:** Integration / chaos. Inject the 3 bounces via mock webhook events.

### J.15 database_partial_failure

- **Setup:** Worker calls Resend successfully; `provider_message_id='msg_xyz'` returned. Worker attempts to commit the second transaction (update `send_attempts.state='DISPATCHED'`, etc.). DB connection drops mid-commit.
- **Action:** Worker's transaction commit raises `OperationalError`.
- **Expected behavior:** Worker catches; opens a NEW connection; writes a single row to `workflow_events` of type `SEND_ATTEMPT_WRITE_FAILED` with the message_id, draft_id, and original-exception message. Does NOT mark outbound_queue as SENT (because the transaction did not commit). The outbox row remains `CLAIMED` until reconciliation (Section F.5 #1) detects the expired claim, queries Resend by idempotency_key, and recovers.
- **Expected DB state:** Outbox `CLAIMED` initially; after reconciliation (within 10 min), outbox `SENT`, send_attempts `DISPATCHED`, with the data backfilled from Resend's API.
- **Expected workflow_events:** `dispatch_db_write_failed`, then later `dispatch_recovered_from_idempotency`.
- **Failure mode:** Without the SEND_ATTEMPT_WRITE_FAILED event, the failure is invisible; without reconciliation, the row stays CLAIMED forever (orphan).
- **Test type:** Chaos. Kill the DB connection between Resend's success and the second transaction commit.

### J.16 worker_crash_mid_send

- **Setup:** Worker calls `resend.Emails.send()` at 10:00:00. Resend accepts at 10:00:00.5. Worker process is SIGKILLed at 10:00:00.6 before the result transaction starts.
- **Action:** Worker restarts at 10:00:30 (Railway restart). New worker process.
- **Expected behavior:** Outbox row is `CLAIMED` with `claim_expires_at=10:10:00`. New worker doesn't pick it up (the gate `WHERE claim_expires_at <= NOW()` is not yet met). At 10:10:00, the reconciliation job sweeps; queries Resend by idempotency_key; finds the message in `delivered` state; recovers the row (as in J.7).
- **Expected DB state:** Eventually `outbound_queue.status='SENT'`, `send_attempts.state='DISPATCHED'`, `interactions` written, `outreach_drafts.lifecycle_state='SENT'`. All backfilled by reconciliation.
- **Expected workflow_events:** `worker_started` (new worker), `outbox_orphan_reset` (at 10:10), `dispatch_recovered_from_idempotency`, `send_delivered` (from webhook when Resend later sends `email.delivered`).
- **Failure mode:** Without reconciliation, the outbox row sits CLAIMED forever; the draft never reaches SENT state; the prospect received the email but the dashboard shows it stuck.
- **Test type:** Chaos. SIGKILL the worker mid-send.

---

## SECTION K — Final Opinionated Recommendation

### K.1 What should be autonomous by default

These workflows run end-to-end without human notification in steady state:

1. **Prospect ingestion** — adding rows from Apollo/imports, capped by daily Apollo budget.
2. **Enrichment** — Apollo+ZeroBounce population of contact/company fields, with 30-day re-enrich skip.
3. **Qualification** — PQS and LLM qualifier, both deterministic over enriched fields.
4. **Research refresh** — bounded by research budget cap; targeted at active outreach companies.
5. **Draft generation** — `DraftGenerator` continuously fills the queue; validator gates the output.
6. **Content validation** — the validator's verdict (PASS/QUARANTINE/HARD_REJECT) is fully autonomous.
7. **Draft approval (LOW risk)** — risk score 0–20, step ≤ 2, validator pass, no sibling traction → `actor_type='SYSTEM'` attestation.
8. **Send execution** — outbound queue + send_attempts; reconciliation handles orphan claims.
9. **Follow-up generation** — step-2 and step-3 for sequences with clean step-N-1 delivery.
10. **Reply classification (clear classes)** — bounce, unsubscribe, auto_reply with confidence > 0.85.
11. **Suppression (system-triggered)** — bounce, complaint, unsubscribe, departed all write `suppression_events` autonomously.
12. **Sequence pause (system-triggered)** — reply received → pause; bounce → abandon.
13. **Company traction detection** — pure read-side derivation; no action attached.
14. **Reporting and alerts** — daily/weekly cron summaries.

### K.2 What should always require human review

These never become autonomous regardless of risk score or confidence:

1. **Positive replies** — every positive-intent reply (booking interest, meeting request, "tell me more") is routed to HITL. The action — replying, scheduling, escalating — is human judgment.
2. **Question replies** — replies asking clarifying questions; HITL because the answer is contextual.
3. **HIGH-risk drafts** — risk score 51–80 across any combination of dimensions.
4. **Tier-1 company drafts** — `companies.engagement_tier='pmfg1'` always requires dual review.
5. **Sibling traction drafts** — any company where a sibling has shown engagement (open, click, reply) within 30 days.
6. **Sequence resume from positive-reply pause** — even if the prospect's intent looks negative on second read, restarting requires a human OK.
7. **Manual DNC (operator-initiated company-level suppression)** — high cross-impact action; requires the operator's identity attached.
8. **Drafts containing claims not registered in `content_claims`** — even if validator returns PASS on other passes, a quarantine claim is HITL.
9. **First-use sequence × tier combinations** — `new_sequence_type` dimension HIGH; reviewer validates the pairing once before autonomy is allowed.
10. **First 10 uses of a new content template** — same reasoning; review the template's first deployments.

### K.3 What should be blocked by policy

These actions are refused even with operator escalation; the schema or service layer rejects them:

1. **Modifying `outreach_drafts.body` or `subject` after `sent_at IS NOT NULL`** — DB trigger raises (Stage 4 D.6).
2. **Writing `approval_status='approved'` without an `approval_attestations` row** — DB CHECK constraint (Stage 4 D.3 + Stage 5 implementation).
3. **Sending to a contact in `SUPPRESSED_*` lifecycle state** — Layer 2 suppression gate is fail-closed (Section C).
4. **Re-engaging an `unsubscribed` contact** — `SUPPRESSED_UNSUBSCRIBED` is terminal; only path forward is a NEW contact record (creating a new logical identity is a manual operator action with full audit).
5. **Dispatching the same draft twice** — UNIQUE constraint on `outbound_queue.draft_id` + UNIQUE on `send_attempts(draft_id, attempt_number)` + Resend's `idempotency_key` (Stage 4 F.4).
6. **Approving the same draft twice (UPDATE re-attestation)** — `approval_attestations.draft_id` is UNIQUE; INSERT-only role.
7. **Auto-actioning a positive-class reply** — `ReplyService` halts on positive classification regardless of confidence.
8. **Generating a draft for a `lifecycle_state='CONVERTED'` contact** — `eligibility_view` excludes; CHECK on `outreach_drafts` insert.
9. **Sending outside the policy snapshot's send window** — Layer 3 policy gate.
10. **Approving a draft via a non-`approval_svc` role** — Postgres role grant violation.

### K.4 What should be allowed only by audited override

These are blocked by default; unlockable with documented justification, named auditor, and timestamped audit record:

1. **Overriding a HIGH-risk auto-approve refusal** — `request_override` + `audit_override` two-step (Section B.3); audit row in `approval_attestations.is_override=true`.
2. **Force-sending to a soft-suppressed contact** — e.g., `auto_reply` classification that the operator believes is misclassified. Requires `request_override`; audit captures reason; suppression event gets `revoked_at` set.
3. **Approving a draft with an unregistered claim** — operator can override after a second user registers the claim. Two human identities involved.
4. **Lifting an active `send_freezes` row early** — admin role, reason required, written to `workflow_events`.
5. **Setting `outreach_send_config.daily_limit` above a hard policy cap** — admin role, reason required, dual approval if cap is moving more than 2x the prior value.
6. **Re-queueing a `DEAD_LETTERED` outbox row** — operator action; writes `dead_letter_queue.resolved_by` and re-inserts to outbound_queue.
7. **Disabling the bounce-rate gate temporarily** — admin role, reason required, expires after 1h.
8. **Adding a contact to `SUPPRESSED_DO_NOT_CONTACT` at domain scope** — broad impact; requires admin + audit reason.
9. **Bulk re-verifying emails via ZeroBounce (> 100 contacts)** — budget impact; admin initiates with budget confirmation.
10. **Restarting an `ABANDONED` sequence** — operator confirms the original abandon reason no longer applies; written to `workflow_events`.

### K.5 What should be built first

Ranked. Each builds on the prior.

**1. Phase 1 schema hardening + `provider_events` + `workflow_events`.**
- *What:* The constraints and event tables that should already exist. UNIQUE on `(workspace_id, contact_id, sequence_name, sequence_step)`, CHECK on approval, immutability trigger, `provider_events` for webhook dedup, `workflow_events` as the append-only audit.
- *Why first:* Every other phase depends on the constraints holding the data clean. Webhook idempotency is also a precondition for trusting `interactions` counts. Cheapest set of changes with the highest blast-radius reduction.
- *What it unblocks:* All subsequent phases — without these, the new tables in Phase 2 reference invariants the existing schema doesn't enforce.

**2. Phase 2 `send_attempts` + `outbound_queue` dual-write.**
- *What:* New transactional outbox path; legacy `sent_at` continues to be canonical for 14 days; reconciliation detects drift.
- *Why second:* Eliminates the orphaned-claim risk that defines today's failure mode (Stage 1 H concurrency #2). Once the outbox exists, the worker process gets a clean target.
- *What it unblocks:* Phase 3 (`ApprovalService` writes to outbox in same transaction); Phase 6 (`worker:` process needs the outbox to consume).

**3. Phase 3 single `ApprovalService` + `approval_attestations` + Postgres roles.**
- *What:* All approval writes flow through one service; eight legacy writers consolidated; `?force=true` replaced by override two-step; risk scoring shipped (still shadow for auto-approve).
- *Why third:* Closes the seven-of-eight bypass paths. Once approvals are single-sourced, all subsequent autonomy decisions can trust the approval contract.
- *What it unblocks:* Phase 4 follow-up auto-approval; Phase 5 risk-based routing.

**4. `worker:` Procfile process + advisory lock singleton.**
- *What:* The scheduler moves out of the API process; one worker holds the advisory lock; API replicas can scale independently.
- *Why fourth:* Lifts the single biggest operational constraint (Stage 3 12.8 hard-stop on Railway replica = 1). Independent of Phases 1–3 work but cleanest to schedule after them.
- *What it unblocks:* Multi-replica API tier; future scale beyond the current single-replica posture.

**5. Phase 5 reply classification autonomy for clear classes.**
- *What:* Bounce, unsubscribe, auto_reply with confidence > 0.85 auto-action. Positive/question/negative continue to HITL.
- *Why fifth:* The single biggest reviewer-queue noise reduction. Replies are the workload; auto-handling the clear ones lets reviewers focus on the actionable ones.
- *What it unblocks:* The autonomous engine's "feels autonomous" milestone — operators stop drowning in low-value queue items.

### K.6 What should not be built yet

Tempting but premature:

**1. Kafka or any streaming platform.**
- *What:* Replace Postgres + APScheduler with Kafka topics for `provider_events`, `workflow_events`, etc.
- *Why premature:* Current scale < 1000 events/day. The Postgres outbox model (Section F.2) is provably correct, simpler to debug, and easier to backfill from. Streaming pays off when fan-out across many independent consumers requires it; ProspectIQ has one consumer per topic.
- *What must exist first:* Sustained > 10k events/day; multiple independent services consuming the same event types; or operational complexity that makes single-Postgres untenable.

**2. Microservices split (separate `approval`, `send`, `webhook`, `draft_gen` services).**
- *What:* Break the monolith into network-bounded services.
- *Why premature:* The Postgres transaction in `ApprovalService.approve()` (Section E.2) is the safety mechanism. Splitting services breaks the transaction across network — replacing it with sagas, eventual consistency, distributed tracing. Massive operational complexity for no measurable safety gain at current team size.
- *What must exist first:* A team large enough that independent deploy lanes matter more than transactional simplicity; or a customer-facing API surface where rate limiting and isolation actually matter.

**3. Custom ML risk model.**
- *What:* Train a custom model on historical reviewer decisions to predict approval/rejection.
- *Why premature:* Stage 5 Section B's deterministic 16-dimension risk score is auditable, explainable, and tunable. A custom model is none of those. The dimensions encode the reasoning a reviewer would apply; encoding them as scoring rules is correct now.
- *What must exist first:* Reviewer feedback that contradicts the current rules on a measurable axis ("you keep auto-approving X but I keep rejecting"). Then train on that signal.

**4. Multi-tenant data isolation redesign (database-per-tenant).**
- *What:* Move each workspace to its own Postgres database/schema.
- *Why premature:* RLS is the right model at this scale. The one cross-tenant risk identified (Stage 1 H tenant leak in `process_webhook_event`) is fixed by routing through the adapter layer (Section G); does not require schema isolation.
- *What must exist first:* Compliance requirement that mandates physical isolation (most SOC2 / SOC2 Type II inspections are satisfied by logical isolation with proven RLS); or a workspace whose data volume is large enough to dominate query performance.

**5. Full event sourcing (rebuild projections from `workflow_events`).**
- *What:* Replace `outreach_drafts`, `contacts`, `companies` tables with read-side projections regenerated from `workflow_events` on demand.
- *Why premature:* The platform documented elsewhere (the Digitillis main platform) is event-sourced; ProspectIQ is not. Converting is a multi-month rewrite. `workflow_events` is an audit log, not the source of truth — by design (Stage 4 B.4).
- *What must exist first:* A compelling product reason to support time-travel queries ("show me the contact state as of 2 weeks ago") that can't be served by snapshots or by querying `workflow_events` directly.

### K.7 Minimum viable architecture for safe scale

The minimum to run autonomously at 50 sends per day without operator surveillance, summarized in one paragraph:

ProspectIQ at the autonomy minimum runs the existing FastAPI `web:` process plus one new `worker:` process holding a `pg_try_advisory_lock` singleton. Schema gains four required tables: `provider_events` (UNIQUE on `(provider, external_event_id)`) so webhook replays dedup; `outbound_queue` (UNIQUE on `draft_id`) so the worker claims exactly once via `SELECT FOR UPDATE SKIP LOCKED`; `send_attempts` (per-attempt state, FK to outbound_queue) so the worker's dispatch is recoverable across crashes via reconciliation that queries Resend by `idempotency_key`; `approval_attestations` (UNIQUE on `draft_id`) plus a CHECK on `outreach_drafts.approval_status='approved' ⇒ approval_attestation_id IS NOT NULL` so the schema rejects unsigned approvals. Application code consolidates around `ApprovalService.approve()` (one writer, one transaction that inserts both attestation and outbox row) and `SendWorker.poll_outbox()` (claim → assertions → Resend → second transaction). Webhooks become two lines of code: `INSERT INTO provider_events ON CONFLICT DO NOTHING` followed by deferring processing to the worker. The current `pre_send_assertions.py` stays unchanged; it just runs at claim time instead of generation time. The operator scripts are deleted; risk scoring runs in shadow mode initially and is hand-checked against a sample of 100 drafts before enabling auto-approve for LOW-bucket step-1 drafts. **This minimum does NOT need:** the content claims registry (the existing integrity regex catches the most common fabrications at this volume), `draft_content_versions` (the immutability trigger on `outreach_drafts.body` is enough for 50/day), full state machine triggers on contacts/companies/sequences (Phase 7 is the polish phase), or Kafka/microservices/Temporal. The architecture above eliminates the seven highest-risk failure modes (orphaned claims, double-send, unsigned approval, body mutation, webhook double-write, multi-replica scheduler collisions, body-after-send modification) using ten new constraints and ~600 lines of new application code. Everything else in this Stage 5 document is layered on top once this minimum is proven safe in production.
