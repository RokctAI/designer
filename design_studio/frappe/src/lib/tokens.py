"""Review-token generation and expiry checks for Design Approval links.

Pure functions: no frappe, no database. Tokens are opaque URL-safe
strings; guests only ever see the token, never internal doc names.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta

TOKEN_BYTES = 32  # 256 bits of entropy -> 43-char urlsafe string
DEFAULT_EXPIRY_DAYS = 14

REVIEW_DECISIONS = ("Approved", "Rejected", "Changes Requested")


def generate_review_token(nbytes: int = TOKEN_BYTES) -> str:
    """Cryptographically random, URL-safe, no padding characters."""
    return secrets.token_urlsafe(nbytes)


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison for token checks."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def default_expiry(now: datetime, days: int = DEFAULT_EXPIRY_DAYS) -> datetime:
    return now + timedelta(days=days)


def token_expired(expires_on: datetime | None, now: datetime) -> bool:
    """No expiry set means the link never expires."""
    if expires_on is None:
        return False
    return now >= expires_on


def is_valid_decision(decision: str) -> bool:
    return decision in REVIEW_DECISIONS
