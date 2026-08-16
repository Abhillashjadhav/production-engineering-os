"""Exact-plan, exact-commit meaningful-red admission."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest

from .models import TestPlan, TestPlanDiagnostic, TestPlanDisposition


@dataclass(frozen=True)
class RedTestExecution:
    plan_node_id: str
    test_node_id: str
    outcome: str
    failure_kind: str
    observed_assertion_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeaningfulRedRun:
    test_plan_digest: str
    commit_sha: str
    toolchain_digest: str
    executions: tuple[RedTestExecution, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit_sha": self.commit_sha,
            "executions": [item.as_dict() for item in self.executions],
            "test_plan_digest": self.test_plan_digest,
            "toolchain_digest": self.toolchain_digest,
        }

    def run_digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True)
class MeaningfulRedAdmission:
    admitted: bool
    diagnostics: tuple[TestPlanDiagnostic, ...]
    plan_digest: str
    commit_sha: str
    red_run_digest: str


def _red_diagnostic(rule_id: str, field_path: str, explanation: str) -> TestPlanDiagnostic:
    return TestPlanDiagnostic(
        rule_id=rule_id,
        disposition=TestPlanDisposition.BLOCKED,
        field_path=field_path,
        owner="ENGINEERING",
        explanation=explanation,
        next_action="Correct the test or evidence and rerun meaningful-red admission.",
    )


class MeaningfulRedGate:
    def validate(
        self,
        plan: TestPlan,
        run: MeaningfulRedRun,
        *,
        expected_commit_sha: str,
    ) -> MeaningfulRedAdmission:
        diagnostics: list[TestPlanDiagnostic] = []
        if not plan.digest_is_valid() or run.test_plan_digest != plan.plan_digest:
            diagnostics.append(
                _red_diagnostic(
                    "RED.PLAN_DIGEST",
                    "/test_plan_digest",
                    "Red evidence is not bound to the exact admitted test plan.",
                )
            )
        if run.commit_sha != expected_commit_sha:
            diagnostics.append(
                _red_diagnostic(
                    "RED.COMMIT",
                    "/commit_sha",
                    "Red evidence is not bound to the exact pre-implementation commit.",
                )
            )
        if run.toolchain_digest != plan.toolchain_digest:
            diagnostics.append(
                _red_diagnostic(
                    "RED.TOOLCHAIN",
                    "/toolchain_digest",
                    "Red evidence used a different test toolchain.",
                )
            )

        by_node: dict[str, RedTestExecution] = {}
        for index, execution in enumerate(run.executions):
            if execution.plan_node_id in by_node:
                diagnostics.append(
                    _red_diagnostic(
                        "RED.DUPLICATE",
                        f"/executions/{index}/plan_node_id",
                        f"Plan node {execution.plan_node_id} has duplicate red evidence.",
                    )
                )
            else:
                by_node[execution.plan_node_id] = execution

        expected_nodes = {
            node.node_id: node
            for node in plan.nodes
            if node.status == "PLANNED"
            and node.execution_mode == "AUTOMATED"
            and node.meaningful_red_required
        }
        for unknown in sorted(set(by_node) - set(expected_nodes)):
            diagnostics.append(
                _red_diagnostic(
                    "RED.UNKNOWN",
                    "/executions",
                    f"Red evidence names unknown or non-red plan node {unknown}.",
                )
            )
        for node_id, node in expected_nodes.items():
            observed = by_node.get(node_id)
            if observed is None:
                diagnostics.append(
                    _red_diagnostic(
                        "RED.MISSING",
                        f"/nodes/{node_id}",
                        f"Required meaningful-red node {node_id} did not execute.",
                    )
                )
                continue
            if observed.test_node_id != node.expected_test_node:
                diagnostics.append(
                    _red_diagnostic(
                        "RED.TEST_NODE",
                        f"/executions/{node_id}/test_node_id",
                        f"Execution for {node_id} came from the wrong test node.",
                    )
                )
            if observed.outcome.upper() == "SKIPPED":
                diagnostics.append(
                    _red_diagnostic(
                        "RED.SKIPPED",
                        f"/executions/{node_id}/outcome",
                        f"Skipped node {node_id} is not meaningful-red evidence.",
                    )
                )
                continue
            if observed.outcome.upper() == "PASSED":
                diagnostics.append(
                    _red_diagnostic(
                        "RED.VACUOUS",
                        f"/executions/{node_id}/outcome",
                        (
                            f"Node {node_id} passed before implementation and does not "
                            "prove missing behavior."
                        ),
                    )
                )
                continue
            if observed.outcome.upper() != "FAILED" or observed.failure_kind.upper() != "ASSERTION":
                diagnostics.append(
                    _red_diagnostic(
                        "RED.FAILURE_KIND",
                        f"/executions/{node_id}/failure_kind",
                        f"Node {node_id} failed outside its intended assertion.",
                    )
                )
                continue
            if observed.observed_assertion_id != node.assertion_id:
                diagnostics.append(
                    _red_diagnostic(
                        "RED.ASSERTION",
                        f"/executions/{node_id}/observed_assertion_id",
                        f"Node {node_id} failed a different assertion than the admitted plan.",
                    )
                )

        ordered = tuple(
            sorted(diagnostics, key=lambda item: (item.rule_id, item.field_path, item.explanation))
        )
        return MeaningfulRedAdmission(
            admitted=not ordered,
            diagnostics=ordered,
            plan_digest=plan.plan_digest,
            commit_sha=run.commit_sha,
            red_run_digest=run.run_digest(),
        )
