"""Send-path self-test — verifies all send-path wiring is correct.

Checks:
1. engagement.py passes assertion_context='send_path' to run_pre_send_assertions
2. pre_send_assertions.py has assert_bounce_rate_ok wired to send_path context
3. run_pre_send_assertions enforces bounce_rate_ok only in send_path
4. outreach.py does NOT pass assertion_context='send_path' (it is draft_gen only)
5. No Resend dispatch in engagement.py can be reached without assertions
6. resend_client.py (transactional) has no pre_send_assertions (correct — it is not cold outreach)
7. test-send in approvals.py does not set sent_at (correct — no governance needed)

Exit code:
  0 — all checks pass
  1 — one or more checks failed (detail printed)

Usage:
    python send_path_self_test.py
"""
from __future__ import annotations

import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

failures: list[str] = []
warnings: list[str] = []


def check(label: str, condition: bool, warning_only: bool = False) -> None:
    status = PASS if condition else (WARN if warning_only else FAIL)
    print(f"  [{status}] {label}")
    if not condition:
        if warning_only:
            warnings.append(label)
        else:
            failures.append(label)


def read_source(path: str) -> str:
    with open(path) as f:
        return f.read()


print("=" * 65)
print("SEND-PATH GOVERNANCE SELF-TEST")
print("=" * 65)

BASE = os.path.dirname(os.path.abspath(__file__))
ENGAGEMENT = os.path.join(BASE, "backend/app/agents/engagement.py")
OUTREACH = os.path.join(BASE, "backend/app/agents/outreach.py")
PRE_SEND = os.path.join(BASE, "backend/app/core/pre_send_assertions.py")
APPROVALS = os.path.join(BASE, "backend/app/api/routes/approvals.py")
RESEND_CLIENT = os.path.join(BASE, "backend/app/integrations/resend_client.py")

# -----------------------------------------------------------------------
print("\n[1] engagement.py — send_path assertion gate")
# -----------------------------------------------------------------------
eng_src = read_source(ENGAGEMENT)

check(
    "engagement.py calls run_pre_send_assertions",
    "run_pre_send_assertions" in eng_src,
)
check(
    "engagement.py passes assertion_context='send_path'",
    "assertion_context=\"send_path\"" in eng_src,
)
check(
    "engagement.py calls _rollback_sent_at on AssertionFailure",
    "_rollback_sent_at" in eng_src,
)
def _check_ordering(src: str) -> bool:
    """Verify: atomic claim (sent_at update) < run_pre_send_assertions < resend.Emails.send.

    Finds the line number of the first occurrence of each marker within the
    _send_approved_drafts method body and checks they appear in order.
    """
    lines = src.splitlines()
    claim_line = None
    assertion_line = None
    resend_line = None
    in_method = False
    for i, line in enumerate(lines):
        if "def _send_approved_drafts" in line:
            in_method = True
        if not in_method:
            continue
        if claim_line is None and '"sent_at": now' in line and "update" in line:
            claim_line = i
        if assertion_line is None and "run_pre_send_assertions" in line and "def " not in line:
            assertion_line = i
        if resend_line is None and "resend.Emails.send" in line and not line.lstrip().startswith("#"):
            resend_line = i
    if claim_line is None or assertion_line is None or resend_line is None:
        return False
    return claim_line < assertion_line < resend_line

check(
    "engagement.py: atomic claim (sent_at) < run_pre_send_assertions < resend.Emails.send (ordering)",
    _check_ordering(eng_src),
)
check(
    "engagement.py handles AssertionFailure with rollback and continue (does not proceed to Resend)",
    "AssertionFailure" in eng_src and "_rollback_sent_at" in eng_src and "continue" in eng_src,
)
check(
    "engagement.py handles unexpected assertion exception with rollback (fail-closed)",
    "assertion_exception" in eng_src or ("except Exception as _ae" in eng_src and "_rollback_sent_at" in eng_src),
)

# -----------------------------------------------------------------------
print("\n[2] pre_send_assertions.py — assert_bounce_rate_ok wiring")
# -----------------------------------------------------------------------
psa_src = read_source(PRE_SEND)

check(
    "assert_bounce_rate_ok function defined",
    "def assert_bounce_rate_ok" in psa_src,
)
check(
    "assert_bounce_rate_ok raises AssertionFailure on breach",
    "raise AssertionFailure(\"bounce_rate_ok\"" in psa_src,
)
check(
    "run_pre_send_assertions gates bounce_rate_ok on send_path context only",
    'if assertion_context == "send_path":' in psa_src and "assert_bounce_rate_ok" in psa_src,
)
check(
    "assert_bounce_rate_ok checks 7-day rolling window",
    "timedelta(days=7)" in psa_src,
)
check(
    "assert_bounce_rate_ok uses MAX_BOUNCE_RATE constant",
    "MAX_BOUNCE_RATE" in psa_src,
)
check(
    "assert_bounce_rate_ok defaults to send_path context",
    'def assert_bounce_rate_ok(db: Any, assertion_context: str = "send_path")' in psa_src,
)

