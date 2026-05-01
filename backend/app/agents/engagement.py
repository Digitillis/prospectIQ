"""Engagement Agent — Sequence orchestration + Resend delivery.

Handles:
- Sending approved outreach via Resend
- Managing multi-stage engagement sequences
- Processing webhook events (opens, clicks, replies, bounces)
- Generating follow-up drafts when sequences are due

Delivery architecture:
- FROM address and sender identity configured in config/outreach_guidelines.yaml (sender section)
- Full per-lead custom subject + body — no template variable limitations
- Replies land in the sender's inbox
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from rich.console import Console

from backend.app.agents.base import BaseAgent, AgentResult
from backend.app.core.config import get_settings, get_sequences_config
from backend.app.integrations.instantly import InstantlyClient

console = Console()
logger = logging.getLogger(__name__)


class EngagementAgent(BaseAgent):
    """Orchestrate email delivery and multi-stage engagement sequences."""

    agent_name = "engagement"

    def run(
        self,
        action: str = "send_approved",
        campaign_name: str | None = None,
    ) -> AgentResult:
        """Execute engagement actions.

        Args:
            action: One of:
                - "send_approved": Send all approved outreach drafts via Resend
                - "process_due": Process sequences with due follow-ups
                - "check_status": Check and log campaign analytics
            campaign_name: Instantly campaign name (created if not exists).

        Returns:
            AgentResult with engagement stats.
        """
        if action == "send_approved":
            return self._send_approved_drafts(campaign_name)
        elif action == "process_due":
            return self._process_due_sequences()
        elif action == "jit_pregenerate":
            return self._jit_pregenerate_upcoming()
        elif action == "check_status":
            return self._check_campaign_status()
        elif action == "poll_events":
            return self._poll_instantly_events()
        else:
            result = AgentResult()
            result.success = False
            result.add_detail("N/A", "error", f"Unknown action: {action}")
            return result

    def _load_send_config(self) -> dict:
        """Load send limits from outreach_send_config table.

        Falls back to safe defaults if table doesn't exist yet.
        Returns: {daily_limit, batch_size, min_gap_minutes, send_enabled}
        """
        defaults = {"daily_limit": 30, "batch_size": 10, "min_gap_minutes": 4, "send_enabled": True}
        try:
            row = (
                self.db.client.table("outreach_send_config")
                .select("daily_limit, batch_size, min_gap_minutes, send_enabled")
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

    def _count_sent_today(self) -> int:
        """Count emails already sent today (UTC date)."""
        from datetime import date
        today = date.today().isoformat()
        try:
            r = (
                self.db.client.table("outreach_drafts")
                .select("id", count="exact")
                .gte("sent_at", f"{today}T00:00:00")
                .execute()
            )
            return r.count or 0
        except Exception:
            return 0

    def _send_approved_drafts(self, campaign_name: str | None = None) -> AgentResult:
        """Send approved unsent outreach drafts via Resend.

        Limits are read from outreach_send_config table (not hardcoded):
        - daily_limit: max emails per calendar day
        - batch_size:  max emails per scheduler run
        - min_gap_minutes: stagger between sends within a batch

        FROM address is read from config/outreach_guidelines.yaml (sender.email).
        """
        result = AgentResult()

        settings = get_settings()
        if not settings.send_enabled:
            console.print(
                "[yellow]SEND_ENABLED is false — drafts staged but not sent.[/yellow]"
            )
            return result

        # Load Resend API key: workspace credential store first, then env var
        from backend.app.core.credential_store import get_credential
        resend_api_key = get_credential("resend", "api_key", self.db.workspace_id) or settings.resend_api_key
        if not resend_api_key:
            console.print("[red]Resend API key not configured. Cannot send.[/red]")
            result.success = False
            return result

        # Load limits from DB — no hardcoding
        send_cfg = self._load_send_config()
        daily_limit = send_cfg["daily_limit"]
        batch_size  = send_cfg["batch_size"]

        # Check daily cap before fetching drafts
        sent_today = self._count_sent_today()
        remaining_today = daily_limit - sent_today
        if remaining_today <= 0:
            console.print(
                f"[yellow]Daily limit reached ({sent_today}/{daily_limit}). No sends.[/yellow]"
            )
            return result

        import hashlib
        import resend
        resend.api_key = resend_api_key

        # Load sender pool: DB (outreach_send_config) → YAML → hardcoded fallback
        # Priority: workspace DB config > outreach_guidelines.yaml > defaults
        _reply_to = "avi@digitillis.io"
        _sender_pool: list[dict] = []
        _fallback_address = "avi@digitillis.io"
        _fallback_display = "Avanish Mehrotra <avi@digitillis.io>"

        # 1. Try DB send config (set per workspace via API/UI)
        try:
            db_cfg_row = (
                self.db.client.table("outreach_send_config")
                .select("sender_pool, reply_to")
                .eq("workspace_id", self.db.workspace_id)
                .limit(1)
                .execute()
            ).data
            if db_cfg_row and db_cfg_row[0].get("sender_pool"):
                _sender_pool = db_cfg_row[0]["sender_pool"] or []
            if db_cfg_row and db_cfg_row[0].get("reply_to"):
                _reply_to = db_cfg_row[0]["reply_to"]
        except Exception:
            pass

        # 2. Fall back to YAML if DB pool is empty
        if not _sender_pool:
            try:
                from backend.app.core.config import get_outreach_guidelines
                _guidelines = get_outreach_guidelines()
                _pool_cfg = _guidelines.get("sender_pool", {})
                _reply_to = _pool_cfg.get("reply_to", _reply_to)
                _sender_pool = _pool_cfg.get("senders", [])
                _s = _guidelines.get("sender", {})
                _e = _s.get("email", "")
                _n = _s.get("name", "")
                if _e:
                    _fallback_address = _e
                    _fallback_display = f"{_n} <{_e}>" if _n else _e
            except Exception:
                pass

        def _pick_sender(contact_email: str) -> tuple[str, str]:
            """Return (from_address, from_display) deterministically from pool."""
            if not _sender_pool:
                return _fallback_address, _fallback_display
            idx = int(hashlib.md5(contact_email.lower().encode()).hexdigest(), 16) % len(_sender_pool)
            s = _sender_pool[idx]
            addr = s.get("email", _fallback_address)
            name = s.get("name", "")
            display = f"{name} <{addr}>" if name else addr
            return addr, display

        # Ensure workspace_id is set on the DB instance so outreach_state_log
        # inserts (which have a NOT NULL workspace_id constraint) succeed in
        # scheduler context where no auth token propagates it automatically.
        if not self.db.workspace_id:
            self.db.workspace_id = settings.default_workspace_id

        # Fetch a larger candidate pool so blocked drafts (suppressed / locked
        # companies) don't silently consume all batch slots. The oldest drafts
        # are checked first; we stop sending once batch_size emails have gone out.
        send_limit = min(batch_size, max(0, remaining_today))
        # Fetch up to 5× the send limit so there are enough candidates even if
        # most are suppressed or locked.
        fetch_limit = min(send_limit * 5, max(0, remaining_today) + 40)
        drafts = (
            self.db.client.table("outreach_drafts")
            .select("*, companies(name, tier, campaign_cluster), contacts(full_name, email, first_name, last_name, company_id, persona_type)")
            .eq("approval_status", "approved")
            .is_("sent_at", "null")
            .eq("channel", "email")
            .not_.is_("subject", "null")
            .neq("subject", "")
            .order("created_at")
            .limit(fetch_limit)
            .execute()
            .data
        )

        if not drafts:
            console.print("[yellow]No approved email drafts to send.[/yellow]")
            return result

        console.print(
            f"[cyan]Checking up to {fetch_limit} draft candidates, sending up to {send_limit} "
            f"(batch_size={batch_size}, {sent_today}/{daily_limit} sent today)...[/cyan]"
        )

        # Track companies sent in this batch to prevent same-run multi-contact collision
        company_ids_sent_this_batch: set[str] = set()
        sent_this_batch = 0

        for draft in drafts:
            if sent_this_batch >= send_limit:
                break
            contact = draft.get("contacts", {}) or {}
            company = draft.get("companies", {}) or {}
            company_name = company.get("name", "Unknown")
            contact_email = contact.get("email")
            company_id = draft["company_id"]

            if not contact_email:
                console.print(f"  [yellow]{company_name}: No email for contact. Skipping.[/yellow]")
                result.skipped += 1
                continue

            # Suppression check — pass skip_duplicate_check=True so the approved
            # draft being sent doesn't trigger the duplicate_draft_pending guard
            from backend.app.core.suppression import is_suppressed
            suppressed, reason = is_suppressed(
                self.db, company_id,
                contact_id=draft.get("contact_id"),
                skip_duplicate_check=True,
            )
            if suppressed:
                console.print(f"  [dim]{company_name}: Suppressed ({reason}). Skipping.[/dim]")
                result.skipped += 1
                continue

            # Company-level send lock — two guards:
            # 1. In-batch: already sent another contact at this company in this run
            # 2. Cross-run: another contact at this company was emailed in the last 24h
            if company_id in company_ids_sent_this_batch:
                console.print(f"  [dim]{company_name}: already sent to another contact this batch. Skipping.[/dim]")
                result.skipped += 1
                continue

            from backend.app.core.channel_coordinator import is_company_locked
            locked, lock_reason = is_company_locked(
                self.db, company_id, exclude_contact_id=draft.get("contact_id")
            )
            if locked:
                console.print(f"  [dim]{company_name}: company locked ({lock_reason}). Skipping.[/dim]")
                result.skipped += 1
                continue

            subject = draft.get("subject", "")
            body = draft.get("edited_body") or draft.get("body", "")

            try:
                # Atomically claim the draft by setting sent_at before calling Resend.
                # This prevents two concurrent scheduler instances from double-sending
                # the same draft (race condition during Railway rolling redeploys).
                now = datetime.now(timezone.utc).isoformat()
                claim = (
                    self.db.client.table("outreach_drafts")
                    .update({"sent_at": now})
                    .eq("id", draft["id"])
                    .is_("sent_at", "null")  # only succeeds if not already claimed
                    .execute()
                )
                if not claim.data:
                    # Another instance already claimed this draft — skip
                    console.print(f"  [dim]{company_name}: draft already claimed by another instance. Skipping.[/dim]")
                    result.skipped += 1
                    continue

                from backend.app.utils.email_html import plain_to_html
                _from_address, _from_display = _pick_sender(contact_email)
                # Pass draft ID as idempotency key — Resend will deduplicate on
                # their end if this exact key was already sent (belt-and-suspenders
                # on top of the DB atomic claim above).
                send_response = resend.Emails.send(
                    {
                        "from": _from_display,
                        "to": [contact_email],
                        "reply_to": [_reply_to],
                        "subject": subject,
                        "html": plain_to_html(body),
                        "text": body,
                    },
                    {"idempotency_key": draft["id"]},
                )

                # Store Resend message ID for webhook correlation
                resend_id = getattr(send_response, "id", None) or (
                    send_response.get("id") if isinstance(send_response, dict) else None
                )
                if resend_id:
                    try:
                        self.db.update_outreach_draft(draft["id"], {"resend_message_id": resend_id})
                    except Exception:
                        pass

                # Log interaction — use default_workspace_id directly since scheduler
                # runs without auth context (_inject_ws would inject null)
                from backend.app.core.config import get_settings as _get_settings
                _settings = _get_settings()
                self.db.client.table("interactions").insert({
                    "company_id": draft["company_id"],
                    "contact_id": draft["contact_id"],
                    "type": "email_sent",
                    "channel": "email",
                    "subject": subject,
                    "body": body,
                    "source": "resend",
                    "workspace_id": _settings.default_workspace_id,
                    "metadata": {
                        "from": _from_address,
                        "reply_to": _reply_to,
                        "sequence_name": draft.get("sequence_name"),
                        "sequence_step": draft.get("sequence_step"),
                    },
                }).execute()

                # Update company status
                self.db.update_company(draft["company_id"], {"status": "contacted"})

                # Create engagement sequence record
                seq_config = get_sequences_config()
                sequence = seq_config["sequences"].get(draft.get("sequence_name", "initial_outreach"), {})
                total_steps = sequence.get("total_steps", 5)
                current_step = draft.get("sequence_step", 1)

                next_step = current_step + 1
                next_action_at = None
                next_action_type = None

                if next_step <= total_steps:
                    for step in sequence.get("steps", []):
                        if step["step"] == next_step:
                            delay = step.get("delay_days", 3)
                            next_action_at = (
                                datetime.now(timezone.utc) + timedelta(days=delay)
                            ).isoformat()
                            next_action_type = f"send_{step['channel']}"
                            break

                self.db.insert_engagement_sequence({
                    "company_id": draft["company_id"],
                    "contact_id": draft["contact_id"],
                    "sequence_name": draft.get("sequence_name", "initial_outreach"),
                    "current_step": current_step,
                    "total_steps": total_steps,
                    "status": "active" if next_step <= total_steps else "completed",
                    "next_action_at": next_action_at,
                    "next_action_type": next_action_type,
                    "started_at": now,
                })

                # Advance contact state machine: enriched → touch_N_sent
                _step = max(1, min(int(draft.get("sequence_step") or 1), 5))
                try:
                    self.db.update_contact_state(
                        contact_id=draft["contact_id"],
                        new_state=f"touch_{_step}_sent",
                        channel="email",
                        instantly_event="email_sent",
                        metadata={
                            "sequence_step": _step,
                            "resend_message_id": resend_id,
                            "sequence_name": draft.get("sequence_name"),
                        },
                        extra_updates={
                            "last_touch_channel": "email",
                            "last_touch_at": now,
                        },
                    )
                except Exception as _e:
                    logger.warning(f"update_contact_state failed (non-fatal): {_e}")

                company_ids_sent_this_batch.add(company_id)
                sent_this_batch += 1
                console.print(f"  [green]{company_name} → {contact_email}: Sent[/green]")
                result.processed += 1
                result.add_detail(company_name, "sent", f"To: {contact_email}")

            except Exception as e:
                logger.error(f"Error sending to {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        return result

    # ------------------------------------------------------------------
    # Condition evaluation helpers (Phase 3 — runtime branching)
    # ------------------------------------------------------------------

    def _get_contact_engagement(self, contact_id: str) -> dict:
        """Return a summary of engagement events for a contact (opens, clicks, replies)."""
        try:
            rows = (
                self.db.client.table("interactions")
                .select("type")
                .eq("contact_id", contact_id)
                .in_("type", ["email_opened", "email_clicked", "email_replied", "reply_received"])
                .execute()
                .data or []
            )
            types = {r["type"] for r in rows}
            return {
                "opened":  bool(types & {"email_opened"}),
                "clicked": bool(types & {"email_clicked"}),
                "replied": bool(types & {"email_replied", "reply_received"}),
            }
        except Exception:
            return {"opened": False, "clicked": False, "replied": False}

    def _evaluate_condition(self, step: dict, contact_id: str, contact_pqs: float = 0.0) -> bool:
        """Evaluate a condition step and return True (branch_yes) or False (branch_no)."""
        ctype = step.get("condition_type", "if_opened")
        engagement = self._get_contact_engagement(contact_id)
        if ctype == "if_opened":
            return engagement["opened"]
        elif ctype == "if_replied":
            return engagement["replied"]
        elif ctype == "if_clicked":
            return engagement["clicked"]
        elif ctype == "if_pqs_above":
            threshold = float(step.get("condition_value") or 50)
            return contact_pqs >= threshold
        return False

    def _find_step_index_by_id(self, steps: list, step_id: str | None) -> int | None:
        """Return 0-based index of step with given step_id, or None."""
        if not step_id:
            return None
        for i, s in enumerate(steps):
            if s.get("step_id") == step_id:
                return i
        return None

    # ------------------------------------------------------------------
    # Sequence execution
    # ------------------------------------------------------------------

    def _process_due_sequences(self) -> AgentResult:
        """Process engagement sequences with due follow-up actions.

        Handles both V1 (YAML-based) and V2 (campaign_sequence_definitions_v2) sequences.
        V2 sequences support runtime conditional branching.
        """
        result = AgentResult()

        now = datetime.now(timezone.utc).isoformat()
        due_sequences = self.db.get_active_sequences(due_before=now)

        if not due_sequences:
            console.print("[yellow]No sequences due for action.[/yellow]")
            return result

        console.print(f"[cyan]Processing {len(due_sequences)} due sequence actions...[/cyan]")

        for seq in due_sequences:
            company = seq.get("companies", {}) or {}
            contact = seq.get("contacts", {}) or {}
            company_name = company.get("name", "Unknown")

            try:
                seq_name = seq["sequence_name"]
                contact_id = seq.get("contact_id")

                # ----------------------------------------------------------------
                # Try to load as a V2 sequence (UUID name stored in sequence_name)
                # ----------------------------------------------------------------
                v2_def = None
                try:
                    v2_result = (
                        self.db.client.table("campaign_sequence_definitions_v2")
                        .select("*")
                        .eq("id", seq_name)
                        .execute()
                    )
                    if v2_result.data:
                        v2_def = v2_result.data[0]
                except Exception:
                    pass

                if v2_def:
                    # ---- V2 path: step_id-based navigation with branching ----
                    v2_steps: list = v2_def.get("steps") or []
                    current_step_id: str | None = seq.get("metadata", {}).get("current_step_id") if seq.get("metadata") else None

                    # Find current position
                    if current_step_id:
                        current_idx = self._find_step_index_by_id(v2_steps, current_step_id)
                        current_idx = (current_idx or 0) + 1  # advance
                    else:
                        current_idx = 0  # first run

                    if current_idx >= len(v2_steps):
                        # All steps done
                        self.db.update_engagement_sequence(seq["id"], {
                            "status": "completed",
                            "completed_at": now,
                        })
                        result.processed += 1
                        result.add_detail(company_name, "completed", "V2 sequence finished")
                        continue

                    step_def = v2_steps[current_idx]
                    stype = step_def.get("step_type", "email")

                    # Condition step — evaluate and branch
                    if stype == "condition":
                        pqs = float(contact.get("pqs_total") or 0)
                        branch_taken = self._evaluate_condition(step_def, contact_id or "", pqs)
                        branch_step_id = step_def.get("branch_yes") if branch_taken else step_def.get("branch_no")
                        next_idx = self._find_step_index_by_id(v2_steps, branch_step_id)
                        if next_idx is None:
                            next_idx = current_idx + 1  # fallback: just advance
                        # Jump to the branched step by updating metadata
                        if next_idx < len(v2_steps):
                            next_step_def = v2_steps[next_idx]
                            delay = next_step_def.get("wait_days") or 0
                            next_at = (datetime.now(timezone.utc) + timedelta(days=delay)).isoformat()
                            self.db.update_engagement_sequence(seq["id"], {
                                "current_step": next_idx,
                                "next_action_at": next_at,
                                "metadata": {**(seq.get("metadata") or {}), "current_step_id": next_step_def["step_id"]},
                            })
                        else:
                            self.db.update_engagement_sequence(seq["id"], {"status": "completed", "completed_at": now})
                        branch_label = "YES" if branch_taken else "NO"
                        result.processed += 1
                        result.add_detail(company_name, f"condition_{branch_label}", step_def.get("condition_type", ""))
                        continue

                    # Wait step — schedule next action
                    if stype == "wait":
                        delay = step_def.get("wait_days") or 1
                        next_at = (datetime.now(timezone.utc) + timedelta(days=delay)).isoformat()
                        next_idx = current_idx + 1
                        next_step_id = v2_steps[next_idx]["step_id"] if next_idx < len(v2_steps) else None
                        self.db.update_engagement_sequence(seq["id"], {
                            "current_step": next_idx,
                            "next_action_at": next_at,
                            "metadata": {**(seq.get("metadata") or {}), "current_step_id": next_step_id},
                            "status": "active" if next_step_id else "completed",
                        })
                        result.processed += 1
                        result.add_detail(company_name, "wait", f"{delay}d")
                        continue

                    # Email / LinkedIn / Task step
                    if stype == "email":
                        from backend.app.agents.outreach import OutreachAgent
                        outreach = OutreachAgent(batch_id=self.batch_id)
                        outreach.run(
                            company_ids=[seq["company_id"]],
                            sequence_name=seq_name,
                            sequence_step=current_idx + 1,
                        )
                    elif stype == "linkedin":
                        self.db.insert_interaction({
                            "company_id": seq["company_id"],
                            "contact_id": contact_id,
                            "type": "linkedin_message",
                            "channel": "linkedin",
                            "subject": f"LinkedIn touch — V2 step {current_idx + 1}",
                            "body": step_def.get("body_template", ""),
                            "source": "system",
                            "metadata": {"action_required": "manual", "sequence_id": seq_name},
                        })
                    elif stype == "task":
                        self.db.insert_interaction({
                            "company_id": seq["company_id"],
                            "contact_id": contact_id,
                            "type": "task",
                            "channel": "internal",
                            "subject": step_def.get("task_description", "Follow-up task"),
                            "body": step_def.get("task_description", ""),
                            "source": "system",
                        })

                    # Advance to next step
                    next_idx = current_idx + 1
                    if next_idx < len(v2_steps):
                        next_step_def = v2_steps[next_idx]
                        delay = next_step_def.get("wait_days") or 1
                        next_at = (datetime.now(timezone.utc) + timedelta(days=delay)).isoformat()
                        self.db.update_engagement_sequence(seq["id"], {
                            "current_step": next_idx,
                            "next_action_at": next_at,
                            "metadata": {**(seq.get("metadata") or {}), "current_step_id": next_step_def["step_id"]},
                            "status": "active",
                        })
                    else:
                        self.db.update_engagement_sequence(seq["id"], {"status": "completed", "completed_at": now})

                    result.processed += 1
                    result.add_detail(company_name, f"v2_step_{current_idx + 1}", stype)
                    continue

                # ----------------------------------------------------------------
                # V1 path: YAML sequence (original logic)
                # ----------------------------------------------------------------
                next_step = seq["current_step"] + 1
                seq_config = get_sequences_config()
                sequence = seq_config["sequences"].get(seq_name, {})

                step_config = None
                for step in sequence.get("steps", []):
                    if step["step"] == next_step:
                        step_config = step
                        break

                if not step_config:
                    self.db.update_engagement_sequence(seq["id"], {
                        "status": "completed",
                        "completed_at": now,
                    })
                    result.processed += 1
                    result.add_detail(company_name, "completed", "Sequence finished")
                    continue

                # channel is defined at sequence level, not per-step in most YAML sequences
                channel = step_config.get("channel") or sequence.get("channel", "email")

                if channel == "email":
                    # Check for a prospect reply to inject as context
                    reply_ctx = self._get_latest_reply_context(seq.get("contact_id"))

                    # Auto-stop sequence if prospect unsubscribed or bounced
                    if reply_ctx and reply_ctx.get("stop_sequence"):
                        self.db.update_engagement_sequence(seq["id"], {
                            "status": "completed",
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        })
                        console.print(f"  [yellow]{company_name}: Sequence stopped ({reply_ctx['reason']})[/yellow]")
                        result.processed += 1
                        result.add_detail(company_name, "stopped", reply_ctx["reason"])
                        continue

                    from backend.app.agents.outreach import OutreachAgent
                    outreach = OutreachAgent(batch_id=self.batch_id)
                    outreach_result = outreach.run(
                        company_ids=[seq["company_id"]],
                        sequence_name=seq_name,
                        sequence_step=next_step,
                        reply_context=reply_ctx.get("context_str") if reply_ctx else None,
                    )
                    if outreach_result.processed > 0:
                        label = "reply-aware " if reply_ctx else ""
                        console.print(f"  [green]{company_name}: {label}Follow-up draft created (step {next_step}, email)[/green]")
                    else:
                        console.print(f"  [yellow]{company_name}: Could not generate follow-up[/yellow]")

                elif channel == "linkedin":
                    console.print(f"  [bold cyan]{company_name}: LinkedIn touch needed (step {next_step}) → {contact.get('full_name', 'Unknown')}[/bold cyan]")
                    self.db.insert_interaction({
                        "company_id": seq["company_id"],
                        "contact_id": seq["contact_id"],
                        "type": "linkedin_connection" if next_step <= 2 else "linkedin_message",
                        "channel": "linkedin",
                        "subject": f"LinkedIn touch — Step {next_step}",
                        "body": step_config.get("instructions", {}).get("approach", ""),
                        "source": "system",
                        "metadata": {"action_required": "manual", "sequence_name": seq_name, "sequence_step": next_step},
                    })

                further_step = next_step + 1
                next_next_action_at = None
                next_next_type = None

                if further_step <= seq["total_steps"]:
                    for step in sequence.get("steps", []):
                        if step["step"] == further_step:
                            delay = step.get("delay_days", 3)
                            next_next_action_at = (datetime.now(timezone.utc) + timedelta(days=delay)).isoformat()
                            next_next_type = f"send_{step.get('channel') or sequence.get('channel', 'email')}"
                            break

                self.db.update_engagement_sequence(seq["id"], {
                    "current_step": next_step,
                    "next_action_at": next_next_action_at,
                    "next_action_type": next_next_type,
                    "status": "active" if further_step <= seq["total_steps"] else "completed",
                })

                result.processed += 1
                result.add_detail(company_name, f"step_{next_step}", f"Channel: {channel}")

            except Exception as e:
                logger.error(f"Error processing sequence for {company_name}: {e}", exc_info=True)
                result.errors += 1
                result.add_detail(company_name, "error", str(e)[:200])

        return result

    def _get_latest_reply_context(self, contact_id: str | None) -> dict | None:
        """Return reply context dict for a contact, or None if no reply exists.

        Returns dict with:
          - context_str: formatted string to inject into prompt
          - stop_sequence: True if sequence should stop (unsubscribe/bounce)
          - reason: human-readable reason for stop
        """
        if not contact_id:
            return None
        try:
            result = (
                self.db.client.table("thread_messages")
                .select("body, classification, direction, created_at")
                .eq("direction", "inbound")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            # Filter by contact via campaign_threads join
            thread_result = (
                self.db.client.table("campaign_threads")
                .select("id")
                .eq("contact_id", contact_id)
                .execute()
            )
            thread_ids = [t["id"] for t in (thread_result.data or [])]
            if not thread_ids:
                return None

            msg_result = (
                self.db.client.table("thread_messages")
                .select("body, classification, direction, created_at")
                .in_("thread_id", thread_ids)
                .eq("direction", "inbound")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not msg_result.data:
                return None

            msg = msg_result.data[0]
            classification = msg.get("classification") or "other"
            body = msg.get("body", "").strip()

            # Stop sequence for these classifications
            if classification in ("unsubscribe", "bounce"):
                return {"stop_sequence": True, "reason": classification, "context_str": None}

            intent_labels = {
                "interested": "INTERESTED — they want to learn more",
                "objection": "OBJECTION — they raised a concern",
                "referral": "REFERRAL — they pointed you to someone else",
                "soft_no": "NOT INTERESTED RIGHT NOW — not a hard no",
                "out_of_office": "OUT OF OFFICE — auto-reply",
                "other": "REPLIED — intent unclear",
            }
            intent_label = intent_labels.get(classification, "REPLIED")
            context_str = (
                f'Intent: {intent_label}\n'
                f'Their message: "{body[:600]}"'
            )
            return {"stop_sequence": False, "context_str": context_str, "reason": classification}

        except Exception as exc:
            logger.debug("_get_latest_reply_context failed: %s", exc)
            return None

    def _jit_pregenerate_upcoming(self) -> AgentResult:
        """JIT pre-generate: create drafts for sequences due within 3 days.

        Runs daily. For each active sequence where next_action_at is within
        3 days, generates the follow-up draft NOW so it appears in the approval
        queue in time. This is the JIT mechanism — drafts are generated just
        before they're needed, not upfront.

        Respects reply context: if a prospect replied, the draft is generated
        with that context injected so it can be reviewed and approved.
        """
        result = AgentResult()
        now = datetime.now(timezone.utc)
        window_end = (now + timedelta(days=3)).isoformat()

        # Get sequences due within 3 days that haven't already generated a pending draft
        try:
            seq_result = (
                self.db._filter_ws(
                    self.db.client.table("engagement_sequences")
                    .select("*, companies(name), contacts(full_name, email)")
                )
                .eq("status", "active")
                .lte("next_action_at", window_end)
                .gte("next_action_at", now.isoformat())
                .execute()
            )
        except Exception as e:
            logger.error("JIT pregenerate: failed to fetch due sequences: %s", e)
            result.success = False
            return result

        sequences = seq_result.data or []
        if not sequences:
            console.print("[dim]JIT pregenerate: no sequences due within 3 days[/dim]")
            return result

        console.print(f"[cyan]JIT pregenerate: {len(sequences)} sequence(s) due within 3 days[/cyan]")

        seq_config = get_sequences_config()

        for seq in sequences:
            company_id = seq["company_id"]
            contact_id = seq["contact_id"]
            seq_name = seq["sequence_name"]
            current_step = seq.get("current_step", 1)
            next_step = current_step + 1
            company = seq.get("companies") or {}
            contact = seq.get("contacts") or {}
            company_name = company.get("name", company_id[:8])

            try:
                # Check if a pending draft already exists for this contact + step
                existing = (
                    self.db._filter_ws(
                        self.db.client.table("outreach_drafts").select("id")
                    )
                    .eq("company_id", company_id)
                    .eq("contact_id", contact_id)
                    .eq("sequence_step", next_step)
                    .eq("approval_status", "pending")
                    .is_("sent_at", "null")
                    .execute()
                )
                if existing.data:
                    console.print(f"  [dim]{company_name}: Step {next_step} draft already pending — skipping[/dim]")
                    result.skipped += 1
                    continue

                # Load the sequence definition to validate the step exists
                sequence_def = seq_config.get("sequences", {}).get(seq_name, {})
                step_exists = any(s["step"] == next_step for s in sequence_def.get("steps", []))
                if not step_exists:
                    console.print(f"  [dim]{company_name}: No step {next_step} in {seq_name} — sequence complete[/dim]")
                    self.db.update_engagement_sequence(seq["id"], {
                        "status": "completed",
                        "completed_at": now.isoformat(),
                    })
                    result.skipped += 1
                    continue

                # Check for reply context
                reply_ctx = self._get_latest_reply_context(contact_id)
                if reply_ctx and reply_ctx.get("stop_sequence"):
                    self.db.update_engagement_sequence(seq["id"], {
                        "status": "completed",
                        "completed_at": now.isoformat(),
                    })
                    console.print(f"  [yellow]{company_name}: Stopped ({reply_ctx['reason']})[/yellow]")
                    result.processed += 1
                    continue

                # Generate the draft JIT
                from backend.app.agents.outreach import OutreachAgent
                outreach = OutreachAgent(batch_id=self.batch_id)
                outreach_result = outreach.run(
                    company_ids=[company_id],
                    sequence_name=seq_name,
                    sequence_step=next_step,
                    reply_context=reply_ctx.get("context_str") if reply_ctx else None,
                )

                if outreach_result.processed > 0:
                    label = "[reply-aware] " if reply_ctx else ""
                    due_date = seq["next_action_at"][:10]
                    console.print(
                        f"  [green]{company_name}: {label}Step {next_step} draft generated "
                        f"(due {due_date}) → approval queue[/green]"
                    )
                    result.processed += 1
                    result.add_detail(company_name, f"jit_step_{next_step}", "draft created")
                else:
                    console.print(f"  [yellow]{company_name}: Could not generate step {next_step}[/yellow]")
                    result.errors += 1

            except Exception as e:
                logger.error(f"JIT pregenerate error for {company_name}: {e}", exc_info=True)
                result.errors += 1

        return result

    def _check_campaign_status(self) -> AgentResult:
        """Check Instantly.ai campaign analytics and update engagement scores."""
        result = AgentResult()

        with InstantlyClient() as instantly:
            campaigns = instantly.list_campaigns()

            if not campaigns:
                console.print("[yellow]No Instantly campaigns found.[/yellow]")
                return result

            console.print(f"[cyan]Checking {len(campaigns)} campaigns...[/cyan]")

            for campaign in campaigns:
                campaign_id = campaign.get("id")
                campaign_name = campaign.get("name", "Unknown")

                try:
                    analytics = instantly.get_campaign_analytics(campaign_id)

                    sent = analytics.get("sent", 0)
                    opened = analytics.get("opened", 0)
                    replied = analytics.get("replied", 0)
                    bounced = analytics.get("bounced", 0)

                    open_rate = (opened / sent * 100) if sent > 0 else 0
                    reply_rate = (replied / sent * 100) if sent > 0 else 0

                    console.print(
                        f"  {campaign_name}: "
                        f"Sent={sent} Opened={opened} ({open_rate:.1f}%) "
                        f"Replied={replied} ({reply_rate:.1f}%) "
                        f"Bounced={bounced}"
                    )

                    result.processed += 1
                    result.add_detail(
                        campaign_name,
                        "analytics",
                        f"Sent={sent}, Open={open_rate:.1f}%, Reply={reply_rate:.1f}%",
                    )

                except Exception as e:
                    logger.error(f"Error checking campaign {campaign_name}: {e}")
                    result.errors += 1

        return result

    def _poll_instantly_events(self) -> AgentResult:
        """Poll Instantly.ai for lead-level activity and sync to database.

        The Instantly v2 API does not support bulk lead listing. Instead we
        poll individually: query our DB for contacts with sent drafts, then
        call get_lead_status(email) for each one to detect new opens/clicks/
        replies/bounces.

        Idempotent: checks existing interactions before creating new ones so
        repeated polls never produce duplicate records.

        Returns:
            AgentResult summarising new events detected.
        """
        import time as _time

        result = AgentResult()

        # Find all contacts that have at least one sent draft
        sent_rows = (
            self.db.client.table("outreach_drafts")
            .select("contact_id, contacts(id, email, company_id)")
            .not_.is_("sent_at", "null")
            .execute()
            .data
        )

        # Deduplicate by contact_id
        seen: set[str] = set()
        contacts_to_poll: list[dict] = []
        for row in sent_rows:
            contact = row.get("contacts") or {}
            contact_id = contact.get("id") or row.get("contact_id")
            email = (contact.get("email") or "").lower().strip()
            if not email or not contact_id or contact_id in seen:
                continue
            seen.add(contact_id)
            contacts_to_poll.append({
                "contact_id": contact_id,
                "email": email,
                "company_id": contact.get("company_id"),
            })

        if not contacts_to_poll:
            console.print("[yellow]No sent drafts found — nothing to poll.[/yellow]")
            return result

        console.print(
            f"[cyan]Polling Instantly for {len(contacts_to_poll)} contacts with sent drafts...[/cyan]"
        )

        with InstantlyClient() as instantly:
            for contact in contacts_to_poll:
                email = contact["email"]
                contact_id = contact["contact_id"]
                company_id = contact["company_id"]

                _time.sleep(0.5)  # respect rate limit

                try:
                    lead = instantly.get_lead_status(email)
                except Exception as e:
                    logger.error(f"Error looking up {email} in Instantly: {e}")
                    result.errors += 1
                    continue

                if not lead:
                    continue

                # Fetch which interaction types we already have for this contact
                stored = (
                    self.db.client.table("interactions")
                    .select("type")
                    .eq("contact_id", contact_id)
                    .in_("type", ["email_opened", "email_clicked", "email_replied", "email_bounced"])
                    .execute()
                    .data
                )
                stored_types = {row["type"] for row in stored}

                # Map Instantly activity flags → event types
                event_checks = [
                    (
                        lead.get("is_opened") or lead.get("opened") or lead.get("times_opened", 0),
                        "email_opened",
                        "email_opened",
                    ),
                    (
                        lead.get("is_clicked") or lead.get("clicked") or lead.get("times_clicked", 0),
                        "email_clicked",
                        "email_clicked",
                    ),
                    (
                        lead.get("is_replied") or lead.get("replied"),
                        "reply_received",
                        "email_replied",
                    ),
                    (
                        lead.get("is_bounced") or lead.get("bounced"),
                        "email_bounced",
                        "email_bounced",
                    ),
                ]

                for activity_flag, instantly_event, interaction_type in event_checks:
                    if not activity_flag:
                        continue
                    if interaction_type in stored_types:
                        continue  # already recorded

                    event_data = {
                        "email": email,
                        "event_id": f"poll_{email}_{instantly_event}",
                    }
                    try:
                        self.process_webhook_event(instantly_event, event_data)
                        console.print(
                            f"  [green]{email}: new {instantly_event} detected[/green]"
                        )
                        result.processed += 1
                        result.add_detail(email, instantly_event, "polled")
                    except Exception as e:
                        logger.error(
                            f"Error processing polled event {instantly_event} for {email}: {e}"
                        )
                        result.errors += 1

        console.print(
            f"[cyan]Poll complete: {result.processed} new events, {result.errors} errors[/cyan]"
        )
        return result

    @staticmethod
    def process_webhook_event(event_type: str, event_data: dict) -> dict:
        """Process an Instantly.ai webhook event.

        Called by the webhook endpoint. Creates interactions and updates sequences.

        Args:
            event_type: One of email_sent, email_opened, email_clicked, reply_received, email_bounced
            event_data: Event payload from Instantly

        Returns:
            Dict with processing result.
        """
        from backend.app.core.database import Database

        # Use unscoped DB for initial lookup — webhooks arrive without auth context.
        # We discover the workspace_id from the contact record, then re-scope all writes.
        _lookup_db = Database()
        email = event_data.get("email") or event_data.get("lead_email", "")

        if not email:
            return {"status": "skipped", "reason": "No email in event"}

        # Find the contact by email (cross-workspace lookup — email is unique globally)
        contacts = (
            _lookup_db.client.table("contacts")
            .select("id, company_id, workspace_id")
            .eq("email", email)
            .execute()
            .data
        )

        if not contacts:
            logger.warning(f"Webhook: No contact found for email {email}")
            return {"status": "skipped", "reason": f"No contact for {email}"}

        contact = contacts[0]
        company_id = contact["company_id"]
        contact_id = contact["id"]
        # Re-scope all subsequent DB operations to the contact's workspace
        db = Database(workspace_id=contact.get("workspace_id"))

        # Map event type to interaction type
        interaction_map = {
            "email_sent": "email_sent",
            "email_opened": "email_opened",
            "email_clicked": "email_clicked",
            "reply_received": "email_replied",
            "email_bounced": "email_bounced",
        }

        interaction_type = interaction_map.get(event_type)
        if not interaction_type:
            return {"status": "skipped", "reason": f"Unknown event type: {event_type}"}

        # Log interaction
        db.insert_interaction({
            "company_id": company_id,
            "contact_id": contact_id,
            "type": interaction_type,
            "channel": "email",
            "subject": event_data.get("subject", ""),
            "body": event_data.get("body", ""),
            "source": "instantly_webhook",
            "external_id": event_data.get("event_id", ""),
            "metadata": event_data,
        })

        # Update engagement score
        engagement_bump = {
            "email_opened": 2,
            "email_clicked": 5,
            "reply_received": 10,
        }.get(event_type, 0)

        if engagement_bump:
            company = db.get_company(company_id)
            if company:
                current_engagement = company.get("pqs_engagement", 0)
                new_engagement = min(current_engagement + engagement_bump, 25)
                new_total = (
                    company.get("pqs_firmographic", 0)
                    + company.get("pqs_technographic", 0)
                    + company.get("pqs_timing", 0)
                    + new_engagement
                )
                db.update_company(company_id, {
                    "pqs_engagement": new_engagement,
                    "pqs_total": new_total,
                })

        # Handle specific events
        if event_type == "email_opened":
            db.update_company(company_id, {"status": "contacted"})

        elif event_type == "email_bounced":
            db.update_company(company_id, {"status": "bounced"})
            db.update_contact(contact_id, {"status": "bounced"})
            # Cancel active sequences
            active_seqs = (
                db.client.table("engagement_sequences")
                .select("id")
                .eq("contact_id", contact_id)
                .eq("status", "active")
                .execute()
                .data
            )
            for seq in active_seqs:
                db.update_engagement_sequence(seq["id"], {"status": "cancelled"})

        elif event_type == "reply_received":
            db.update_company(company_id, {"status": "engaged"})
            # Notify Slack about the hot reply
            try:
                from backend.app.utils.notifications import notify_slack
                company = db.get_company(company_id)
                company_name = company.get("name", "Unknown company") if company else "Unknown company"
                notify_slack(
                    f"*Hot reply received!* {company_name} ({email}) replied to your outreach. "
                    f"Check the ProspectIQ dashboard to respond.",
                    emoji=":fire:",
                )
            except Exception:
                pass

        return {
            "status": "processed",
            "event_type": event_type,
            "company_id": company_id,
            "contact_id": contact_id,
        }
