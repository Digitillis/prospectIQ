"""Contact function filter — single source of truth for outreach eligibility.

All contact screening decisions flow through this module. Used by:
  - Discovery agent (at import time — prevents bad contacts entering the DB)
  - Enrichment agent (before spending Apollo credits on a contact)
  - Outreach agent (final hard gate before draft generation)
  - Post-send audit job (weekly consistency check)

Three-tier classification:
  target     — ops/engineering/quality/maintenance/executive buyer persona
  borderline — may have cross-functional authority; human review required
  excluded   — non-buyer role; never draft for cold outreach

Email-name consistency check:
  Validates that the contact's name tokens appear in the email local part.
  Catches Apollo's wrong-email-assigned-to-person errors before they send.
"""

from __future__ import annotations

import re
import unicodedata
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wrong-function title signals (case-insensitive substring match)
# ---------------------------------------------------------------------------

_EXCLUDED_SIGNALS = frozenset({
    # Sales & business development
    "sales representative", "sales manager", "sales engineer", "sales director",
    "sales specialist", "sales coordinator", "sales associate",
    "regional sales", "territory sales", "area sales", "key account",
    "account manager", "account executive", "account representative",
    "national sales", "inside sales", "outside sales", "channel sales",
    "customer success", "customer service", "client services",
    "business development manager", "business development director",
    "business development representative", "bdr", "sdr",
    # Marketing
    "marketing manager", "marketing director", "marketing specialist",
    "marketing coordinator", "marketing analyst", "marketing associate",
    "product marketing", "brand manager", "digital marketing",
    "content marketing", "demand generation", "growth marketing",
    "communications manager", "public relations",
    # Human resources
    "human resources", "hr manager", "hr director", "hr generalist",
    "hr business partner", "hr coordinator", "hrbp",
    "recruiter", "recruiting manager", "talent acquisition",
    "talent development", "talent management",
    "people operations", "people partner",
    "compensation manager", "benefits manager", "payroll manager",
    # Legal
    "legal counsel", "general counsel", "attorney", "lawyer",
    "associate counsel", "deputy general counsel",
    # Finance & accounting
    "controller", "accounting manager", "accounts payable",
    "accounts receivable", "payroll", "treasurer", "tax manager",
    "financial analyst", "financial manager", "financial director",
    # Procurement / purchasing (don't own AI budgets)
    "purchasing manager", "purchasing director", "purchasing agent",
    "buyer ", "procurement manager", "procurement director",
    "supply chain coordinator",  # narrow: coordinator level, not director
    # Customer-facing ops (not buyers)
    "customer experience", "customer support",
    "field service", "field sales",
    "dealer", "distributor",
    "inside sales",
})

# Signals for borderline contacts — may have cross-functional authority
_BORDERLINE_SIGNALS = frozenset({
    # Business development at VP/director could be market-facing, not outbound sales
    "business development",  # without manager/director, could be strategic BD
    # EHS / safety (adjacent to ops, may sponsor reliability/safety tech)
    "environmental", "health and safety", "ehs manager", "ehs director",
    "safety manager", "safety director", "process safety",
    # IT / OT (could be buyer for IIoT/ML platforms)
    "information technology", "it manager", "it director",
    "technology manager",
    # Continuous improvement / lean (ops-adjacent, sometimes sponsors digital tools)
    "lean manager", "lean director", "six sigma",
    # Supply chain at director/VP level (may sponsor AI for planning)
    "supply chain manager",
    "logistics manager", "logistics director",
    # R&D (sometimes sponsors process intelligence tools)
    "r&d manager", "r&d director", "research and development",
    # Compliance — borderline by default; upgraded to target when food-safety context present
    "compliance officer", "compliance manager", "compliance director",
    "regulatory affairs",
})

# F&B food-safety context keywords — upgrade compliance titles to target in this context
_FOOD_SAFETY_COMPLIANCE_UPGRADE = frozenset({
    "food safety", "fsma", "haccp", "food quality", "sanitation", "sqa",
    "food", "quality assurance", "fda",
})

# Seniority tokens that override wrong-function signals (VP/C-level have budget authority)
_SENIORITY_OVERRIDE = frozenset({
    "vp", "v.p.", "vice president", "evp", "svp", "senior vice president",
    "executive vice president",
    "chief", "ceo", "coo", "cto", "cfo", "ciso", "cdo",
    "president",
    "partner", "managing partner", "managing director",
    "owner", "co-founder", "founder",
    "general manager",
})

