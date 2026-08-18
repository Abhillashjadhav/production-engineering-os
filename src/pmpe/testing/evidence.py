"""Exact-plan, exact-commit meaningful-red admission."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.quality.test_evidence import run_tests_with_evidence

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
class ToolExecutionReceipt:
    command: tuple[str, ...]
    returncode: int
    stdout_digest: str
    stderr_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "stderr_digest": self.stderr_digest,
            "stdout_digest": self.stdout_digest,
        }


@dataclass(frozen=True)
class MeaningfulRedRun:
    test_plan_digest: str
    commit_sha: str
    toolchain_digest: str
    executions: tuple[RedTestExecution, ...]
    tool_executions: tuple[ToolExecutionReceipt, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit_sha": self.commit_sha,
            "executions": [item.as_dict() for item in self.executions],
            "test_plan_digest": self.test_plan_digest,
            "tool_executions": [item.as_dict() for item in self.tool_executions],
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

        expected_commands = {
            node.command
            for node in plan.nodes
            if node.status == "PLANNED" and node.execution_mode == "AUTOMATED" and node.command
        }
        observed_commands: set[tuple[str, ...]] = set()
        for index, receipt in enumerate(run.tool_executions):
            if receipt.command in observed_commands:
                diagnostics.append(
                    _red_diagnostic(
                        "RED.TOOL_EXECUTION_DUPLICATE",
                        f"/tool_executions/{index}/command",
                        "A plan-bound command has more than one execution receipt.",
                    )
                )
            observed_commands.add(receipt.command)
        if observed_commands != expected_commands:
            diagnostics.append(
                _red_diagnostic(
                    "RED.TOOL_EXECUTION",
                    "/tool_executions",
                    "Meaningful-red did not execute exactly the admitted plan commands.",
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


def execute_meaningful_red(
    plan: TestPlan,
    workspace: Path,
    *,
    expected_commit_sha: str,
) -> MeaningfulRedRun:
    """Run the fixed evidence harness and derive red claims from its raw output."""

    repository = Path(workspace).resolve()
    commit = subprocess.run(
        ("git", "-C", str(repository), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()
    if commit != expected_commit_sha:
        raise ValueError("meaningful-red workspace is not at the expected commit")
    status = subprocess.run(
        ("git", "-C", str(repository), "status", "--porcelain", "--untracked-files=all"),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout
    if status:
        raise ValueError("meaningful-red workspace contains uncommitted changes")
    commands = sorted(
        {
            node.command
            for node in plan.nodes
            if node.status == "PLANNED" and node.execution_mode == "AUTOMATED" and node.command
        }
    )
    tool_executions: list[ToolExecutionReceipt] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=300,
        )
        tool_executions.append(
            ToolExecutionReceipt(
                command=command,
                returncode=completed.returncode,
                stdout_digest=canonical_digest({"output": completed.stdout}),
                stderr_digest=canonical_digest({"output": completed.stderr}),
            )
        )
    evidence = run_tests_with_evidence(repository)
    by_node = evidence.by_node()
    executions: list[RedTestExecution] = []
    for node in plan.nodes:
        if (
            node.status != "PLANNED"
            or node.execution_mode != "AUTOMATED"
            or not node.meaningful_red_required
        ):
            continue
        observed = by_node.get(node.expected_test_node)
        if observed is None:
            continue
        executions.append(
            RedTestExecution(
                plan_node_id=node.node_id,
                test_node_id=observed.node_id,
                outcome=observed.outcome.upper(),
                failure_kind=observed.failure_kind.upper(),
                observed_assertion_id=(
                    node.assertion_id if node.assertion_id in observed.detail else ""
                ),
            )
        )
    return MeaningfulRedRun(
        test_plan_digest=plan.plan_digest,
        commit_sha=commit,
        toolchain_digest=plan.toolchain_digest,
        executions=tuple(executions),
        tool_executions=tuple(tool_executions),
    )
