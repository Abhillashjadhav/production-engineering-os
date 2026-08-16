"""Executed traceability: requirements classified by executed test results.

The chain is contract requirement -> claimed test nodes (markers/plans are
supplementary metadata) -> EXECUTED results -> classification:

- VERIFIED: at least one mapped test node executed and passed, none failed
  through its own assertion
- FAILED: a mapped test failed through its intended assertion
- NOT_PROVEN: mapped tests missing, never executed, skipped, or dead on
  import/collection errors — none of which is evidence
- BLOCKED_PRODUCT_DECISION: an open ProductChangeRequest covers the requirement
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pmpe.quality.test_evidence import TestEvidence
from pmpe.testing.models import TestPlan

_FAILED_TEST_PREFIX = "unittest.loader._FailedTest."


def normalize_node_id(raw: str) -> str:
    """pytest-style path::Class::test -> unittest module.Class.test."""
    if "::" not in raw:
        return raw
    path, _, rest = raw.partition("::")
    module = path.removesuffix(".py").replace("/", ".").replace("\\", ".")
    return module + "." + rest.replace("::", ".")


@dataclass
class RequirementEvidence:
    requirement_id: str
    classification: str  # VERIFIED | FAILED | NOT_PROVEN | BLOCKED_PRODUCT_DECISION
    evidence_nodes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExecutedTraceabilityReport:
    entries: list[RequirementEvidence]

    @property
    def all_verified(self) -> bool:
        return bool(self.entries) and all(e.classification == "VERIFIED" for e in self.entries)

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for entry in self.entries:
            tally[entry.classification] = tally.get(entry.classification, 0) + 1
        return tally


@dataclass
class PlanEvidenceEntry:
    """Executed classification for any TestPlan target, not only a requirement."""

    target_ref: str
    classification: str
    plan_node_ids: list[str] = field(default_factory=list)
    evidence_nodes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExecutedPlanTraceabilityReport:
    entries: list[PlanEvidenceEntry]

    @property
    def all_verified(self) -> bool:
        return bool(self.entries) and all(
            item.classification == "VERIFIED" for item in self.entries
        )

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for entry in self.entries:
            tally[entry.classification] = tally.get(entry.classification, 0) + 1
        return tally


def red_summary(evidence: TestEvidence) -> dict[str, object]:
    """Classify a red run: only assertion failures are meaningful red evidence."""
    kinds = {"assertion": 0, "import": 0, "error": 0, "skipped": 0, "passed": 0}
    for execution in evidence.executions:
        if execution.outcome == "passed":
            kinds["passed"] += 1
        elif execution.outcome == "skipped":
            kinds["skipped"] += 1
        elif execution.failure_kind == "assertion":
            kinds["assertion"] += 1
        elif execution.failure_kind == "import":
            kinds["import"] += 1
        else:
            kinds["error"] += 1
    return {**kinds, "meaningful_red": kinds["assertion"] > 0}


def build_executed_traceability(
    *,
    requirement_ids: list[str],
    tests_by_requirement: dict[str, list[str]],
    evidence: TestEvidence,
    blocked_requirements: set[str],
) -> ExecutedTraceabilityReport:
    executed = evidence.by_node()
    import_dead_modules = [
        node.removeprefix(_FAILED_TEST_PREFIX)
        for node in executed
        if node.startswith(_FAILED_TEST_PREFIX)
    ]

    entries: list[RequirementEvidence] = []
    for requirement_id in requirement_ids:
        if requirement_id in blocked_requirements:
            entries.append(
                RequirementEvidence(
                    requirement_id=requirement_id,
                    classification="BLOCKED_PRODUCT_DECISION",
                    reasons=["an open ProductChangeRequest covers this requirement"],
                )
            )
            continue

        claimed = [normalize_node_id(n) for n in tests_by_requirement.get(requirement_id, [])]
        if not claimed:
            entries.append(
                RequirementEvidence(
                    requirement_id=requirement_id,
                    classification="NOT_PROVEN",
                    reasons=["no test is mapped to this requirement"],
                )
            )
            continue

        passed: list[str] = []
        reasons: list[str] = []
        assertion_failed = False
        for node in claimed:
            execution = executed.get(node)
            if execution is None:
                dead = next((m for m in import_dead_modules if node.startswith(m + ".")), None)
                if dead is not None:
                    reasons.append(
                        f"{node}: module '{dead}' died on an import/collection error — "
                        "not meaningful evidence"
                    )
                else:
                    reasons.append(f"{node}: mapped test was not executed")
                continue
            if execution.outcome == "passed":
                passed.append(node)
            elif execution.outcome == "skipped":
                reasons.append(f"{node}: skipped tests do not create coverage")
            elif execution.failure_kind == "assertion":
                assertion_failed = True
                reasons.append(f"{node}: failed through its assertion")
            elif execution.failure_kind == "import":
                reasons.append(f"{node}: import failure is not meaningful evidence")
            else:
                reasons.append(f"{node}: errored ({execution.failure_kind})")

        if assertion_failed:
            classification = "FAILED"
        elif passed:
            classification = "VERIFIED"
        else:
            classification = "NOT_PROVEN"
        entries.append(
            RequirementEvidence(
                requirement_id=requirement_id,
                classification=classification,
                evidence_nodes=passed,
                reasons=reasons,
            )
        )
    return ExecutedTraceabilityReport(entries=entries)


def build_executed_plan_traceability(
    *,
    plan: TestPlan,
    evidence: TestEvidence,
    manual_attestations: set[str],
) -> ExecutedPlanTraceabilityReport:
    """Bind executed and manual evidence to every criterion/risk/guardrail plan target."""

    executed = evidence.by_node()
    entries: list[PlanEvidenceEntry] = []
    priority = {
        "VERIFIED": 0,
        "NOT_PROVEN": 1,
        "MANUAL_REQUIRED": 2,
        "BLOCKED": 3,
        "FAILED": 4,
    }
    for target_ref in plan.required_refs:
        nodes = [node for node in plan.nodes if target_ref in node.target_refs]
        classifications: list[str] = []
        evidence_nodes: list[str] = []
        reasons: list[str] = []
        for node in nodes:
            if node.status != "PLANNED":
                classifications.append("BLOCKED")
                reasons.append(f"{node.node_id}: {node.blocker_reason or 'plan node is blocked'}")
                continue
            if node.execution_mode == "MANUAL":
                if node.node_id in manual_attestations:
                    classifications.append("VERIFIED")
                    evidence_nodes.append(f"manual:{node.node_id}")
                else:
                    classifications.append("MANUAL_REQUIRED")
                    reasons.append(f"{node.node_id}: required manual attestation is absent")
                continue
            execution = executed.get(normalize_node_id(node.expected_test_node))
            if execution is None:
                classifications.append("NOT_PROVEN")
                reasons.append(f"{node.node_id}: mapped test was not executed")
            elif execution.outcome == "passed":
                classifications.append("VERIFIED")
                evidence_nodes.append(execution.node_id)
            elif execution.failure_kind == "assertion":
                classifications.append("FAILED")
                reasons.append(f"{node.node_id}: failed through its assertion")
            elif execution.outcome == "skipped":
                classifications.append("NOT_PROVEN")
                reasons.append(f"{node.node_id}: skipped tests do not create evidence")
            elif execution.failure_kind == "import":
                classifications.append("NOT_PROVEN")
                reasons.append(f"{node.node_id}: import failure is not evidence")
            else:
                classifications.append("NOT_PROVEN")
                reasons.append(f"{node.node_id}: errored ({execution.failure_kind})")
        if not nodes:
            classifications.append("NOT_PROVEN")
            reasons.append("no TestPlan node maps to this required reference")
        classification = max(classifications, key=priority.__getitem__)
        entries.append(
            PlanEvidenceEntry(
                target_ref=target_ref,
                classification=classification,
                plan_node_ids=[node.node_id for node in nodes],
                evidence_nodes=evidence_nodes,
                reasons=reasons,
            )
        )
    return ExecutedPlanTraceabilityReport(entries=entries)
