"""Issue #106 red-first contract for plan-bound, adapter-derived evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.admission import FileArtifactAdmissionAuthority, FileArtifactAdmissionVerifier
from pmpe.contracts.intake import KeyedFingerprint
from pmpe.execution import (
    CommandOutcome,
    ExecutionCommand,
    ExecutionPolicy,
    IsolatedExecutionKernel,
)


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

    def __init__(
        self,
        stdout: bytes,
        stderr: bytes = b"",
        return_code: int = 1,
        resolved_executable: str = "/usr/bin/pytest",
    ) -> None:
        self.outcome = CommandOutcome(
            return_code,
            stdout,
            stderr,
            resolved_executable=resolved_executable,
        )

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
    resolved_executable: str | None = None,
    planned_nodes: tuple[tuple[str, str], ...] | None = None,
):  # type: ignore[no-untyped-def]
    repository, commit = _repository(tmp_path)
    provisional_digest = "sha256:" + "0" * 64
    kernel = IsolatedExecutionKernel(
        authority=FileArtifactAdmissionAuthority(tmp_path / "receipts", _FingerprintProvider()),
        sandbox=_OutputSandbox(
            stdout,
            stderr,
            return_code,
            resolved_executable=resolved_executable
            or ("/usr/bin/node" if command.argv[0] == "node" else "/usr/bin/pytest"),
        ),
        policy=ExecutionPolicy(timeout_seconds=5, max_output_bytes=64 * 1024),
    )
    if plan_digest == "sha256:" + "a" * 64 or planned_nodes is not None:
        provisional = kernel.execute(
            repository=repository,
            commit_sha=commit,
            plan_digest=provisional_digest,
            command=command,
        )
        effective_plan_digest = _plan_digest(
            command,
            nodes=planned_nodes,
            commit_sha=provisional.commit_sha,
            subject_digest=provisional.subject_digest_before,
        )
    else:
        effective_plan_digest = plan_digest
    return kernel.execute(
        repository=repository,
        commit_sha=commit,
        plan_digest=effective_plan_digest,
        command=command,
    )


def _pytest_report(
    *,
    node: str = "tests/test_feature.py::test_rejects_invalid",
    assertion_id: str = "ASSERT-001",
    outcome: str = "failed",
    message: str | None = None,
    exitcode: int = 1,
) -> bytes:
    if message is None:
        message = f"AssertionError: [assertion:{assertion_id}] planned assertion failed"
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


def _tap_assertion_report(
    *, bailout: bool = False, diagnostic_assertion_id: str = "ASSERT-001"
) -> bytes:
    lines = [
        "TAP version 13",
        "not ok 1 - feature rejects invalid [assertion:ASSERT-001]",
        "  ---",
        "  failureType: 'testCodeFailure'",
        f"  error: '[assertion:{diagnostic_assertion_id}] expected rejection'",
        "  code: 'ERR_ASSERTION'",
        "  name: 'AssertionError'",
        "  ...",
    ]
    if bailout:
        lines.append("Bail out! configuration unavailable")
    lines.append("1..1")
    return ("\n".join(lines) + "\n").encode()


def _trusted_pytest_command() -> ExecutionCommand:
    return ExecutionCommand(
        (
            "pytest",
            "--json-report",
            "--json-report-file=/dev/stdout",
            "--noconftest",
            "-c",
            "/dev/null",
            "-p",
            "no:terminal",
        )
    )


def _plan_digest(
    command: ExecutionCommand,
    *,
    command_id: str = "CMD-001",
    tool: str | None = None,
    evidence_format: str | None = None,
    node: str | None = None,
    assertion_id: str = "ASSERT-001",
    nodes: tuple[tuple[str, str], ...] | None = None,
    commit_sha: str = "0" * 40,
    subject_digest: str = "sha256:" + "0" * 64,
) -> str:
    api = _api()
    is_tap = command.argv[0] == "node"
    resolved_tool = tool or ("node:test" if is_tap else "pytest")
    resolved_format = evidence_format or ("tap13/v1" if is_tap else "pytest-json-report/v1")
    resolved_node = node or (
        "feature rejects invalid [assertion:ASSERT-001]"
        if is_tap
        else "tests/test_feature.py::test_rejects_invalid"
    )
    node_specs = nodes or ((resolved_node, assertion_id),)
    draft = api.EvidenceExpectation(
        command_id=command_id,
        tool=resolved_tool,
        evidence_format=resolved_format,
        plan_digest="sha256:" + "0" * 64,
        commit_sha=commit_sha,
        subject_digest=subject_digest,
        command=command,
        nodes=tuple(
            api.NodeExpectation(node_id=node_id, assertion_id=planned_assertion)
            for node_id, planned_assertion in node_specs
        ),
    )
    return api.evidence_plan_digest((draft,))


def _expectation(
    *,
    command_id: str = "CMD-001",
    tool: str = "pytest",
    evidence_format: str = "pytest-json-report/v1",
    command: ExecutionCommand | None = None,
    node: str = "tests/test_feature.py::test_rejects_invalid",
    assertion_id: str = "ASSERT-001",
    execution: object | None = None,
):  # type: ignore[no-untyped-def]
    api = _api()
    commit_sha = getattr(execution, "commit_sha", "0" * 40)
    subject_digest = getattr(execution, "subject_digest_before", "sha256:" + "0" * 64)
    return api.EvidenceExpectation(
        command_id=command_id,
        tool=tool,
        evidence_format=evidence_format,
        plan_digest=_plan_digest(
            command or _trusted_pytest_command(),
            command_id=command_id,
            tool=tool,
            evidence_format=evidence_format,
            node=node,
            assertion_id=assertion_id,
            commit_sha=commit_sha,
            subject_digest=subject_digest,
        ),
        commit_sha=commit_sha,
        subject_digest=subject_digest,
        command=command or _trusted_pytest_command(),
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
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
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
        (
            json.dumps({"exitcode": 2, "collectors": [{"outcome": "failed"}]}).encode(),
            2,
            "collection",
        ),
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
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        return_code=return_code,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized
    assert any(reason in item for item in decision.reasons)


def test_non_python_tap13_adapter_proves_assertion_behavior(tmp_path: Path) -> None:
    api = _api()
    stdout = _tap_assertion_report()
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
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
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(command=command, execution=result)
    submission = api.EvidenceSubmission("CMD-001", result, stdout, b"")

    assert not _gate(tmp_path).evaluate(expectations=(expectation,), submissions=()).authorized
    assert (
        not _gate(tmp_path)
        .evaluate(expectations=(expectation,), submissions=(submission, submission))
        .authorized
    )
    unknown = replace(submission, command_id="CMD-UNKNOWN")
    assert (
        not _gate(tmp_path).evaluate(expectations=(expectation,), submissions=(unknown,)).authorized
    )


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
    command = _trusted_pytest_command()
    result = _execution(tmp_path, payload, command=command, plan_digest="sha256:" + "a" * 64)

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result, **expectation_changes),),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized


def test_duplicate_nodes_and_vacuous_all_passed_results_are_rejected(tmp_path: Path) -> None:
    api = _api()
    command = _trusted_pytest_command()
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
        expectations=(_expectation(command=command, execution=duplicate_result),),
        submissions=(api.EvidenceSubmission("CMD-001", duplicate_result, duplicate_payload, b""),),
    )
    assert not duplicate_decision.authorized

    passed = _pytest_report(outcome="passed", exitcode=0)
    passed_result = _execution(
        tmp_path, passed, command=command, plan_digest="sha256:" + "a" * 64, return_code=0
    )
    passed_decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=passed_result),),
        submissions=(api.EvidenceSubmission("CMD-001", passed_result, passed, b""),),
    )
    assert not passed_decision.authorized
    assert any("vacuous" in reason for reason in passed_decision.reasons)


def test_raw_output_tampering_and_forged_execution_receipt_are_rejected(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(command=command, execution=result)

    tampered = api.EvidenceSubmission("CMD-001", result, stdout + b" ", b"")
    assert (
        not _gate(tmp_path)
        .evaluate(expectations=(expectation,), submissions=(tampered,))
        .authorized
    )

    forged_result = replace(result, receipt=replace(result.receipt, fingerprint="0" * 64))
    forged = api.EvidenceSubmission("CMD-001", forged_result, stdout, b"")
    assert (
        not _gate(tmp_path).evaluate(expectations=(expectation,), submissions=(forged,)).authorized
    )


def test_registry_rejects_unsupported_or_duplicate_tool_format_pairs() -> None:
    api = _api()
    registry = api.default_adapter_registry()

    with pytest.raises(api.EvidenceError, match="unsupported"):
        registry.validate_expectations(
            (_expectation(tool="unknown", evidence_format="unknown/v1"),)
        )
    with pytest.raises(api.EvidenceError, match="duplicate"):
        api.EvidenceAdapterRegistry((api.PytestJsonReportAdapter(), api.PytestJsonReportAdapter()))


def test_declared_adapter_must_match_the_executed_tool(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = ExecutionCommand(("python", "emit_fabricated.py"))
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("tool" in reason for reason in decision.reasons)


def test_expectation_binds_exact_commit_and_subject_digest(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expected = _expectation(command=command, execution=result)
    submission = api.EvidenceSubmission("CMD-001", result, stdout, b"")

    wrong_commit = replace(expected, commit_sha="f" * 40)
    wrong_subject = replace(expected, subject_digest="sha256:" + "f" * 64)

    assert (
        not _gate(tmp_path)
        .evaluate(expectations=(wrong_commit,), submissions=(submission,))
        .authorized
    )
    assert (
        not _gate(tmp_path)
        .evaluate(expectations=(wrong_subject,), submissions=(submission,))
        .authorized
    )


def test_signed_execution_fields_are_recomputed_before_parsing(tmp_path: Path) -> None:
    api = _api()
    stdout = _tap_assertion_report()
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        return_code=0,
    )
    forged = replace(result, return_code=1)
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", forged, stdout, b""),),
    )

    assert not decision.authorized
    assert any("signed" in reason for reason in decision.reasons)


def test_pytest_configuration_name_containing_assert_is_not_assertion(
    tmp_path: Path,
) -> None:
    api = _api()
    stdout = _pytest_report(message="fixture 'assertion_client' not found")
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("configuration" in reason for reason in decision.reasons)


def test_contradictory_pytest_success_report_is_rejected(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report(exitcode=0)
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        return_code=0,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized


@pytest.mark.parametrize(
    ("payload", "return_code", "reason"),
    (
        (_tap_assertion_report(), 124, "timeout"),
        (_tap_assertion_report(bailout=True), 1, "bailout"),
    ),
)
def test_tap_timeout_and_bailout_are_rejected(
    tmp_path: Path, payload: bytes, return_code: int, reason: str
) -> None:
    api = _api()
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(
        tmp_path,
        payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        return_code=return_code,
    )
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized
    assert any(reason in item for item in decision.reasons)


def test_tap_skip_directive_is_not_counted_as_a_pass(tmp_path: Path) -> None:
    api = _api()
    payload = _tap_assertion_report().replace(
        b"1..1\n",
        b"ok 2 - optional feature # SKIP unavailable\n1..2\n",
    )
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    planned_nodes = (
        ("feature rejects invalid [assertion:ASSERT-001]", "ASSERT-001"),
        ("optional feature", "ASSERT-SKIP"),
    )
    result = _execution(
        tmp_path,
        payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        planned_nodes=planned_nodes,
    )
    plan_digest = str(result.receipt_bindings["plan_digest"])
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )
    expectation = replace(
        expectation,
        plan_digest=plan_digest,
        nodes=(
            expectation.nodes[0],
            api.NodeExpectation(node_id="optional feature", assertion_id="ASSERT-SKIP"),
        ),
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized
    assert any("skip" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    "command",
    (
        ExecutionCommand(("./pytest", "--json-report")),
        ExecutionCommand(("./node", "--test", "--test-reporter=tap", "test.mjs")),
    ),
)
def test_adapter_rejects_repository_relative_tool_impersonation(
    command: ExecutionCommand,
) -> None:
    api = _api()
    expectation = _expectation(
        tool="pytest" if "pytest" in command.argv[0] else "node:test",
        evidence_format=("pytest-json-report/v1" if "pytest" in command.argv[0] else "tap13/v1"),
        command=command,
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((expectation,))


def test_pytest_runtime_error_containing_assert_is_not_assertion(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report(message="NameError: name 'assertion_client' is not defined")
    command = _trusted_pytest_command()
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("error" in reason for reason in decision.reasons)


def test_generic_node_assertion_code_is_not_a_plan_assertion(tmp_path: Path) -> None:
    api = _api()
    stdout = _tap_assertion_report().replace(b" [assertion:ASSERT-001]", b"")
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid",
        assertion_id="ASSERT-001",
        execution=result,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized


def test_nested_node_tap_plan_authorizes_leaf_assertion(tmp_path: Path) -> None:
    api = _api()
    stdout = b"""TAP version 13
