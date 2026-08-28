"""Platform-neutral canonical prohibited-secret matching."""

from __future__ import annotations

import re

PROHIBITED_SECRET_PATTERNS = (
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        rb"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}"
    ),
)


def contains_prohibited_secret(payload: bytes) -> bool:
    """Return whether bytes match the canonical prohibited-secret patterns."""
    return any(pattern.search(payload) for pattern in PROHIBITED_SECRET_PATTERNS)
