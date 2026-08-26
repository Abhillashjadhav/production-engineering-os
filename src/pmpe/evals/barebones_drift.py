"""Deterministic behavior-drift comparison for recorded provider responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ProviderBehavior:
    purpose: str
    request_digest: str
    output_digest: str
    provider: str
    model: str
    prompt_version: str
    cli_version: str


@dataclass(frozen=True)
class BehaviorDrift:
    detected: bool
    cause: str
    attribution: tuple[str, ...]
    baseline_output_digest: str
    current_output_digest: str


def observe_provider_behavior(*, purpose: str, response: Mapping[str, Any]) -> ProviderBehavior:
    """Reduce one recorded provider response to comparable, non-secret behavior evidence."""

    if purpose not in {"code", "advisory_review"}:
        raise ValueError("unsupported provider purpose")
    request_digest = response.get("request_digest")
    metadata = response.get("provider_metadata")
    if (
        not isinstance(request_digest, str)
        or _DIGEST.fullmatch(request_digest) is None
        or not isinstance(metadata, Mapping)
    ):
        raise ValueError("provider response lacks digest-bound metadata")
    identity: dict[str, str] = {}
    for field in ("provider", "model", "prompt_version"):
        value = metadata.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"provider metadata lacks {field}")
        identity[field] = value
    cli_version = metadata.get("cli_version", "unknown")
    if not isinstance(cli_version, str) or not cli_version:
        raise ValueError("provider metadata has malformed cli_version")
    if purpose == "code":
        output = response.get("files")
        if not isinstance(output, Mapping) or any(
            not isinstance(path, str) or not isinstance(content, str)
            for path, content in output.items()
        ):
            raise ValueError("code response lacks a UTF-8 file mapping")
    else:
        output = response.get("summary")
        if not isinstance(output, str):
            raise ValueError("advisory response lacks a summary")
    return ProviderBehavior(
        purpose=purpose,
        request_digest=request_digest,
        output_digest=canonical_digest(output),
        provider=identity["provider"],
        model=identity["model"],
        prompt_version=identity["prompt_version"],
        cli_version=cli_version,
    )


def compare_provider_behavior(
    baseline: ProviderBehavior, current: ProviderBehavior
) -> BehaviorDrift:
    """Detect output drift and name changed provider configuration that can explain it."""

    if (baseline.purpose, baseline.request_digest) != (
        current.purpose,
        current.request_digest,
    ):
        raise ValueError("provider behavior observations are not comparable")
    if baseline.output_digest == current.output_digest:
        return BehaviorDrift(
            False,
            "NO_BEHAVIOR_DRIFT",
            (),
            baseline.output_digest,
            current.output_digest,
        )
    attribution = tuple(
        field
        for field in ("provider", "model", "prompt_version", "cli_version")
        if getattr(baseline, field) != getattr(current, field)
    )
    return BehaviorDrift(
        True,
        "PROVIDER_CONFIGURATION_CHANGED" if attribution else "UNATTRIBUTED_BEHAVIOR_DRIFT",
        attribution,
        baseline.output_digest,
        current.output_digest,
    )