# Subtest: feature suite
    # Subtest: feature rejects invalid [assertion:ASSERT-001]
    not ok 1 - feature rejects invalid [assertion:ASSERT-001]
      ---
      failureType: 'testCodeFailure'
      error: '[assertion:ASSERT-001] expected rejection'
      code: 'ERR_ASSERTION'
      name: 'AssertionError'
      ...
    1..1
not ok 1 - feature suite
  ---
  failureType: 'subtestsFailed'
  ...
1..1
"""
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(tmp_path, stdout, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert decision.authorized


def test_python_module_runner_cannot_import_pytest_from_the_workspace() -> None:
    api = _api()
    expectation = _expectation(
        command=ExecutionCommand(("python3", "-m", "pytest", "--json-report"))
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((expectation,))


def test_tap_todo_directive_is_blocking_evidence(tmp_path: Path) -> None:
    api = _api()
    payload = _tap_assertion_report().replace(
        b"1..1\n",
        b"ok 2 - deferred behavior [assertion:ASSERT-002] # TODO pending\n1..2\n",
    )
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    planned_nodes = (
        ("feature rejects invalid [assertion:ASSERT-001]", "ASSERT-001"),
        ("deferred behavior [assertion:ASSERT-002]", "ASSERT-002"),
    )
    result = _execution(
        tmp_path,
        payload,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        planned_nodes=planned_nodes,
    )
    plan_digest = str(result.receipt_bindings["plan_digest"])
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )
    expectation = replace(
        expectation,
        plan_digest=plan_digest,
        nodes=(
            expectation.nodes[0],
            api.NodeExpectation(
                node_id="deferred behavior [assertion:ASSERT-002]",
                assertion_id="ASSERT-002",
            ),
        ),
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized
    assert any("todo" in reason.lower() for reason in decision.reasons)


def test_tap_failure_diagnostic_must_match_the_planned_assertion(tmp_path: Path) -> None:
    api = _api()
    payload = _tap_assertion_report(diagnostic_assertion_id="ASSERT-OTHER")
    command = ExecutionCommand(("node", "--test", "--test-reporter=tap", "test.mjs"))
    result = _execution(tmp_path, payload, command=command, plan_digest="sha256:" + "a" * 64)
    expectation = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=command,
        node="feature rejects invalid [assertion:ASSERT-001]",
        assertion_id="ASSERT-001",
        execution=result,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(expectation,),
        submissions=(api.EvidenceSubmission("CMD-001", result, payload, b""),),
    )

    assert not decision.authorized


def test_repository_tool_cannot_impersonate_a_system_evidence_runner(tmp_path: Path) -> None:
    api = _api()
    stdout = _pytest_report()
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
        resolved_executable="/workspace/pytest",
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("trusted system runner" in reason for reason in decision.reasons)


def test_expectation_nodes_cannot_be_rewritten_while_retaining_the_plan_digest(
    tmp_path: Path,
) -> None:
    api = _api()
    forged_node = "tests/test_feature.py::test_forged_observation"
    stdout = _pytest_report(node=forged_node)
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
    )
    rewritten = replace(
        _expectation(command=command, execution=result),
        nodes=(api.NodeExpectation(node_id=forged_node, assertion_id="ASSERT-001"),),
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(rewritten,),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("plan" in reason for reason in decision.reasons)


def test_pytest_failure_exit_requires_at_least_one_failed_node() -> None:
    api = _api()
    payload = _pytest_report(outcome="passed", exitcode=1)

    parsed = api.PytestJsonReportAdapter().parse(payload, b"", 1)

    assert parsed.blocking_failure == "pytest runner error without failed node"


def test_tap_leaf_selection_consumes_records_once() -> None:
    from pmpe.evidence import adapters as adapter_module

    class SinglePassRecords(list[tuple[int, int, re.Match[str]]]):
        iterations = 0

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.iterations += 1
            assert self.iterations == 1
            return super().__iter__()

    records = SinglePassRecords()
    for index, (indent, line) in enumerate(
        (
            (4, "ok 1 - child"),
            (0, "not ok 1 - parent"),
            (0, "ok 2 - leaf"),
        )
    ):
        match = adapter_module._TAP_RESULT.fullmatch(line)  # noqa: SLF001
        assert match is not None
        records.append((index, indent, match))

    selected = list(adapter_module._tap_leaf_records(records))  # noqa: SLF001

    assert [record[0] for record in selected] == [0, 2]


def test_pytest_evidence_rejects_workspace_configuration_and_conftest_hooks() -> None:
    api = _api()
    unsafe = _expectation(command=ExecutionCommand(("pytest", "--json-report")))

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((unsafe,))


def test_tap_evidence_rejects_additional_reporters_and_destinations() -> None:
    api = _api()
    unsafe = _expectation(
        tool="node:test",
        evidence_format="tap13/v1",
        command=ExecutionCommand(
            (
                "node",
                "--test",
                "--test-reporter=tap",
                "--test-reporter-destination=/dev/null",
                "--test-reporter=./evil.mjs",
                "--test-reporter-destination=stdout",
                "test.mjs",
            )
        ),
        node="feature rejects invalid [assertion:ASSERT-001]",
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((unsafe,))


def test_pytest_failure_requires_the_planned_marker_in_the_call_diagnostic(
    tmp_path: Path,
) -> None:
    api = _api()
    stdout = _pytest_report(message="AssertionError: unrelated preliminary failure")
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("assertion" in reason for reason in decision.reasons)


def test_pytest_teardown_failure_blocks_a_planned_call_assertion(tmp_path: Path) -> None:
    api = _api()
    report = json.loads(_pytest_report())
    report["tests"][0]["teardown"] = {
        "outcome": "failed",
        "crash": {"message": "RuntimeError: cleanup failed"},
    }
    stdout = json.dumps(report).encode()
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("teardown" in reason for reason in decision.reasons)


def test_pytest_evidence_rejects_a_later_long_form_workspace_config() -> None:
    api = _api()
    command = ExecutionCommand(
        _trusted_pytest_command().argv + ("--config-file=/workspace/pytest.ini",)
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((_expectation(command=command),))


def test_pytest_evidence_rejects_plugin_and_import_path_overrides() -> None:
    api = _api()
    command = ExecutionCommand(
        _trusted_pytest_command().argv + ("-o", "pythonpath=/workspace", "-p", "evil_plugin")
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations((_expectation(command=command),))


def test_pytest_marker_in_preceding_traceback_source_does_not_bind_failure(
    tmp_path: Path,
) -> None:
    api = _api()
    report = json.loads(_pytest_report(message="AssertionError: unrelated preliminary failure"))
    report["tests"][0]["call"]["longrepr"] = (
        "assert True, '[assertion:ASSERT-001] planned'\nE   assert False"
    )
    stdout = json.dumps(report).encode()
    command = _trusted_pytest_command()
    result = _execution(
        tmp_path,
        stdout,
        command=command,
        plan_digest="sha256:" + "a" * 64,
    )

    decision = _gate(tmp_path).evaluate(
        expectations=(_expectation(command=command, execution=result),),
        submissions=(api.EvidenceSubmission("CMD-001", result, stdout, b""),),
    )

    assert not decision.authorized
    assert any("assertion" in reason for reason in decision.reasons)


def test_plan_digest_binds_commit_and_subject_identity() -> None:
    api = _api()
    original = _expectation()
    changed = replace(
        original,
        commit_sha="f" * 40,
        subject_digest="sha256:" + "e" * 64,
    )

    assert api.evidence_plan_digest((original,)) != api.evidence_plan_digest((changed,))


def test_pytest_evidence_requires_json_on_authenticated_stdout() -> None:
    api = _api()
    terminal_output_command = ExecutionCommand(
        ("pytest", "--json-report", "--noconftest", "-c", "/dev/null")
    )

    with pytest.raises(api.EvidenceError, match="tool"):
        api.default_adapter_registry().validate_expectations(
            (_expectation(command=terminal_output_command),)
        )
