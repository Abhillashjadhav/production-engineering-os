"""Workflow steps 9-18: quality gates through the final report (the ship half)."""

from __future__ import annotations

from pmpe.audit.traceability import TraceabilityBuilder
from pmpe.config import PipelineConfig
from pmpe.deployment.local import LocalProcessDeployer
from pmpe.domain.errors import StepFailure
from pmpe.domain.models import (
    DeploymentResult,
    FixResult,
    MergeRecommendation,
    PullRequestRecord,
    ReviewReport,
    StepStatus,
    TraceabilityReport,
)
from pmpe.orchestration import decoders
from pmpe.orchestration import report as report_mod
from pmpe.orchestration.context import RunContext
from pmpe.orchestration.render import _review_markdown
from pmpe.policies.engine import PolicyEngine
from pmpe.review.fixer import FixAgent
from pmpe.review.merge_gate import MergeGate
from pmpe.review.reviewer import PrReviewer
from pmpe.telemetry.metrics import LocalMetricsRecorder


class ShipSteps:
    def __init__(self, config: PipelineConfig, policy: PolicyEngine) -> None:
        self.config = config
        self.policy = policy

    def _run_gates(self, ctx: RunContext, artifact: str, stage: str) -> None:
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

    def _step_quality_gates(self, ctx: RunContext) -> None:
        self._run_gates(ctx, "gate_results.json", "quality_gates")

    def _step_create_pr(self, ctx: RunContext) -> None:
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

    def _step_review(self, ctx: RunContext) -> None:
        result = PrReviewer().review(ctx.workspace, ctx.spec, ctx.plan)
        ctx.store.write_json("review_report.json", result)
        ctx.store.write_text("review_report.md", _review_markdown(result))

    def _step_fix(self, ctx: RunContext) -> None:
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

    def _step_retest(self, ctx: RunContext) -> None:
        self._run_gates(ctx, "gate_results_retest.json", "retest")

    def _step_merge_gate(self, ctx: RunContext) -> None:
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

    def _step_merge(self, ctx: RunContext) -> None:
        sha = ctx.git.merge_to_main(ctx.branch)
        ctx.events.emit("merged", branch=ctx.branch, sha=sha)

    def _step_deploy(self, ctx: RunContext) -> None:
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

    def _step_verify(self, ctx: RunContext) -> None:
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

    def _step_report(self, ctx: RunContext) -> None:
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
        ctx: RunContext,
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
