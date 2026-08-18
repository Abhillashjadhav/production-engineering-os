"""Fail-closed meaningful-red gate over verified receipts and adapter evidence."""

from __future__ import annotations

import hashlib

from pmpe.admission import FileArtifactAdmissionVerifier
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.adapters import EvidenceAdapterRegistry
from pmpe.evidence.models import (
    EvidenceDecision,
    EvidenceError,
    EvidenceExpectation,
    EvidenceSubmission,
    NodeEvidence,
)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class MeaningfulRedGate:
    def __init__(
        self,
        *,
        verifier: FileArtifactAdmissionVerifier,
        registry: EvidenceAdapterRegistry,
    ) -> None:
        self.verifier = verifier
        self.registry = registry

    def evaluate(
        self,
        *,
        expectations: tuple[EvidenceExpectation, ...],
        submissions: tuple[EvidenceSubmission, ...],
    ) -> EvidenceDecision:
        reasons: list[str] = []
        nodes: list[NodeEvidence] = []
        if not expectations:
            return EvidenceDecision(False, (), ("vacuous plan has no admitted commands",))
        try:
            self.registry.validate_expectations(expectations)
        except EvidenceError as exc:
            return EvidenceDecision(False, (), (str(exc),))
        expectation_ids = [item.command_id for item in expectations]
        if len(expectation_ids) != len(set(expectation_ids)):
            return EvidenceDecision(False, (), ("duplicate command expectation",))
        submission_ids = [item.command_id for item in submissions]
        duplicates = sorted(
            command_id for command_id in set(submission_ids) if submission_ids.count(command_id) > 1
        )
        if duplicates:
            reasons.append("duplicate result receipt for command: " + ", ".join(duplicates))
        missing = sorted(set(expectation_ids) - set(submission_ids))
        unknown = sorted(set(submission_ids) - set(expectation_ids))
        if missing:
            reasons.append("missing result receipt for command: " + ", ".join(missing))
        if unknown:
            reasons.append("unknown result receipt for command: " + ", ".join(unknown))
        if reasons:
            return EvidenceDecision(False, (), tuple(reasons))
        submission_by_id = {item.command_id: item for item in submissions}
        seen_nodes: set[str] = set()
        for expectation in expectations:
            submission = submission_by_id[expectation.command_id]
            execution = submission.execution
            if execution.command != expectation.command:
                reasons.append(f"{expectation.command_id}: wrong plan-bound command")
                continue
            if execution.receipt_bindings.get("plan_digest") != expectation.plan_digest:
                reasons.append(f"{expectation.command_id}: wrong plan digest")
                continue
            if execution.commit_sha != expectation.commit_sha:
                reasons.append(f"{expectation.command_id}: wrong admitted commit")
                continue
            if (
                execution.subject_digest_before != expectation.subject_digest
                or execution.subject_digest_after != expectation.subject_digest
            ):
                reasons.append(f"{expectation.command_id}: wrong admitted subject")
                continue
            expected_command_digest = canonical_digest(list(expectation.command.argv))
            if execution.receipt_bindings.get("command_digest") != expected_command_digest:
                reasons.append(f"{expectation.command_id}: wrong command digest")
                continue
            if (
                _digest(submission.stdout) != execution.stdout_digest
                or _digest(submission.stderr) != execution.stderr_digest
            ):
                reasons.append(f"{expectation.command_id}: raw output digest mismatch")
                continue
            if not self.verifier.verify(
                execution.receipt,
                artifact_kind="RED_TEST_EXECUTION",
                artifact_digest=execution.execution_digest,
                subject_bindings=execution.receipt_bindings,
            ):
                reasons.append(f"{expectation.command_id}: execution receipt is not verified")
                continue
            signed_evidence = {
                "command_digest": expected_command_digest,
                "commit_sha": execution.commit_sha,
                "isolation_policy": execution.isolation_policy,
                "plan_digest": expectation.plan_digest,
                "policy_digest": execution.receipt_bindings.get("policy_digest", ""),
                "return_code": execution.return_code,
                "stderr_digest": execution.stderr_digest,
                "stdout_digest": execution.stdout_digest,
                "subject_digest": execution.subject_digest_before,
            }
            signed_bindings = {key: str(value) for key, value in signed_evidence.items()}
            if (
                signed_bindings != dict(execution.receipt_bindings)
                or canonical_digest(signed_evidence) != execution.execution_digest
            ):
                reasons.append(f"{expectation.command_id}: signed execution fields changed")
                continue
            adapter = self.registry.resolve(expectation.tool, expectation.evidence_format)
            parsed = adapter.parse(submission.stdout, submission.stderr, execution.return_code)
            if parsed.blocking_failure:
                reasons.append(f"{expectation.command_id}: {parsed.blocking_failure}")
                continue
            expected_nodes = {item.node_id: item for item in expectation.nodes}
            parsed_ids = [item.node_id for item in parsed.nodes]
            duplicate_nodes = sorted(
                node_id for node_id in set(parsed_ids) if parsed_ids.count(node_id) > 1
            )
            if duplicate_nodes:
                reasons.append(
                    f"{expectation.command_id}: duplicate node results: "
                    + ", ".join(duplicate_nodes)
                )
                continue
            unknown_nodes = sorted(set(parsed_ids) - set(expected_nodes))
            missing_nodes = sorted(set(expected_nodes) - set(parsed_ids))
            if unknown_nodes:
                reasons.append(
                    f"{expectation.command_id}: unknown node results: " + ", ".join(unknown_nodes)
                )
            if missing_nodes:
                reasons.append(
                    f"{expectation.command_id}: missing node results: " + ", ".join(missing_nodes)
                )
            for node in parsed.nodes:
                expected = expected_nodes.get(node.node_id)
                if expected is None:
                    continue
                if node.node_id in seen_nodes:
                    reasons.append(f"duplicate node across commands: {node.node_id}")
                    continue
                seen_nodes.add(node.node_id)
                if node.failure_kind and node.failure_kind != "assertion":
                    reasons.append(
                        f"{expectation.command_id}: {node.failure_kind} is not meaningful red"
                    )
                if node.assertion_id != expected.assertion_id:
                    reasons.append(f"{expectation.command_id}: wrong assertion for {node.node_id}")
                    continue
                if node.failure_kind not in {
                    "",
                    "assertion",
                    "usage",
                    "collection",
                    "configuration",
                    "timeout",
                    "skip",
                    "internal",
                    "error",
                }:
                    reasons.append(f"{expectation.command_id}: unknown failure kind")
                    continue
                nodes.append(node)
        meaningful = any(
            node.outcome == "failed" and node.failure_kind == "assertion" for node in nodes
        )
        if not meaningful:
            reasons.append("vacuous result contains no plan-bound assertion failure")
        return EvidenceDecision(not reasons, tuple(nodes), tuple(reasons))
