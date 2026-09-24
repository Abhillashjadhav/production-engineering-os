"""Admission of typed process evidence inputs before provider/workspace side effects."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import strict_loads
from pmpe.evidence.process_gate_validation import snapshot_digest
from pmpe.process_approval import validate_approval_packet
from pmpe.process_sources import (
    implementation_identity,
    raw_digest,
    reject_bytecode,
    validate_sources,
)

if TYPE_CHECKING:
    from pmpe.barebones import CandidateSandbox, Template
    from pmpe.contracts.acceptance import AcceptanceBuildPlan
    from pmpe.model_provider import ModelProvider


@dataclass(frozen=True)
class ProcessGateInputs:
    approval_freeze: bytes = b""
    approval_freeze_expected_digest: str = ""
    approval_paths: Mapping[str, Path] = field(default_factory=dict)
    generation_mode: str = "unknown"
    provider_attestation: Mapping[str, str] = field(default_factory=dict)
    source_manifest: bytes = b""
    source_paths: Mapping[str, Path] = field(default_factory=dict)
    execution_profile: bytes = b""
    negative_controls: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    real_sandbox_leg: Mapping[str, str] = field(default_factory=dict)


def validate_process_inputs(
    plan: AcceptanceBuildPlan,
    inputs: ProcessGateInputs | None,
    template: Template,
    provider: ModelProvider,
    sandbox: CandidateSandbox,
    *,
    receipt_bytes: bytes | None = None,
    approval_verified: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    bindings = [gate.binding for gate in plan.release_gates if gate.binding is not None]
    if not bindings:
        return report
    from pmpe.barebones import ContractInvalidError

    try:
        reject_bytecode([Path(__file__).parent])
        if not isinstance(inputs, ProcessGateInputs):
            raise ValueError("process gate inputs are required")
        for binding in bindings:
            kind = binding["kind"]
            if kind == "negative_controls":
                for mutant in binding["mutants"]:
                    snapshot = inputs.negative_controls.get(mutant["id"])
                    if (
                        not isinstance(snapshot, Mapping)
                        or not snapshot
                        or any(
                            not isinstance(path, str) or not isinstance(content, bytes)
                            for path, content in snapshot.items()
                        )
                    ):
                        raise ValueError("process gate requires exact mutant snapshot bytes")
                    if snapshot_digest(snapshot) != mutant["snapshot_digest"]:
                        raise ValueError("process gate mutant snapshot digest mismatch")
            elif kind == "digest_boundaries":
                if raw_digest(inputs.source_manifest) != binding["source_manifest_digest"]:
                    raise ValueError("process gate source manifest binding mismatch")
                validate_sources(
                    inputs.source_manifest,
                    inputs.source_paths,
                    template,
                    inputs.execution_profile,
                    (provider, sandbox),
                )
                validate_approval_packet(
                    inputs, plan, receipt_bytes=receipt_bytes, approval_verified=approval_verified
                )
            elif kind == "generation_provenance":
                if (
                    inputs.generation_mode not in {"fresh", "replay"}
                    or set(inputs.provider_attestation) != {"kind", "statement"}
                    or inputs.provider_attestation["kind"] not in {"live_model", "test", "replay"}
                    or not inputs.provider_attestation["statement"].strip()
                ):
                    raise ValueError(
                        "process gate requires explicit generation mode and provider attestation"
                    )
                if inputs.provider_attestation["kind"] == "live_model":
                    from pmpe.cli.barebones_cmd import CommandModelProvider

                    implementation_identity(provider)
                    if type(provider) is not CommandModelProvider:
                        raise ValueError(
                            "process gate live-model attestation requires the command provider; "
                            "test providers cannot qualify"
                        )
            elif kind == "execution_disclosure":
                from pmpe.barebones import BubblewrapCandidateSandbox

                if type(sandbox) is not BubblewrapCandidateSandbox:
                    if not any(item["kind"] == "digest_boundaries" for item in bindings):
                        raise ValueError(
                            "process gate fallback disclosure requires a bound source manifest"
                        )
                    validate_sources(
                        inputs.source_manifest,
                        inputs.source_paths,
                        template,
                        inputs.execution_profile,
                        (provider, sandbox),
                    )
                profile = strict_loads(inputs.execution_profile, "application/json")
                if (
                    not isinstance(profile, dict)
                    or raw_digest(inputs.execution_profile) != binding["execution_profile_sha256"]
                ):
                    raise ValueError("process gate execution profile binding mismatch")
                leg = inputs.real_sandbox_leg
                if (
                    set(leg) != {"status", "reason"}
                    or leg["status"] not in {"ATTEMPTED", "BLOCKED", "NOT_ATTEMPTED"}
                    or not isinstance(leg["reason"], str)
                    or not leg["reason"].strip()
                ):
                    raise ValueError("process gate requires explicit sandbox-leg disclosure")
                report_method = getattr(sandbox, "isolation_report", None)
                if not callable(report_method):
                    raise ValueError("process gate sandbox must supply actual isolation report")
                report = report_method()
                if (
                    not isinstance(report, dict)
                    or set(report) != {"mode", "missing_isolations", "full_isolation_claimed"}
                    or report["mode"] not in {"bubblewrap", "authorized_host_fallback"}
                    or not isinstance(report["missing_isolations"], list)
                    or any(
                        not isinstance(item, str) or not item
                        for item in report["missing_isolations"]
                    )
                    or report["full_isolation_claimed"] is not False
                ):
                    raise ValueError(
                        "process gate isolation report is invalid or overclaims isolation"
                    )
                if (
                    report["mode"] == "bubblewrap"
                    and type(sandbox) is not BubblewrapCandidateSandbox
                ):
                    raise ValueError(
                        "process gate unknown sandbox cannot claim bubblewrap identity"
                    )
                if report["mode"] == "authorized_host_fallback" and (
                    not report["missing_isolations"]
                    or report["missing_isolations"]
                    != profile.get("authorized_fallback", {}).get(
                        "unavailable_additional_protections"
                    )
                ):
                    raise ValueError(
                        "process gate fallback must match bound profile isolation limits"
                    )
        return copy.deepcopy(report)
    except (ValueError, TypeError, AttributeError, KeyError, OSError) as exc:
        raise ContractInvalidError("process gate input invalid: " + str(exc)) from exc
