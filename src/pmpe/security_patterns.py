"""Platform-neutral canonical prohibited-secret matching."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

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
    re.compile(rb"(?i)\b[a-z][a-z0-9+.-]*://[^/@\s]+@"),
    re.compile(
        rb"(?i)[\"']?\b(?:accountkey|sharedaccesskey|sharedaccesssignature|pwd|password"
        rb"|passwd|authorization|proxy-authorization|cookie|set-cookie"
        rb"|aws_access_key_id|aws_secret_access_key"
        rb"|aws_session_token|client_secret|private_key|api[-_]?key|access[-_]?token"
        rb"|refresh[-_]?token|token|secret|signature|sig|credential)[\"']?"
        rb"\s*[=:]\s*(?:\"[^\"]+\"|'[^']+'|[^\s,;]+)"
    ),
    re.compile(
        rb"(?i)(?:^|[\s,;({\[])(?:authorization|credential|password|passwd|pwd"
        rb"|api[-_]?key|x-api-key|access[-_]?token|refresh[-_]?token"
        rb"|client[-_]?secret|private[-_]?key|aws_access_key_id"
        rb"|aws_secret_access_key|aws_session_token|token|secret|cookie|set-cookie)"
        rb"[ \t]+(?:\"[^\"]+\"|'[^']+'|[^\s,;]+)"
    ),
)

_EMBEDDED_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+")
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?i)(?:^|[-_])(?:access[-_]?token|refresh[-_]?token|api[-_]?key|token|key"
    r"|secret|password|passwd|signature|sig|credential|code)(?:$|[-_])"
)


def contains_prohibited_secret(payload: bytes) -> bool:
    """Return whether bytes match the canonical prohibited-secret patterns."""
    return any(pattern.search(payload) for pattern in PROHIBITED_SECRET_PATTERNS)


def contains_credential_material(payload: bytes) -> bool:
    """Return whether one scalar contains any credential format the platform redacts."""

    if any(pattern.search(payload) for pattern in _CREDENTIAL_MATERIAL_PATTERNS):
        return True
    text = payload.decode("utf-8", errors="replace")
    for match in _EMBEDDED_URL.finditer(text):
        try:
            parts = urlsplit(match.group(0))
            if any(
                _SENSITIVE_QUERY_KEY.search(key)
                for component in (parts.query, parts.fragment)
                for key, _ in parse_qsl(component, keep_blank_values=True)
            ):
                return True
        except (UnicodeError, ValueError):
            return True
    return False
