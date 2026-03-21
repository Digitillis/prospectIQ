"""Domain and MX record verification.

Validates that a company's email domain is active and can receive
email before spending Apollo credits on enrichment. Prevents:
- Wasted enrichment credits on dead domains
- Email bounces that damage sender reputation
- Outreach to companies that no longer exist
"""

from __future__ import annotations

import logging
import socket
from functools import lru_cache

logger = logging.getLogger(__name__)

# Cache MX lookups — domains don't change frequently
_mx_cache: dict[str, tuple[bool, str]] = {}


def verify_domain(domain: str | None) -> tuple[bool, str]:
    """Verify a domain has valid MX records and can receive email.

    Args:
        domain: Company domain (e.g., 'acme.com').

    Returns:
        Tuple of (is_valid, reason).
        is_valid=True means the domain has MX records and can receive email.
    """
    if not domain:
        return False, "no_domain"

    # Normalize
    domain = domain.lower().strip().lstrip("www.")

    # Check cache
    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        import dns.resolver

        # Check MX records first (preferred)
        try:
            mx_records = dns.resolver.resolve(domain, "MX")
            if mx_records:
                result = (True, f"mx_valid:{len(mx_records)}_records")
                _mx_cache[domain] = result
                return result
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass
        except dns.resolver.NoNameservers:
            result = (False, "dns_unreachable")
            _mx_cache[domain] = result
            return result

        # Fallback: check A record (some domains accept email without MX)
        try:
            a_records = dns.resolver.resolve(domain, "A")
            if a_records:
                result = (True, "a_record_only")
                _mx_cache[domain] = result
                return result
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass

        result = (False, "no_mx_or_a_records")
        _mx_cache[domain] = result
        return result

    except ImportError:
        # dnspython not installed — fall back to socket
        return _verify_domain_socket(domain)
    except Exception as e:
        logger.warning(f"DNS lookup failed for {domain}: {e}")
        # Don't cache failures from transient errors
        return (True, "dns_lookup_error_assumed_valid")


def _verify_domain_socket(domain: str) -> tuple[bool, str]:
    """Fallback domain verification using socket when dnspython is unavailable."""
    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        socket.getaddrinfo(domain, 25, socket.AF_INET, socket.SOCK_STREAM)
        result = (True, "socket_port25_reachable")
        _mx_cache[domain] = result
        return result
    except socket.gaierror:
        # Domain doesn't resolve at all
        result = (False, "domain_not_found")
        _mx_cache[domain] = result
        return result
    except socket.timeout:
        # Timeout — assume valid (don't block on network issues)
        return (True, "socket_timeout_assumed_valid")
    except Exception as e:
        logger.warning(f"Socket verification failed for {domain}: {e}")
        return (True, "socket_error_assumed_valid")


def extract_domain_from_email(email: str | None) -> str | None:
    """Extract domain from an email address."""
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].lower().strip()


def clear_cache() -> None:
    """Clear the MX verification cache."""
    _mx_cache.clear()
