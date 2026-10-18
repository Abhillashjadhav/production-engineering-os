"""Bounded, deterministic disclosure checks before a provider or evidence sink.

This detects known credential forms, ambient secret values and explicit synthetic
private-data canaries. It does not claim to classify arbitrary personal data.
No decision contains the inspected value or a path supplied by the request.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

_MAX_BYTES = 1_000_000
_MAX_NODES = 30_000
_MAX_DEPTH = 16
_ALLOWED_REQUEST_KEYS = frozenset({"contract", "plan", "files", "findings", "request_digest"})
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|secret|token|credential|api[_-]?key|"
    r"private[_-]?key|env(?:ironment)?)(?:$|[_-])",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_-])(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9_.~+/-]{12,})",
    re.IGNORECASE,
)
_CANARY = re.compile(
    r"(?:PEOS|PMPE|SYNTHETIC)[_-](?:(?:PRIVATE|PII|CUSTOMER|SECRET)[_-])?"
    r"CANARY(?:[_-][A-Za-z0-9]+)*|"
    r"PEOS[_-]PRIVATE[_-][A-Za-z0-9_-]{5,}|"
    r"PEOS[_-]PLANTED[_-]SECRET",
    re.IGNORECASE,
)


class PrivacyPolicyError(RuntimeError):
    """Fixed diagnostic without inspected content, keys, paths or environment values."""

    def __init__(self, rule_id: str) -> None:
        self.rule_id = rule_id
        super().__init__("MODEL_REQUEST_PRIVACY_BLOCKED")


@dataclass(frozen=True)
class ProviderPrivacyPolicy:
    """Declared disclosure destination and retention boundary, never a bypass.

    The generic command's external retention is unknown; run-local describes
    only an offline confined adapter, not a guarantee about copied evidence.
    """

    destination: str = "generic_command"
    retention: str = "external_unknown"

    def __post_init__(self) -> None:
        if (self.destination, self.retention) not in {
            ("generic_command", "external_unknown"),
            ("offline_confined", "run_local"),
        }:
            raise ValueError("unsupported provider privacy destination or retention")


def _ambient_secret_values() -> tuple[str, ...]:
    __tracebackhide__ = True
    # Deliberately inspect only likely secret variables. No values leave this
    # function except for in-memory comparison, and short/common values are
    # excluded to avoid false matches against ordinary contract prose.
    return tuple(
        value for key, value in os.environ.items() if _SENSITIVE_KEY.search(key) and len(value) >= 8
    )


def _check_string(value: str, matches_ambient_secret: Callable[[str], bool]) -> None:
    __tracebackhide__ = True
    if _CREDENTIAL.search(value):
        raise PrivacyPolicyError("POL-016")
    if _CANARY.search(value):
        raise PrivacyPolicyError("POL-018")
    if matches_ambient_secret(value):
        raise PrivacyPolicyError("POL-017")


def validate_private_payload(payload: Any, *, policy: ProviderPrivacyPolicy | None = None) -> None:
    """Reject known secrets/canaries in contract, receipt, request or response.

    Iterative traversal bounds nested input before any serializer/provider call.
    The original payload is never copied, changed, logged or included in errors.
    """
    __tracebackhide__ = True
    active_policy = policy or ProviderPrivacyPolicy()
    if not isinstance(active_policy, ProviderPrivacyPolicy):
        raise PrivacyPolicyError("POL-014")
    ambient_secrets = _ambient_secret_values()

    def matches_ambient_secret(value: str) -> bool:
        __tracebackhide__ = True
        return any(secret in value for secret in ambient_secrets)

    stack: list[tuple[Any, int]] = [(payload, 0)]
    nodes = 0
    size = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise PrivacyPolicyError("POL-015")
        if isinstance(value, str):
            size += len(value.encode("utf-8"))
            if size > _MAX_BYTES:
                raise PrivacyPolicyError("POL-015")
            _check_string(value, matches_ambient_secret)
        elif isinstance(value, Mapping):
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise PrivacyPolicyError("POL-014")
                if _SENSITIVE_KEY.search(key):
                    raise PrivacyPolicyError("POL-017")
                stack.append((nested, depth + 1))
                stack.append((key, depth + 1))
        elif isinstance(value, (list, tuple)):
            stack.extend((nested, depth + 1) for nested in value)
        elif value is None or type(value) in (bool, int, float):
            size += 32
        else:
            raise PrivacyPolicyError("POL-014")
        if size > _MAX_BYTES:
            raise PrivacyPolicyError("POL-015")


def validate_private_blobs(blobs: Mapping[str, bytes]) -> None:
    """Inspect every candidate blob before any blob in a snapshot is persisted."""
    __tracebackhide__ = True
    for payload in blobs.values():
        if len(payload) > _MAX_BYTES:
            raise PrivacyPolicyError("POL-015")
        validate_private_payload(payload.decode("utf-8", errors="ignore"))


def validate_provider_request(
    purpose: str,
    request: Mapping[str, Any],
    *,
    policy: ProviderPrivacyPolicy | None = None,
) -> None:
    """Require explicit context fields and inspect every nested value."""
    __tracebackhide__ = True
    if purpose not in {"code", "advisory_review"}:
        raise PrivacyPolicyError("POL-014")
    if not isinstance(request, Mapping) or frozenset(request) not in {
        frozenset({"request_digest"}),
        _ALLOWED_REQUEST_KEYS,
        _ALLOWED_REQUEST_KEYS | {"task_graph"},
    }:
        raise PrivacyPolicyError("POL-014")
    if not isinstance(request.get("request_digest"), str):
        raise PrivacyPolicyError("POL-014")
    if "files" in request and not isinstance(request.get("files"), Mapping):
        raise PrivacyPolicyError("POL-014")
    validate_private_payload(request, policy=policy)


__all__ = [
    "PrivacyPolicyError",
    "ProviderPrivacyPolicy",
    "validate_private_payload",
    "validate_private_blobs",
    "validate_provider_request",
]
