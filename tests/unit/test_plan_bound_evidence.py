"""Issue #106 red-first contract for plan-bound, adapter-derived evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.admission import FileArtifactAdmissionAuthority, FileArtifactAdmissionVerifier
from pmpe.contracts.intake import KeyedFingerprint
from pmpe.execution import CommandOutcome, ExecutionCommand, ExecutionPolicy, IsolatedExecutionKernel


class _FingerprintProvider:
    key_version = "test-v1"

    def fingerprint(self, domain: str, payload: bytes) -> str:
        return hmac.new(
            b"issue-106-test-key", domain.encode() + b"\0" + payload, hashlib.sha256
        ).hexdigest()

    def candidate_fingerprints(self, domain: str, payload: bytes) -> tuple[KeyedFingerprint, ...]:
        return (KeyedFingerprint(self.key_version, self.fingerprint(domain, payload)),)


class _OutputSandbox:
    identity = "fixture-sandbox/1"

    def __init__(self, stdout: bytes, stderr: bytes = b"", return_code: int = 1) -> None:
        self.outcome = CommandOutcome(return_code, stdout, stderr)

    def run(
        self, workspace: Path, command: ExecutionCommand, policy: ExecutionPolicy
    ) -> CommandOutcome:
        return self.outcome


def _api():  # type: ignore[no-untyped-def]
    try:
        from pmpe import evidence
    except (ImportError, ModuleNotFoundError):
        pytest.fail("issue #106 evidence adapters are not implemented", pytrace=False)
    return evidence


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir(exist_ok=True)
    if not (repository / ".git").exists():
        _git(repository, "init", "-q")
        (repository / "test.txt").write_text("fixture\n")
        _git(repository, "add", "test.txt")
        _git(repository, "commit", "-qm", "fixture")
    return repository, _git(repository, "rev-parse", "HEAD")


def _execution(
    tmp_path: Path,
    stdout: bytes,
    *,
    command: ExecutionCommand,
    plan_digest: str,
    stderr: bytes = b"",
    return_code: int = 1,
):  # type: ignore[no-untyped-def]
    repository, commit = _repository(tmp_path)
    kernel = IsolatedExecutionKernel(
        authority=FileArtifactAdmissionAuthority(tmp_path / "receipts", _FingerprintProvider()),
        sandbox=_OutputSandbox(stdout, stderr, return_code),
        policy=ExecutionPolicy(timeout_seconds=5, max_output_bytes=64 * 1024),
    )
    return kernel.execute(
        repository=repository,
        commit_sha=commit,
        plan_digest=plan_digest,
        command=command,
    )


def _pytest_report(
    *,
    node: str = "tests/test_feature.py::test_rejects_invalid",
    assertion_id: str = "ASSERT-001",
    outcome: str = "failed",
    message: str = "assert False",
    exitcode: int = 1,
) -> bytes:
    phase = {"outcome": outcome}
    if outcome == "failed":
        phase["crash"] = {"message": message}
    return json.dumps(
        {
            "exitcode": exitcode,
            "tests": [
                {
                    "nodeid": node,
                    "outcome": outcome,
                    "user_properties": [["assertion_id", assertion_id]],
                    "call": phase,
                }
            ],
        }
    ).encode()


def _expectation(
    *,
    command_id: str = "CMD-001",
    tool: str = "pytest",
    evidence_format: str = "pytest-json-report/v1",
    command: ExecutionCommand | None = None,
    node: str = "tests/test_feature.py::test_rejects_invalid",
    assertion_id: str = "ASSERT-001",
):  # type: ignore[no-untyped-def]
    api = _api()
    return api.EvidenceExpectation(
        command_id=command_id,
        tool=tool,
        evidence_format=evidence_format,
        plan_digest="sha256:" + "a" * 64,
        command=command or ExecutionCommand(("pytest", "--json-report")),
        nodes=(api.NodeExpectation(node_id=node, assertion_id=assertion_id),),
    )


def _gate(tmp_path: Path):  # type: ignore[no-untyped-def]
    api = _api()
    return api.MeaningfulRedGate(
        verifier=FileArtifactAdmissionVerifier(tmp_path / "receipts", _FingerprintProvider()),
        registry=api.default_adapter_registry(),
    )


def test_planted_pytest_assertion_failure_authorizes_meaningful_red(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = ExecutionCommand(("pytest", "--json-report"))
    result = _execution(
        tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert decision.authorized
    assert decision.nodes[0].node_id == "tests/test_feature.py::test_rejects_invalid"
    assert decision.nodes[0].failure_kind == "assertion"
    assert decision.nodes[0].assertion_id == "ASSERT-001"
    assert decision.nodes[0].raw_output_digest == result.stdout_digest


@pytest.mark.parametrize(
    ("payload", "return_code", "reason"),
    (
        (json.dumps({"exitcode": 4, "tests": []}).encode(), 4, "usage"),
        (json.dumps({"exitcode": 2, "collectors": [{"outcome": "failed"}]}).encode(), 2, "collection"),
        (_pytest_report(message="fixture setup failed"), 1, "configuration"),
        (json.dumps({"exitcode": 3, "tests": []}).encode(), 3, "internal"),
        (_pytest_report(outcome="skipped", exitcode=0), 0, "skip"),
        (b"", 124, "timeout"),
    ),
)
def test_non_assertion_failures_never_satisfy_meaningful_red(
    tmp_path: Path, payload: bytes, return_code: int, reason: str
) -> None:
    api = _api()
    command = ExecutionCommand(("pytest", "--json-report"))
    result = _execution(
        tmp_path,
        payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        return_code=return_code,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command),),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized
    assert any(reason in item for item in decision.reasons)


def test_non_python_tap13_adapter_proves_assertion_behavior(tmp_path: Path) -> None:
    api = _api()
    stdout = (
        b"TAP version 13\n1..1\n"
        b"not ok 1 - feature rejects invalid # assertion=ASSERT-002 kind=assertion\n"
    )
    command = ExecutionCommand(("node", "test.mjs", "--tap"))
    result = _execution(
        tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64
    )
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid",
        assertion_id="ASSERT-002",
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert decision.authorized
    assert decision.nodes[0].failure_kind == "assertion"


def test_missing_duplicate_and_unknown_command_results_are_rejected(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = ExecutionCommand(("pytest", "--json-report"))
    result = _execution(
        tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64
    )
    expectation = _expectation(command=command)
    submission = api.EvidenceSubmission("CMD-001", result, stdout, b"")

    assert not _gate(tmp_path).evaluate(expectations=(expectation,), submissions=()).authorized
    assert not _gate(tmp_path).evaluate(
        expectations=(expectation,), submissions=(submission, submission)
    ).authorized
    unknown = replace(submission, command_id="CMD-UNKNOWN")
    assert not _gate(tmp_path).evaluate(
        expectations=(expectation,), submissions=(unknown,)
    ).authorized


@pytest.mark.parametrize(
    ("expectation_changes", "payload"),
    (
        ({"tool": "node:test"}, _pytest_report()),
        ({"evidence_format": "tap13/v1"}, _pytest_report()),
        ({"node": "tests/test_feature.py::test_other"}, _pytest_report()),
        ({"assertion_id": "ASSERT-OTHER"}, _pytest_report()),
        ({}, _pytest_report(node="tests/test_feature.py::test_unknown")),
    ),
)
def test_wrong_tool_format_node_or_assertion_is_rejected(
    tmp_path: Path, expectation_changes: dict[str, str], payload: bytes
) -> None:
    api = _api()
    command = ExecutionCommand(("pytest", "--json-report"))
    result = _execution(
        tmp_path, payload, command=command, plan_digest="sha256:" + "a" * 64
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, **expectation_changes),),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized


def test_duplicate_nodes_and_vacuous_all_passed_results_are_rejected(tmp_path: Path) -> None:
    api = _api()
    command = ExecutionCommand(("pytest", "--json-report"))
    duplicated = json.loads(_pytest_report())
    duplicated["tests"].append(dict(duplicated["tests"][0]))
    duplicate_payload = json.dumps(duplicated).encode()
    duplicate_result = _execution(
        tmp_path,
        duplicate_payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
    )
    duplicate_decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command),),
        submissions=(api.EvidenceSubmission("CMD-001", duplicate_result, duplicate_payload, b""),),
    )
    assert not duplicate_decision.authorized

    passed = _pytest_report(outcome="passed", exitcode=0)
    passed_result = _execution(
        tmp_path, passed, command=command, plan_digest="sha256:" + "a" * 64, return_code=0
    )
    passed_decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command),),
        submissions=(api.EvidenceSubmission("CMD-001", passed_result, passed, b""),),
    )
    assert not passed_decision.authorized
    assert any("vacuous" in reason for reason in passed_decision.reasons)


def test_raw_output_tampering_and_forged_execution_receipt_are_rejected(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = ExecutionCommand(("pytest", "--json-report"))
    result = _execution(
        tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64
    )
    expectation = _expectation(command=command)

    tampered = api.EvidenceSubmission("CMD-001", result, stdout + b" ", b"")
    assert not _gate(tmp_path).evaluate(
        expectations=(expectation,), submissions=(tampered,)
    ).authorized

    forged_result = replace(result, receipt=replace(result.receipt, fingerprint="0" * 64))
    forged = api.EvidenceSubmission("CMD-001", forged_result, stdout, b"")
    assert not _gate(tmp_path).evaluate(
        expectations=(expectation,), submissions=(forged,)
    ).authorized


def test_registry_rejects_unsupported_or_duplicate_tool_format_pairs() -> None:
    api = _api()
    registry = api.default_adapter_registry()

    with pytest.raises(api.EvidenceError, match="unsupported"):
        registry.validate_expectations(
            (_expectation(tool="unknown", evidence_format="unknown/v1"),)
        )
    with pytest.raises(api.EvidenceError, match="duplicate"):
        api.EvidenceAdapterRegistry((api.PytestJsonReportAdapter(), api.PytestJsonReportAdapter()))
