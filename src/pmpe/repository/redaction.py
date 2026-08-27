"""Central fail-closed redaction for persisted repository evidence."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any, final
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


class RedactionError(RuntimeError):
    """Raised when evidence cannot be safely sanitized."""


def assert_distinct_identities_preserved(
    namespace: str,
    identities: Iterable[tuple[str, str]],
) -> None:
    """Fail when redaction maps different persisted identities to one value."""

    originals_by_sanitized: dict[str, str] = {}
    for original, sanitized in identities:
        previous = originals_by_sanitized.setdefault(sanitized, original)
        if previous != original:
            raise RedactionError(f"redaction collapsed distinct identities in {namespace}")


@final
class EvidenceRedactor:
    """Sanitize all strings before they enter an artifact or diagnostic."""

    version = "central-redactor/2.7.0"
    __slots__ = ("_environment_secrets",)
    _token = re.compile(
        r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}"
        r"|glpat-[A-Za-z0-9_-]{16,}"
        r"|(?:api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]+"
        r"|(?:basic|bearer)\s+[A-Za-z0-9._~+\-/=]{8,})"
    )
    _authorization = re.compile(
        r"(?im)\b(?:proxy-)?authorization[ \t]*:[ \t]*[^\r\n]*"
        r"(?:\r?\n[ \t]+[^\r\n]*)*"
    )
    _cookie_header = re.compile(
        r"(?im)\b(?:set-)?cookie[ \t]*:[ \t]*[^\r\n]*"
        r"(?:\r?\n[ \t]+[^\r\n]*)*"
    )
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
    _modern_service_token = re.compile(
        r"(?i)(?:sk-(?:proj|svcacct|ant)-[A-Za-z0-9_-]{16,}"
        r"|sk-or-v1-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{20,}"
        r"|hf_[A-Za-z0-9_-]{20,})"
    )
    _sensitive_assignment = re.compile(
        r"(?i)(?P<quote>[\"']?)\b(?P<key>accountkey|sharedaccesskey|sharedaccesssignature"
        r"|pwd|password|passwd"
        r"|cookie|set-cookie|aws_access_key_id|aws_secret_access_key|aws_session_token"
        r"|client_secret|private_key|api[-_]?key|access[-_]?token|refresh[-_]?token"
        r"|token|secret|signature|sig|credential)"
        r"(?P=quote)(?P<separator>\s*[=:]\s*)"
        r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\{[^}]*\}|[^\s,;]+)"
    )
    _sensitive_whitespace_assignment = re.compile(
        r"(?i)(?P<prefix>^|[\s,;({\[])(?P<key>authorization|credential|password|passwd|pwd"
        r"|api[-_]?key|x-api-key|access[-_]?token|refresh[-_]?token|client[-_]?secret"
        r"|private[-_]?key|aws_access_key_id|aws_secret_access_key|aws_session_token"
        r"|token|secret|cookie|set-cookie)"
        r"(?P<separator>[ \t]+)"
        r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\{[^}]*\}|[^\s,;]+)"
    )
    _sensitive_query = re.compile(
        r"(?i)(?:^|[-_])(?:access[-_]?token|refresh[-_]?token|api[-_]?key|token|key"
        r"|secret|password|passwd|signature|sig|credential|code)(?:$|[-_])"
    )
    _sensitive_field = re.compile(
        r"(?i)(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key"
        r"|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret"
        r"|private[_-]?key|credential|token|signature|sig)"
    )
    _sensitive_environment_field = re.compile(
        r"(?i)(?:auth|authorization|cookie|credential|database[_-]?url|db[_-]?url"
        r"|redis[_-]?url|api[_-]?key|access[_-]?key|private[_-]?key|password|passwd"
        r"|pwd|secret|signature|token)"
    )
    _home_path = re.compile(
        r"(?<![A-Za-z0-9_])(?:(?:/Users|/home|/usr/home)/[^/\s]+|/var/root|/root)"
        r"(?=/|\s|$)"
    )

    @classmethod
    def _path_contains_credential(cls, hostname: str, path: str) -> bool:
        normalized = hostname.rstrip(".").lower()
        lowered_path = unquote(path).lower()
        return bool(
            (normalized == "hooks.slack.com" and lowered_path.startswith("/services/"))
            or (
                normalized == "api.telegram.org"
                and re.match(r"/bot[^/]+(?:/|$)", lowered_path, re.IGNORECASE)
            )
            or (
                (
                    normalized in {"discord.com", "discordapp.com"}
                    or normalized.endswith(".discord.com")
                    or normalized.endswith(".discordapp.com")
                )
                and lowered_path.startswith("/api/webhooks/")
            )
        )

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        source = os.environ if environment is None else environment
        self._environment_secrets = tuple(
            sorted(
                {
                    value
                    for key, value in source.items()
                    if self._sensitive_environment_field.search(key)
                    and isinstance(value, str)
                    and len(value) >= 4
                },
                key=lambda item: (-len(item), item),
            )
        )

    @staticmethod
    def _redact_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        replacement = (
            '"[REDACTED]"'
            if value.startswith('"')
            else "'[REDACTED]'"
            if value.startswith("'")
            else "[REDACTED]"
        )
        return (
            f"{match.group('quote')}{match.group('key')}{match.group('quote')}"
            f"{match.group('separator')}{replacement}"
        )

    @staticmethod
    def _redact_whitespace_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        unquoted = value.strip("\"'{}")
        credential_like = (
            value[:1] in {'"', "'", "{"}
            or len(unquoted) >= 16
            or any(character.isdigit() for character in unquoted)
            or any(character in "_-+=/@." for character in unquoted)
        )
        if not credential_like:
            return match.group(0)
        return f"{match.group('prefix')}{match.group('key')}{match.group('separator')}[REDACTED]"

    def _sanitize_url(self, value: str) -> str:
        if "://" not in value:
            return value
        try:
            parts = urlsplit(value)
            hostname = (parts.hostname or "").rstrip(".").lower()
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            path = (
                "/[REDACTED_PATH]"
                if self._path_contains_credential(hostname, parts.path)
                else parts.path
            )
            query = urlencode(
                [
                    (key, "[REDACTED]" if self._sensitive_query.search(key) else item)
                    for key, item in parse_qsl(parts.query, keep_blank_values=True)
                ]
            )
        except (UnicodeError, ValueError):
            return "[REDACTED_URL]"
        return urlunsplit((parts.scheme, netloc, path, query, ""))

    @classmethod
    def _url_contains_credential(cls, value: str) -> bool:
        if "://" not in value:
            return False
        try:
            parts = urlsplit(value)
            hostname = (parts.hostname or "").rstrip(".").lower()
            return bool(
                parts.username is not None
                or parts.password is not None
                or cls._path_contains_credential(hostname, parts.path)
                or any(
                    cls._sensitive_query.search(key)
                    for component in (parts.query, parts.fragment)
                    for key, _ in parse_qsl(component, keep_blank_values=True)
                )
            )
        except (UnicodeError, ValueError):
            return True

    def _sanitize_string(self, value: str) -> str:
        sanitized = value
        for secret in self._environment_secrets:
            sanitized = sanitized.replace(secret, "[REDACTED_ENV]")
        sanitized = self._private_key.sub("[REDACTED_PRIVATE_KEY]", sanitized)
        sanitized = self._private_key_header.sub("[REDACTED_PRIVATE_KEY]", sanitized)
        sanitized = self._authorization.sub("Authorization: [REDACTED]", sanitized)
        sanitized = self._cookie_header.sub("Cookie: [REDACTED]", sanitized)
        sanitized = self._url_credentials.sub(r"\1[REDACTED]@", sanitized)
        sanitized = self._common_access_key.sub("[REDACTED]", sanitized)
        sanitized = self._vendor_token.sub("[REDACTED]", sanitized)
        sanitized = self._modern_service_token.sub("[REDACTED]", sanitized)
        sanitized = self._sensitive_assignment.sub(self._redact_assignment, sanitized)
        sanitized = self._sensitive_whitespace_assignment.sub(
            self._redact_whitespace_assignment, sanitized
        )
        sanitized = self._token.sub("[REDACTED]", sanitized)
        sanitized = self._embedded_url.sub(
            lambda match: self._sanitize_url(match.group(0)), sanitized
        )
        return self._home_path.sub("$HOME", sanitized)

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
                    sensitive_field = self._sensitive_field.search(safe_key) is not None
                    result[safe_key] = (
                        "[REDACTED]"
                        if sensitive_field and not isinstance(item, bool)
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


def contains_known_credential(text: str) -> bool:
    """Return whether text matches any central credential-redaction rule."""
    patterns = (
        EvidenceRedactor._token,
        EvidenceRedactor._authorization,
        EvidenceRedactor._cookie_header,
        EvidenceRedactor._private_key,
        EvidenceRedactor._private_key_header,
        EvidenceRedactor._url_credentials,
        EvidenceRedactor._common_access_key,
        EvidenceRedactor._vendor_token,
        EvidenceRedactor._modern_service_token,
        EvidenceRedactor._sensitive_assignment,
        EvidenceRedactor._sensitive_whitespace_assignment,
    )
    if any(pattern.search(text) for pattern in patterns):
        return True
    return any(
        EvidenceRedactor._url_contains_credential(match.group(0))
        for match in EvidenceRedactor._embedded_url.finditer(text)
    )
