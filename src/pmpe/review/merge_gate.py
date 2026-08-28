"""Merge gate: the single place that says MERGE or NO_MERGE, with reasons.

All four checks must hold:
1. every required quality gate passed
2. zero blocking review findings remain
3. traceability is complete (every requirement maps to code and tests)
4. every escalation raised during the run has a positive human approval

An approval never turns a failing gate green — it only satisfies check 4.
"""

from __future__ import annotations

from pmpe.domain.models import (
    Approval,
    Escalation,
    GateResult,
    MergeDecision,
    MergeRecommendation,
    ReviewReport,
    TraceabilityReport,
)


class MergeGate:
    def decide(
        self,
        gate_results: list[GateResult],
        review: ReviewReport,
        traceability: TraceabilityReport,
        escalations: list[Escalation],
        approvals: dict[str, Approval],
    ) -> MergeDecision:
        reasons: list[str] = []

        failed_gates = [g for g in gate_results if g.required and not g.passed]
        for gate in failed_gates:
            reasons.append(f"required gate '{gate.gate}' failed: {gate.details[:200]}")

        for finding in review.blocking:
            reasons.append(
                f"blocking finding {finding.id} [{finding.rule}] at "
                f"{finding.file}:{finding.line} — {finding.message}"
            )

        if not traceability.complete:
            for gap in traceability.gaps:
                reasons.append(f"traceability gap: {gap}")

        unapproved: list[str] = []
        for esc in escalations:
            approval = approvals.get(esc.id)
            if approval is None:
                unapproved.append(f"escalation {esc.id} has no recorded approval")
            elif not approval.approved:
                unapproved.append(
                    f"escalation {esc.id} was rejected by {approval.approver}: {approval.reason}"
                )
        reasons.extend(unapproved)

        checks = {
            "required_gates_passed": not failed_gates,
            "no_blocking_findings": not review.blocking,
            "traceability_complete": traceability.complete,
            "escalations_approved": not unapproved,
        }

        if all(checks.values()):
            return MergeDecision(
                recommendation=MergeRecommendation.MERGE,
                reasons=[
                    f"all {sum(1 for g in gate_results if g.required)} required gates passed",
                    "no blocking review findings",
                    f"traceability complete across {len(traceability.entries)} requirement(s)",
                    f"escalations approved: {len(escalations)}",
                ],
                checks=checks,
            )
        return MergeDecision(
            recommendation=MergeRecommendation.NO_MERGE, reasons=reasons, checks=checks
        )