# Apollo scraping artifact patterns embedded in title fields
_ARTIFACT_PATTERNS = (
    "related to search terms in your query",
    "related to search",
    " at ",  # "Plant Manager at Acme Corp" — company name leaked in
)


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def _strip_artifacts(title: str) -> str:
    """Remove Apollo scraping artifacts to recover the real title text."""
    t = title.lower().strip()
    for artifact in _ARTIFACT_PATTERNS:
        if artifact in t:
            t = t[:t.index(artifact)].strip(" ,|-–—")
    return t


def _has_seniority(title_lower: str) -> bool:
    return any(s in title_lower for s in _SENIORITY_OVERRIDE)


def classify_contact_tier(title: str | None) -> str:
    """Classify a contact into 'target', 'borderline', or 'excluded'.

    Args:
        title: Raw title string from Apollo or CRM.

    Returns:
        'target'     — ops/engineering/executive buyer, safe to draft
        'borderline' — may be relevant but needs human review
        'excluded'   — non-buyer role, never draft
    """
    if not title or not title.strip():
        return "target"  # Unknown title: default to target, benefit of the doubt

    t = _strip_artifacts(title)

    if not t:
        return "excluded"  # Title was pure artifact

    # Seniority override: VP/C-level retains outreach eligibility even with
    # a mixed-function title (e.g., "VP of Sales" is borderline, not excluded)
    if _has_seniority(t):
        # Check if the seniority-override person is in a pure non-buyer function
        # (e.g., "Chief HR Officer" should still be borderline, not target)
        if any(sig in t for sig in ("human resources", "hr ", "recrui", "talent acquisition",
                                     "marketing", "public relations", "legal counsel",
                                     "general counsel", "attorney")):
            return "borderline"
        return "target"

    # HR prefix check (catches "HR Manager" where "hr" starts the title)
    if t == "hr" or t.startswith("hr "):
        return "excluded"

    # Check excluded signals first
    for signal in _EXCLUDED_SIGNALS:
        if signal in t:
            return "excluded"

    # Check borderline signals — with food-safety upgrade for compliance titles
    for signal in _BORDERLINE_SIGNALS:
        if signal in t:
            # Compliance titles with food-safety context are target buyers (FSMA 204)
            if signal in ("compliance officer", "compliance manager", "compliance director",
                          "regulatory affairs"):
                if any(fs in t for fs in _FOOD_SAFETY_COMPLIANCE_UPGRADE):
                    return "target"
            return "borderline"

    return "target"


def is_outreach_eligible(title: str | None) -> bool:
    """Return True if this contact is eligible for cold outreach draft generation.

    Excluded contacts → False. Target and borderline → True.
    (Borderline contacts get a UI warning flag in the approval queue.)
    """
    return classify_contact_tier(title) != "excluded"


# ---------------------------------------------------------------------------
# Email-name consistency check (catches wrong-email-assigned-to-person)
# ---------------------------------------------------------------------------

# Common nickname ↔ formal name pairs
_NICKNAMES: dict[str, set[str]] = {
    "joe": {"joseph", "jo"},
    "joseph": {"joe", "jo"},
    "bill": {"william", "will", "billy"},
    "william": {"bill", "will", "billy"},
    "bob": {"robert", "rob", "bobby"},
    "bobby": {"robert", "rob", "bob"},
    "robert": {"bob", "bobby", "rob"},
    "rob": {"robert", "bob", "bobby"},
    "jim": {"james", "jimmy"},
    "james": {"jim", "jimmy"},
    "jimmy": {"james", "jim"},
    "tom": {"thomas", "tommy"},
    "thomas": {"tom", "tommy"},
    "mike": {"michael", "mick"},
    "michael": {"mike", "mick"},
    "mick": {"michael", "mike"},
    "dan": {"daniel", "danny"},
    "daniel": {"dan", "danny"},
    "dave": {"david"},
    "david": {"dave"},
    "chris": {"christopher", "kristopher"},
    "christopher": {"chris"},
    "kristopher": {"chris"},
    "steve": {"steven", "stephen"},
    "steven": {"steve"},
    "stephen": {"steve"},
    "matt": {"matthew"},
    "matthew": {"matt"},
    "pat": {"patrick"},
    "patrick": {"pat"},
    "andy": {"andrew"},
    "andrew": {"andy"},
    "jeff": {"jeffrey", "geoff", "geoffrey"},
    "jeffrey": {"jeff"},
    "geoff": {"geoffrey", "jeff", "jeffrey"},
    "rick": {"richard", "dick"},
    "richard": {"rick", "dick"},
    "tony": {"anthony"},
    "anthony": {"tony"},
    "ken": {"kenneth"},
    "kenneth": {"ken"},
    "tim": {"timothy"},
    "timothy": {"tim"},
    "ron": {"ronald"},
    "ronald": {"ron"},
    "don": {"donald"},
    "donald": {"don"},
    "larry": {"lawrence"},
    "lawrence": {"larry"},
    "sue": {"susan", "susannah"},
    "susan": {"sue"},
    "liz": {"elizabeth", "beth"},
    "elizabeth": {"liz", "beth", "eliza"},
    "beth": {"elizabeth", "liz"},
    "kate": {"katherine", "kathy", "kathryn"},
    "kathy": {"katherine", "kate", "kathryn"},
    "katherine": {"kate", "kathy", "kathryn"},
    "kathryn": {"kate", "kathy", "katherine"},
    "jen": {"jennifer"},
    "jennifer": {"jen"},
    "amy": {"amelia"},
    "linda": {"melinda"},
}


