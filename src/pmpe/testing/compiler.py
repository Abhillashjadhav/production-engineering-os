"""Deterministic compiler from approved product truth to an executable TestPlan."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from pmpe.architecture.models import ArchitecturePack
from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence import EvidenceAdapterRegistry, EvidenceError, default_adapter_registry
from pmpe.execution import ExecutionCommand, ExecutionError
from pmpe.repository.models import RepositorySnapshot

from .models import (
    TEST_PLAN_SCHEMA_VERSION,
    CoverageEntry,
    RepositoryTestCapability,
    TestClass,
    TestClassDecision,
    TestPlan,
    TestPlanCompilationResult,
    TestPlanDiagnostic,
    TestPlanDisposition,
    TestPlanNode,
)

TEST_PLAN_COMPILER_VERSION = "1.0.0"


class ContractAdmission(Protocol):
    bundle_digest: str

    @property
    def engineering_admissible(self) -> bool: ...


def _diagnostic(
    rule_id: str,
    field_path: str,
    explanation: str,
    next_action: str,
    *,
    owner: str = "ENGINEERING",
    disposition: TestPlanDisposition = TestPlanDisposition.BLOCKED,
) -> TestPlanDiagnostic:
    return TestPlanDiagnostic(
        rule_id=rule_id,
        disposition=disposition,
        field_path=field_path,
        owner=owner,
        explanation=explanation,
        next_action=next_action,
    )


def _section(contract: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    value: Any = contract
    for key in path:
        if not isinstance(value, Mapping):
            return {}
        value = value.get(key, {})
    return value if isinstance(value, Mapping) else {}


def _has_manual(value: Any) -> bool:
    text = str(value).upper()
    return "MANUAL" in text or "HUMAN" in text


def _class_for_text(value: Any, *, default: TestClass) -> TestClass:
    text = str(value).upper()
    if any(token in text for token in ("ACCESSIBILITY", "A11Y", "WCAG")):
        return TestClass.ACCESSIBILITY
    if any(token in text for token in ("SECURITY", "PRIVACY", "SECRET", "CREDENTIAL")):
        return TestClass.SECURITY_PRIVACY
    if any(
        token in text
        for token in (
            "CAPACITY",
            "LATENCY",
            "LOAD",
            "PERFORMANCE",
            "SCALABILITY",
            "THROUGHPUT",
        )
    ):
        return TestClass.PERFORMANCE
    return default


def _command_invokes_tool(command: Sequence[str], tool: str) -> bool:
    if not command or not tool.strip():
        return False

    def executable(value: str) -> str:
        name = value.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        return name.removesuffix(".exe")

    expected = executable({"node:test": "node"}.get(tool.casefold(), tool))
    invoked = executable(command[0])
    if invoked == expected:
        return True
    if invoked in {"py", "python", "python3"} and len(command) > 2 and command[1] == "-m":
        return executable(command[2]) == expected
    if invoked == "npx" and len(command) > 1:
        return executable(command[1]) == expected
    if invoked in {"pnpm", "yarn"} and len(command) > 2 and command[1] == "exec":
        return executable(command[2]) == expected
    return False


def _command_executes_tests(command: Sequence[str]) -> bool:
    non_executing_options = {
        "--co",
        "--collect-only",
        "--collectonly",
        "--fixtures",
        "--fixtures-per-test",
        "--help",
        "--list",
        "--list-tests",
        "--markers",
        "--setup-plan",
        "--setup-only",
        "--trace-config",
        "--version",
        "-h",
        "-V",
    }
    return not any(
        argument in non_executing_options or argument.startswith("--collect-only=")
        for argument in command[1:]
    )


def _is_canonical_capability(value: Any) -> bool:
    return (
        type(value) is RepositoryTestCapability
        and type(value.test_class) is TestClass
        and type(value.command) is tuple
        and all(type(item) is str for item in value.command)
        and type(value.environment) is str
        and type(value.tool) is str
        and type(value.evidence_format) is str
        and type(value.observed_paths) is tuple
        and all(type(item) is str for item in value.observed_paths)
    )


class TestPlanCompiler:
    def __init__(self, registry: EvidenceAdapterRegistry | None = None) -> None:
        schema = packaged_schema_dir() / "test_plan.schema.json"
        self._schema = Draft202012Validator(json.loads(schema.read_text()))
        self._registry = registry or default_adapter_registry()

    def compile(
        self,
        contract_bundle: Mapping[str, Any],
        contract_validation: ContractAdmission,
        repository_snapshot: RepositorySnapshot,
        architecture_pack: ArchitecturePack,
        capabilities: Sequence[RepositoryTestCapability],
    ) -> TestPlanCompilationResult:
        diagnostics: list[TestPlanDiagnostic] = []
        try:
            contract = copy.deepcopy(json.loads(canonical_json_bytes(contract_bundle)))
            contract_digest = canonical_digest(contract)
        except Exception:
            diagnostic = _diagnostic(
                "TESTPLAN.INPUT.CANONICAL",
                "/",
                "The contract is outside the canonical JSON domain.",
                "Correct the admitted contract and rerun compilation.",
                owner="PRODUCT",
                disposition=TestPlanDisposition.ERROR,
            )
            return self._result("sha256:" + "0" * 64, [diagnostic], None)

        invalid_capabilities = [
            index
            for index, capability in enumerate(capabilities)
            if not _is_canonical_capability(capability)
        ]
        if invalid_capabilities:
            diagnostics.extend(
                _diagnostic(
                    "TESTPLAN.TOOLCHAIN.TYPE",
                    f"/capabilities/{index}",
                    "Capability input is not a canonical RepositoryTestCapability.",
                    "Use the typed repository-intelligence adapter output.",
                )
                for index in invalid_capabilities
            )
            input_digest = canonical_digest(
                {
                    "architecture_pack_digest": getattr(architecture_pack, "pack_digest", ""),
                    "contract_digest": contract_digest,
                    "invalid_capability_indexes": invalid_capabilities,
                    "repository_snapshot_digest": getattr(
                        repository_snapshot, "snapshot_digest", ""
                    ),
                }
            )
            return self._result(input_digest, diagnostics, None)

        capability_payload = sorted(
            (item.as_dict() for item in capabilities),
            key=canonical_json_bytes,
        )
        input_digest = canonical_digest(
            {
                "architecture_pack_digest": getattr(architecture_pack, "pack_digest", ""),
                "capabilities": capability_payload,
                "contract_digest": contract_digest,
                "repository_snapshot_digest": getattr(repository_snapshot, "snapshot_digest", ""),
            }
        )
        self._validate_inputs(
            contract_digest,
            contract_validation,
            repository_snapshot,
            architecture_pack,
            diagnostics,
        )
        if diagnostics:
            return self._result(input_digest, diagnostics, None)

        capability_by_class = self._validate_capabilities(
            capabilities, repository_snapshot, diagnostics
        )
        specs, selected_reasons = self._node_specs(contract)
        required_refs = self._required_refs(contract)
        selected_classes = {item[0] for item in specs}
        automated_classes = {item[0] for item in specs if item[4] == "AUTOMATED"}

        decisions: list[TestClassDecision] = []
        for test_class in TestClass:
            if test_class in selected_classes:
                capability_required = test_class in automated_classes
                status = (
                    "SELECTED"
                    if not capability_required or test_class in capability_by_class
                    else "BLOCKED"
                )
                decisions.append(
                    TestClassDecision(
                        test_class=test_class,
                        status=status,
                        rule_id=f"TESTCLASS.{test_class.value}.SELECT",
                        justification=selected_reasons[test_class],
                    )
                )
                if capability_required and test_class not in capability_by_class:
                    diagnostics.append(
                        _diagnostic(
                            "TESTPLAN.TOOLCHAIN.MISSING",
                            f"/class_decisions/{test_class.value}",
                            (
                                f"Selected {test_class.value} evidence has no observed "
                                "executable capability."
                            ),
                            (
                                "Add repository-backed test infrastructure or record a "
                                "product-owned manual evidence procedure."
                            ),
                        )
                    )
            else:
                decisions.append(
                    TestClassDecision(
                        test_class=test_class,
                        status="NOT_APPLICABLE",
                        rule_id=f"TESTCLASS.{test_class.value}.NOT_APPLICABLE",
                        justification=self._not_applicable_reason(test_class),
                    )
                )

        nodes: list[TestPlanNode] = []
        manual_refs: set[str] = set()
        for index, spec in enumerate(specs, start=1):
            (
                test_class,
                target_refs,
                assertion,
                evidence_expectation,
                execution_mode,
                owner,
            ) = spec
            node_id = f"TPN-{index:04d}"
            capability = capability_by_class.get(test_class)
            status = "PLANNED"
            blocker = ""
            if execution_mode == "MANUAL":
                manual_refs.update(target_refs)
                command: tuple[str, ...] = ()
                environment = "human-observation"
                toolchain_refs: tuple[str, ...] = ()
                interpretation_mode = "MANUAL"
            elif capability is None:
                status = "BLOCKED"
                blocker = f"No admitted {test_class.value} repository capability"
                command = ()
                environment = "UNAVAILABLE"
                toolchain_refs = ()
                interpretation_mode = "AUTOMATED"
            else:
                command = capability.command
                environment = capability.environment
                toolchain_refs = (
                    capability.tool,
                    capability.evidence_format,
                    *capability.observed_paths,
                )
                interpretation_mode = "AUTOMATED"
            assertion_id = f"ASSERT-{node_id}"
            expected_test_node = (
                "tests/generated/test_plan.py::GeneratedPlanTests::"
                f"test_{node_id.lower().replace('-', '_')}"
            )
            if capability is not None and capability.evidence_format == "tap13/v1":
                expected_test_node = f"{node_id} [assertion:{assertion_id}]"
            nodes.append(
                TestPlanNode(
                    node_id=node_id,
                    test_class=test_class,
                    target_refs=tuple(sorted(set(target_refs))),
                    assertion=assertion,
                    assertion_id=assertion_id,
                    fixture=f"synthetic:{min(target_refs)}",
                    environment=environment,
                    owner=owner,
                    execution_mode=execution_mode,
                    interpretation_mode=interpretation_mode,
                    evidence_expectation=evidence_expectation,
                    toolchain_refs=toolchain_refs,
                    command=command,
                    expected_test_node=expected_test_node,
                    meaningful_red_required=(
                        execution_mode == "AUTOMATED" and test_class is not TestClass.RELEASE
                    ),
                    status=status,
                    blocker_reason=blocker,
                )
            )

        coverage = self._coverage(required_refs, nodes)
        for entry in coverage:
            if entry.status == "MISSING":
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.COVERAGE.MISSING",
                        f"/coverage_matrix/{entry.target_ref}",
                        (
                            f"Required contract reference {entry.target_ref} has no "
                            "evidence-producing plan node."
                        ),
                        "Add an executable test or explicit blocker for this reference.",
                        owner="PRODUCT",
                    )
                )

        disposition = TestPlanDisposition.BLOCKED if diagnostics else TestPlanDisposition.ADMITTED
        toolchain_digest = canonical_digest(capability_payload)
        plan = TestPlan(
            schema_version=TEST_PLAN_SCHEMA_VERSION,
            compiler_version=TEST_PLAN_COMPILER_VERSION,
            plan_id=f"TESTPLAN-{input_digest.removeprefix('sha256:')[:16].upper()}",
            contract_digest=contract_digest,
            repository_snapshot_digest=repository_snapshot.snapshot_digest,
            repository_commit=repository_snapshot.commit_sha,
            architecture_pack_digest=architecture_pack.pack_digest,
            toolchain_digest=toolchain_digest,
            disposition=disposition.value,
            required_refs=required_refs,
            class_decisions=tuple(decisions),
            nodes=tuple(nodes),
            coverage_matrix=coverage,
            autonomy_eligible=not diagnostics and not manual_refs,
            manual_intervention_refs=tuple(sorted(manual_refs)),
            plan_digest="",
        )
        payload = plan.as_dict()
        payload.pop("plan_digest")
        plan = replace(plan, plan_digest=canonical_digest(payload))
        schema_errors = sorted(
            self._schema.iter_errors(plan.as_dict()), key=lambda item: list(item.absolute_path)
        )
        if schema_errors:
            diagnostics.extend(
                _diagnostic(
                    "TESTPLAN.SCHEMA",
                    "/" + "/".join(str(part) for part in error.absolute_path),
                    error.message,
                    "Correct the compiler output; this is an engineering defect.",
                    disposition=TestPlanDisposition.ERROR,
                )
                for error in schema_errors
            )
            return self._result(input_digest, diagnostics, None)
        return self._result(input_digest, diagnostics, plan, disposition=disposition)

    def _validate_inputs(
        self,
        contract_digest: str,
        validation: ContractAdmission,
        snapshot: RepositorySnapshot,
        architecture: ArchitecturePack,
        diagnostics: list[TestPlanDiagnostic],
    ) -> None:
        if getattr(validation, "bundle_digest", None) != contract_digest or not getattr(
            validation, "engineering_admissible", False
        ):
            diagnostics.append(
                _diagnostic(
                    "TESTPLAN.INPUT.CONTRACT",
                    "/contract_digest",
                    "The contract is not the exact engineering-admissible subject.",
                    "Admit the exact canonical contract before compiling tests.",
                    owner="PRODUCT",
                    disposition=TestPlanDisposition.ERROR,
                )
            )
        if type(snapshot) is not RepositorySnapshot or not snapshot.digest_is_valid():
            diagnostics.append(
                _diagnostic(
                    "TESTPLAN.INPUT.REPOSITORY",
                    "/repository_snapshot_digest",
                    "Repository intelligence is not a digest-valid canonical snapshot.",
                    "Run repository intelligence for the exact target commit.",
                    disposition=TestPlanDisposition.ERROR,
                )
            )
            return
        if snapshot.disposition != "COMPLETE":
            diagnostics.append(
                _diagnostic(
                    "TESTPLAN.INPUT.REPOSITORY",
                    "/repository_snapshot_digest",
                    "An incomplete repository snapshot cannot prove toolchain feasibility.",
                    "Resolve repository-intelligence blockers and rescan.",
                    disposition=TestPlanDisposition.ERROR,
                )
            )
        if type(architecture) is not ArchitecturePack or not architecture.digest_is_valid():
            diagnostics.append(
                _diagnostic(
                    "TESTPLAN.INPUT.ARCHITECTURE",
                    "/architecture_pack_digest",
                    "Architecture input is not a digest-valid ArchitecturePack.",
                    "Compile and admit architecture before compiling tests.",
                    disposition=TestPlanDisposition.ERROR,
                )
            )
            return
        if (
            architecture.disposition != "ADMITTED"
            or architecture.contract_digest != contract_digest
            or architecture.repository_snapshot_digest != snapshot.snapshot_digest
            or architecture.repository_commit != snapshot.commit_sha
        ):
            diagnostics.append(
                _diagnostic(
                    "TESTPLAN.INPUT.SUBJECT",
                    "/architecture_pack_digest",
                    "Architecture is not admitted for the exact contract and repository subject.",
                    "Recompile architecture against the admitted inputs.",
                    disposition=TestPlanDisposition.ERROR,
                )
            )

    def _validate_capabilities(
        self,
        capabilities: Sequence[RepositoryTestCapability],
        snapshot: RepositorySnapshot,
        diagnostics: list[TestPlanDiagnostic],
    ) -> dict[TestClass, RepositoryTestCapability]:
        result: dict[TestClass, RepositoryTestCapability] = {}
        tools = {item.tool.casefold() for item in snapshot.tool_versions}
        quality_inventory = snapshot.inventory.get("tests_quality")
        declared_tools = {
            (item.path, item.location.removeprefix("tool:").casefold())
            for item in (() if quality_inventory is None else quality_inventory.items)
            if item.kind == "DECLARED_QUALITY_TOOL" and item.location.startswith("tool:")
        }
        paths = set(snapshot.included_paths)
        for index, capability in enumerate(capabilities):
            path = f"/capabilities/{index}"
            if type(capability) is not RepositoryTestCapability:
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.TYPE",
                        path,
                        "Capability input is not a canonical RepositoryTestCapability.",
                        "Use the typed repository-intelligence adapter output.",
                    )
                )
                continue
            if capability.test_class in result:
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.DUPLICATE",
                        path,
                        f"More than one capability claims {capability.test_class.value}.",
                        "Provide one deterministic capability per test class.",
                    )
                )
                continue
            if not capability.command or any(not item.strip() for item in capability.command):
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.COMMAND",
                        path + "/command",
                        "Executable capability has no complete command.",
                        "Record the exact repository-backed invocation.",
                    )
                )
                continue
            tool = capability.tool.casefold()
            declared_for_capability = any(
                (observed_path, tool) in declared_tools
                for observed_path in capability.observed_paths
            )
            if tool not in tools and not declared_for_capability:
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.TOOL",
                        path + "/tool",
                        (
                            f"Tool {capability.tool!r} was neither observed at runtime nor "
                            "declared by repository quality inventory."
                        ),
                        "Declare and lock the tool or refresh repository intelligence.",
                    )
                )
                continue
            unknown_paths = sorted(set(capability.observed_paths) - paths)
            if not capability.observed_paths or unknown_paths:
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.PATH",
                        path + "/observed_paths",
                        "Capability provenance is absent from the exact repository snapshot.",
                        "Bind the capability to observed repository configuration paths.",
                    )
                )
                continue
            if not _command_invokes_tool(capability.command, capability.tool):
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.COMMAND_TOOL_MISMATCH",
                        path + "/command",
                        (
                            "Executable capability command does not invoke its claimed "
                            f"tool {capability.tool!r}."
                        ),
                        "Bind the exact repository-backed invocation to the declared tool.",
                    )
                )
                continue
            if not _command_executes_tests(capability.command):
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.NON_EXECUTING_COMMAND",
                        path + "/command",
                        "Executable capability command selects a non-executing tool mode.",
                        "Record a repository-backed invocation that executes the planned tests.",
                    )
                )
                continue
            try:
                command = ExecutionCommand(capability.command)
                adapter = self._registry.resolve(
                    capability.tool,
                    capability.evidence_format,
                )
                if not adapter.supports(command):
                    raise EvidenceError("command is not admitted by the evidence adapter")
            except (EvidenceError, ExecutionError) as exc:
                diagnostics.append(
                    _diagnostic(
                        "TESTPLAN.TOOLCHAIN.EVIDENCE_REGISTRY",
                        path + "/evidence_format",
                        (f"Capability is not supported by the trusted evidence registry: {exc}"),
                        "Use a registry-backed command and structured evidence format.",
                    )
                )
                continue
            result[capability.test_class] = capability
        return result

    def _required_refs(self, contract: Mapping[str, Any]) -> tuple[str, ...]:
        refs: set[str] = set()
        for path in (
            ("functional_requirements",),
            ("non_functional_requirements",),
            ("acceptance_criteria",),
            ("guardrails",),
            ("risks",),
            ("security", "requirements"),
            ("privacy", "requirements"),
            ("quality_assurance", "expectations"),
            ("quality_assurance", "release_gates"),
            ("release", "expectations"),
            ("rollback", "requirements"),
            ("ux", "accessibility"),
        ):
            refs.update(str(key) for key in _section(contract, *path))
        return tuple(sorted(refs))

    def _node_specs(
        self, contract: Mapping[str, Any]
    ) -> tuple[
        list[tuple[TestClass, tuple[str, ...], str, str, str, str]],
        dict[TestClass, str],
    ]:
        specs: list[tuple[TestClass, tuple[str, ...], str, str, str, str]] = []
        reasons: dict[TestClass, str] = {}

        def add(
            test_class: TestClass,
            refs: Sequence[str],
            assertion: str,
            expectation: str,
            *,
            mode: str = "AUTOMATED",
            owner: str = "ENGINEERING",
            reason: str,
        ) -> None:
            clean_refs = tuple(sorted({str(item) for item in refs if str(item)}))
            if not clean_refs:
                return
            specs.append((test_class, clean_refs, assertion, expectation, mode, owner))
            reasons.setdefault(test_class, reason)

        criteria = _section(contract, "acceptance_criteria")
        covered_requirements: set[str] = set()
        for criterion_id, raw in sorted(criteria.items()):
            item = raw if isinstance(raw, Mapping) else {}
            refs = [str(criterion_id), *map(str, item.get("requirement_refs", ()))]
            covered_requirements.update(map(str, item.get("requirement_refs", ())))
            method = str(item.get("verification_method", "Automated executable assertion"))
            manual_required = _has_manual(method)
            automated_required = "AUTOMATED" in method.upper() or not manual_required
            reason = "Acceptance criteria require executable behavioral assertions."
            if automated_required:
                add(
                    TestClass.UNIT,
                    refs,
                    str(item.get("criterion", criterion_id)),
                    method,
                    reason=reason,
                )
            if manual_required:
                add(
                    TestClass.UNIT,
                    refs,
                    str(item.get("criterion", criterion_id)),
                    method,
                    mode="MANUAL",
                    owner="PRODUCT",
                    reason=reason,
                )

        for expectation_id, raw in sorted(
            _section(contract, "quality_assurance", "expectations").items()
        ):
            item = raw if isinstance(raw, Mapping) else {}
            evidence_type = str(item.get("evidence_type", ""))
            refs = [str(expectation_id), *map(str, item.get("requirement_refs", ()))]
            add(
                TestClass.UNIT,
                refs,
                str(item.get("expectation", expectation_id)),
                evidence_type or "Quality-assurance evidence",
                mode="AUTOMATED" if evidence_type == "AUTOMATED_TEST" else "MANUAL",
                owner="ENGINEERING" if evidence_type == "AUTOMATED_TEST" else "PRODUCT",
                reason="Typed quality-assurance expectations require matching evidence.",
            )

        for requirement_id, raw in sorted(_section(contract, "functional_requirements").items()):
            if str(requirement_id) in covered_requirements:
                continue
            item = raw if isinstance(raw, Mapping) else {}
            add(
                TestClass.UNIT,
                [str(requirement_id)],
                str(item.get("statement", item.get("title", requirement_id))),
                "Executed functional assertion",
                reason="Every functional requirement needs executable evidence.",
            )

        for requirement_id, raw in sorted(
            _section(contract, "non_functional_requirements").items()
        ):
            item = raw if isinstance(raw, Mapping) else {}
            test_class = _class_for_text(item.get("category", ""), default=TestClass.UNIT)
            expectation = str(item.get("evidence_expectation", "Executed non-functional assertion"))
            manual_required = _has_manual(expectation)
            automated_required = "AUTOMATED" in expectation.upper() or not manual_required
            reason = "Contract non-functional requirements select their applicable evidence class."
            if automated_required:
                add(
                    test_class,
                    [str(requirement_id)],
                    str(item.get("requirement", requirement_id)),
                    expectation,
                    reason=reason,
                )
            if manual_required:
                add(
                    test_class,
                    [str(requirement_id)],
                    str(item.get("requirement", requirement_id)),
                    expectation,
                    mode="MANUAL",
                    owner=("ACCESSIBILITY" if test_class is TestClass.ACCESSIBILITY else "PRODUCT"),
                    reason=reason,
                )

        for guardrail_id, raw in sorted(_section(contract, "guardrails").items()):
            item = raw if isinstance(raw, Mapping) else {}
            test_class = _class_for_text(item.get("category", ""), default=TestClass.RELEASE)
            add(
                test_class,
                [str(guardrail_id)],
                str(item.get("description", guardrail_id)),
                str(item.get("threshold", "Binary guardrail evidence")),
                reason="Guardrail category and threshold require a blocking test.",
            )

        for requirement_id, raw in sorted(_section(contract, "security", "requirements").items()):
            item = raw if isinstance(raw, Mapping) else {}
            add(
                TestClass.SECURITY_PRIVACY,
                [str(requirement_id)],
                str(item.get("requirement", requirement_id)),
                str(item.get("verification", "Security gate evidence")),
                reason="Security and privacy requirements require dedicated blocking evidence.",
            )
        for requirement_id, raw in sorted(_section(contract, "privacy", "requirements").items()):
            item = raw if isinstance(raw, Mapping) else {}
            add(
                TestClass.SECURITY_PRIVACY,
                [str(requirement_id)],
                str(item.get("requirement", requirement_id)),
                "Privacy-policy execution evidence",
                reason="Security and privacy requirements require dedicated blocking evidence.",
            )

        for risk_id, raw in sorted(_section(contract, "risks").items()):
            item = raw if isinstance(raw, Mapping) else {}
            description = str(item.get("description", risk_id))
            test_class = _class_for_text(description, default=TestClass.INTEGRATION)
            add(
                test_class,
                [str(risk_id)],
                str(item.get("mitigation", description)),
                "Risk-mitigation execution evidence",
                reason=(
                    "Named risks require evidence that their mitigation holds across boundaries."
                ),
            )

        functional_refs = tuple(sorted(map(str, _section(contract, "functional_requirements"))))
        if any(_section(contract, key) for key in ("api_contracts", "integrations", "data")):
            add(
                TestClass.INTEGRATION,
                functional_refs,
                "Declared API, integration, and data boundaries interoperate as contracted.",
                "Cross-component executed evidence",
                reason="Declared API, integration, or data boundaries require integration tests.",
            )
        ux = _section(contract, "ux")
        if any(_section(ux, key) for key in ("flows", "primary_journey", "screens")):
            add(
                TestClass.E2E,
                functional_refs,
                "The primary user journey reaches its contract-defined outcome.",
                "Executed journey evidence",
                reason="A declared user journey requires end-to-end evidence.",
            )

        rollback_requirements = _section(contract, "rollback", "requirements")
        for requirement_id, raw in sorted(rollback_requirements.items()):
            item = raw if isinstance(raw, Mapping) else {}
            add(
                TestClass.MIGRATION,
                [str(requirement_id)],
                str(item.get("requirement", requirement_id)),
                str(item.get("recovery_evidence", "Migration/rollback evidence")),
                reason="Declared rollback or compatibility behavior requires migration evidence.",
            )

        for requirement_id, raw in sorted(_section(ux, "accessibility").items()):
            item = raw if isinstance(raw, Mapping) else {}
            expectation = str(item.get("evidence_expectation", "Accessibility evidence"))
            if not _has_manual(expectation) or "AUTOMATED" in expectation.upper():
                add(
                    TestClass.ACCESSIBILITY,
                    [str(requirement_id)],
                    str(item.get("requirement", requirement_id)),
                    expectation,
                    reason="Declared accessibility requirements require accessibility evidence.",
                )
            if _has_manual(expectation):
                add(
                    TestClass.ACCESSIBILITY,
                    [str(requirement_id)],
                    str(item.get("requirement", requirement_id)),
                    expectation,
                    mode="MANUAL",
                    owner="ACCESSIBILITY",
                    reason="Declared accessibility requirements require accessibility evidence.",
                )

        for gate_id, raw in sorted(
            _section(contract, "quality_assurance", "release_gates").items()
        ):
            item = raw if isinstance(raw, Mapping) else {}
            expectation = str(item.get("evidence_expectation", "Exact-head release-gate evidence"))
            manual_required = _has_manual(expectation)
            automated_required = "AUTOMATED" in expectation.upper() or not manual_required
            reason = "Declared release gates require exact-head release evidence."
            if automated_required:
                add(
                    TestClass.RELEASE,
                    [str(gate_id)],
                    str(item.get("description", gate_id)),
                    expectation,
                    reason=reason,
                )
            if manual_required:
                add(
                    TestClass.RELEASE,
                    [str(gate_id)],
                    str(item.get("description", gate_id)),
                    expectation,
                    mode="MANUAL",
                    owner="RELEASE",
                    reason=reason,
                )

        release_targets = list(map(str, _section(contract, "release", "expectations")))
        if release_targets:
            add(
                TestClass.RELEASE,
                release_targets,
                "Every declared release gate and release expectation is satisfied.",
                "Exact-head release-gate evidence",
                reason="Declared release gates require an exact-head release test.",
            )
        return specs, reasons

    def _coverage(
        self, required_refs: tuple[str, ...], nodes: Sequence[TestPlanNode]
    ) -> tuple[CoverageEntry, ...]:
        entries: list[CoverageEntry] = []
        for target in required_refs:
            matching = tuple(node.node_id for node in nodes if target in node.target_refs)
            if not matching:
                status = "MISSING"
            elif any(node.status == "BLOCKED" for node in nodes if node.node_id in matching):
                status = "BLOCKED"
            else:
                status = "COVERED"
            entries.append(CoverageEntry(target_ref=target, plan_node_ids=matching, status=status))
        return tuple(entries)

    def _not_applicable_reason(self, test_class: TestClass) -> str:
        reasons = {
            TestClass.PERFORMANCE: (
                "No performance, latency, throughput, or load requirement is declared."
            ),
            TestClass.MIGRATION: (
                "No migration, compatibility, or rollback requirement is declared."
            ),
            TestClass.ACCESSIBILITY: "No accessibility requirement is declared.",
            TestClass.SECURITY_PRIVACY: (
                "No security, privacy, or secret-handling requirement is declared."
            ),
            TestClass.INTEGRATION: (
                "No API, integration, data boundary, or cross-boundary risk is declared."
            ),
            TestClass.E2E: "No user flow, primary journey, or screen behavior is declared.",
            TestClass.RELEASE: (
                "No release gate, expectation, or release-class guardrail is declared."
            ),
            TestClass.UNIT: "No executable functional or non-functional behavior is declared.",
        }
        return reasons[test_class]

    def _result(
        self,
        input_digest: str,
        diagnostics: Sequence[TestPlanDiagnostic],
        plan: TestPlan | None,
        *,
        disposition: TestPlanDisposition | None = None,
    ) -> TestPlanCompilationResult:
        ordered = tuple(
            sorted(diagnostics, key=lambda item: (item.rule_id, item.field_path, item.explanation))
        )
        actual = disposition or (
            TestPlanDisposition.ERROR
            if any(item.disposition is TestPlanDisposition.ERROR for item in ordered)
            else TestPlanDisposition.BLOCKED
        )
        return TestPlanCompilationResult(
            compiler_version=TEST_PLAN_COMPILER_VERSION,
            disposition=actual,
            input_digest=input_digest,
            diagnostics=ordered,
            plan=plan,
        )
