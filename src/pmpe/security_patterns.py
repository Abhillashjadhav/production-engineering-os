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

_CREDENTIAL_MATERIAL_PATTERNS = PROHIBITED_SECRET_PATTERNS + (
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(rb"\bglpat-[A-Za-z0-9_-]{16,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        rb"\b(?:AIza[0-9A-Za-z_-]{35}|sk_(?:live|test)_[0-9A-Za-z]{16,}"
        rb"|rk_(?:live|test)_[0-9A-Za-z]{16,}|npm_[0-9A-Za-z]{20,}"
        rb"|pypi-[0-9A-Za-z_-]{20,})\b"
    ),
    re.compile(
        rb"(?i)\b(?:sk-(?:proj|svcacct|ant)-[A-Za-z0-9_-]{16,}"
        rb"|sk-or-v1-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{20,}"
        rb"|hf_[A-Za-z0-9_-]{20,})\b"
    ),
    re.compile(rb"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+\-/=]{8,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.DOTALL),
)


def contains_prohibited_secret(payload: bytes) -> bool:
    """Return whether bytes match the canonical prohibited-secret patterns."""
    return any(pattern.search(payload) for pattern in PROHIBITED_SECRET_PATTERNS)


def contains_credential_material(payload: bytes) -> bool:
    """Return whether one scalar contains any credential format the platform redacts."""

    return any(pattern.search(payload) for pattern in _CREDENTIAL_MATERIAL_PATTERNS)
