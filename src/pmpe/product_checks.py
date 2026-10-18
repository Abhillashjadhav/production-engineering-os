"""Supervisor-evaluated checks bound to a sealed candidate and built-in profile."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.product_profile import CompiledProductProfile, ProductProfileError
from pmpe.product_syntax import check_python_syntax

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def candidate_manifest_digest(source_files: Mapping[str, bytes]) -> str:
    """Reconstruct the ledger's SHA-256 blob-of-manifest candidate identity."""

    if not all(
        isinstance(path, str) and isinstance(content, bytes)
        for path, content in source_files.items()
    ):
        raise ProductProfileError("source snapshot must contain byte values")
    files = {
        path: "sha256:" + hashlib.sha256(content).hexdigest()
        for path, content in sorted(source_files.items())
    }
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    stage: str
    status: str
    reason: str
    evidence_digest: str | None


@dataclass(frozen=True)
class RequiredCheckReport:
    binding: dict[str, Any]
    binding_digest: str
    results: tuple[CheckResult, ...]
    candidate_qualified: bool
    delivery_qualified: bool
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding,
            "binding_digest": self.binding_digest,
            "results": [item.__dict__ for item in self.results],
            "candidate_qualified": self.candidate_qualified,
            "delivery_qualified": self.delivery_qualified,
        }


def evaluate_required_checks(
    profile: CompiledProductProfile,
    *,
    candidate_digest: str,
    source_files: Mapping[str, bytes],
    acceptance_observations: Mapping[str, Mapping[str, Any]],
    security_findings: Sequence[str],
) -> RequiredCheckReport:
    """Evaluate only supervisor inputs; absent observations/adapters block.

    REV_REQUIRED_CHECKS: neither a candidate JSON check status nor a skipped
    adapter qualifies the sealed candidate. The caller must supply source and
    observations from the existing trusted snapshot/observer, never a provider.
    """

    if profile.manifest_digest != canonical_digest(profile.manifest):
        raise ProductProfileError("profile manifest binding changed")
    if not isinstance(candidate_digest, str) or _SHA256.fullmatch(candidate_digest) is None:
        raise ProductProfileError("candidate digest is malformed")
    if candidate_digest != candidate_manifest_digest(source_files):
        raise ProductProfileError("candidate manifest binding differs from sealed source snapshot")
    binding = {
        "schema_version": "peos-required-check-binding/v1",
        "profile_id": profile.profile_id,
        "profile_manifest_digest": profile.manifest_digest,
        "contract_digest": profile.contract_digest,
        "template_digest": profile.template_digest,
        "harness_digest": profile.harness_digest,
        "candidate_digest": candidate_digest,
    }
    evidence = {
        "source_files": {
            name: "sha256:" + hashlib.sha256(content).hexdigest()
            for name, content in sorted(source_files.items())
        },
        "observations": dict(acceptance_observations),
        "security_findings": list(security_findings),
    }
    results: list[CheckResult] = []
    for check in profile.checks:
        if check.check_id == "python-syntax":
            if not source_files:
                status, reason = "BLOCKED", "sealed source snapshot missing"
            else:
                status, reason = check_python_syntax(source_files)
        elif check.check_id == "source-security":
            if not source_files:
                status, reason = "BLOCKED", "sealed source snapshot missing"
            elif security_findings:
                status, reason = "FAIL", "trusted static scanner reported findings"
            else:
                status, reason = "PASS", "trusted static scanner found no findings"
        elif check.check_id == "functional-acceptance":
            if set(acceptance_observations) != set(profile.criterion_ids):
                status, reason = "BLOCKED", "required criterion observation missing or extra"
            elif all(
                item.get("criterion_id") == criterion_id
                and item.get("assertions_passed") is True
                and isinstance(item.get("response_digest"), str)
                and _SHA256.fullmatch(item["response_digest"]) is not None
                for criterion_id, item in acceptance_observations.items()
            ):
                status, reason = "PASS", "all fixed observer assertions passed"
            else:
                status, reason = "FAIL", "fixed observer assertion or evidence invalid"
        else:
            status, reason = "BLOCKED", "required trusted adapter unavailable"
        results.append(
            CheckResult(
                check.check_id,
                check.stage,
                status,
                reason,
                canonical_digest(evidence) if status != "BLOCKED" else None,
            )
        )
    candidate = [item for item in results if item.stage == "candidate"]
    return RequiredCheckReport(
        binding,
        canonical_digest(binding),
        tuple(results),
        bool(candidate) and all(item.status == "PASS" for item in candidate),
        bool(results) and all(item.status == "PASS" for item in results),
        evidence,
    )
