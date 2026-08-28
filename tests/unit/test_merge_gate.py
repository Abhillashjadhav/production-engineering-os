"""SYS-12: merge gate — gates AND findings AND traceability AND approvals."""

from __future__ import annotations

from pmpe.domain.models import (
    Approval,
    Escalation,
    Finding,
    GateResult,
    MergeRecommendation,
    ReviewReport,
    RiskLevel,
    Severity,
    TraceabilityEntry,
    TraceabilityReport,
)
from pmpe.review.merge_gate import MergeGate


def _green_gates() -> list[GateResult]:
    return [
        GateResult(gate="lint", passed=True, required=True, details="ok"),
        GateResult(gate="unit", passed=True, required=True, details="ok"),
        GateResult(gate="security", passed=True, required=True, details="ok"),
    ]


def _clean_review() -> ReviewReport:
    return ReviewReport(findings=[], summary="clean")


def _complete_traceability() -> TraceabilityReport:
    entry = TraceabilityEntry(
        requirement_id="FR-001",
        tasks=["T-001"],
        adrs=["ADR-001"],
        code_files=["src/app.py"],
        tests=["test_app.py::test_ok"],
        finding_ids=[],
        deployment_evidence="journey passed",
    )
    return TraceabilityReport(entries=[entry], complete=True, gaps=[])


def _blocking_finding() -> Finding:
    return Finding(
        id="F-001",
        category="security",
        severity=Severity.CRITICAL,
        blocking=True,
        safe_to_autofix=False,
        file="src/app.py",
        line=1,
        message="eval() on user input",
        rule="SEC_EVAL",
    )


def _escalation() -> Escalation:
    return Escalation(
        id="ESC-001",
        risk=RiskLevel.HIGH,
        reason="production deployment requested",
        step="validate",
        context={},
    )


def test_all_green_recommends_merge() -> None:
    decision = MergeGate().decide(_green_gates(), _clean_review(), _complete_traceability(), [], {})
    assert decision.recommendation is MergeRecommendation.MERGE
    assert decision.reasons


def test_failing_required_gate_blocks_merge() -> None:
    gates = _green_gates()
    gates[1] = GateResult(gate="unit", passed=False, required=True, details="2 failed")
    decision = MergeGate().decide(gates, _clean_review(), _complete_traceability(), [], {})
    assert decision.recommendation is MergeRecommendation.NO_MERGE
    assert any("unit" in r for r in decision.reasons)


def test_failing_optional_gate_does_not_block(caplog) -> None:  # type: ignore[no-untyped-def]
    gates = [*_green_gates(), GateResult(gate="format", passed=False, required=False, details="")]
    decision = MergeGate().decide(gates, _clean_review(), _complete_traceability(), [], {})
    assert decision.recommendation is MergeRecommendation.MERGE


def test_blocking_finding_blocks_merge() -> None:
    review = ReviewReport(findings=[_blocking_finding()], summary="1 blocking")
    decision = MergeGate().decide(_green_gates(), review, _complete_traceability(), [], {})
    assert decision.recommendation is MergeRecommendation.NO_MERGE
    assert any("F-001" in r or "blocking" in r.lower() for r in decision.reasons)


def test_non_blocking_findings_do_not_block() -> None:
    finding = Finding(
        id="F-002",
        category="maintainability",
        severity=Severity.MINOR,
        blocking=False,
        safe_to_autofix=False,
        file="src/app.py",
        line=10,
        message="long function",
        rule="REV_LONG_FUNCTION",
    )
    review = ReviewReport(findings=[finding], summary="1 minor")
    decision = MergeGate().decide(_green_gates(), review, _complete_traceability(), [], {})
    assert decision.recommendation is MergeRecommendation.MERGE


def test_incomplete_traceability_blocks_merge() -> None:
    trace = TraceabilityReport(entries=[], complete=False, gaps=["FR-001 has no tests"])
    decision = MergeGate().decide(_green_gates(), _clean_review(), trace, [], {})
    assert decision.recommendation is MergeRecommendation.NO_MERGE


def test_unapproved_escalation_blocks_merge() -> None:
    decision = MergeGate().decide(
        _green_gates(), _clean_review(), _complete_traceability(), [_escalation()], {}
    )
    assert decision.recommendation is MergeRecommendation.NO_MERGE
    assert any("ESC-001" in r for r in decision.reasons)


def test_approved_escalation_allows_merge() -> None:
    approval = Approval(
        escalation_id="ESC-001",
        approver="abhillash",
        reason="local fallback accepted",
        approved=True,
        timestamp="2026-07-12T00:00:00Z",
    )
    decision = MergeGate().decide(
        _green_gates(),
        _clean_review(),
        _complete_traceability(),
        [_escalation()],
        {"ESC-001": approval},
    )
    assert decision.recommendation is MergeRecommendation.MERGE


def test_rejected_escalation_blocks_merge() -> None:
    rejection = Approval(
        escalation_id="ESC-001",
        approver="abhillash",
        reason="not acceptable",
        approved=False,
        timestamp="2026-07-12T00:00:00Z",
    )
    decision = MergeGate().decide(
        _green_gates(),
        _clean_review(),
        _complete_traceability(),
        [_escalation()],
        {"ESC-001": rejection},
    )
    assert decision.recommendation is MergeRecommendation.NO_MERGE
