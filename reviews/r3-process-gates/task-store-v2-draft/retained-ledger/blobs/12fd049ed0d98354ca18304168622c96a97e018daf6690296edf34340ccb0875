"""Workflow steps 1-8: ingest through implement (the build half).

Step bodies are exactly the pipeline lifecycle documented in ARCHITECTURE.md;
they communicate only through the RunContext and its artifacts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from pmpe.config import PipelineConfig
from pmpe.domain.errors import StepFailure
from pmpe.domain.serialize import jsonable
from pmpe.implementation.workspace import write_files
from pmpe.orchestration.context import RunContext, _Blocked, _Rejected
from pmpe.orchestration.render import (
    _adr_markdown,
    _architecture_markdown,
    _generated,
    _plan_markdown,
)
from pmpe.policies.engine import PolicyEngine
from pmpe.quality.gates import (
    SUBPROCESS_TIMEOUT_S,
    normalize_format,
    tail_output,
)

_ISSUE_POLICY = {
    "CONTRADICTION": "validation.contradiction",
    "NSM_ACTIVITY_ONLY": "validation.activity_only_nsm",
    "AC_UNTESTABLE": "validation.unclear_acceptance_criteria",
    "UNSUPPORTED_DEPLOYMENT": "deployment.production_target",
}

# Structural spec defects (broken references, invalid identifiers, capability gaps)
# are NOT approvable: no human decision can make downstream stages act on them —
# an approved run would crash in codegen. The spec must be fixed and re-run.
_STRUCTURAL_ERROR_CODES = frozenset(
    {
        "AC_UNKNOWN_REQUIREMENT",
        "FR_WITHOUT_AC",
        "MISSING_ENTITY",
        "INVALID_IDENTIFIER",
        "REQUIREMENT_ID_FORMAT",
        "CAPABILITY_DEPENDENCY",
    }
)


class BuildSteps:
    def __init__(self, config: PipelineConfig, policy: PolicyEngine) -> None:
        self.config = config
        self.policy = policy

    def _escalate_or_pass(
        self, ctx: RunContext, step: str, items: list[tuple[str, str, str]]
    ) -> None:
        """items: (unique_key, decision_type, reason). Blocks unless every item has a
        positive approval; a rejection fails the run."""
        if not items:
            return
        approvals = ctx.load_approvals()
        pending: list[str] = []
        for key, decision_type, reason in items:
            decision = self.policy.classify(decision_type)
            ctx.events.emit(
                "decision",
                step=step,
                decision_type=decision_type,
                rule=decision.rule_id,
                level=decision.level.value,
                justification=decision.justification,
            )
            if not self.policy.requires_approval(decision.level):
                continue
            esc, created = ctx.ensure_escalation(
                key=key,
                step=step,
                risk=decision.level,
                reason=reason,
                rule=decision.rule_id,
            )
            if created:
                pending.append(esc.id)
                continue
            approval = approvals.get(esc.id)
            if approval is None:
                pending.append(esc.id)
            elif not approval.approved:
                raise _Rejected(
                    f"escalation {esc.id} rejected by {approval.approver}: {approval.reason}"
                )
        if pending:
            raise _Blocked(
                "legacy test harness waiting for fixture approval: " + ", ".join(pending)
            )

    def _step_ingest(self, ctx: RunContext) -> None:
        spec = ctx.spec  # raises SpecError on schema violations
        ctx.store.write_json("normalized_spec.json", spec)

    def _step_validate(self, ctx: RunContext) -> None:
        from pmpe.validation.validator import RequirementValidator

        result = RequirementValidator().validate(ctx.spec)
        ctx.store.write_json("validation_report.json", result)
        structural = [i for i in result.errors if i.code in _STRUCTURAL_ERROR_CODES]
        if structural:
            details = "; ".join(f"[{i.code}] {i.message}" for i in structural)
            raise StepFailure(
                "validate",
                "specification defects require a spec fix (not approvable): " + details,
            )
        items = [
            (
                f"{issue.code}:{issue.field}",
                _ISSUE_POLICY.get(issue.code, "validation.missing_product_decision"),
                issue.message,
            )
            for issue in [*result.errors, *result.questions]
        ]
        self._escalate_or_pass(ctx, "validate", items)
        for issue in result.warnings:
            ctx.events.emit("validation_warning", code=issue.code, message=issue.message)

    def _step_plan(self, ctx: RunContext) -> None:
        plan = ctx.plan
        ctx.store.write_json("engineering_plan.json", plan)
        ctx.store.write_text("engineering_plan.md", _plan_markdown(plan))

    def _step_architecture(self, ctx: RunContext) -> None:
        arch = ctx.architecture
        ctx.store.write_json(
            "architecture.json", {"doc": jsonable(arch.doc), "adrs": jsonable(arch.adrs)}
        )
        ctx.store.write_text("architecture.md", _architecture_markdown(arch))
        for adr in arch.adrs:
            ctx.store.write_text(f"adr/{adr.id}.md", _adr_markdown(adr))
        items = [
            (
                f"arch:{esc.context.get('adr', esc.reason[:40])}",
                "architecture.irreversible_choice",
                esc.reason,
            )
            for esc in arch.escalations
        ]
        self._escalate_or_pass(ctx, "architecture", items)

    def _step_acceptance(self, ctx: RunContext) -> None:
        ctx.store.write_json("acceptance_criteria.json", ctx.spec.acceptance_criteria)
        lines = ["# Acceptance criteria", ""]
        for fr in ctx.spec.functional_requirements:
            lines.append(f"## {fr.id} — {fr.title}")
            for ac in ctx.spec.criteria_for(fr.id):
                lines.append(f"- **{ac.id}**: {ac.criterion}")
            lines.append("")
        ctx.store.write_text("acceptance_criteria.md", "\n".join(lines))

    def _step_generate_tests(self, ctx: RunContext) -> None:
        workspace = ctx.workspace
        if workspace.exists():
            shutil.rmtree(workspace)  # step was interrupted mid-way: rebuild from scratch
        workspace.mkdir(parents=True)
        git = ctx.git
        git.init()
        scaffold_task = ctx.plan.tasks[0]
        (workspace / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n*.db\n.ruff_cache/\n.pytest_cache/\n"
        )
        (workspace / "README.md").write_text(
            f"# {ctx.spec.product_name}\n\nBuild in progress ({ctx.state.run_id}).\n"
        )
        git.commit_all(f"chore: {scaffold_task.id} scaffold workspace")
        git.create_branch(ctx.branch)

        tests = ctx.generated_tests
        test_task = next(t for t in ctx.plan.tasks if t.kind == "test")
        write_files(workspace, tests.files)
        normalize_format(workspace)
        git.commit_all(f"test: {test_task.id} add generated test suite (before implementation)")
        ctx.store.write_json(
            "test_plan.json",
            {
                "files": [f.path for f in tests.files],
                "tests_by_requirement": tests.tests_by_requirement,
            },
        )

    def _step_confirm_red(self, ctx: RunContext) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
            cwd=ctx.workspace,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
        if proc.returncode == 0:
            raise StepFailure(
                "confirm_red",
                "generated tests PASSED before implementation — the suite is vacuous "
                "and cannot gate anything",
            )
        tail = tail_output(proc.stdout + proc.stderr)
        ctx.store.write_json(
            "confirm_red.json",
            {"tests_failed_before_implementation": True, "output_tail": tail},
        )

    def _step_implement(self, ctx: RunContext) -> None:
        implementation = ctx.implementation
        git = ctx.git
        if git.current_branch() != ctx.branch:
            git.checkout(ctx.branch)
        for task_id in ctx.plan.order:
            files = implementation.files_by_task.get(task_id)
            if not files:
                continue
            task = ctx.plan.task(task_id)
            write_files(ctx.workspace, files)
            normalize_format(ctx.workspace)
            git.commit_all(f"feat: {task.id} {task.title}")
        if self.config.chaos_inject_files:
            injected = [
                _generated(path, content)
                for path, content in self.config.chaos_inject_files.items()
            ]
            write_files(ctx.workspace, injected)
            git.commit_all("feat: chaos-injected files (test hook)")
        ctx.store.write_json(
            "implementation.json",
            {
                "files_by_task": {
                    tid: [f.path for f in files]
                    for tid, files in implementation.files_by_task.items()
                },
                "code_by_requirement": implementation.code_by_requirement,
            },
        )
