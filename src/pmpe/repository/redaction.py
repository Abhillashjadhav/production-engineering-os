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

    version = "central-redactor/1.2.0"
    _token = re.compile(
        r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}"
        r"|glpat-[A-Za-z0-9_-]{16,}"
        r"|(?:api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]+"
        r"|(?:basic|bearer)\s+[A-Za-z0-9._~+\-/=]{8,})"
    )
    _authorization = re.compile(r"(?i)authorization\s*:\s*(?:basic|bearer|digest)\s+[^\s,;]+")
    _private_key = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    )
    _private_key_header = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*", re.DOTALL)
    _url_credentials = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@")
    _embedded_url = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>'\"]+")
    _common_access_key = re.compile(r"(?:AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})")
    _vendor_token = re.compile(
        r"(?:AIza[0-9A-Za-z_-]{35}|sk_(?:live|test)_[0-9A-Za-z]{16,}"
        r"|rk_(?:live|test)_[0-9A-Za-z]{16,}|npm_[0-9A-Za-z]{20,}"
        r"|pypi-[0-9A-Za-z_-]{20,})"
    )
    _sensitive_query = re.compile(r"(?i)(token|key|secret|password|signature|credential)")
    _sensitive_field = re.compile(
        r"(?i)(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key"
        r"|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret"
        r"|private[_-]?key|credential)"
    )

    def __init__(self) -> None:
        self._home = str(Path.home())

    def _sanitize_url(self, value: str) -> str:
        if "://" not in value:
            return value
        try:
            parts = urlsplit(value)
            hostname = parts.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            query = urlencode(
                [
                    (key, "[REDACTED]" if self._sensitive_query.search(key) else item)
                    for key, item in parse_qsl(parts.query, keep_blank_values=True)
                ]
            )
        except (UnicodeError, ValueError):
            return "[REDACTED_URL]"
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))

    def _sanitize_string(self, value: str) -> str:
        sanitized = self._private_key.sub("[REDACTED_PRIVATE_KEY]", value)
        sanitized = self._private_key_header.sub("[REDACTED_PRIVATE_KEY]", sanitized)
        sanitized = self._authorization.sub("Authorization: [REDACTED]", sanitized)
        sanitized = self._url_credentials.sub(r"\1[REDACTED]@", sanitized)
        sanitized = self._common_access_key.sub("[REDACTED]", sanitized)
        sanitized = self._vendor_token.sub("[REDACTED]", sanitized)
        sanitized = self._token.sub("[REDACTED]", sanitized)
        sanitized = self._embedded_url.sub(
            lambda match: self._sanitize_url(match.group(0)), sanitized
        )
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
                result: dict[str, Any] = {}
                for key, item in value.items():
                    safe_key = str(self.sanitize(key))
                    if safe_key in result:
                        raise RedactionError("redacted object keys collide")
                    result[safe_key] = (
                        "[REDACTED]"
                        if self._sensitive_field.search(safe_key)
                        else self.sanitize(item)
                    )
                return result
            if isinstance(value, (list, tuple)):
                return [self.sanitize(item) for item in value]
            if value is None or isinstance(value, (bool, int, float)):
                return value
        except Exception as exc:
            raise RedactionError("evidence redaction failed") from exc
        raise RedactionError("unsupported evidence type during redaction")
