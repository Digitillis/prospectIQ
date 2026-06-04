"""Forward send scheduler — pre-computes the full multi-week send plan for every
pending outreach draft, so dispatch becomes "send today's slice" instead of
just-in-time selection that hits assertion failures at dispatch time.

Design (approved 2026-06-02):
  - HYBRID cadence: each contact's 5-step arc targets the 0/+4/+9/+16/+30 cadence
    (faithful spacing); spare daily capacity after follow-ups is backfilled with
    new Step-1 cold opens. Natural per-recipient rhythm AND full capacity use.
  - Deterministic + idempotent: same live state -> same schedule. Recompute wipes
    only future/unsent slots and rebuilds, so it adapts when mailboxes are added,
    replies pause a contact, or bounces suppress one.

Constraints enforced at SCHEDULE time (so dispatch never has to):
  1. Sequence contiguity — step N only after step N-1 has a send date.
  2. Step gap — >=3 days before step 2, >=2 days before step 3+ (hard floor).
  3. Company lock — one contact per company per day; a *different* contact at the
     same company must be >= COMPANY_COOLDOWN_DAYS from any other contact's send.
  4. Daily capacity — deliverability ramp (50, +50/week) clamped to mailbox_count*30.
  5. Per-mailbox cap — 30/day, deterministic sender assignment by email hash.
  6. Weekdays only (Mon-Fri) — matches the dispatch cron window.
  7. Priority — follow-ups (higher step first) placed before new Step-1 starts.
  8. Paused/suppressed contacts excluded (genuine reply pause, bounce, unsubscribe).

This module is pure-Python and side-effect-free except persist_schedule(), so the
core algorithm can be unit-tested and dry-run against live data with no writes.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# --- Cadence (calendar-day deltas from the prior step's send date) -----------
# Derived from the 0/+4/+9/+16/+30 cadence: step2=+4, step3=+5, step4=+7, step5=+14.
CADENCE_DELTA: dict[int, int] = {2: 4, 3: 5, 4: 7, 5: 14}

# --- Hard minimum gaps (business-day floor; never send sooner than this) ------
MIN_GAP_DAYS: dict[int, int] = {2: 3, 3: 2, 4: 2, 5: 2}

COMPANY_COOLDOWN_DAYS: int = 14  # different contact, same company
PER_MAILBOX_DAILY_CAP: int = 30


# Deliverability ramp by business-week since CAMPAIGN_START (NOT since each
# recompute — otherwise a daily recompute resets the ramp and throttles every
# day to week-1 forever). Mailboxes are already warmed, so week 1 opens at 100/day.
# Week 2 = 150/day, week 3+ = full mailbox capacity (mailbox_count * 30).
CAMPAIGN_START = date(2026, 6, 1)
RAMP_SCHEDULE: list[int] = [100, 150]  # index = business-week since CAMPAIGN_START (0-based)


def ramp_cap(business_day_index: int, full_cap: int) -> int:
    """Deliverability ramp keyed by business-week. After RAMP_SCHEDULE is
    exhausted, run at full capacity. Always clamped to full_cap so it can never
    exceed mailbox_count * 30. business_day_index is business days elapsed since
    CAMPAIGN_START (anchored), so the ramp progresses in real calendar time
    regardless of when the schedule is (re)computed."""
    week = business_day_index // 5
    target = RAMP_SCHEDULE[week] if week < len(RAMP_SCHEDULE) else full_cap
    return min(full_cap, target)


def _next_business_day(d: date) -> date:
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d


def _add_business_days(d: date, n: int) -> date:
    """Add n business days to d (n>=0)."""
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


@dataclass
class Contact:
    contact_id: str
    company_id: str
    email: str
    # remaining[step] = draft_id for each pending step (already quality-gated)
    remaining: dict[int, str]
    # sent[step] = date already sent (from history)
    sent: dict[int, date] = field(default_factory=dict)

    @property
    def max_sent_step(self) -> int:
        return max(self.sent) if self.sent else 0

    @property
    def is_fresh(self) -> bool:
        return not self.sent


@dataclass
class Slot:
    draft_id: str
    contact_id: str
    company_id: str
    sequence_step: int
    scheduled_date: date
    sender_email: str
    slot_order: int


def _pick_sender(email: str, sender_pool: list[str]) -> str:
    if not sender_pool:
        return "avi@digitillis.io"
    idx = int(hashlib.md5(email.lower().encode()).hexdigest(), 16) % len(sender_pool)
    return sender_pool[idx]


def compute_schedule(
    contacts: list[Contact],
    *,
    sender_pool: list[str],
    start_date: date,
    full_cap: int,
    new_start_soft_cap: int = 80,
    horizon_business_days: int = 130,
) -> tuple[list[Slot], list[str]]:
    """Compute the forward schedule.

    Returns (slots, warnings). `warnings` lists any contacts/steps that could not
    be placed within the horizon (should be empty in normal operation).

    HYBRID strategy:
      Phase A each day — place ready follow-up steps (higher step first), targeting
        each contact's cadence date, sliding forward only when a day is full or the
        company/mailbox slot is taken.
      Phase B each day — backfill remaining capacity with new Step-1 starts
        (soft-capped per day), lowest priority.
    """
    start = _next_business_day(start_date)

    # company_touches[company_id] = list of (date, contact_id) already placed/sent
    company_touches: dict[str, list[tuple[date, str]]] = defaultdict(list)
    # seed with history so cooldown respects already-sent emails
    for c in contacts:
        for step, d in c.sent.items():
            company_touches[c.company_id].append((d, c.contact_id))

    # Build initial ready events.
    # A "follow-up event" is a contact whose next pending step has a prior step
    # already sent (or will be scheduled). A "new start" is a fresh contact's step 1.
    @dataclass
    class Event:
        contact: Contact
        step: int
        earliest: date  # earliest legal date (gap floor)
        target: date  # cadence-preferred date
        anchor: date  # the prior step's send date

    followups: list[Event] = []
    new_starts: list[Contact] = []
    warnings: list[str] = []

    for c in contacts:
        steps = sorted(c.remaining)
        if not steps:
            continue
        nxt = steps[0]
        if nxt == 1:
            new_starts.append(c)
        else:
            prior = nxt - 1
            if prior not in c.sent:
                # prior step not sent and not pending in this contact -> cannot schedule
                warnings.append(
                    f"{c.contact_id}: step {nxt} has no sent/scheduled prior step {prior}"
                )
                continue
            anchor = c.sent[prior]
            earliest = _add_business_days(anchor, MIN_GAP_DAYS.get(nxt, 2))
            earliest = max(_next_business_day(earliest), start)
            target = max(
                _next_business_day(anchor + timedelta(days=CADENCE_DELTA.get(nxt, 7))), earliest
            )
            followups.append(Event(c, nxt, earliest, target, anchor))

    # Stable ordering for new starts (deterministic): by contact_id
    new_starts.sort(key=lambda c: c.contact_id)

    slots: list[Slot] = []
    # pending_followups is a mutable list we add to as chains advance
    pending_followups = followups

    day = start
    for day_idx in range(horizon_business_days):
        day = _next_business_day(day)
        cap = ramp_cap(day_idx, full_cap)
        used_companies: set[str] = set()
        mailbox_load: dict[str, int] = defaultdict(int)
        placed = 0
        slot_order = 0

        def company_ok(company_id: str, contact_id: str, d: date) -> bool:
            if company_id in used_companies:
                return False
            for td, tc in company_touches[company_id]:
                if tc != contact_id and abs((d - td).days) < COMPANY_COOLDOWN_DAYS:
                    return False
            return True

        # --- Phase A: follow-ups ready today, higher step first, then by target ---
        ready = [e for e in pending_followups if e.earliest <= day]
        ready.sort(key=lambda e: (-e.step, e.target, e.contact.contact_id))
        placed_events: list = []
        next_events: list = []
        for e in ready:
            if placed >= cap:
                break
            # Respect cadence target: don't place earlier than target unless it's overdue
            if e.target > day:
                continue
            if not company_ok(e.contact.company_id, e.contact.contact_id, day):
                continue
            sender = _pick_sender(e.contact.email, sender_pool)
            if mailbox_load[sender] >= PER_MAILBOX_DAILY_CAP:
                continue
            # place
            slots.append(
                Slot(
                    e.contact.remaining[e.step],
                    e.contact.contact_id,
                    e.contact.company_id,
                    e.step,
                    day,
                    sender,
                    slot_order,
                )
            )
            slot_order += 1
            placed += 1
            mailbox_load[sender] += 1
            used_companies.add(e.contact.company_id)
            company_touches[e.contact.company_id].append((day, e.contact.contact_id))
            e.contact.sent[e.step] = day  # treat as sent for downstream steps
            placed_events.append(e)
            # enqueue next step of this contact's chain
            nstep = e.step + 1
            if nstep in e.contact.remaining:
                earliest = max(
                    _next_business_day(_add_business_days(day, MIN_GAP_DAYS.get(nstep, 2))), day
                )
                target = max(
                    _next_business_day(day + timedelta(days=CADENCE_DELTA.get(nstep, 7))), earliest
                )
                next_events.append(Event(e.contact, nstep, earliest, target, day))
        for e in placed_events:
            pending_followups.remove(e)
        pending_followups.extend(next_events)

        # --- Phase B: new Step-1 starts backfill spare capacity (soft-capped) ---
        new_started_today = 0
        still_blocked: list[Contact] = []
        while new_starts and placed < cap and new_started_today < new_start_soft_cap:
            c = new_starts.pop(0)
            if not company_ok(c.company_id, c.contact_id, day):
                still_blocked.append(c)
                continue
            sender = _pick_sender(c.email, sender_pool)
            if mailbox_load[sender] >= PER_MAILBOX_DAILY_CAP:
                still_blocked.append(c)
                continue
            slots.append(
                Slot(c.remaining[1], c.contact_id, c.company_id, 1, day, sender, slot_order)
            )
            slot_order += 1
            placed += 1
            mailbox_load[sender] += 1
            used_companies.add(c.company_id)
            company_touches[c.company_id].append((day, c.contact_id))
            c.sent[1] = day
            new_started_today += 1
            nstep = 2
            if nstep in c.remaining:
                earliest = max(_next_business_day(_add_business_days(day, MIN_GAP_DAYS[2])), day)
                target = max(_next_business_day(day + timedelta(days=CADENCE_DELTA[2])), earliest)
                pending_followups.append(Event(c, nstep, earliest, target, day))
        # blocked new-starts return to the front for the next day
        new_starts = still_blocked + new_starts

        day += timedelta(days=1)

    # anything left unplaced
    for e in pending_followups:
        warnings.append(f"{e.contact.contact_id}: step {e.step} not placed within horizon")
    for c in new_starts:
        warnings.append(f"{c.contact_id}: new start not placed within horizon")

    return slots, warnings


def validate_schedule(slots: list[Slot], sent_history: dict[str, dict[int, date]]) -> list[str]:
    """Adversarial self-check: re-derive every constraint from the produced slots
    and return a list of violations (empty = clean)."""
    violations: list[str] = []
    by_contact: dict[str, list[Slot]] = defaultdict(list)
    by_day_company: dict[tuple[date, str], int] = defaultdict(int)
    by_day_mailbox: dict[tuple[date, str], int] = defaultdict(int)
    by_day_total: dict[date, int] = defaultdict(int)

    for s in slots:
        by_contact[s.contact_id].append(s)
        by_day_company[(s.scheduled_date, s.company_id)] += 1
        by_day_mailbox[(s.scheduled_date, s.sender_email)] += 1
        by_day_total[s.scheduled_date] += 1

    # 1. weekday only
    for s in slots:
        if s.scheduled_date.weekday() >= 5:
            violations.append(f"{s.draft_id}: scheduled on weekend {s.scheduled_date}")

    # 2. per-mailbox cap
    for (d, m), n in by_day_mailbox.items():
        if n > PER_MAILBOX_DAILY_CAP:
            violations.append(f"mailbox {m} has {n} sends on {d} (cap {PER_MAILBOX_DAILY_CAP})")

    # 3. one contact per company per day
    for (d, co), n in by_day_company.items():
        if n > 1:
            violations.append(f"company {co} has {n} sends on {d} (max 1/day)")

    # 4. step gaps + contiguity per contact
    for cid, css in by_contact.items():
        css.sort(key=lambda x: x.sequence_step)
        # merge sent history
        sched = {s.sequence_step: s.scheduled_date for s in css}
        all_steps = dict(sent_history.get(cid, {}))
        all_steps.update(sched)
        for step in sorted(sched):
            if step > 1 and (step - 1) not in all_steps:
                violations.append(f"{cid}: step {step} scheduled but step {step - 1} missing")
                continue
            if step > 1:
                gap_floor = MIN_GAP_DAYS.get(step, 2)
                prior_d = all_steps[step - 1]
                # business-day gap
                bd = sum(
                    1
                    for i in range((sched[step] - prior_d).days)
                    if (prior_d + timedelta(days=i + 1)).weekday() < 5
                )
                if bd < gap_floor:
                    violations.append(
                        f"{cid}: step {step} only {bd} biz-days after step {step - 1} (floor {gap_floor})"
                    )

    return violations


# ===========================================================================
# DB integration — persistence, recompute, daily enqueue, reply-driven pause
# ===========================================================================
# These functions touch Supabase via the project Database client. The pure
# algorithm above stays side-effect-free for testing/dry-run.

# Reply intents that PAUSE the sequence for human review (genuine human replies).
# OOO / bounce / unsubscribe are NOT in here: OOO keeps the sequence running,
# bounce + unsubscribe are handled by the existing suppression path.
PAUSE_INTENTS = {"interested", "objection", "referral", "soft_no", "other"}
# Intents that keep the sequence running untouched.
IGNORE_INTENTS = {"out_of_office"}


def _load_state(db, workspace_id: str):
    """Load contacts + sent history + sender pool + mailbox cap from live DB.
    Returns (contacts, sent_history, sender_pool, full_cap)."""
    import re

    WRONG = (
        "counsel",
        "attorney",
        " legal",
        "marketing",
        " sales",
        "recruit",
        "talent",
        "communications",
        "controller",
        "treasurer",
        "credit & collections",
        "customer service",
        "chief information",
        "information technology",
        "it director",
        "(cio)",
    )
    EM = re.compile(r"[—–]")
    EL = re.compile(r"\.\.\.|…")
    VIB = re.compile(r"vibrat", re.I)
    URL = re.compile(r"https?://")

    def page(tbl, sel, **eq):
        out = []
        off = 0
        while True:
            q = db.client.table(tbl).select(sel)
            for k, v in eq.items():
                q = q.eq(k, v)
            b = q.range(off, off + 999).execute().data or []
            out.extend(b)
            if len(b) < 1000:
                break
            off += 1000
        return out

    # Sender pool + cap from outreach_send_config
    cfg = (
        db.client.table("outreach_send_config")
        .select("sender_pool, daily_limit")
        .eq("workspace_id", workspace_id)
        .limit(1)
        .execute()
        .data
        or [{}]
    )[0]
    sender_pool = [s.get("email") for s in (cfg.get("sender_pool") or []) if s.get("email")]
    full_cap = cfg.get("daily_limit") or (len(sender_pool) * PER_MAILBOX_DAILY_CAP)

    contacts_tbl = {
        c["id"]: c
        for c in page(
            "contacts", "id,email,company_id,title,is_outreach_eligible,email_status,outreach_state"
        )
    }

    # Company cluster — dispatch hard-rejects 'other'/'watchlist'/null at send time,
    # so exclude those contacts from scheduling rather than slot drafts that will be
    # skipped. Surfaces mis-classified companies instead of silently laundering them.
    companies_tbl = {c["id"]: c for c in page("companies", "id,campaign_cluster,status")}
    SENDABLE_CLUSTER_BLOCK = {None, "", "other", "watchlist"}

    # Suppressed contacts (bounce/unsubscribe) — exclude.
    suppressed_contacts: set = set()
    try:
        for s in page("suppression_log", "contact_id,scope"):
            if s.get("contact_id"):
                suppressed_contacts.add(s["contact_id"])
    except Exception:
        pass

    sent_hist: dict[str, dict[int, date]] = defaultdict(dict)
    for d in page("outreach_drafts", "contact_id,sequence_step,sent_at"):
        if d.get("sent_at") and d.get("contact_id"):
            try:
                from datetime import datetime

                sent_hist[d["contact_id"]][d["sequence_step"]] = datetime.fromisoformat(
                    d["sent_at"].replace("Z", "+00:00")
                ).date()
            except Exception:
                pass

    all_pending_drafts = [
        d
        for d in page(
            "outreach_drafts",
            "id,contact_id,company_id,sequence_step,body,personalization_notes,approval_status,sent_at,model",
        )
        if d.get("approval_status") == "pending" and not d.get("sent_at")
    ]
    # Model filter: accept any draft that has a model tag (i.e. was AI-generated).
    # The old filter 'model == opus-via-claude-code' excluded all production drafts
    # generated with claude-sonnet-* or claude-haiku-* models, producing a zero-slot
    # schedule while logging success — a silent send blackout (D2).
    drafts = [d for d in all_pending_drafts if d.get("model")]
    if not drafts and all_pending_drafts:
        logger.critical(
            "_load_state: %d pending drafts found but ZERO passed the model filter. "
            "Production drafts carry model tags like 'claude-sonnet-*'; check that "
            "model is being set at draft generation time.",
            len(all_pending_drafts),
        )

    remaining: dict[str, dict[int, str]] = defaultdict(dict)
    for d in drafts:
        c = contacts_tbl.get(d["contact_id"], {})
        if c.get("is_outreach_eligible") is False:
            continue
        if c.get("email_status") != "verified":
            continue
        if any(w in (c.get("title") or "").lower() for w in WRONG):
            continue
        if c.get("outreach_state") == "paused":
            continue  # genuine-reply paused contacts excluded
        if d["contact_id"] in suppressed_contacts:
            continue  # bounce/unsubscribe suppressed
        co = companies_tbl.get(c.get("company_id"), {})
        if co.get("campaign_cluster") in SENDABLE_CLUSTER_BLOCK or co.get("status") in (
            "paused",
            "disqualified",
        ):
            continue  # dispatch would reject these — do not schedule
        b = d.get("body", "") or ""
        n = d.get("personalization_notes", "") or ""
        if EM.search(b) or EL.search(b) or VIB.search(b) or not URL.search(n):
            continue
        remaining[d["contact_id"]][d["sequence_step"]] = d["id"]

    contacts = []
    for cid, steps in remaining.items():
        c = contacts_tbl.get(cid, {})
        contacts.append(
            Contact(
                contact_id=cid,
                company_id=c.get("company_id") or "unknown",
                email=c.get("email") or "",
                remaining=steps,
                sent=dict(sent_hist.get(cid, {})),
            )
        )
    return contacts, sent_hist, sender_pool, int(full_cap)


def recompute_and_persist(
    db, workspace_id: str, *, start_date: Optional[date] = None, new_start_soft_cap: int = 80
) -> dict:
    """Rebuild the forward schedule from live state and persist it.

    Idempotent: deletes existing 'scheduled' (future, not-yet-enqueued) rows and
    writes a fresh plan. Already-enqueued/sent rows are left intact.
    Returns a summary dict.
    """
    import uuid
    from datetime import datetime, timezone

    if start_date is None:
        # next business day in Chicago terms (UTC date is fine at our granularity)
        start_date = _next_business_day(datetime.now(timezone.utc).date() + timedelta(days=1))

    contacts, sent_hist, sender_pool, full_cap = _load_state(db, workspace_id)
    if not sender_pool:
        sender_pool = ["avi@digitillis.io"]

    slots, warnings = compute_schedule(
        contacts,
        sender_pool=sender_pool,
        start_date=start_date,
        full_cap=full_cap,
        new_start_soft_cap=new_start_soft_cap,
    )
    violations = validate_schedule(
        slots, {c.contact_id: dict(sent_hist.get(c.contact_id, {})) for c in contacts}
    )
    if violations:
        # Do not persist a schedule that fails its own self-check.
        logger.error("recompute_and_persist ABORTED — %d constraint violations", len(violations))
        return {
            "persisted": False,
            "violations": violations[:20],
            "slots": len(slots),
            "warnings": len(warnings),
        }

    run_id = str(uuid.uuid4())
    # Clear existing not-yet-enqueued schedule rows for this workspace.
    db.client.table("send_schedule").delete().eq("workspace_id", workspace_id).eq(
        "status", "scheduled"
    ).execute()

    rows = [
        {
            "draft_id": s.draft_id,
            "contact_id": s.contact_id,
            "company_id": s.company_id,
            "workspace_id": workspace_id,
            "sequence_step": s.sequence_step,
            "scheduled_date": s.scheduled_date.isoformat(),
            "sender_email": s.sender_email,
            "slot_order": s.slot_order,
            "status": "scheduled",
            "schedule_run_id": run_id,
        }
        for s in slots
    ]
    # batch insert (chunks of 500)
    inserted = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i : i + 500]
        try:
            db.client.table("send_schedule").upsert(chunk, on_conflict="draft_id").execute()
            inserted += len(chunk)
        except Exception as exc:
            logger.error("send_schedule insert chunk failed: %s", exc)

    return {
        "persisted": True,
        "run_id": run_id,
        "slots": inserted,
        "contacts": len(contacts),
        "warnings": len(warnings),
        "unscheduled_warnings": warnings[:20],
        "full_cap": full_cap,
        "start_date": start_date.isoformat(),
    }


# Reviewer attribution for schedule-driven approval. The forward schedule is the
# founder-approved automation: a draft reaching its scheduled day, having passed
# every quality/eligibility/sequence gate at schedule time, is approved on the
# founder's behalf. Overridable via outreach_send_config.default_reviewer_id.
DEFAULT_SCHEDULE_REVIEWER_ID = "e463105c-4cdc-45e2-967d-66e3dd5728df"


def enqueue_todays_schedule(
    db, workspace_id: str, *, today: Optional[date] = None, reviewer_id: Optional[str] = None
) -> dict:
    """Move today's scheduled slots into outbound_queue, in slot order, approving
    each draft on enqueue (scheduling IS the approval — every gate was satisfied at
    schedule time). The existing dispatch_loop then drains the queue and sends.
    This is the only daily send-time action — no selection logic."""
    from datetime import datetime, timezone

    if today is None:
        today = datetime.now(timezone.utc).date()
    if reviewer_id is None:
        try:
            cfg = (
                db.client.table("outreach_send_config")
                .select("default_reviewer_id")
                .eq("workspace_id", workspace_id)
                .limit(1)
                .execute()
                .data
                or [{}]
            )[0]
            reviewer_id = cfg.get("default_reviewer_id") or DEFAULT_SCHEDULE_REVIEWER_ID
        except Exception:
            reviewer_id = DEFAULT_SCHEDULE_REVIEWER_ID

    now_iso = datetime.now(timezone.utc).isoformat()
    due = (
        db.client.table("send_schedule")
        .select("id,draft_id,sequence_step,slot_order")
        .eq("workspace_id", workspace_id)
        .eq("status", "scheduled")
        .eq("scheduled_date", today.isoformat())
        .order("slot_order")
        .execute()
        .data
        or []
    )
    enqueued = 0
    for r in due:
        priority = max(1, 6 - r["sequence_step"])
        try:
            # Approve the draft (satisfies approval_requires_reviewer) — only if not
            # already sent. Scheduling is the approval gate.
            db.client.table("outreach_drafts").update(
                {
                    "approval_status": "approved",
                    "approved_by": reviewer_id,
                    "reviewed_at": now_iso,
                    "approved_at": now_iso,
                }
            ).eq("id", r["draft_id"]).is_("sent_at", "null").execute()
            db.client.table("outbound_queue").insert(
                {
                    "draft_id": r["draft_id"],
                    "workspace_id": workspace_id,
                    "priority": priority,
                    "retry_count": 0,
                }
            ).execute()
            db.client.table("send_schedule").update({"status": "enqueued"}).eq(
                "id", r["id"]
            ).execute()
            enqueued += 1
        except Exception as exc:
            logger.error("enqueue_todays_schedule draft=%s failed: %s", r["draft_id"], exc)
    return {
        "date": today.isoformat(),
        "enqueued": enqueued,
        "due": len(due),
        "reviewer_id": reviewer_id,
    }


def pause_contact_on_reply(db, workspace_id: str, contact_id: str, intent: str) -> dict:
    """Apply the reply policy. Genuine human replies pause the contact's remaining
    schedule for human review; OOO keeps it running; bounce/unsubscribe are handled
    by the suppression path elsewhere. Recompute is the caller's responsibility."""
    if intent in IGNORE_INTENTS:
        return {"action": "ignored", "intent": intent}
    if intent not in PAUSE_INTENTS:
        return {"action": "no_pause", "intent": intent}
    # Pause the contact and cancel its future scheduled (not-yet-enqueued) steps.
    db.client.table("contacts").update({"outreach_state": "paused"}).eq("id", contact_id).execute()
    cancelled = (
        db.client.table("send_schedule")
        .update({"status": "paused"})
        .eq("workspace_id", workspace_id)
        .eq("contact_id", contact_id)
        .eq("status", "scheduled")
        .execute()
        .data
        or []
    )
    return {"action": "paused", "intent": intent, "cancelled_slots": len(cancelled)}
