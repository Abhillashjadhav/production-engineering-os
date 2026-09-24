"""Typed inputs and runtime integration for explicitly declared process gates."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.process_collection import RecordingSandbox
from pmpe.process_evaluators import (
    criterion_evidence,
    digest_boundaries_result,
    execution_disclosure_result,
    generation_provenance_result,
    negative_controls_result,
)
from pmpe.process_gate_inputs import ProcessGateInputs, validate_process_inputs
from pmpe.process_sources import (
    build_source_manifest,
    implementation_identity,
    raw_digest,
    validate_sources,
)

if TYPE_CHECKING:
    from pmpe.barebones import CandidateSandbox, Finding, Template
    from pmpe.contracts.acceptance import AcceptanceBuildPlan
    from pmpe.evidence.ledger import EvidenceLedger
    from pmpe.model_provider import ModelProvider

__all__ = [
    "ProcessGateInputs",
    "ProcessGateRuntime",
    "build_source_manifest",
    "raw_digest",
    "validate_process_inputs",
]


class ProcessGateRuntime:
    def __init__(
        self,
        plan: AcceptanceBuildPlan,
        inputs: ProcessGateInputs,
        template: Template,
        provider: ModelProvider,
        sandbox: CandidateSandbox,
        ledger: EvidenceLedger,
    ) -> None:
        self.plan, self.inputs, self.template, self.ledger = plan, inputs, template, ledger
        self.bindings = [gate.binding for gate in plan.release_gates if gate.binding is not None]
        paths: dict[str, Path] = {}
        expected: dict[str, str] = {}
        if any(binding["kind"] == "digest_boundaries" for binding in self.bindings):
            paths, expected = validate_sources(
                inputs.source_manifest,
                inputs.source_paths,
                template,
                inputs.execution_profile,
                (provider, sandbox),
            )
        self.sandbox = RecordingSandbox(sandbox, ledger, paths, expected)
        self.provider_class = type(provider).__module__ + "." + type(provider).__qualname__
        self.origin: dict[str, bytes] = {}
        self.baseline: tuple[Finding, ...] = ()
        self.controls: list[dict[str, Any]] = []
        self.disclosure: dict[str, Any] = {}
        if any(binding["kind"] == "execution_disclosure" for binding in self.bindings):
            report = sandbox.isolation_report()  # type: ignore[attr-defined]
            self.disclosure = {
                "effective_uid": os.geteuid(),
                "is_root": os.geteuid() == 0,
                "sandbox_class": type(sandbox).__module__ + "." + type(sandbox).__qualname__,
                "sandbox_identity": implementation_identity(sandbox),
                "isolation_mode": report["mode"],
                "missing_isolations": report["missing_isolations"],
                "full_isolation_claimed": False,
                "isolation_report_limit": (
                    "Sandbox implementation report; not independent isolation certification."
                ),
                "approval_receipt_authentication": (
                    "content-hash and operator authority; unsigned "
                    "and forgeable by recomputing public hashes"
                ),
                "generation_mode": inputs.generation_mode,
                "real_sandbox_leg": dict(inputs.real_sandbox_leg),
                "real_sandbox_leg_basis": (
                    "Operator-supplied historical/current disclosure; no new attempt implied."
                ),
                "execution_profile_sha256": raw_digest(inputs.execution_profile),
                "readiness_scope": "can attempt and evaluate; not a delivery guarantee",
                "tamper_limit": (
                    "Root can rewrite checker/evidence or make and "
                    "restore transient changes; hashes are not prevention."
                ),
            }

    def materialized(self, origin: Mapping[str, bytes], protected: set[str]) -> None:
        self.origin = dict(origin)
        self.sandbox.protected = {path: origin[path] for path in protected if path in origin}
        blobs = [self.sandbox.blob(value) for value in origin.values()]
        blobs.extend(self.sandbox.blob(path.read_bytes()) for path in self.sandbox.paths.values())
        blobs.extend(
            self.sandbox.blob(value)
            for value in (self.inputs.source_manifest, self.inputs.execution_profile)
            if value
        )
        evidence = {
            "run_id": self.ledger.run_id,
            "template_files": {path: raw_digest(content) for path, content in origin.items()},
            "protected_files": {
                path: raw_digest(content) for path, content in self.sandbox.protected.items()
            },
            "disclosure": self.disclosure,
        }
        blob = self.sandbox.blob(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        )
        self.ledger.append(
            event_type="process_evidence_started",
            state="VALIDATED",
            subject_digest=self.plan.contract_digest,
            blob_digests=(*blobs, blob),
            payload=evidence,
        )
        self.sandbox.boundary("command_before")

    def baseline_complete(self, findings: tuple[Finding, ...]) -> None:
        self.baseline = findings
        self.sandbox.boundary("command_after")

    def start_attempt(self, attempt: int) -> None:
        self.controls = []
        self.sandbox.phase, self.sandbox.attempt = "candidate", attempt
        self.sandbox.boundary("command_before")

    def evaluate_controls(self, snapshot: Mapping[str, bytes]) -> None:
        from pmpe.barebones import ContractInvalidError, _candidate_manifest, _verify_snapshot

        required = {
            mutant["id"]: mutant
            for binding in self.bindings
            if binding["kind"] == "negative_controls"
            for mutant in binding["mutants"]
        }
        candidate_digest, candidate_blobs = _candidate_manifest(snapshot, self.ledger)
        self.sandbox.blobs.update((candidate_digest, *candidate_blobs))
        for identifier, binding in required.items():
            mutant = self.inputs.negative_controls[identifier]
            changed = sorted(
                path
                for path in set(snapshot) | set(mutant)
                if snapshot.get(path) != mutant.get(path)
            )
            invalid = (
                not changed
                or set(snapshot) != set(mutant)
                or any(
                    path in self.sandbox.protected
                    or any(path.startswith(prefix) for prefix in binding["must_not_touch"])
                    for path in changed
                )
            )
            outcomes: dict[str, tuple[Finding, ...]] = {}
            error = ""
            if not invalid:
                self.sandbox.phase = "mutant:" + identifier
                try:
                    _verify_snapshot(
                        self.plan, mutant, self.template, self.sandbox, criterion_results=outcomes
                    )
                except (ContractInvalidError, ValueError) as exc:
                    error = str(exc)
            mutant_digest, mutant_blobs = _candidate_manifest(mutant, self.ledger)
            self.sandbox.blobs.update((mutant_digest, *mutant_blobs))
            self.controls.append(
                {
                    "run_id": self.ledger.run_id,
                    "attempt": self.sandbox.attempt,
                    "mutant_id": identifier,
                    "candidate_digest": candidate_digest,
                    "mutant_digest": mutant_digest,
                    "plan_digest": self.plan.plan_digest,
                    "changed_paths": changed,
                    "invalid_mutation": invalid,
                    "error": error,
                    "criterion_results": criterion_evidence(
                        outcomes, [item.criterion_id for item in self.plan.criteria]
                    ),
                }
            )
        self.sandbox.phase = "candidate"

    def results(
        self,
        snapshot: Mapping[str, bytes],
        outcomes: Mapping[str, tuple[Finding, ...]],
        attempt: int,
    ) -> dict[str, dict[str, Any]]:
        self.sandbox.phase = "candidate"
        boundary_error = ""
        try:
            self.sandbox.boundary("command_after")
            self.sandbox.boundary("release_before")
        except ValueError as exc:
            boundary_error = str(exc)
        ids = [item.criterion_id for item in self.plan.criteria]
        mutants = list(
            dict.fromkeys(
                mutant["id"]
                for binding in self.bindings
                if binding["kind"] == "negative_controls"
                for mutant in binding["mutants"]
            )
        )
        results: dict[str, dict[str, Any]] = {}
        for gate in self.plan.release_gates:
            binding = gate.binding
            if binding is None:
                continue
            kind = binding["kind"]
            if kind == "negative_controls":
                status, evidence = negative_controls_result(
                    binding,
                    self.baseline,
                    self.controls,
                    ids,
                    {
                        item.criterion_id
                        for item in self.plan.criteria
                        if item.form != "satisfied_by_template"
                    },
                )
            elif kind == "digest_boundaries":
                status, evidence = digest_boundaries_result(self.sandbox, attempt, ids, mutants)
                evidence["source_manifest_digest"] = raw_digest(self.inputs.source_manifest)
                if boundary_error:
                    status = "FAIL"
                    evidence["boundary_error"] = boundary_error
            elif kind == "generation_provenance":
                status, evidence = generation_provenance_result(
                    ledger=self.ledger,
                    snapshot=snapshot,
                    origin=self.origin,
                    process_records=self.sandbox.selected(self.sandbox.records, attempt),
                    criterion_ids=ids,
                    criterion_results=outcomes,
                    attempt=attempt,
                    generation_mode=self.inputs.generation_mode,
                    provider_attestation=self.inputs.provider_attestation,
                    provider_class=self.provider_class,
                    contract_digest=self.plan.contract_digest,
                )
            else:
                status, evidence = execution_disclosure_result(binding, self.disclosure)
            evidence.update({"run_id": self.ledger.run_id, "attempt": attempt})
            results[gate.gate_id] = {
                "gate_id": gate.gate_id,
                "binding": dict(binding),
                "status": status,
                "evidence": evidence,
            }
        return results
