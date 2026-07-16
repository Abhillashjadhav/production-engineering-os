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
