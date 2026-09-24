"""Immutable artifacts for contract-to-test compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes

TEST_PLAN_SCHEMA_VERSION = "1.0.0"


class TestClass(StrEnum):
    UNIT = "UNIT"
    INTEGRATION = "INTEGRATION"
    E2E = "E2E"
    MIGRATION = "MIGRATION"
    PERFORMANCE = "PERFORMANCE"
    ACCESSIBILITY = "ACCESSIBILITY"
    SECURITY_PRIVACY = "SECURITY_PRIVACY"
    RELEASE = "RELEASE"


class TestPlanDisposition(StrEnum):
    ADMITTED = "ADMITTED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class RepositoryTestCapability:
    """A repository-observed executable test capability, not a model assertion."""

    test_class: TestClass
    command: tuple[str, ...]
    environment: str
    tool: str
    evidence_format: str
    observed_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(asdict(self)))


@dataclass(frozen=True)
class TestClassDecision:
    test_class: TestClass
    status: str
    rule_id: str
    justification: str

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(asdict(self)))


@dataclass(frozen=True)
class TestPlanNode:
    node_id: str
    test_class: TestClass
    target_refs: tuple[str, ...]
    assertion: str
    assertion_id: str
    fixture: str
    environment: str
    owner: str
    execution_mode: str
    interpretation_mode: str
    evidence_expectation: str
    toolchain_refs: tuple[str, ...]
    command: tuple[str, ...]
    expected_test_node: str
    meaningful_red_required: bool
    status: str
    blocker_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(asdict(self)))


@dataclass(frozen=True)
class CoverageEntry:
    target_ref: str
    plan_node_ids: tuple[str, ...]
    status: str

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(asdict(self)))


@dataclass(frozen=True)
class TestPlan:
    schema_version: str
    compiler_version: str
    plan_id: str
    contract_digest: str
    repository_snapshot_digest: str
    repository_commit: str
    architecture_pack_digest: str
    toolchain_digest: str
    disposition: str
    required_refs: tuple[str, ...]
    class_decisions: tuple[TestClassDecision, ...]
    nodes: tuple[TestPlanNode, ...]
    coverage_matrix: tuple[CoverageEntry, ...]
    autonomy_eligible: bool
    manual_intervention_refs: tuple[str, ...]
    plan_digest: str
    artifact_kind: str = "TEST_PLAN"

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_refs", tuple(self.required_refs))
        object.__setattr__(self, "class_decisions", tuple(self.class_decisions))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "coverage_matrix", tuple(self.coverage_matrix))
        object.__setattr__(self, "manual_intervention_refs", tuple(self.manual_intervention_refs))

    def as_dict(self) -> dict[str, Any]:
        return {
            "architecture_pack_digest": self.architecture_pack_digest,
            "artifact_kind": self.artifact_kind,
            "autonomy_eligible": self.autonomy_eligible,
            "class_decisions": [item.as_dict() for item in self.class_decisions],
            "compiler_version": self.compiler_version,
            "contract_digest": self.contract_digest,
            "coverage_matrix": [item.as_dict() for item in self.coverage_matrix],
            "disposition": self.disposition,
            "manual_intervention_refs": list(self.manual_intervention_refs),
            "nodes": [item.as_dict() for item in self.nodes],
            "plan_digest": self.plan_digest,
            "plan_id": self.plan_id,
            "repository_commit": self.repository_commit,
            "repository_snapshot_digest": self.repository_snapshot_digest,
            "required_refs": list(self.required_refs),
            "schema_version": self.schema_version,
            "toolchain_digest": self.toolchain_digest,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.as_dict())

    def digest_is_valid(self) -> bool:
        payload = self.as_dict()
        claimed = str(payload.pop("plan_digest", ""))
        return bool(claimed) and claimed == canonical_digest(payload)


@dataclass(frozen=True)
class TestPlanDiagnostic:
    rule_id: str
    disposition: TestPlanDisposition
    field_path: str
    owner: str
    explanation: str
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        result = _plain(asdict(self))
        return dict(result)


@dataclass(frozen=True)
class TestPlanCompilationResult:
    compiler_version: str
    disposition: TestPlanDisposition
    input_digest: str
    diagnostics: tuple[TestPlanDiagnostic, ...]
    plan: TestPlan | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "disposition": self.disposition.value,
            "input_digest": self.input_digest,
            "plan": self.plan.as_dict() if self.plan else None,
        }