def _normalize(text: str) -> str:
    """Lowercase, strip accents, keep only alphanumeric."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def _name_variants(name: str) -> set[str]:
    """Return normalized name plus all known nickname/formal alternates."""
    n = _normalize(name)
    variants = {n}
    for nick, formals in _NICKNAMES.items():
        if n == nick:
            variants.update(_normalize(f) for f in formals)
        elif n in {_normalize(f) for f in formals}:
            variants.add(_normalize(nick))
    return variants


def check_email_name_consistency(
    first_name: str | None,
    last_name: str | None,
    email: str | None,
) -> tuple[bool, str]:
    """Check whether the contact's name is consistent with their email address.

    Uses a multi-pass algorithm:
    1. Check if full first name appears in the email local part
    2. Check if last name appears in the email local part
    3. Check if first initial matches the first character of the local part
       (handles formats like mthompson, john.s, j.smith)
    4. Apply nickname mapping to avoid false positives

    Args:
        first_name: Contact's first name.
        last_name: Contact's last name.
        email: Email address to check.

    Returns:
        Tuple of (is_consistent: bool, reason: str).
        is_consistent=True  → email plausibly belongs to this person
        is_consistent=False → email likely belongs to a different person
        is_consistent=True  → also returned when email/name data is missing (can't check)
    """
    if not email or not first_name:
        return True, "insufficient_data"

    local = email.split("@")[0].lower() if "@" in email else email.lower()
    local_clean = re.sub(r"[^a-z0-9]", "", local)

    fn_norm = _normalize(first_name)
    ln_norm = _normalize(last_name) if last_name else ""
    fn_variants = _name_variants(first_name)

    # Pass 1: Full first name (or any variant) appears in local part
    for variant in fn_variants:
        if len(variant) >= 3 and variant in local_clean:
            return True, f"first_name_match:{variant}"

    # Pass 2: Last name appears in local part
    if ln_norm and len(ln_norm) >= 3 and ln_norm in local_clean:
        # Also verify first initial matches (avoids false positive where
        # two people at the same company have the same last name)
        if fn_norm and local_clean[0] == fn_norm[0]:
            return True, "last_name_match+initial_match"
        # Last name matches but different first initial — suspicious
        first_char = local_clean[0] if local_clean else ""
        if fn_norm and first_char and first_char != fn_norm[0]:
            # Different initial spelled out in email (e.g., michael.belcher for Kade Belcher)
            # Check if the initial could be a different person's name
            return False, f"last_name_match_but_wrong_initial:{first_char}!={fn_norm[0]}"

    # Pass 3: First initial appears at start of local part
    # Handles: mthompson (Mark Thompson), jsmith (John Smith), parkerk (Parker K.)
    if fn_norm and local_clean and local_clean[0] == fn_norm[0]:
        return True, f"initial_match:{fn_norm[0]}"

    # Pass 4: Initials-only email (e.g., am@company.com) — can't verify
    if len(local_clean) <= 3:
        return True, "initials_only_cannot_verify"

    # Nothing matched — this email likely belongs to a different person
    return False, f"no_name_token_found:fn={fn_norm},ln={ln_norm},local={local_clean[:20]}"


# ---------------------------------------------------------------------------
# Convenience function for agents
# ---------------------------------------------------------------------------

def compute_ccs(contact_data: dict) -> float:
    """Compute Contact Confidence Score (0-100) for a contact dict.

    Higher score = higher confidence that this email will reach the right human.
    Threshold: CCS >= 70 → outbound_eligible_contacts. CCS >= 85 → preferred.

    Gates and their weights:
      Email deliverability (verified)   30 pts  — most important gate
      Email-name consistency            20 pts  — wrong-person detection
      Persona tier = target             15 pts  — buyer role confirmed
      Is decision maker                 15 pts  — explicit DM flag
      Multi-source agreement            10 pts  — 2+ raw_contacts sources agree
      Has email (base quality)           5 pts
    """
    score = 0.0

    # Email deliverability
    email_status = contact_data.get("email_status")
    if email_status == "verified":
        score += 30
    elif email_status in ("catch_all", "accept_all", "unverified", "unknown", None):
        score += 15  # Partial credit — not confirmed invalid
    # invalid / bounce → 0 (contact will not be eligible anyway)

    # Email-name consistency
    email_name_verified = contact_data.get("email_name_verified")
    if email_name_verified is True:
        score += 20
    elif email_name_verified is None:
        score += 10  # Not checked yet — partial credit

    # Persona tier
    tier = contact_data.get("contact_tier") or classify_contact_tier(contact_data.get("title"))
    if tier == "target":
        score += 15
    elif tier == "borderline":
        score += 7

    # Decision maker flag
    if contact_data.get("is_decision_maker"):
        score += 15

    # Has verified email (base email quality)
    if contact_data.get("email"):
        score += 5

    # Multi-source agreement — raw_source_count populated by backfill_ccs.py
    # and on each new contact insert after raw_contacts tracking was added.
    raw_source_count = contact_data.get("raw_source_count")
    if raw_source_count is None:
        pass  # Not yet computed — no penalty, no bonus
    elif raw_source_count >= 2:
        score += 10  # Two or more independent sources confirm this person
    elif raw_source_count >= 1:
        score += 5   # Single source verified

    return min(round(score, 2), 100.0)


def screen_contact_at_import(contact_data: dict, db=None) -> dict:
    """Apply all screening logic to a contact dict at import time.

    Adds 'contact_tier', 'is_outreach_eligible', and optionally
    'email_name_verified' to the dict. Returns the augmented dict.

    Args:
        contact_data: Dict with at minimum 'title', and optionally
                      'first_name', 'last_name', 'email'.
        db: Optional Database instance. When provided, uses the three-pass
            TitleClassifier (keyword → Haiku cached → human review queue)
            for borderline titles. Without db, falls back to deterministic only.

    Returns:
        The input dict augmented with screening fields.
    """
    title = contact_data.get("title")
    if db is not None:
        from backend.app.core.title_classifier import TitleClassifier
        industry = contact_data.get("industry", "")
        tier, _confidence, _source = TitleClassifier(db).classify(title, industry)
    else:
        tier = classify_contact_tier(title)
    eligible = tier != "excluded"

    contact_data["contact_tier"] = tier
    contact_data["is_outreach_eligible"] = eligible

    # Apollo email_status gate: block confirmed-invalid/bounced addresses immediately.
    # This field is populated by the enrichment agent from Apollo's people/match
    # response. If present at import time (bulk upload with prior enrichment data),
    # apply the same gate here.
    email_status = contact_data.get("email_status")
    if email_status in ("invalid", "bounce"):
        contact_data["is_outreach_eligible"] = False

    # Email-name consistency check (only if we have both name and email)
    first = contact_data.get("first_name") or ""
    last = contact_data.get("last_name") or ""
    email = contact_data.get("email") or ""

    if first and email:
        consistent, reason = check_email_name_consistency(first, last, email)
        contact_data["email_name_verified"] = consistent
        if not consistent:
            logger.warning(
                "Email-name mismatch at import: %s %s → %s (%s)",
                first, last, email, reason,
            )
            # Block outreach if email doesn't match the person — even if function is fine
            contact_data["is_outreach_eligible"] = False
    else:
        contact_data["email_name_verified"] = None  # not enough data to check

    # Compute CCS now that all gate fields are set
    from datetime import datetime, timezone
    contact_data["ccs_score"] = compute_ccs(contact_data)
    contact_data["ccs_computed_at"] = datetime.now(timezone.utc).isoformat()

    return contact_data
