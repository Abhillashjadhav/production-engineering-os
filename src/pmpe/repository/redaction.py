"""Central fail-closed redaction for persisted repository evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class RedactionError(RuntimeError):
    """Raised when evidence cannot be safely sanitized."""


class EvidenceRedactor:
    """Sanitize all strings before they enter an artifact or diagnostic."""

    version = "central-redactor/1.0.0"
    _token = re.compile(
        r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}"
        r"|(?:api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]+"
        r"|bearer\s+[A-Za-z0-9._~+\-/=]{12,})"
    )
    _private_key = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    )
    _sensitive_query = re.compile(r"(?i)(token|key|secret|password|signature|credential)")

    def __init__(self) -> None:
        self._home = str(Path.home())

    def _sanitize_url(self, value: str) -> str:
        if "://" not in value:
            return value
        try:
            parts = urlsplit(value)
        except ValueError:
            return "[REDACTED_URL]"
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        query = urlencode(
            [
                (key, "[REDACTED]" if self._sensitive_query.search(key) else item)
                for key, item in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))

    def _sanitize_string(self, value: str) -> str:
        sanitized = self._private_key.sub("[REDACTED_PRIVATE_KEY]", value)
        sanitized = self._token.sub("[REDACTED]", sanitized)
        if "://" in sanitized:
            sanitized = self._sanitize_url(sanitized)
        if self._home and sanitized.startswith(self._home):
            sanitized = "$HOME" + sanitized[len(self._home) :]
        return sanitized

    def sanitize(self, value: Any) -> Any:
        try:
            if isinstance(value, str):
                return self._sanitize_string(value)
            if isinstance(value, bytes):
                return self._sanitize_string(value.decode("utf-8", errors="replace"))
            if isinstance(value, dict):
                return {str(self.sanitize(key)): self.sanitize(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [self.sanitize(item) for item in value]
            if value is None or isinstance(value, (bool, int, float)):
                return value
        except Exception as exc:
            raise RedactionError("evidence redaction failed") from exc
        raise RedactionError("unsupported evidence type during redaction")
