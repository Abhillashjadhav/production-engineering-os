"""The workflow engine: 18 idempotent steps, persisted state, human gates.

Design rules (see ARCHITECTURE.md):
- steps communicate through artifacts, never in-memory state that a resume would lose;
  deterministic products (plan, architecture, generated files) are recomputed from the
  spec on demand (ADR-002)
- a HIGH-risk decision writes an Escalation and blocks; `approve` + `resume` continue
- gate failures never stop the pipeline silently: the run completes through the merge
  gate, which says NO_MERGE with reasons, and the final report still lands
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pmpe.architecture.agent import ArchitectureAgent
from pmpe.artifacts.store import ArtifactStore
from pmpe.audit.traceability import TraceabilityBuilder
from pmpe.config import PipelineConfig
from pmpe.deployment.local import LocalProcessDeployer
from pmpe.domain.errors import SpecError, StepFailure
from pmpe.domain.models import (
    Adr,
    Approval,
    ArchitectureOutput,
    DeploymentResult,
    EngineeringPlan,
    Escalation,
    FixResult,
    GeneratedFile,
    GeneratedTests,
    Implementation,
    MergeRecommendation,
    MvpSpec,
    PullRequestRecord,
    ReviewReport,
    RiskLevel,
    StepStatus,
    TraceabilityReport,
)
from pmpe.domain.serialize import atomic_write_json, jsonable
from pmpe.gitops.local import LocalGitAdapter
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion import ingest
from pmpe.orchestration import decoders
from pmpe.orchestration import report as report_mod
from pmpe.orchestration.state import RunState
from pmpe.planning.planner import EngineeringPlanner
from pmpe.policies.engine import PolicyEngine
from pmpe.quality.gates import (
    SUBPROCESS_TIMEOUT_S,
    QualityGateRunner,
    normalize_format,
    tail_output,
)
from pmpe.review.fixer import FixAgent
from pmpe.review.merge_gate import MergeGate
from pmpe.review.reviewer import PrReviewer
from pmpe.telemetry.events import EventLog, utc_now
from pmpe.telemetry.metrics import LocalMetricsRecorder
from pmpe.testing.architect import TestArchitect

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


class _Blocked(Exception):  # noqa: N818 — control-flow signal, not an error
    pass


class _Rejected(Exception):  # noqa: N818 — control-flow signal, not an error
    pass


@dataclass
class RunResult:
    run_id: str
    status: str  # success | no_merge | blocked | failed
    run_dir: Path
    state: RunState


class WorkflowEngine:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.policy = PolicyEngine()

    # --- public API -----------------------------------------------------------------

    def run(self, spec_path: Path) -> RunResult:
        spec_path = Path(spec_path)
        if not spec_path.exists():
            raise SpecError(f"specification file not found: {spec_path}")
        run_id = "run-{}-{}".format(
            datetime.now(UTC).strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3)
        )
        run_dir = self.config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        spec_copy = run_dir / ("spec" + spec_path.suffix.lower())
        shutil.copyfile(spec_path, spec_copy)
        digest = hashlib.sha256(spec_copy.read_bytes()).hexdigest()
        state = RunState.new(
            run_id=run_id, run_dir=run_dir, spec_digest=digest, spec_file=spec_copy.name
        )
        state.save()
        return self._execute(state)

    def resume(self, run_id: str) -> RunResult:
        state = RunState.load(self.config.runs_dir / run_id)
        # blocked/failed steps are re-executed; done/skipped steps never are
        return self._execute(state)

    def approve(
        self,
        run_id: str,
        escalation_id: str,
        approver: str,
        reason: str,
        approved: bool = True,
    ) -> Approval:
        run_dir = self.config.runs_dir / run_id
        esc_path = run_dir / "escalations" / f"{escalation_id}.json"
        if not esc_path.exists():
            raise StepFailure("approve", f"unknown escalation '{escalation_id}' in {run_id}")
        approval = Approval(
            escalation_id=escalation_id,
            approver=approver,
            reason=reason,
            approved=approved,
            timestamp=utc_now(),
        )
        atomic_write_json(run_dir / "approvals" / f"{escalation_id}.json", approval)
        EventLog(run_dir).emit(
            "approval_recorded",
            escalation_id=escalation_id,
            approver=approver,
            approved=approved,
        )
        return approval

    # --- engine loop ------------------------------------------------------------------

    def _execute(self, state: RunState) -> RunResult:
        ctx = _RunContext(self.config, state)
        handlers = {
            "ingest": self._step_ingest,
            "validate": self._step_validate,
            "plan": self._step_plan,
            "architecture": self._step_architecture,
            "acceptance": self._step_acceptance,
            "generate_tests": self._step_generate_tests,
            "confirm_red": self._step_confirm_red,
            "implement": self._step_implement,
            "quality_gates": self._step_quality_gates,
            "create_pr": self._step_create_pr,
            "review": self._step_review,
            "fix": self._step_fix,
            "retest": self._step_retest,
            "merge_gate": self._step_merge_gate,
            "merge": self._step_merge,
            "deploy": self._step_deploy,
            "verify": self._step_verify,
            "report": self._step_report,
        }
        while (step := state.next_step()) is not None:
            if self.config.chaos_fail_at_step == step:
                state.mark(step, StepStatus.FAILED, detail="chaos_fail_at_step (test hook)")
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error="chaos hook")
                return RunResult(state.run_id, "failed", state.run_dir, state)
            state.mark(step, StepStatus.RUNNING)
            state.save()
            ctx.events.emit("step_started", step=step)
            try:
                handlers[step](ctx)
            except _Blocked as blocked:
                state.mark(step, StepStatus.BLOCKED, detail=str(blocked))
                state.outcome = "blocked"
                state.save()
                ctx.events.emit("step_blocked", step=step, reason=str(blocked))
                return RunResult(state.run_id, "blocked", state.run_dir, state)
            except _Rejected as rejected:
                state.mark(step, StepStatus.FAILED, detail=str(rejected))
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error=str(rejected))
                return RunResult(state.run_id, "failed", state.run_dir, state)
            except SpecError:
                state.mark(step, StepStatus.FAILED, detail="specification rejected")
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error="specification rejected")
                raise
            except Exception as exc:
                state.mark(step, StepStatus.FAILED, detail=str(exc)[:500])
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error=str(exc)[:500])
                raise
            if state.status_of(step) is StepStatus.RUNNING:
                state.mark(step, StepStatus.DONE)
            state.save()
            ctx.events.emit("step_completed", step=step, status=state.status_of(step).value)

        outcome = "success"
        if ctx.store.exists("merge_decision.json"):
            decision = decoders.merge_decision_from_dict(ctx.store.read_json("merge_decision.json"))
            if decision.recommendation is MergeRecommendation.NO_MERGE:
                outcome = "no_merge"
        state.outcome = outcome
        state.save()
        ctx.events.emit("run_finished", outcome=outcome)
        return RunResult(state.run_id, outcome, state.run_dir, state)

    # --- escalation machinery ---------------------------------------------------------

    def _escalate_or_pass(
        self, ctx: _RunContext, step: str, items: list[tuple[str, str, str]]
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
                "waiting for human approval: "
                + ", ".join(pending)
                + f" (pmpe approve {ctx.state.run_id} <ESC-ID> --approver ... --reason ...)"
            )

    # --- steps ------------------------------------------------------------------------

    def _step_ingest(self, ctx: _RunContext) -> None:
        spec = ctx.spec  # raises SpecError on schema violations
        ctx.store.write_json("normalized_spec.json", spec)

    def _step_validate(self, ctx: _RunContext) -> None:
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

    def _step_plan(self, ctx: _RunContext) -> None:
        plan = ctx.plan
        ctx.store.write_json("engineering_plan.json", plan)
        ctx.store.write_text("engineering_plan.md", _plan_markdown(plan))

    def _step_architecture(self, ctx: _RunContext) -> None:
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

    def _step_acceptance(self, ctx: _RunContext) -> None:
        ctx.store.write_json("acceptance_criteria.json", ctx.spec.acceptance_criteria)
        lines = ["# Acceptance criteria", ""]
        for fr in ctx.spec.functional_requirements:
            lines.append(f"## {fr.id} — {fr.title}")
            for ac in ctx.spec.criteria_for(fr.id):
                lines.append(f"- **{ac.id}**: {ac.criterion}")
            lines.append("")
        ctx.store.write_text("acceptance_criteria.md", "\n".join(lines))

    def _step_generate_tests(self, ctx: _RunContext) -> None:
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

    def _step_confirm_red(self, ctx: _RunContext) -> None:
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

    def _step_implement(self, ctx: _RunContext) -> None:
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

    def _run_gates(self, ctx: _RunContext, artifact: str, stage: str) -> None:
        results = ctx.gate_runner.run()
        ctx.store.write_json(artifact, results)
        for result in results:
            ctx.events.emit(
                "gate_result",
                stage=stage,
                gate=result.gate,
                passed=result.passed,
                required=result.required,
                skipped=result.skipped,
            )

    def _step_quality_gates(self, ctx: _RunContext) -> None:
        self._run_gates(ctx, "gate_results.json", "quality_gates")

    def _step_create_pr(self, ctx: _RunContext) -> None:
        git = ctx.git
        record = PullRequestRecord(
            title=f"feat: {ctx.spec.product_name} MVP ({ctx.state.run_id})",
            body=(
                f"Automated build of {ctx.spec.product_name} from the approved MVP "
                f"specification.\n\nPlan: {len(ctx.plan.tasks)} tasks; "
                f"APIs: {', '.join(ctx.plan.apis)}.\n"
                f"Requirement coverage is enforced by the merge gate."
            ),
            branch=ctx.branch,
            base="main",
            commits=[c.subject for c in git.log()],
            diff_stat=git.diff_stat("main"),
        )
        ctx.store.write_json("pull_request.json", record)
        ctx.store.write_text(
            "pull_request.md",
            f"# {record.title}\n\n{record.body}\n\n## Commits\n"
            + "\n".join(f"- {c}" for c in record.commits)
            + f"\n\n## Diff\n```\n{record.diff_stat}\n```\n",
        )

    def _step_review(self, ctx: _RunContext) -> None:
        result = PrReviewer().review(ctx.workspace, ctx.spec, ctx.plan)
        ctx.store.write_json("review_report.json", result)
        ctx.store.write_text("review_report.md", _review_markdown(result))

    def _step_fix(self, ctx: _RunContext) -> None:
        review = ctx.load_review("review_report.json")
        result = FixAgent().apply(ctx.workspace, review)
        if result.fixed:
            ctx.git.commit_all("fix: apply safe review fixes (allow-listed)")
        ctx.store.write_json("fix_result.json", result)
        if result.escalated:
            ids = ", ".join(sorted({f.id for f in result.escalated}))
            decision = self.policy.classify("fix.unresolvable_test_failure")
            ctx.ensure_escalation(
                key="fix:blocking",
                step="fix",
                risk=decision.level,
                reason=(
                    f"blocking findings the fix agent cannot safely resolve: {ids}. "
                    f"{decision.justification}"
                ),
                rule=decision.rule_id,
            )
            # deliberately no block: the run completes through the merge gate,
            # which will say NO_MERGE and the report will carry the open escalation

    def _step_retest(self, ctx: _RunContext) -> None:
        self._run_gates(ctx, "gate_results_retest.json", "retest")

    def _step_merge_gate(self, ctx: _RunContext) -> None:
        gates = [
            decoders.gate_result_from_dict(raw)
            for raw in ctx.store.read_json("gate_results_retest.json")
        ]
        review = PrReviewer().review(ctx.workspace, ctx.spec, ctx.plan)
        ctx.store.write_json("review_report_final.json", review)
        trace = self._traceability(ctx, review, deployment=None)
        decision = MergeGate().decide(
            gates, review, trace, ctx.load_escalations(), ctx.load_approvals()
        )
        ctx.store.write_json("merge_decision.json", decision)
        ctx.store.write_text(
            "merge_decision.md",
            f"# Merge decision: {decision.recommendation.value}\n\n"
            + "\n".join(f"- {r}" for r in decision.reasons)
            + "\n",
        )
        ctx.events.emit(
            "merge_decision",
            recommendation=decision.recommendation.value,
            checks=decision.checks,
        )
        if decision.recommendation is MergeRecommendation.NO_MERGE:
            for step in ("merge", "deploy", "verify"):
                ctx.state.mark(step, StepStatus.SKIPPED, detail="merge gate said NO_MERGE")
            ctx.state.save()
        else:
            # heal a crash window where a previous NO_MERGE pass marked steps skipped
            # before merge_gate itself was durably done and the decision then flipped
            for step in ("merge", "deploy", "verify"):
                if ctx.state.status_of(step) is StepStatus.SKIPPED:
                    ctx.state.mark(step, StepStatus.PENDING, detail="re-enabled by MERGE")
            ctx.state.save()

    def _step_merge(self, ctx: _RunContext) -> None:
        sha = ctx.git.merge_to_main(ctx.branch)
        ctx.events.emit("merged", branch=ctx.branch, sha=sha)

    def _step_deploy(self, ctx: _RunContext) -> None:
        deployer = LocalProcessDeployer(timeout_s=self.config.deploy_timeout_s)
        artifact_files = deployer.write_artifacts(ctx.workspace, ctx.spec)
        ctx.git.commit_all(
            "chore: deployment artifacts (run.sh, Dockerfile, rollback)", allow_noop=True
        )
        result = deployer.deploy(ctx.workspace, ctx.spec)
        ctx.store.write_json("deployment_result.json", result)
        ctx.events.emit(
            "deployment",
            environment=result.environment,
            healthy=result.healthy,
            journey_passed=result.journey_passed,
            artifacts=artifact_files,
        )
        if not (result.healthy and result.journey_passed):
            raise StepFailure(
                "deploy",
                f"deployment verification failed: {result.details} — see "
                "deploy/ROLLBACK.md for recovery",
            )

    def _step_verify(self, ctx: _RunContext) -> None:
        deployment = decoders.deployment_from_dict(ctx.store.read_json("deployment_result.json"))
        checks = {
            "health_check_passed": deployment.healthy,
            "main_user_journey_passed": deployment.journey_passed,
            "rollback_instructions_exist": (
                ctx.workspace / deployment.rollback_instructions_path
            ).exists(),
            "deployable_artifact_exists": (ctx.workspace / "deploy" / "Dockerfile").exists()
            and (ctx.workspace / "deploy" / "run.sh").exists(),
        }
        if not all(checks.values()):
            failed = [name for name, ok in checks.items() if not ok]
            raise StepFailure("verify", "production validation failed: " + ", ".join(failed))
        ctx.store.write_json("verification.json", {"verified": True, "checks": checks})

    def _step_report(self, ctx: _RunContext) -> None:
        review = ctx.load_review("review_report_final.json")
        fix_raw = ctx.store.read_json("fix_result.json")
        fix = FixResult(
            fixed=[decoders.finding_from_dict(f) for f in fix_raw["fixed"]],
            escalated=[decoders.finding_from_dict(f) for f in fix_raw["escalated"]],
            skipped=[decoders.finding_from_dict(f) for f in fix_raw["skipped"]],
        )
        gates = [
            decoders.gate_result_from_dict(raw)
            for raw in ctx.store.read_json("gate_results_retest.json")
        ]
        merge_decision = decoders.merge_decision_from_dict(
            ctx.store.read_json("merge_decision.json")
        )
        deployment = None
        if ctx.store.exists("deployment_result.json"):
            deployment = decoders.deployment_from_dict(
                ctx.store.read_json("deployment_result.json")
            )
        trace = self._traceability(ctx, review, deployment)
        ctx.store.write_json("traceability.json", trace)
        ctx.store.write_text("traceability.md", trace.to_markdown())

        validation_raw = ctx.store.read_json("validation_report.json")
        escalations = ctx.load_escalations()
        approvals = ctx.load_approvals()
        outcome = (
            "no_merge"
            if merge_decision.recommendation is MergeRecommendation.NO_MERGE
            else "success"
        )
        metrics = report_mod.build_metrics(
            step_statuses={n: r.status for n, r in ctx.state.steps.items()},
            validation_passed=not validation_raw.get("errors"),
            retest_gates=gates,
            tests_by_requirement=ctx.generated_tests.tests_by_requirement,
            requirements_total=len(ctx.spec.functional_requirements),
            escalation_count=len(escalations),
            review=review,
            fix=fix,
            created_at=ctx.state.created_at,
            outcome=outcome,
        )
        recorder = LocalMetricsRecorder()
        for name, value in metrics.items():
            recorder.record(name, value)
        ctx.store.write_json("metrics.json", recorder.snapshot())
        ctx.store.write_text(
            "final_report.md",
            report_mod.render_final_report(
                run_id=ctx.state.run_id,
                spec=ctx.spec,
                validation_raw=validation_raw,
                plan=ctx.plan,
                adrs=ctx.architecture.adrs,
                retest_gates=gates,
                review=review,
                fix=fix,
                merge=merge_decision,
                deployment=deployment,
                escalations=escalations,
                approvals=approvals,
                traceability=trace,
                metrics=metrics,
            ),
        )

    def _traceability(
        self,
        ctx: _RunContext,
        review: ReviewReport,
        deployment: DeploymentResult | None,
    ) -> TraceabilityReport:
        adr_map: dict[str, list[str]] = {}
        for adr in ctx.architecture.adrs:
            for rid in adr.requirement_ids:
                adr_map.setdefault(rid, []).append(adr.id)
        return TraceabilityBuilder().build(
            spec=ctx.spec,
            plan=ctx.plan,
            adr_ids_by_requirement=adr_map,
            tests_by_requirement=ctx.generated_tests.tests_by_requirement,
            code_by_requirement=ctx.implementation.code_by_requirement,
            findings=review.findings,
            deployment=deployment,
            workspace=ctx.workspace,
        )


# --- run context ------------------------------------------------------------------------


class _RunContext:
    """Lazy access to everything a step needs; deterministic products are recomputed."""

    def __init__(self, config: PipelineConfig, state: RunState) -> None:
        self.config = config
        self.state = state
        self.store = ArtifactStore(state.run_dir)
        self.events = EventLog(state.run_dir)
        self.workspace = state.run_dir / "workspace"
        self.branch = f"build/{state.run_id}"
        self._spec: MvpSpec | None = None
        self._plan: EngineeringPlan | None = None
        self._arch: ArchitectureOutput | None = None
        self._tests: GeneratedTests | None = None
        self._impl: Implementation | None = None

    @property
    def spec(self) -> MvpSpec:
        if self._spec is None:
            spec_path = self.state.run_dir / self.state.spec_file
            self._spec = ingest(spec_path, self.config.schema_path)
        return self._spec

    @property
    def plan(self) -> EngineeringPlan:
        if self._plan is None:
            self._plan = EngineeringPlanner().plan(self.spec)
        return self._plan

    @property
    def architecture(self) -> ArchitectureOutput:
        if self._arch is None:
            self._arch = ArchitectureAgent(PolicyEngine()).design(self.spec, self.plan)
        return self._arch

    @property
    def generated_tests(self) -> GeneratedTests:
        if self._tests is None:
            self._tests = TestArchitect().design(self.spec, self.plan)
        return self._tests

    @property
    def implementation(self) -> Implementation:
        if self._impl is None:
            self._impl = StdlibCrudGenerator().implement(self.spec, self.plan)
        return self._impl

    @property
    def git(self) -> LocalGitAdapter:
        return LocalGitAdapter(self.workspace)

    @property
    def gate_runner(self) -> QualityGateRunner:
        return QualityGateRunner(self.workspace, tuple(self.config.required_gates))

    def load_review(self, name: str) -> ReviewReport:
        raw = self.store.read_json(name)
        return ReviewReport(
            findings=[decoders.finding_from_dict(f) for f in raw["findings"]],
            summary=raw["summary"],
        )

    def load_escalations(self) -> list[Escalation]:
        return decoders.load_escalations(self.state.run_dir)

    def load_approvals(self) -> dict[str, Approval]:
        return decoders.load_approvals(self.state.run_dir)

    def ensure_escalation(
        self, *, key: str, step: str, risk: RiskLevel, reason: str, rule: str
    ) -> tuple[Escalation, bool]:
        """Create-or-return the escalation identified by ``key``.

        Single owner of id allocation (max existing suffix + 1, collision-proof
        across gaps) and of the dedup convention that makes resume idempotent.
        """
        existing = self.load_escalations()
        for esc in existing:
            if esc.context.get("key") == key:
                return esc, False
        highest = 0
        for esc in existing:
            _, _, suffix = esc.id.partition("-")
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        new = Escalation(
            id=f"ESC-{highest + 1:03d}",
            risk=risk,
            reason=reason,
            step=step,
            context={"key": key, "rule": rule},
            created_at=utc_now(),
        )
        self._write_escalation(new)
        return new, True

    def _write_escalation(self, esc: Escalation) -> None:
        atomic_write_json(self.state.run_dir / "escalations" / f"{esc.id}.json", esc)
        self.events.emit(
            "escalation_created",
            escalation_id=esc.id,
            step=esc.step,
            reason=esc.reason,
        )


# --- markdown helpers ---------------------------------------------------------------------


def _generated(path: str, content: str) -> GeneratedFile:
    return GeneratedFile(path=path, content=content, kind="code")


def _plan_markdown(plan: EngineeringPlan) -> str:
    lines = [
        "# Engineering plan",
        "",
        "| Task | Title | Component | Covers | Depends on | Size |",
        "|---|---|---|---|---|---|",
    ]
    for t in plan.tasks:
        lines.append(
            f"| {t.id} | {t.title} | {t.component} | {', '.join(t.requirement_ids) or '—'} "
            f"| {', '.join(t.depends_on) or '—'} | {t.complexity} |"
        )
    lines += [
        "",
        f"Order: {' → '.join(plan.order)}",
        "",
        f"APIs: {', '.join(plan.apis)}",
        "",
        "Risks:",
        *[f"- {r}" for r in plan.risks],
    ]
    return "\n".join(lines) + "\n"


def _architecture_markdown(arch: ArchitectureOutput) -> str:
    lines = ["# Architecture", "", arch.doc.overview, "", "## Components"]
    lines += [f"- **{name}**: {desc}" for name, desc in arch.doc.components.items()]
    lines += ["", "## Implications"]
    lines += [f"- **{k}**: {v}" for k, v in arch.doc.implications.items()]
    lines += ["", "## Decisions"]
    lines += [f"- {adr.id}: {adr.title}" for adr in arch.adrs]
    return "\n".join(lines) + "\n"


def _adr_markdown(adr: Adr) -> str:
    return (
        f"# {adr.id}: {adr.title}\n\n"
        f"Risk: {adr.risk.value} · Reversibility: {adr.reversibility} · "
        f"Covers: {', '.join(adr.requirement_ids) or '—'}\n\n"
        f"## Context\n{adr.context}\n\n## Decision\n{adr.decision}\n\n"
        f"## Consequences\n{adr.consequences}\n"
    )


def _review_markdown(review: ReviewReport) -> str:
    lines = [f"# Review report\n\n{review.summary}\n"]
    for f in review.findings:
        flag = "BLOCKING" if f.blocking else f.severity.value
        lines.append(f"- [{flag}] {f.id} {f.rule} at {f.file}:{f.line} — {f.message}")
    return "\n".join(lines) + "\n"