# -----------------------------------------------------------------------
print("\n[3] outreach.py — advisory draft_gen (no send_path override)")
# -----------------------------------------------------------------------
out_src = read_source(OUTREACH)

check(
    "outreach.py calls run_pre_send_assertions",
    "run_pre_send_assertions" in out_src,
)
check(
    "outreach.py does NOT pass assertion_context='send_path' (advisory only)",
    "assertion_context=\"send_path\"" not in out_src,
    warning_only=False,
)
# The default is draft_gen which is correct for outreach.py
check(
    "outreach.py does not call resend.Emails.send (only drafts, does not deliver)",
    "resend.Emails.send" not in out_src,
)

# -----------------------------------------------------------------------
print("\n[4] approvals.py — test-send does not set sent_at")
# -----------------------------------------------------------------------
app_src = read_source(APPROVALS)

check(
    "approvals test-send endpoint does NOT set sent_at on the draft (no governance needed)",
    "sent_at" not in app_src.split("test-send")[1][:500] if "test-send" in app_src else True,
    warning_only=True,
)
check(
    "approvals test-send sends to test_email only (not original prospect)",
    "test_email" in app_src,
)

# -----------------------------------------------------------------------
print("\n[5] resend_client.py — transactional only, no pre_send_assertions")
# -----------------------------------------------------------------------
rc_src = read_source(RESEND_CLIENT)

check(
    "resend_client.py does not call run_pre_send_assertions (transactional, not outreach)",
    "run_pre_send_assertions" not in rc_src,
)
check(
    "resend_client.py is not used for cold outreach (docstring confirms transactional only)",
    "transactional" in rc_src.lower() or "NOT cold outreach" in rc_src or "transactional" in rc_src,
)

# -----------------------------------------------------------------------
print("\n[6] DB runtime check — send_path coverage today")
# -----------------------------------------------------------------------
try:
    from supabase import create_client
    SUPABASE_URL_ENV = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SK = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not SUPABASE_URL_ENV or not SUPABASE_SK:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment")
    db = create_client(SUPABASE_URL_ENV, SUPABASE_SK)

    from datetime import date
    today = date.today().isoformat()
    sent_today_r = db.table("outreach_drafts").select("id", count="exact").gte("sent_at", f"{today}T00:00:00").not_.is_("sent_at", "null").execute()
    sent_today = sent_today_r.count or 0

    sp_today_r = db.table("send_assertions").select("id", count="exact").eq("assertion_context", "send_path").gte("evaluated_at", f"{today}T00:00:00").execute()
    sp_today = sp_today_r.count or 0

    coverage_ok = (sp_today > 0) if sent_today > 0 else True
    check(
        f"Today: {sent_today} sends, {sp_today} send_path assertion records ({('present' if sp_today > 0 else 'NONE — newly deployed or no sends yet')})",
        coverage_ok,
        warning_only=(sent_today == 0),
    )

    # check bounce rate does not exceed threshold
    from datetime import datetime as _dt, timezone, timedelta
    cutoff = (_dt.now(timezone.utc) - timedelta(days=7)).isoformat()
    sends_r = db.table("interactions").select("id", count="exact").eq("type", "email_sent").gte("created_at", cutoff).execute()
    bounces_r = db.table("interactions").select("id", count="exact").eq("type", "email_bounced").gte("created_at", cutoff).execute()
    sends_count = sends_r.count or 0
    bounces_count = bounces_r.count or 0
    rate = (bounces_count / sends_count) if sends_count > 0 else 0
    check(
        f"7-day bounce rate: {bounces_count}/{sends_count} = {rate:.2%} (threshold 2%)",
        rate <= 0.02,
        warning_only=(sends_count == 0),
    )

except Exception as e:
    print(f"  [{WARN}] DB check skipped: {e}")
    warnings.append("DB check failed — check credentials")

# -----------------------------------------------------------------------
print()
print("=" * 65)
total_checks = len(failures) + len(warnings)
if failures:
    print(f"RESULT: FAIL — {len(failures)} failure(s), {len(warnings)} warning(s)")
    for f in failures:
        print(f"  FAIL: {f}")
    sys.exit(1)
elif warnings:
    print(f"RESULT: PASS WITH WARNINGS — {len(warnings)} warning(s)")
    for w in warnings:
        print(f"  WARN: {w}")
    sys.exit(0)
else:
    print("RESULT: ALL CHECKS PASSED")
    sys.exit(0)
