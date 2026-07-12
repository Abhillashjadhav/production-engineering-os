"""Final build report rendering and per-run metric assembly."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pmpe.domain.models import (
    Adr,
    Approval,
    DeploymentResult,
    EngineeringPlan,
    Escalation,
    FixResult,
    GateResult,
    MergeDecision,
    MvpSpec,
    ReviewReport,
    StepStatus,
    TraceabilityReport,
)
from pmpe.telemetry.metrics import compute_run_metrics

_RAN_RE = re.compile(r"Ran (\d+) tests?")
_FAILURES_RE = re.compile(r"failures=(\d+)")
_ERRORS_RE = re.compile(r"errors=(\d+)")


def parse_test_counts(gates: list[GateResult]) -> tuple[int, int]:
    """(total, passed) across unit+integration gate output."""
    total = 0
    failed = 0
    for gate in gates:
        if gate.gate not in ("unit", "integration"):
            continue
        match = _RAN_RE.search(gate.details)
        if match:
            total += int(match.group(1))
        if not gate.passed:
            failures = _FAILURES_RE.search(gate.details)
            errors = _ERRORS_RE.search(gate.details)
            failed += int(failures.group(1)) if failures else 0
            failed += int(errors.group(1)) if errors else 0
            if not failures and not errors:
                failed += 1  # e.g. import error before any test ran
    return total, max(0, total - failed)


def _duration_seconds(created_at: str) -> float:
    try:
        started = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - started).total_seconds()


def build_metrics(
    *,
    step_statuses: dict[str, StepStatus],
    validation_passed: bool,
    retest_gates: list[GateResult],
    tests_by_requirement: dict[str, list[str]],
    requirements_total: int,
    escalation_count: int,
    review: ReviewReport,
    fix: FixResult,
    created_at: str,
    outcome: str,
) -> dict[str, Any]:
    tests_total, tests_passed = parse_test_counts(retest_gates)
    functional_gates_green = all(
        g.passed for g in retest_gates if g.gate in ("unit", "integration")
    )
    return compute_run_metrics(
        step_statuses=step_statuses,
        validation_passed=validation_passed,
        tests_total=tests_total,
        tests_passed=tests_passed,
        requirements_total=requirements_total,
        requirements_with_passing_tests=(
            len(tests_by_requirement) if functional_gates_green else 0
        ),
        escalation_count=escalation_count,
        blocking_findings=len(review.blocking),
        fixes_applied=len(fix.fixed),
        duration_seconds=_duration_seconds(created_at),
        outcome=outcome,
    )


def render_final_report(
    *,
    run_id: str,
    spec: MvpSpec,
    validation_raw: dict[str, Any],
    plan: EngineeringPlan,
    adrs: list[Adr],
    retest_gates: list[GateResult],
    review: ReviewReport,
    fix: FixResult,
    merge: MergeDecision,
    deployment: DeploymentResult | None,
    escalations: list[Escalation],
    approvals: dict[str, Approval],
    traceability: TraceabilityReport,
    metrics: dict[str, Any],
) -> str:
    lines: list[str] = [
        f"# Final build report — {spec.product_name} ({run_id})",
        "",
        f"Outcome: **{metrics['run_outcome']}**",
        "",
        "## Specification",
        f"- Problem: {spec.problem_statement}",
        f"- Target user: {spec.target_user}",
        f"- North Star Metric: {spec.north_star_metric}",
        f"- Validation: {'PASSED' if not validation_raw.get('errors') else 'FAILED'} "
        f"({len(validation_raw.get('warnings', []))} warning(s), "
        f"{len(validation_raw.get('questions', []))} question(s))",
        "",
        "## Engineering plan",
        f"- {len(plan.tasks)} task(s) across components: {', '.join(plan.components)}",
        f"- APIs: {', '.join(plan.apis)}",
        f"- Data model: {'; '.join(plan.data_model) or 'none'}",
        "",
        "## Architecture decisions",
    ]
    lines += [
        f"- {adr.id}: {adr.title} (risk: {adr.risk.value}, {adr.reversibility})" for adr in adrs
    ]
    lines += ["", "## Quality gates (final re-run)"]
    for gate in retest_gates:
        mark = "SKIP" if gate.skipped else ("PASS" if gate.passed else "FAIL")
        req = "required" if gate.required else "optional"
        lines.append(f"- {gate.gate}: {mark} ({req}, {gate.duration_s}s)")
    lines += [
        "",
        "## Review",
        f"- {review.summary}",
        f"- Safe fixes applied: {len(fix.fixed)}; escalated: {len(fix.escalated)}; "
        f"left for humans (non-blocking): {len(fix.skipped)}",
        "",
        "## Merge decision",
        f"- Recommendation: **{merge.recommendation.value}**",
    ]
    lines += [f"  - {reason}" for reason in merge.reasons]
    lines += ["", "## Deployment"]
    if deployment is None:
        lines.append("- Not deployed (merge gate did not clear the build).")
    else:
        lines += [
            f"- Environment: {deployment.environment} at {deployment.url}",
            f"- Health check: {'passed' if deployment.healthy else 'FAILED'}",
            f"- Main user journey: {'passed' if deployment.journey_passed else 'FAILED'} "
            f"({deployment.details})",
            f"- Rollback instructions: {deployment.rollback_instructions_path}",
        ]
    lines += ["", "## Human escalations"]
    if not escalations:
        lines.append("- None: the build required no human intervention.")
    for esc in escalations:
        approval = approvals.get(esc.id)
        if approval is None:
            resolution = "OPEN — no decision recorded"
        elif approval.approved:
            resolution = f"approved by {approval.approver}: {approval.reason}"
        else:
            resolution = f"rejected by {approval.approver}: {approval.reason}"
        lines.append(f"- {esc.id} [{esc.risk.value}] at step '{esc.step}': {esc.reason}")
        lines.append(f"  - Resolution: {resolution}")
    lines += ["", "## Metrics (leading-metric hooks)"]
    lines += [f"- {key}: {value}" for key, value in sorted(metrics.items())]
    lines += ["", "## Traceability", "", traceability.to_markdown()]
    return "\n".join(lines) + "\n"
