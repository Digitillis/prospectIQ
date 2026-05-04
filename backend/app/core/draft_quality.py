"""Outreach draft quality validator.

Pre-send quality gate that ensures every outreach email meets
minimum personalization and quality standards before approval.

Generic emails get ignored. Personalized emails convert.
This validator enforces the difference.

Quality checks:
1. References company by name (not just template variable)
2. Mentions a specific fact about the company (from research hooks)
3. No banned phrases (filler, manipulation, feature dumps)
4. Appropriate length (not too short, not a wall of text)
5. Has a clear, single CTA
6. Subject line is relevant and short
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Spam trigger words that activate email filters
SPAM_TRIGGER_WORDS = [
    "act now", "limited time", "click here",
    "special offer", "exclusive deal", "risk-free",
    "no obligation", "winner", "congratulations", "urgent",
    "best price", "buy now", "order now", "subscribe",
    "unsubscribe", "opt-in", "double your", "earn money",
    "incredible deal", "once in a lifetime", "don't miss",
    "money-back guarantee", "guaranteed results", "we guarantee",
]

# Banned phrases that signal generic/low-quality outreach
_BANNED_PHRASES = [
    "i hope this email finds you well",
    "i hope this finds you well",
    "just wanted to reach out",
    "just reaching out",
    "just following up",
    "touching base",
    "i wanted to introduce",
    "my name is",
    "i'm reaching out because",
    "limited time",
    "act now",
    "don't miss",
    "exclusive offer",
    "schedule a call today",
    "we help companies like",
    "we work with companies",
    "our platform offers",
    "our solution provides",
    "leading provider",
    "best-in-class",
    "cutting-edge",
    "state-of-the-art",
    "revolutionary",
    "game-changing",
    "synergy",
    "leverage",
    "paradigm",
]

# CTA patterns (at least one should appear)
_CTA_PATTERNS = [
    r"would\s+(?:it|a|this)\s+(?:be\s+)?worth",
    r"would\s+you\s+be\s+open",
    r"interested\s+in",
    r"make\s+sense",
    r"15[- ]minute",
    r"quick\s+call",
    r"calendar\s+link",
    r"happy\s+to\s+(?:chat|connect|discuss|share|show)",
    r"want\s+me\s+to\s+send",
    r"shall\s+i",
    r"let\s+me\s+know",
]


@dataclass
class QualityIssue:
    """A single quality issue found in a draft."""
    severity: str       # "error" (blocks send) or "warning" (flag but allow)
    check_name: str     # Which check caught it
    message: str        # Human-readable description


@dataclass
class QualityReport:
    """Quality assessment of an outreach draft."""
    draft_id: str
    passed: bool = True
    score: int = 100        # 0-100, deduct per issue
    issues: list[QualityIssue] = field(default_factory=list)

    def add_issue(self, severity: str, check_name: str, message: str) -> None:
        issue = QualityIssue(severity=severity, check_name=check_name, message=message)
        self.issues.append(issue)
        if severity == "error":
            self.passed = False
            self.score -= 25
        elif severity == "warning":
            self.score -= 10
        self.score = max(self.score, 0)


def validate_draft(
    draft: dict,
    company: dict | None = None,
    research: dict | None = None,
) -> QualityReport:
    """Validate an outreach draft for quality and personalization.

    Args:
        draft: The outreach draft dict (subject, body, etc.).
        company: Company dict for context validation.
        research: Research intelligence for personalization check.

    Returns:
        QualityReport with pass/fail and detailed issues.
    """
    report = QualityReport(draft_id=draft.get("id", "unknown"))

    subject = draft.get("subject", "")
    body = draft.get("edited_body") or draft.get("body", "")
    body_lower = body.lower()

    # 1. Subject line checks
    if not subject:
        report.add_issue("error", "no_subject", "Missing subject line")
    elif len(subject) > 60:
        report.add_issue("warning", "long_subject", f"Subject is {len(subject)} chars (target: <60)")
    elif len(subject) < 10:
        report.add_issue("warning", "short_subject", "Subject too short — may look like spam")

    # 2. Body length check
    word_count = len(body.split())
    if word_count < 30:
        report.add_issue("error", "too_short", f"Body is only {word_count} words — too short to be credible")
    elif word_count > 250:
        report.add_issue("warning", "too_long", f"Body is {word_count} words — manufacturing VPs won't read walls of text")

    # 3. Company name reference
    if company:
        company_name = company.get("name", "")
        if company_name and company_name.lower() not in body_lower:
            report.add_issue(
                "warning", "no_company_name",
                f"Body doesn't mention '{company_name}' — feels generic"
            )

    # 4. Personalization check — does it reference specific research?
    if research:
        hooks = research.get("personalization_hooks") or company.get("personalization_hooks") or []
        if hooks:
            # Check if ANY hook content appears in the body
            hook_found = False
            for hook in hooks:
                # Check for key phrases from the hook (not exact match)
                hook_words = [w for w in hook.lower().split() if len(w) > 4]
                matches = sum(1 for w in hook_words if w in body_lower)
                if matches >= 2:  # At least 2 significant words from a hook
                    hook_found = True
                    break

            if not hook_found:
                report.add_issue(
                    "warning", "low_personalization",
                    "Body doesn't reference any research-derived personalization hooks — "
                    "may feel generic to the prospect"
                )

    # 5. Banned phrases check
    for phrase in _BANNED_PHRASES:
        if phrase in body_lower:
            report.add_issue(
                "error", "banned_phrase",
                f"Contains banned phrase: '{phrase}'"
            )
            break  # One is enough to flag

    # 5b. Spam trigger words check — word-boundary match prevents false positives
    # on company names (e.g. "Freepoint") or legitimate references ("DOE guarantee")
    spam_found = [w for w in SPAM_TRIGGER_WORDS if re.search(r'\b' + re.escape(w) + r'\b', body_lower)]
    if spam_found:
        report.add_issue(
            "error", "spam_words",
            f"Contains spam trigger words: {', '.join(spam_found)}. These trigger email filters.",
        )

    # 6. CTA check — must have exactly one clear call-to-action
    cta_count = 0
    for pattern in _CTA_PATTERNS:
        if re.search(pattern, body_lower):
            cta_count += 1

    if cta_count == 0:
        report.add_issue(
            "warning", "no_cta",
            "No clear call-to-action detected — email needs a specific ask"
        )
    elif cta_count > 2:
        report.add_issue(
            "warning", "multiple_ctas",
            f"Found {cta_count} CTAs — emails with a single clear CTA convert better"
        )

    # 7. AI-sounding language check
    ai_tells = [
        ("—", "em_dash", "Contains em dash (—) — use comma or period instead"),
        ("–", "en_dash", "Contains en dash (–) — use comma or period instead"),
        ("moreover", "moreover", "Contains 'moreover' — sounds like AI, not a person"),
        ("furthermore", "furthermore", "Contains 'furthermore' — too formal, sounds AI-generated"),
        ("in today's", "in_todays", "Contains 'in today's...' — generic AI opener"),
        ("i'd love to", "id_love_to", "Contains 'I'd love to' — overused AI phrase"),
        ("i came across", "came_across", "Contains 'I came across' — overused AI opener"),
        ("it's worth noting", "worth_noting", "Contains 'it's worth noting' — AI filler"),
        ("needless to say", "needless", "Contains 'needless to say' — if needless, don't say it"),
        ("at the end of the day", "end_of_day", "Contains 'at the end of the day' — cliché"),
    ]
    for marker, check_name, message in ai_tells:
        if marker in body if marker in ("—", "–") else marker in body_lower:
            report.add_issue("warning", f"ai_tell_{check_name}", message)

    # 8. Sign-off check — must include a signature block
    # Try to load expected sender info from config
    try:
        from backend.app.core.config import get_outreach_guidelines
        guidelines = get_outreach_guidelines()
        sender = guidelines.get("sender", {})
        sender_name = sender.get("name", "").lower() if sender.get("name") else ""
    except Exception:
        sender_name = ""

    # Only check for signature if config has a sender name
    if sender_name:
        if sender_name not in body_lower:
            report.add_issue(
                "warning", "no_signoff",
                f"Missing full signature (should include '{sender_name}')"
            )
    else:
        # Fallback: just check for any reasonable signature marker
        if "—" not in body and "//" not in body:
            report.add_issue(
                "warning", "no_signoff",
                "Missing signature block (should end with sender name and details)"
            )

    return report


def validate_batch(
    drafts: list[dict],
    db=None,
) -> list[QualityReport]:
    """Validate a batch of drafts.

    Args:
        drafts: List of outreach draft dicts.
        db: Optional Database instance for fetching company/research data.

    Returns:
        List of QualityReports.
    """
    reports = []

    for draft in drafts:
        company = None
        research = None

        if db:
            company_id = draft.get("company_id")
            if company_id:
                company = db.get_company(company_id)
                research = db.get_research(company_id)

        report = validate_draft(draft, company, research)
        reports.append(report)

    return reports
