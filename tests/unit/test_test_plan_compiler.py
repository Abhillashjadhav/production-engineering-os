"""Issue #67 red-first contract for executable test-plan compilation."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pmpe.architecture.models import ArchitecturePack
from pmpe.audit.executed import build_executed_plan_traceability
from pmpe.contracts.canonical import canonical_digest
from pmpe.quality.test_evidence import TestEvidence, TestExecution
from pmpe.repository.models import (
    AdapterMetadata,
    EvidenceItem,
    InventoryCategory,
    RepositorySnapshot,
    ToolVersion,
)

ROOT = Path(__file__).resolve().parents[2]
VALID_BUNDLE = ROOT / "tests" / "fixtures" / "pmos" / "v1" / "valid_bundle.json"


def _api() -> Any:
    try:
        from pmpe import testing
    except (ImportError, ModuleNotFoundError):
        pytest.fail("issue #67 test-plan compiler is not implemented", pytrace=False)
    return testing


def _contract() -> dict[str, Any]:
    return json.loads(VALID_BUNDLE.read_text())


def _snapshot() -> RepositorySnapshot:
    snapshot = RepositorySnapshot(
        repository="Abhillashjadhav/production-engineering-os",
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        git_object_format="sha1",
        default_branch="main",
        default_branch_source="symbolic-ref",
        scanner_version="1.0.0",
        scan_configuration_digest="sha256:" + "1" * 64,
        adapter_set_digest="sha256:" + "2" * 64,
        implementation_digest="sha256:" + "3" * 64,
        tracked_tree_digest="sha256:" + "4" * 64,
        scanned_content_digest="sha256:" + "5" * 64,
        scan_scope="FULL_TRACKED_TREE",
        included_paths=("pyproject.toml", "tests/unit/test_contracts.py"),
        tooling_digest="sha256:" + "6" * 64,
        tool_versions=(
            ToolVersion(tool="bandit", version="1.8.6"),
            ToolVersion(tool="playwright", version="1.54.0"),
            ToolVersion(tool="pytest", version="8.4.1"),
        ),
        adapters=(
            AdapterMetadata(
                adapter_id="python",
                version="1.0.0",
                detector_version="1.0.0",
                file_patterns=("*.py",),
                supported_categories=("tests_quality",),
            ),
        ),
        command_provenance=(),
        inventory={"tests_quality": InventoryCategory(status="SUPPORTED", items=())},
        findings=(),
        boundary_candidates=(),
        unsupported_categories=(),
        disposition="COMPLETE",
        redaction={"status": "SANITIZED"},
        snapshot_digest="",
    )
    payload = snapshot.as_dict()
    payload.pop("snapshot_digest")
    return replace(snapshot, snapshot_digest=canonical_digest(payload))


def _snapshot_with_declared_quality_tools() -> RepositorySnapshot:
    snapshot = replace(
        _snapshot(),
        tool_versions=(
            ToolVersion(tool="git", version="2.50.0"),
            ToolVersion(tool="python", version="3.12.0"),
        ),
        inventory={
            "tests_quality": InventoryCategory(
                status="SUPPORTED",
                items=tuple(
                    EvidenceItem(
                        kind="DECLARED_QUALITY_TOOL",
                        path="pyproject.toml",
                        file_digest="sha256:" + str(index) * 64,
                        detector_id="stack.python",
                        detector_version="1.0.0",
                        location=f"tool:{tool}",
                    )
                    for index, tool in enumerate(("pytest", "bandit", "playwright"), start=1)
                ),
            )
        },
        snapshot_digest="",
    )
    payload = snapshot.as_dict()
    payload.pop("snapshot_digest")
    return replace(snapshot, snapshot_digest=canonical_digest(payload))


def _architecture(contract: dict[str, Any], snapshot: RepositorySnapshot) -> ArchitecturePack:
    value: dict[str, Any] = {
        "schema_version": "1.0.0",
        "compiler_version": "1.0.0",
        "pack_id": "ARCH-TEST-001",
        "contract_digest": canonical_digest(contract),
        "repository_snapshot_digest": snapshot.snapshot_digest,
        "repository_commit": snapshot.commit_sha,
        "governance_observation_digest": "sha256:" + "7" * 64,
        "disposition": "ADMITTED",
        "repository_boundary_evidence": [],
        "components": [],
        "data_architecture": [],
        "api_architecture": [],
        "integration_architecture": [],
        "security_boundaries": [],
        "data_flows": [],
        "deployment": {},
        "observability": {},
        "rollback": {},
        "adrs": [],
        "threat_model": {},
        "approval_requests": [],
        "pack_digest": "",
        "artifact_kind": "ARCHITECTURE_PACK",
    }
    value["pack_digest"] = canonical_digest(
        {key: item for key, item in value.items() if key != "pack_digest"}
    )
    return ArchitecturePack.from_dict(value)


def _capabilities() -> tuple[Any, ...]:
    api = _api()
    return tuple(
        api.RepositoryTestCapability(
            test_class=test_class,
            command=(
                "bandit" if test_class is api.TestClass.SECURITY_PRIVACY else "pytest",
                "-q",
            ),
            environment="ci",
            tool=("bandit" if test_class is api.TestClass.SECURITY_PRIVACY else "pytest"),
            evidence_format="PMPE_TEST_EVIDENCE_V1",
            observed_paths=("pyproject.toml",),
        )
        for test_class in api.TestClass
        if test_class is not api.TestClass.ACCESSIBILITY
    ) + (
        api.RepositoryTestCapability(
            test_class=api.TestClass.ACCESSIBILITY,
            command=("playwright", "test"),
            environment="ci-browser",
            tool="playwright",
            evidence_format="PMPE_TEST_EVIDENCE_V1",
            observed_paths=("pyproject.toml",),
        ),
    )


def _compile(
    contract: dict[str, Any] | None = None,
    *,
    capabilities: tuple[Any, ...] | None = None,
) -> Any:
    api = _api()
    value = contract or _contract()
    snapshot = _snapshot()
    architecture = _architecture(value, snapshot)
    validation = SimpleNamespace(bundle_digest=canonical_digest(value), engineering_admissible=True)
    return api.TestPlanCompiler().compile(
        value,
        validation,
        snapshot,
        architecture,
        _capabilities() if capabilities is None else capabilities,
    )


def _snapshot_at(commit_sha: str) -> RepositorySnapshot:
    snapshot = replace(_snapshot(), commit_sha=commit_sha, snapshot_digest="")
    payload = snapshot.as_dict()
    payload.pop("snapshot_digest")
    return replace(snapshot, snapshot_digest=canonical_digest(payload))


def _compile_with_snapshot(
    snapshot: RepositorySnapshot,
    *,
    contract: dict[str, Any] | None = None,
    capabilities: tuple[Any, ...] | None = None,
) -> Any:
    value = contract or _contract()
    validation = SimpleNamespace(bundle_digest=canonical_digest(value), engineering_admissible=True)
    return (
        _api()
        .TestPlanCompiler()
        .compile(
            value,
            validation,
            snapshot,
            _architecture(value, snapshot),
            _capabilities() if capabilities is None else capabilities,
        )
    )


def _pytest_capabilities() -> tuple[Any, ...]:
    return tuple(
        replace(capability, command=("pytest", "-q"), tool="pytest")
        for capability in _capabilities()
    )


def _store_admit(
    store: Any,
    *,
    contract: dict[str, Any] | None = None,
    snapshot: RepositorySnapshot | None = None,
    capabilities: tuple[Any, ...] | None = None,
) -> Any:
    value = contract or _contract()
    subject = snapshot or _snapshot()
    validation = SimpleNamespace(bundle_digest=canonical_digest(value), engineering_admissible=True)
    return store.admit(
        contract_bundle=value,
        contract_validation=validation,
        repository_snapshot=subject,
        architecture_pack=_architecture(value, subject),
        capabilities=_capabilities() if capabilities is None else capabilities,
    )


def test_valid_plan_is_deterministic_digest_bound_and_complete() -> None:
    first = _compile()
    second = _compile(copy.deepcopy(_contract()))

    assert first.disposition.value == "ADMITTED"
    assert first.plan is not None
    assert first.as_dict() == second.as_dict()
    assert first.plan.digest_is_valid()
    assert first.plan.contract_digest == canonical_digest(_contract())
    assert first.plan.repository_commit == "a" * 40
    assert (
        first.plan.architecture_pack_digest == _architecture(_contract(), _snapshot()).pack_digest
    )

    covered = {
        target
        for node in first.plan.nodes
        if node.status == "PLANNED"
        for target in node.target_refs
    }
    assert set(first.plan.required_refs) <= covered
    assert all(decision.rule_id for decision in first.plan.class_decisions)
    assert {decision.test_class for decision in first.plan.class_decisions} == set(_api().TestClass)


def test_generated_test_node_ids_are_valid_unittest_identifiers() -> None:
    result = _compile()
    assert result.plan is not None

    for node in result.plan.nodes:
        parts = node.expected_test_node.split(".")
        assert parts[-2] == "GeneratedPlanTests"
        assert all(part.isidentifier() for part in parts)


def test_capability_order_does_not_change_compiler_identity() -> None:
    capabilities = _capabilities()

    forward = _compile(capabilities=capabilities)
    reversed_order = _compile(capabilities=tuple(reversed(capabilities)))

    assert forward.as_dict() == reversed_order.as_dict()


def test_compiler_admits_capabilities_declared_by_repository_quality_inventory() -> None:
    contract = _contract()
    snapshot = _snapshot_with_declared_quality_tools()
    architecture = _architecture(contract, snapshot)
    validation = SimpleNamespace(
        bundle_digest=canonical_digest(contract), engineering_admissible=True
    )

    result = (
        _api()
        .TestPlanCompiler()
        .compile(
            contract,
            validation,
            snapshot,
            architecture,
            _capabilities(),
        )
    )

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None


def test_declared_quality_tool_must_match_capability_evidence_path() -> None:
    contract = _contract()
    snapshot = _snapshot_with_declared_quality_tools()
    architecture = _architecture(contract, snapshot)
    validation = SimpleNamespace(
        bundle_digest=canonical_digest(contract), engineering_admissible=True
    )
    capabilities = list(_capabilities())
    capabilities[0] = replace(capabilities[0], observed_paths=("tests/unit/test_contracts.py",))

    result = (
        _api()
        .TestPlanCompiler()
        .compile(
            contract,
            validation,
            snapshot,
            architecture,
            tuple(capabilities),
        )
    )

    assert result.disposition.value == "BLOCKED"
    assert any(item.rule_id == "TESTPLAN.TOOLCHAIN.TOOL" for item in result.diagnostics)


def test_malformed_capability_returns_typed_diagnostic_instead_of_crashing() -> None:
    result = _compile(capabilities=(object(),))

    assert result.disposition.value == "BLOCKED"
    assert any(item.rule_id == "TESTPLAN.TOOLCHAIN.TYPE" for item in result.diagnostics)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("test_class", "UNIT"),
        ("command", (None,)),
        ("environment", None),
        ("tool", None),
        ("evidence_format", None),
        ("observed_paths", (None,)),
    ),
)
def test_malformed_capability_fields_fail_closed(field: str, value: Any) -> None:
    capability = replace(_capabilities()[0], **{field: value})

    result = _compile(capabilities=(capability,))

    assert result.disposition.value == "BLOCKED"
    assert any(item.rule_id == "TESTPLAN.TOOLCHAIN.TYPE" for item in result.diagnostics)


def test_capability_command_must_invoke_its_observed_tool() -> None:
    capabilities = list(_capabilities())
    capabilities[0] = replace(
        capabilities[0],
        tool="pytest",
        command=("bandit", "-q"),
    )

    result = _compile(capabilities=tuple(capabilities))

    assert result.disposition.value == "BLOCKED"
    assert any(
        item.rule_id == "TESTPLAN.TOOLCHAIN.COMMAND_TOOL_MISMATCH" for item in result.diagnostics
    )


@pytest.mark.parametrize(
    "command",
    (
        ("pytest", "--collect-only"),
        ("pytest", "--version"),
        ("python", "-m", "pytest", "--help"),
        ("pytest", "--setup-only"),
    ),
)
def test_capability_command_must_execute_tests(command: tuple[str, ...]) -> None:
    capabilities = list(_capabilities())
    capabilities[0] = replace(capabilities[0], command=command)

    result = _compile(capabilities=tuple(capabilities))

    assert result.disposition.value == "BLOCKED"
    assert any(
        item.rule_id == "TESTPLAN.TOOLCHAIN.NON_EXECUTING_COMMAND" for item in result.diagnostics
    )


def test_compiler_selects_risk_based_classes_and_justifies_not_applicable() -> None:
    result = _compile()
    assert result.plan is not None
    decisions = {item.test_class: item for item in result.plan.class_decisions}

    assert decisions[_api().TestClass.UNIT].status == "SELECTED"
    assert decisions[_api().TestClass.INTEGRATION].status == "SELECTED"
    assert decisions[_api().TestClass.E2E].status == "SELECTED"
    assert decisions[_api().TestClass.MIGRATION].status == "SELECTED"
    assert decisions[_api().TestClass.ACCESSIBILITY].status == "SELECTED"
    assert decisions[_api().TestClass.SECURITY_PRIVACY].status == "SELECTED"
    assert decisions[_api().TestClass.RELEASE].status == "SELECTED"
    assert decisions[_api().TestClass.PERFORMANCE].status == "NOT_APPLICABLE"
    assert decisions[_api().TestClass.PERFORMANCE].justification


def test_manual_evidence_is_valid_but_excludes_autonomous_numerator() -> None:
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"]["verification_method"] = (
        "Manual product-owner observation"
    )

    result = _compile(contract)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    manual = [node for node in result.plan.nodes if node.execution_mode == "MANUAL"]
    assert any("AC-001" in node.target_refs for node in manual)
    assert not result.plan.autonomy_eligible
    assert result.plan.manual_intervention_refs


def test_mixed_mode_acceptance_criterion_preserves_manual_attestation() -> None:
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"]["verification_method"] = (
        "Automated assertion and manual product-owner review"
    )

    result = _compile(contract)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    matching_nodes = [node for node in result.plan.nodes if "AC-001" in node.target_refs]
    assert {node.execution_mode for node in matching_nodes} == {"AUTOMATED", "MANUAL"}
    assert not result.plan.autonomy_eligible
    assert "AC-001" in result.plan.manual_intervention_refs


def test_manual_quality_assurance_expectation_is_compiled() -> None:
    contract = _contract()
    contract["quality_assurance"]["expectations"]["QA-001"] = {
        "evidence_type": "MANUAL_EVIDENCE",
        "expectation": "A product owner inspects deterministic outcomes.",
        "requirement_refs": ["FR-001"],
    }

    result = _compile(contract)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    matching_nodes = [node for node in result.plan.nodes if "QA-001" in node.target_refs]
    assert matching_nodes
    assert all(node.execution_mode == "MANUAL" for node in matching_nodes)
    assert "QA-001" in result.plan.required_refs
    assert "QA-001" in result.plan.manual_intervention_refs
    assert not result.plan.autonomy_eligible


def test_manual_release_gate_preserves_manual_attestation() -> None:
    contract = _contract()
    contract["quality_assurance"]["release_gates"]["GATE-MANUAL"] = {
        "description": "An operator approves the exact release candidate.",
        "evidence_expectation": "Manual operator approval",
    }

    result = _compile(contract)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    matching_nodes = [node for node in result.plan.nodes if "GATE-MANUAL" in node.target_refs]
    assert matching_nodes
    assert all(node.execution_mode == "MANUAL" for node in matching_nodes)
    assert "GATE-MANUAL" in result.plan.manual_intervention_refs
    assert not result.plan.autonomy_eligible


def test_missing_selected_toolchain_blocks_with_explicit_targets() -> None:
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.SECURITY_PRIVACY
    )

    result = _compile(capabilities=capabilities)

    assert result.disposition.value == "BLOCKED"
    assert result.plan is not None
    assert any(item.rule_id == "TESTPLAN.TOOLCHAIN.MISSING" for item in result.diagnostics)
    blocked = [node for node in result.plan.nodes if node.status == "BLOCKED"]
    assert blocked
    assert any("SEC-001" in node.target_refs for node in blocked)
    assert not result.plan.autonomy_eligible


def test_accessibility_non_functional_requirement_requires_accessibility_evidence() -> None:
    contract = _contract()
    contract["ux"]["accessibility"] = {}
    contract["non_functional_requirements"]["NFR-ACCESSIBILITY-001"] = {
        "category": "ACCESSIBILITY",
        "evidence_expectation": "Automated WCAG evidence at the exact commit.",
        "requirement": "The primary journey is keyboard accessible.",
        "target": "WCAG 2.2 AA",
    }
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.ACCESSIBILITY
    )

    result = _compile(contract, capabilities=capabilities)

    assert result.disposition.value == "BLOCKED"
    assert result.plan is not None
    decisions = {item.test_class: item for item in result.plan.class_decisions}
    assert decisions[_api().TestClass.ACCESSIBILITY].status == "BLOCKED"
    assert any(
        node.test_class is _api().TestClass.ACCESSIBILITY
        and "NFR-ACCESSIBILITY-001" in node.target_refs
        and node.status == "BLOCKED"
        for node in result.plan.nodes
    )


def test_manual_only_accessibility_requires_no_automated_capability() -> None:
    contract = _contract()
    contract["ux"]["accessibility"]["A11Y-001"]["evidence_expectation"] = (
        "Manual screen-reader review"
    )
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.ACCESSIBILITY
    )

    result = _compile(contract, capabilities=capabilities)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    accessibility_nodes = [
        node for node in result.plan.nodes if node.test_class is _api().TestClass.ACCESSIBILITY
    ]
    assert accessibility_nodes
    assert all(node.execution_mode == "MANUAL" for node in accessibility_nodes)
    assert all(not node.meaningful_red_required for node in accessibility_nodes)
    decisions = {item.test_class: item for item in result.plan.class_decisions}
    assert decisions[_api().TestClass.ACCESSIBILITY].status == "SELECTED"
    assert not result.plan.autonomy_eligible


def test_manual_only_accessibility_nfr_requires_no_automated_capability() -> None:
    contract = _contract()
    contract["ux"]["accessibility"] = {}
    contract["non_functional_requirements"]["NFR-ACCESSIBILITY-MANUAL-001"] = {
        "category": "ACCESSIBILITY",
        "evidence_expectation": "Manual screen-reader review",
        "requirement": "A screen-reader specialist verifies the primary journey.",
        "target": "Product-approved manual evidence",
    }
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.ACCESSIBILITY
    )

    result = _compile(contract, capabilities=capabilities)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    matching_nodes = [
        node for node in result.plan.nodes if "NFR-ACCESSIBILITY-MANUAL-001" in node.target_refs
    ]
    assert matching_nodes
    assert all(node.execution_mode == "MANUAL" for node in matching_nodes)
    assert all(not node.meaningful_red_required for node in matching_nodes)
    assert not result.plan.autonomy_eligible


def test_mixed_mode_accessibility_nfr_preserves_manual_attestation() -> None:
    contract = _contract()
    contract["ux"]["accessibility"] = {}
    contract["non_functional_requirements"]["NFR-ACCESSIBILITY-MIXED-001"] = {
        "category": "ACCESSIBILITY",
        "evidence_expectation": "Automated axe scan and manual screen-reader review",
        "requirement": "The primary journey is machine-scanned and human-verified.",
        "target": "WCAG 2.2 AA",
    }

    result = _compile(contract)

    assert result.disposition.value == "ADMITTED"
    assert result.plan is not None
    matching_nodes = [
        node for node in result.plan.nodes if "NFR-ACCESSIBILITY-MIXED-001" in node.target_refs
    ]
    assert {node.execution_mode for node in matching_nodes} == {"AUTOMATED", "MANUAL"}
    assert any(
        node.owner == "ACCESSIBILITY" for node in matching_nodes if node.execution_mode == "MANUAL"
    )
    assert not result.plan.autonomy_eligible
    assert "NFR-ACCESSIBILITY-MIXED-001" in result.plan.manual_intervention_refs


def test_scalability_non_functional_requirement_requires_performance_evidence() -> None:
    contract = _contract()
    contract["non_functional_requirements"]["NFR-SCALABILITY-001"] = {
        "category": "SCALABILITY",
        "evidence_expectation": "Load evidence at the exact commit.",
        "requirement": "The workflow sustains the contracted peak volume.",
        "target": "100 requests per second",
    }
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.PERFORMANCE
    )

    result = _compile(contract, capabilities=capabilities)

    assert result.disposition.value == "BLOCKED"
    assert result.plan is not None
    assert any(
        node.test_class is _api().TestClass.PERFORMANCE
        and "NFR-SCALABILITY-001" in node.target_refs
        and node.status == "BLOCKED"
        for node in result.plan.nodes
    )


@pytest.mark.parametrize(
    ("mutation", "rule_id"),
    [
        (
            lambda capability: replace(capability, tool="unobserved-tool"),
            "TESTPLAN.TOOLCHAIN.TOOL",
        ),
        (
            lambda capability: replace(capability, observed_paths=("unobserved.toml",)),
            "TESTPLAN.TOOLCHAIN.PATH",
        ),
        (
            lambda capability: replace(capability, command=()),
            "TESTPLAN.TOOLCHAIN.COMMAND",
        ),
    ],
)
def test_unproven_toolchain_capability_fails_closed(mutation: Any, rule_id: str) -> None:
    capabilities = list(_capabilities())
    capabilities[0] = mutation(capabilities[0])

    result = _compile(capabilities=tuple(capabilities))

    assert result.disposition.value == "BLOCKED"
    assert any(item.rule_id == rule_id for item in result.diagnostics)


def _red_run(plan: Any) -> Any:
    api = _api()
    executions = tuple(
        api.RedTestExecution(
            plan_node_id=node.node_id,
            test_node_id=node.expected_test_node,
            outcome="FAILED",
            failure_kind="ASSERTION",
            observed_assertion_id=node.assertion_id,
        )
        for node in plan.nodes
        if node.status == "PLANNED"
        and node.execution_mode == "AUTOMATED"
        and node.meaningful_red_required
    )
    return api.MeaningfulRedRun(
        test_plan_digest=plan.plan_digest,
        commit_sha="c" * 40,
        toolchain_digest=plan.toolchain_digest,
        executions=executions,
        tool_executions=tuple(
            api.ToolExecutionReceipt(
                command=command,
                returncode=1,
                stdout_digest=canonical_digest({"output": "red"}),
                stderr_digest=canonical_digest({"output": ""}),
            )
            for command in sorted(
                {
                    node.command
                    for node in plan.nodes
                    if node.status == "PLANNED"
                    and node.execution_mode == "AUTOMATED"
                    and node.command
                }
            )
        ),
    )


def test_meaningful_red_admits_exact_assertion_failures() -> None:
    result = _compile()
    assert result.plan is not None

    admission = (
        _api()
        .MeaningfulRedGate()
        .validate(result.plan, _red_run(result.plan), expected_commit_sha="c" * 40)
    )

    assert admission.admitted
    assert admission.diagnostics == ()


@pytest.mark.parametrize(
    ("mutation", "rule_id"),
    [
        (
            lambda run: replace(
                run,
                executions=(replace(run.executions[0], failure_kind="IMPORT"),)
                + run.executions[1:],
            ),
            "RED.FAILURE_KIND",
        ),
        (
            lambda run: replace(
                run,
                executions=(replace(run.executions[0], outcome="SKIPPED"),) + run.executions[1:],
            ),
            "RED.SKIPPED",
        ),
        (
            lambda run: replace(
                run,
                executions=(replace(run.executions[0], outcome="PASSED"),) + run.executions[1:],
            ),
            "RED.VACUOUS",
        ),
        (
            lambda run: replace(
                run,
                executions=(replace(run.executions[0], observed_assertion_id="WRONG"),)
                + run.executions[1:],
            ),
            "RED.ASSERTION",
        ),
        (
            lambda run: replace(run, executions=run.executions[1:]),
            "RED.MISSING",
        ),
    ],
)
def test_meaningful_red_rejects_false_red(mutation: Any, rule_id: str) -> None:
    result = _compile()
    assert result.plan is not None
    run = mutation(_red_run(result.plan))

    admission = _api().MeaningfulRedGate().validate(result.plan, run, expected_commit_sha="c" * 40)

    assert not admission.admitted
    assert any(item.rule_id == rule_id for item in admission.diagnostics)


def test_changed_plan_or_wrong_commit_invalidates_red_evidence() -> None:
    result = _compile()
    assert result.plan is not None
    run = _red_run(result.plan)

    wrong_plan = replace(result.plan, plan_digest="sha256:" + "0" * 64)
    wrong_plan_result = (
        _api().MeaningfulRedGate().validate(wrong_plan, run, expected_commit_sha="c" * 40)
    )
    wrong_commit_result = (
        _api().MeaningfulRedGate().validate(result.plan, run, expected_commit_sha="d" * 40)
    )

    assert not wrong_plan_result.admitted
    assert any(item.rule_id == "RED.PLAN_DIGEST" for item in wrong_plan_result.diagnostics)
    assert not wrong_commit_result.admitted
    assert any(item.rule_id == "RED.COMMIT" for item in wrong_commit_result.diagnostics)


def _runner_workspace(
    tmp_path: Path,
    plan: Any,
    *,
    failures: bool,
    pytest_marker: bool = False,
) -> tuple[Path, str]:
    workspace = tmp_path / ("red-workspace" if failures else "passing-workspace")
    generated = workspace / "tests" / "generated"
    generated.mkdir(parents=True)
    (workspace / "tests" / "__init__.py").write_text("")
    (generated / "__init__.py").write_text("")
    methods: list[str] = []
    for node in plan.nodes:
        if not node.meaningful_red_required or node.execution_mode != "AUTOMATED":
            continue
        method = node.expected_test_node.rsplit(".", 1)[-1]
        statement = f'self.fail("{node.assertion_id}")' if failures else "self.assertTrue(True)"
        methods.extend((f"    def {method}(self):", f"        {statement}", ""))
    (generated / "test_plan.py").write_text(
        "import unittest\n\n\nclass GeneratedPlanTests(unittest.TestCase):\n" + "\n".join(methods)
    )
    if pytest_marker:
        (workspace / "conftest.py").write_text(
            "from pathlib import Path\n\nPath('pytest-command-ran').write_text('executed')\n"
        )
    subprocess.run(("git", "init", "-q", str(workspace)), check=True)
    subprocess.run(("git", "-C", str(workspace), "add", "."), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(workspace),
            "-c",
            "user.name=PMPE Test",
            "-c",
            "user.email=pmpe@example.invalid",
            "commit",
            "-qm",
            "runner fixture",
        ),
        check=True,
    )
    commit = subprocess.run(
        ("git", "-C", str(workspace), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return workspace, commit


def test_plan_must_be_persisted_before_implementation_authorization(tmp_path: Path) -> None:
    preliminary = _compile(capabilities=_pytest_capabilities())
    assert preliminary.plan is not None
    workspace, commit = _runner_workspace(tmp_path, preliminary.plan, failures=True)
    snapshot = _snapshot_at(commit)
    result = _compile_with_snapshot(snapshot, capabilities=_pytest_capabilities())
    assert result.plan is not None
    store = _api().TestPlanStore(tmp_path / "run")

    with pytest.raises(_api().TestPlanNotAdmitted):
        store.authorize_implementation(
            result.plan,
            workspace=workspace,
            expected_commit_sha=commit,
        )

    receipt = _store_admit(
        store,
        snapshot=snapshot,
        capabilities=_pytest_capabilities(),
    )
    authorization = store.authorize_implementation(
        result.plan,
        workspace=workspace,
        expected_commit_sha=commit,
    )

    assert receipt.plan_digest == result.plan.plan_digest
    assert authorization.plan_digest == result.plan.plan_digest
    assert authorization.red_run_digest.startswith("sha256:")
    assert authorization.commit_sha == commit
    assert (tmp_path / "run" / "test-plan.json").exists()


def test_implementation_authorization_ignores_self_asserted_red_claims(tmp_path: Path) -> None:
    preliminary = _compile(capabilities=_pytest_capabilities())
    assert preliminary.plan is not None
    workspace, commit = _runner_workspace(tmp_path, preliminary.plan, failures=False)
    snapshot = _snapshot_at(commit)
    result = _compile_with_snapshot(snapshot, capabilities=_pytest_capabilities())
    assert result.plan is not None
    store = _api().TestPlanStore(tmp_path / "run")
    _store_admit(store, snapshot=snapshot, capabilities=_pytest_capabilities())
    forged = _red_run(result.plan)
    assert forged.executions and all(item.outcome == "FAILED" for item in forged.executions)

    with pytest.raises(_api().TestPlanNotAdmitted, match="RED.VACUOUS"):
        store.authorize_implementation(
            result.plan,
            workspace=workspace,
            expected_commit_sha=commit,
        )


def test_authorization_requires_the_plan_repository_commit(tmp_path: Path) -> None:
    result = _compile()
    assert result.plan is not None
    store = _api().TestPlanStore(tmp_path / "run")
    _store_admit(store)
    workspace, commit = _runner_workspace(tmp_path, result.plan, failures=True)
    assert commit != result.plan.repository_commit

    with pytest.raises(_api().TestPlanNotAdmitted, match="repository commit"):
        store.authorize_implementation(
            result.plan,
            workspace=workspace,
            expected_commit_sha=commit,
        )


def test_authorization_executes_the_admitted_plan_command(tmp_path: Path) -> None:
    preliminary = _compile(capabilities=_pytest_capabilities())
    assert preliminary.plan is not None
    workspace, commit = _runner_workspace(
        tmp_path,
        preliminary.plan,
        failures=True,
        pytest_marker=True,
    )
    snapshot = _snapshot_at(commit)
    result = _compile_with_snapshot(snapshot, capabilities=_pytest_capabilities())
    assert result.plan is not None
    store = _api().TestPlanStore(tmp_path / "run")
    _store_admit(store, snapshot=snapshot, capabilities=_pytest_capabilities())

    store.authorize_implementation(
        result.plan,
        workspace=workspace,
        expected_commit_sha=commit,
    )

    assert (workspace / "pytest-command-ran").read_text() == "executed"


def test_store_rejects_a_caller_constructed_admitted_plan(tmp_path: Path) -> None:
    result = _compile()
    assert result.plan is not None
    forged = replace(
        result.plan,
        autonomy_eligible=True,
        class_decisions=(),
        coverage_matrix=(),
        manual_intervention_refs=(),
        nodes=(),
        required_refs=(),
        plan_digest="",
    )
    payload = forged.as_dict()
    payload.pop("plan_digest")
    forged = replace(forged, plan_digest=canonical_digest(payload))
    assert forged.digest_is_valid() and forged.disposition == "ADMITTED"

    with pytest.raises(TypeError):
        _api().TestPlanStore(tmp_path / "run").admit(forged)


def test_implementation_authorization_rejects_a_persisted_blocked_plan(tmp_path: Path) -> None:
    capabilities = tuple(
        item for item in _capabilities() if item.test_class is not _api().TestClass.SECURITY_PRIVACY
    )
    result = _compile(capabilities=capabilities)
    assert result.plan is not None
    assert result.plan.disposition == "BLOCKED"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "test-plan.json").write_bytes(result.plan.canonical_bytes())

    with pytest.raises(_api().TestPlanNotAdmitted):
        _api().TestPlanStore(run_dir).authorize_implementation(
            result.plan,
            workspace=tmp_path,
            expected_commit_sha="c" * 40,
        )


def test_plan_store_is_idempotent_and_refuses_overwrite(tmp_path: Path) -> None:
    result = _compile()
    assert result.plan is not None
    store = _api().TestPlanStore(tmp_path / "run")

    first = _store_admit(store)
    second = _store_admit(store)
    assert first == second

    changed = _contract()
    changed["acceptance_criteria"]["AC-001"]["criterion"] += " Changed subject."
    with pytest.raises(_api().TestPlanConflict):
        _store_admit(store, contract=changed)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_plan_store_rejects_a_symlinked_plan_without_reading_its_target(
    tmp_path: Path,
) -> None:
    result = _compile()
    assert result.plan is not None
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(result.plan.canonical_bytes())
    (run_dir / "test-plan.json").symlink_to(outside)

    with pytest.raises(_api().TestPlanNotAdmitted):
        _store_admit(_api().TestPlanStore(run_dir))

    assert outside.read_bytes() == result.plan.canonical_bytes()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_plan_store_rejects_a_symlinked_run_directory_without_writing_outside(
    tmp_path: Path,
) -> None:
    result = _compile()
    assert result.plan is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = tmp_path / "run"
    run_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(_api().TestPlanNotAdmitted):
        _store_admit(_api().TestPlanStore(run_dir))

    assert not (outside / "test-plan.json").exists()


def test_compiler_does_not_mutate_inputs() -> None:
    contract = _contract()
    original = copy.deepcopy(contract)

    _compile(contract)

    assert contract == original


def test_executed_traceability_covers_criteria_risks_guardrails_and_manual_evidence() -> None:
    result = _compile()
    assert result.plan is not None
    plan = result.plan
    automated = [
        TestExecution(
            node_id=node.expected_test_node,
            outcome="passed",
            failure_kind="",
        )
        for node in plan.nodes
        if node.status == "PLANNED" and node.execution_mode == "AUTOMATED"
    ]
    manual = {
        node.node_id
        for node in plan.nodes
        if node.status == "PLANNED" and node.execution_mode == "MANUAL"
    }

    report = build_executed_plan_traceability(
        plan=plan,
        evidence=TestEvidence(executions=automated),
        manual_attestations=manual,
    )

    assert report.all_verified
    by_ref = {item.target_ref: item for item in report.entries}
    assert by_ref["AC-001"].classification == "VERIFIED"
    assert by_ref["RISK-001"].classification == "VERIFIED"
    assert by_ref["GUARD-SECURITY-001"].classification == "VERIFIED"

    missing_manual = build_executed_plan_traceability(
        plan=plan,
        evidence=TestEvidence(executions=automated),
        manual_attestations=set(),
    )
    assert not missing_manual.all_verified
    assert missing_manual.counts["MANUAL_REQUIRED"] >= 1


def test_executed_plan_traceability_rejects_skipped_and_import_dead_nodes() -> None:
    result = _compile()
    assert result.plan is not None
    plan = result.plan
    automated_nodes = [
        node
        for node in plan.nodes
        if node.status == "PLANNED" and node.execution_mode == "AUTOMATED"
    ]
    evidence = TestEvidence(
        executions=[
            TestExecution(
                node_id=node.expected_test_node,
                outcome="skipped" if index == 0 else "failed",
                failure_kind="skip" if index == 0 else "import",
            )
            for index, node in enumerate(automated_nodes)
        ]
    )

    report = build_executed_plan_traceability(
        plan=plan,
        evidence=evidence,
        manual_attestations=set(),
    )

    assert not report.all_verified
    assert report.counts["NOT_PROVEN"] >= 1
