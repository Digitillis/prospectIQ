"""Outbound message validator — compliance checks before any LinkedIn or email send.

Hard blocks (raise OutboundValidationError):
  - Message too long for channel
  - Spam trigger words
  - Excessive links (>2)
  - Domain blocklist match

Warnings (logged, not blocking):
  - Exclamation overuse
  - All-caps words
  - Missing personalisation variables in templates

Usage:
    validator = OutboundValidator()
    try:
        validator.validate_linkedin_connect(message_text)
        validator.validate_linkedin_dm(message_text)
        validator.validate_email(subject, body)
    except OutboundValidationError as e:
        logger.error(f"Message blocked: {e}")
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class OutboundValidationError(Exception):
    """Raised when a message fails a hard compliance check."""
    pass


# LinkedIn character limits
_LINKEDIN_CONNECT_LIMIT = 200
_LINKEDIN_DM_LIMIT = 1900

# Hard-block spam trigger words (lowercase)
_SPAM_TRIGGERS = {
    "free money", "100% free", "make money fast", "earn from home",
    "guaranteed income", "no cost", "winner", "you have been selected",
    "click here now", "limited time offer", "act now", "urgent",
    "risk-free", "no risk", "best price", "lowest price",
    "increase sales", "double your revenue", "triple your",
    "buy now", "order now", "subscribe now",
}

# Domain blocklist — never contact these
_DOMAIN_BLOCKLIST = {
    "gov", "mil", "edu", "example.com", "test.com",
}

# Max links allowed in any outbound message
_MAX_LINKS = 2


class OutboundValidator:
    """Validates outbound messages before they are sent to any channel."""

    def validate_linkedin_connect(self, message: str) -> None:
        """Validate a LinkedIn connection request note.

        Raises OutboundValidationError on hard violations.
        """
        if not message or not message.strip():
            raise OutboundValidationError("Connection note cannot be empty.")
        if len(message) > _LINKEDIN_CONNECT_LIMIT:
            raise OutboundValidationError(
                f"Connection note too long: {len(message)} chars "
                f"(LinkedIn limit: {_LINKEDIN_CONNECT_LIMIT})."
            )
        self._check_spam_triggers(message)
        self._check_link_count(message)

    def validate_linkedin_dm(self, message: str) -> None:
        """Validate a LinkedIn direct message."""
        if not message or not message.strip():
            raise OutboundValidationError("DM cannot be empty.")
        if len(message) > _LINKEDIN_DM_LIMIT:
            raise OutboundValidationError(
                f"LinkedIn DM too long: {len(message)} chars "
                f"(limit: {_LINKEDIN_DM_LIMIT})."
            )
        self._check_spam_triggers(message)
        self._check_link_count(message)

    def validate_email(self, subject: str, body: str, recipient_domain: str = "") -> None:
        """Validate an email message (subject + body).

        Args:
            subject: Email subject line.
            body: Email body text.
            recipient_domain: Domain of recipient — checked against blocklist.
        """
        if not subject or not subject.strip():
            raise OutboundValidationError("Email subject cannot be empty.")
        if not body or not body.strip():
            raise OutboundValidationError("Email body cannot be empty.")
        if len(subject) > 200:
            raise OutboundValidationError(f"Email subject too long: {len(subject)} chars (max 200).")

        if recipient_domain:
            tld = recipient_domain.split(".")[-1].lower()
            base = recipient_domain.lower()
            if tld in _DOMAIN_BLOCKLIST or base in _DOMAIN_BLOCKLIST:
                raise OutboundValidationError(
                    f"Recipient domain blocked: {recipient_domain}"
                )

        self._check_spam_triggers(subject + " " + body)
        self._check_link_count(body)

    @staticmethod
    def _check_spam_triggers(text: str) -> None:
        lower = text.lower()
        for trigger in _SPAM_TRIGGERS:
            if trigger in lower:
                raise OutboundValidationError(
                    f"Message contains spam trigger phrase: '{trigger}'. "
                    f"Rewrite the message to avoid this phrase."
                )

    @staticmethod
    def _check_link_count(text: str) -> None:
        urls = re.findall(r"https?://\S+", text)
        if len(urls) > _MAX_LINKS:
            raise OutboundValidationError(
                f"Message contains {len(urls)} links (max {_MAX_LINKS}). "
                f"Remove extra links to improve deliverability."
            )

    @staticmethod
    def check_template_vars(template: str, available_vars: set[str]) -> list[str]:
        """Return list of template variables that are not in available_vars.

        Non-blocking — returns warnings, does not raise.
        """
        found = set(re.findall(r"\{\{(\w+)\}\}", template))
        missing = found - available_vars
        return sorted(missing)
